"""Affectation conducteur <-> véhicule PERSISTANTE (source de vérité métier).

SÉPARÉ du domaine BLE/présence (`driver_sessions`, timeout 5 min) : une affectation
ne se ferme QUE sur action explicite (Fin de service, Changement, Force admin).
Jamais sur inactivité/déconnexion/pause.

TOPOLOGIE MONGO : STANDALONE (aucune transaction multi-doc). Toutes les mutations
d'état courant sont MONO-DOCUMENT (atomiques) et protégées par des INDEX UNIQUES
PARTIELS incluant tenant_id :
    UNIQUE (tenant_id, driver_id)  WHERE status="ACTIVE"   (Règle 1)
    UNIQUE (tenant_id, vehicle_id) WHERE status="ACTIVE"   (Règles 2/3)

DEUX COLLECTIONS
  - vehicle_assignments        : ÉTAT COURANT autoritatif (1 doc ACTIVE max/chauffeur).
  - vehicle_assignment_events  : JOURNAL métier (source unique d'HISTORIQUE).
        Champs MÉTIER FIGÉS après création (tenant_id, driver_id, type,
        from_vehicle_id, to_vehicle_id, at, actor_id, actor_role, reason, request_id).
        Seuls les champs de FINALISATION évoluent de façon MONOTONE :
        result (PENDING->OK|REJECTED), completed_at, error_code.
        Jamais OK->PENDING ni OK->REJECTED.

PATTERN ANTI-CRASH (idempotent) — pour TAKE/END/CHANGE/FORCE_END :
    1. INSERT event {result:PENDING, request_id}     (idempotence UNIQUE(tenant,request_id))
    2. opération état courant MONO-DOC atomique
    3. finalisation event -> OK (succès) | REJECTED (conflit prouvé)
  Un retry réseau (même request_id) NE ré-exécute JAMAIS l'action métier :
  l'event PENDING existant est relu et la reprise est idempotente.

HISTORIQUE : reconstruit UNIQUEMENT depuis vehicle_assignment_events
(TAKE A -> CHANGE A->B -> CHANGE B->C -> END C). Le doc vehicle_assignments
représente seulement l'état courant/terminal, jamais les anciens segments.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "ACTIVE"
STATUS_ENDED = "ENDED"

RESULT_PENDING = "PENDING"
RESULT_OK = "OK"
RESULT_REJECTED = "REJECTED"

EV_TAKE = "VEHICLE_TAKEN"
EV_END = "VEHICLE_RELEASED"
EV_CHANGE = "VEHICLE_CHANGED"
EV_FORCE = "VEHICLE_FORCE_RELEASED"
EV_REJECTED = "VEHICLE_ASSIGNMENT_REJECTED"

END_REASON_DRIVER = "DRIVER_END_OF_SERVICE"
END_REASON_CHANGE = "VEHICLE_CHANGE"
END_REASON_ADMIN = "ADMIN_FORCE_RELEASE"

# Un event PENDING n'est réconcilié que s'il est plus vieux que ce seuil
# (évite de concurrencer une requête encore en cours).
RECONCILE_MIN_AGE_S = int(os.environ.get("VEHICLE_ASSIGNMENT_RECONCILE_MIN_AGE_S", "30"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Index (idempotent). Appelé au startup. RAW db (non scopé) — on filtre tenant.
# ---------------------------------------------------------------------------
async def ensure_indexes(db) -> None:
    """Crée les index uniques partiels (tenant-scopés) + idempotence events.
    Idempotent : create_index ne recrée pas un index identique existant."""
    await db.vehicle_assignments.create_index(
        [("tenant_id", 1), ("driver_id", 1)], unique=True,
        partialFilterExpression={"status": STATUS_ACTIVE},
        name="uniq_active_driver_per_tenant")
    await db.vehicle_assignments.create_index(
        [("tenant_id", 1), ("vehicle_id", 1)], unique=True,
        partialFilterExpression={"status": STATUS_ACTIVE},
        name="uniq_active_vehicle_per_tenant")
    # Idempotence des events : scope (tenant_id, request_id). sparse -> events sans
    # request_id (ex. réconciliation interne) ne violent pas l'unicité.
    await db.vehicle_assignment_events.create_index(
        [("tenant_id", 1), ("request_id", 1)], unique=True,
        partialFilterExpression={"request_id": {"$type": "string"}},
        name="uniq_event_request_per_tenant")
    await db.vehicle_assignment_events.create_index(
        [("tenant_id", 1), ("driver_id", 1), ("at", 1)],
        name="events_by_driver_time")
    await db.vehicle_assignment_events.create_index(
        [("result", 1), ("at", 1)], name="events_by_result")


# ---------------------------------------------------------------------------
# Journal d'événements (append-only pour les champs métier).
# ---------------------------------------------------------------------------
async def _find_event_by_request(db, tenant_id: str, request_id: Optional[str]) -> Optional[dict]:
    if not request_id:
        return None
    return await db.vehicle_assignment_events.find_one(
        {"tenant_id": tenant_id, "request_id": request_id}, {"_id": 0})


async def _create_pending_event(db, *, tenant_id: str, driver_id: str, ev_type: str,
                                 from_vehicle_id: Optional[str], to_vehicle_id: Optional[str],
                                 actor_id: str, actor_role: str, reason: Optional[str],
                                 request_id: Optional[str]) -> dict:
    """Crée l'event PENDING (champs métier figés). Idempotent via UNIQUE(tenant,request_id) :
    si l'event existe déjà (retry), on le RELIT et on le renvoie tel quel (aucune ré-exécution)."""
    ev = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "driver_id": driver_id,
        "type": ev_type,
        "from_vehicle_id": from_vehicle_id,
        "to_vehicle_id": to_vehicle_id,
        "at": _now(),
        "actor_id": actor_id,
        "actor_role": actor_role,
        "reason": reason,
        "request_id": request_id,
        # finalisation (monotone)
        "result": RESULT_PENDING,
        "completed_at": None,
        "error_code": None,
    }
    try:
        await db.vehicle_assignment_events.insert_one(dict(ev))
        return ev
    except DuplicateKeyError:
        existing = await _find_event_by_request(db, tenant_id, request_id)
        if existing:
            return existing
        raise


async def _finalize_event(db, event_id: str, result: str, error_code: Optional[str] = None) -> None:
    """Finalise un event de façon MONOTONE : n'écrase JAMAIS un OK/REJECTED déjà posé."""
    await db.vehicle_assignment_events.update_one(
        {"id": event_id, "result": RESULT_PENDING},
        {"$set": {"result": result, "completed_at": _now(), "error_code": error_code}})


async def _audit(db, tenant_id: str, action: str, payload: dict) -> None:
    doc = {"ts": _now(), "scope": "vehicle_assignment", "action": action,
           "tenant_id": tenant_id, **payload}
    try:
        await db.audit_log.insert_one(doc)
    except Exception:
        logger.warning("vehicle_assignment audit insert failed (non bloquant)")


# ---------------------------------------------------------------------------
# Lecture état courant.
# ---------------------------------------------------------------------------
async def get_active(db, tenant_id: str, driver_id: str) -> Optional[dict]:
    return await db.vehicle_assignments.find_one(
        {"tenant_id": tenant_id, "driver_id": driver_id, "status": STATUS_ACTIVE},
        {"_id": 0})


async def get_active_by_vehicle(db, tenant_id: str, vehicle_id: str) -> Optional[dict]:
    return await db.vehicle_assignments.find_one(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "status": STATUS_ACTIVE},
        {"_id": 0})


async def resolve_active_vehicle(db, driver_id: str, tenant_id: str) -> Optional[str]:
    """SEULE intégration autorisée avec le Mode Privé : renvoie le vehicle_id ACTIF
    du chauffeur (ou None). Ne touche PAS au moteur Mode Privé."""
    a = await get_active(db, tenant_id, driver_id)
    return a.get("vehicle_id") if a else None


# ---------------------------------------------------------------------------
# TAKE — prendre un véhicule (crée une affectation ACTIVE).
# ---------------------------------------------------------------------------
async def take(db, *, tenant_id: str, driver_id: str, vehicle_id: str,
               actor_id: str, actor_role: str = "driver",
               request_id: Optional[str] = None, source: str = "MOBILE_APP") -> dict:
    """Prend un véhicule. Idempotent (request_id). Fail-closed sur conflits.
    Retour : {result, assignment?, reason?}."""
    # Idempotence : requête déjà traitée ?
    ev = await _find_event_by_request(db, tenant_id, request_id) if request_id else None
    if ev and ev.get("result") == RESULT_OK:
        cur = await get_active(db, tenant_id, driver_id)
        return {"result": "ok", "idempotent": True, "assignment": cur}

    # 0) déjà une affectation ACTIVE pour ce chauffeur ?
    cur = await get_active(db, tenant_id, driver_id)
    if cur:
        if cur.get("vehicle_id") == vehicle_id:
            return {"result": "ok", "idempotent": True, "assignment": cur}
        # Chauffeur déjà sur un AUTRE véhicule -> il faut CHANGE, pas TAKE.
        return {"result": "conflict", "reason": "DRIVER_ALREADY_ACTIVE",
                "assignment": cur}

    # 1) event PENDING
    ev = await _create_pending_event(
        db, tenant_id=tenant_id, driver_id=driver_id, ev_type=EV_TAKE,
        from_vehicle_id=None, to_vehicle_id=vehicle_id,
        actor_id=actor_id, actor_role=actor_role, reason=None, request_id=request_id)
    if ev.get("result") == RESULT_OK:  # retry d'un event déjà finalisé
        return {"result": "ok", "idempotent": True,
                "assignment": await get_active(db, tenant_id, driver_id)}

    # 2) INSERT état courant (atomique ; index unique = protection concurrence)
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id, "driver_id": driver_id, "vehicle_id": vehicle_id,
        "status": STATUS_ACTIVE,
        "assignment_started_at": _now(), "segment_started_at": _now(),
        "previous_vehicle_id": None,
        "ended_at": None, "ended_by": None, "end_reason": None,
        "source": source, "created_by": actor_id,
        "updated_at": _now(), "last_event_id": ev["id"],
    }
    try:
        await db.vehicle_assignments.insert_one(dict(doc))
    except DuplicateKeyError:
        # 3b) conflit : véhicule déjà pris (index vehicle) OU chauffeur déjà actif (index driver)
        await _finalize_event(db, ev["id"], RESULT_REJECTED, error_code="ACTIVE_CONFLICT")
        occ = await get_active_by_vehicle(db, tenant_id, vehicle_id)
        drv = await get_active(db, tenant_id, driver_id)
        if occ and occ.get("driver_id") != driver_id:
            await _audit(db, tenant_id, EV_REJECTED, {"driver_id": driver_id,
                         "vehicle_id": vehicle_id, "reason": "VEHICLE_OCCUPIED",
                         "actor_id": actor_id, "result": "rejected"})
            return {"result": "conflict", "reason": "VEHICLE_OCCUPIED"}
        if drv:
            return {"result": "conflict", "reason": "DRIVER_ALREADY_ACTIVE",
                    "assignment": drv}
        return {"result": "conflict", "reason": "ACTIVE_CONFLICT"}

    # 3a) succès
    await _finalize_event(db, ev["id"], RESULT_OK)
    await _audit(db, tenant_id, EV_TAKE, {"driver_id": driver_id, "vehicle_id": vehicle_id,
                 "actor_id": actor_id, "actor_role": actor_role, "result": "ok"})
    return {"result": "ok", "assignment": doc}


# ---------------------------------------------------------------------------
# END — fin de service (libère le véhicule).
# ---------------------------------------------------------------------------
async def end(db, *, tenant_id: str, driver_id: str, actor_id: str,
              actor_role: str = "driver", request_id: Optional[str] = None,
              reason: str = END_REASON_DRIVER) -> dict:
    ev0 = await _find_event_by_request(db, tenant_id, request_id) if request_id else None
    if ev0 and ev0.get("result") == RESULT_OK:
        return {"result": "ok", "idempotent": True}

    cur = await get_active(db, tenant_id, driver_id)
    if not cur:
        return {"result": "noop", "reason": "NO_ACTIVE_ASSIGNMENT"}

    ev = await _create_pending_event(
        db, tenant_id=tenant_id, driver_id=driver_id, ev_type=EV_END,
        from_vehicle_id=cur.get("vehicle_id"), to_vehicle_id=None,
        actor_id=actor_id, actor_role=actor_role, reason=reason, request_id=request_id)
    if ev.get("result") == RESULT_OK:
        return {"result": "ok", "idempotent": True}

    res = await db.vehicle_assignments.update_one(
        {"tenant_id": tenant_id, "driver_id": driver_id, "status": STATUS_ACTIVE,
         "vehicle_id": cur.get("vehicle_id")},
        {"$set": {"status": STATUS_ENDED, "ended_at": _now(), "ended_by": actor_id,
                  "end_reason": reason, "updated_at": _now(), "last_event_id": ev["id"]}})
    if res.modified_count == 1:
        await _finalize_event(db, ev["id"], RESULT_OK)
        await _audit(db, tenant_id, EV_END, {"driver_id": driver_id,
                     "vehicle_id": cur.get("vehicle_id"), "actor_id": actor_id,
                     "reason": reason, "result": "ok"})
        return {"result": "ok", "vehicle_id": cur.get("vehicle_id")}
    # rien modifié -> déjà terminé entre-temps
    await _finalize_event(db, ev["id"], RESULT_OK)  # état cible déjà atteint = idempotent
    return {"result": "ok", "idempotent": True}


# ---------------------------------------------------------------------------
# CHANGE A -> B — mutation ATOMIQUE du document ACTIVE (jamais END+CREATE).
# ---------------------------------------------------------------------------
async def change(db, *, tenant_id: str, driver_id: str, to_vehicle_id: str,
                 actor_id: str, actor_role: str = "driver",
                 request_id: Optional[str] = None) -> dict:
    ev0 = await _find_event_by_request(db, tenant_id, request_id) if request_id else None
    if ev0 and ev0.get("result") == RESULT_OK:
        return {"result": "ok", "idempotent": True,
                "assignment": await get_active(db, tenant_id, driver_id)}

    cur = await get_active(db, tenant_id, driver_id)
    if not cur:
        # Pas d'affectation A -> ce n'est pas un CHANGE. On tente un TAKE propre.
        return await take(db, tenant_id=tenant_id, driver_id=driver_id,
                          vehicle_id=to_vehicle_id, actor_id=actor_id,
                          actor_role=actor_role, request_id=request_id)
    vehicle_a = cur.get("vehicle_id")
    if vehicle_a == to_vehicle_id:
        return {"result": "ok", "idempotent": True, "assignment": cur}

    ev = await _create_pending_event(
        db, tenant_id=tenant_id, driver_id=driver_id, ev_type=EV_CHANGE,
        from_vehicle_id=vehicle_a, to_vehicle_id=to_vehicle_id,
        actor_id=actor_id, actor_role=actor_role, reason=END_REASON_CHANGE,
        request_id=request_id)
    if ev.get("result") == RESULT_OK:
        return {"result": "ok", "idempotent": True,
                "assignment": await get_active(db, tenant_id, driver_id)}

    # Mutation atomique A->B sur le MÊME document ACTIVE.
    try:
        res = await db.vehicle_assignments.update_one(
            {"tenant_id": tenant_id, "driver_id": driver_id,
             "status": STATUS_ACTIVE, "vehicle_id": vehicle_a},
            {"$set": {"vehicle_id": to_vehicle_id, "previous_vehicle_id": vehicle_a,
                      "segment_started_at": _now(), "updated_at": _now(),
                      "last_event_id": ev["id"]}})
    except DuplicateKeyError:
        # B déjà occupé -> A reste STRICTEMENT inchangé.
        await _finalize_event(db, ev["id"], RESULT_REJECTED, error_code="VEHICLE_OCCUPIED")
        await _audit(db, tenant_id, EV_REJECTED, {"driver_id": driver_id,
                     "from_vehicle_id": vehicle_a, "to_vehicle_id": to_vehicle_id,
                     "reason": "VEHICLE_OCCUPIED", "actor_id": actor_id, "result": "rejected"})
        return {"result": "conflict", "reason": "VEHICLE_OCCUPIED",
                "assignment": cur}  # A inchangé

    if res.modified_count == 1:
        await _finalize_event(db, ev["id"], RESULT_OK)
        await _audit(db, tenant_id, EV_CHANGE, {"driver_id": driver_id,
                     "from_vehicle_id": vehicle_a, "to_vehicle_id": to_vehicle_id,
                     "actor_id": actor_id, "result": "ok"})
        return {"result": "ok", "assignment": await get_active(db, tenant_id, driver_id)}
    # match=0 : l'affectation A n'existait plus (course) -> analyse déterministe
    now_active = await get_active(db, tenant_id, driver_id)
    if now_active and now_active.get("vehicle_id") == to_vehicle_id:
        await _finalize_event(db, ev["id"], RESULT_OK)  # déjà appliqué
        return {"result": "ok", "idempotent": True, "assignment": now_active}
    await _finalize_event(db, ev["id"], RESULT_REJECTED, error_code="STATE_CHANGED")
    return {"result": "conflict", "reason": "STATE_CHANGED", "assignment": now_active}


# ---------------------------------------------------------------------------
# FORCE_END — libération forcée par un gestionnaire (audit renforcé).
# ---------------------------------------------------------------------------
async def force_end(db, *, tenant_id: str, vehicle_id: str, actor_id: str,
                    actor_role: str = "admin", request_id: Optional[str] = None,
                    reason: str = END_REASON_ADMIN) -> dict:
    ev0 = await _find_event_by_request(db, tenant_id, request_id) if request_id else None
    if ev0 and ev0.get("result") == RESULT_OK:
        return {"result": "ok", "idempotent": True}

    cur = await get_active_by_vehicle(db, tenant_id, vehicle_id)
    if not cur:
        return {"result": "noop", "reason": "NO_ACTIVE_ASSIGNMENT"}

    ev = await _create_pending_event(
        db, tenant_id=tenant_id, driver_id=cur.get("driver_id"), ev_type=EV_FORCE,
        from_vehicle_id=vehicle_id, to_vehicle_id=None,
        actor_id=actor_id, actor_role=actor_role, reason=reason, request_id=request_id)
    if ev.get("result") == RESULT_OK:
        return {"result": "ok", "idempotent": True}

    res = await db.vehicle_assignments.update_one(
        {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "status": STATUS_ACTIVE},
        {"$set": {"status": STATUS_ENDED, "ended_at": _now(), "ended_by": actor_id,
                  "end_reason": reason, "updated_at": _now(), "last_event_id": ev["id"]}})
    if res.modified_count == 1:
        await _finalize_event(db, ev["id"], RESULT_OK)
        await _audit(db, tenant_id, EV_FORCE, {"driver_id": cur.get("driver_id"),
                     "vehicle_id": vehicle_id, "actor_id": actor_id,
                     "ended_by": actor_id, "reason": reason, "result": "ok"})
        return {"result": "ok", "vehicle_id": vehicle_id, "driver_id": cur.get("driver_id")}
    await _finalize_event(db, ev["id"], RESULT_OK)
    return {"result": "ok", "idempotent": True}


# ---------------------------------------------------------------------------
# HISTORIQUE — reconstruit UNIQUEMENT depuis les events (jamais le doc courant).
# ---------------------------------------------------------------------------
async def history(db, tenant_id: str, *, vehicle_id: Optional[str] = None,
                  driver_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    q: dict = {"tenant_id": tenant_id, "result": RESULT_OK}
    if driver_id:
        q["driver_id"] = driver_id
    if vehicle_id:
        q["$or"] = [{"from_vehicle_id": vehicle_id}, {"to_vehicle_id": vehicle_id}]
    rows = await db.vehicle_assignment_events.find(q, {"_id": 0}).sort("at", 1).to_list(limit)
    return rows


# ---------------------------------------------------------------------------
# RÉCONCILIATEUR — idempotent, déterministe. Ne DEVINE jamais.
# Traite les events PENDING assez ANCIENS (> RECONCILE_MIN_AGE_S) :
#   - déjà appliqué (état courant == cible)   -> OK
#   - preuve de rejet (cible occupée par autre) -> REJECTED
#   - encore applicable                        -> replay idempotent
#   - ambigu                                   -> laisser PENDING + log
# ---------------------------------------------------------------------------
async def reconcile_pending_vehicle_assignment_events(db, tenant_id: Optional[str] = None) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=RECONCILE_MIN_AGE_S)).isoformat()
    q: dict = {"result": RESULT_PENDING, "at": {"$lte": cutoff}}
    if tenant_id:
        q["tenant_id"] = tenant_id
    pend = await db.vehicle_assignment_events.find(q, {"_id": 0}).sort("at", 1).to_list(500)
    stats = {"scanned": len(pend), "ok": 0, "rejected": 0, "replayed": 0, "ambiguous": 0}
    for ev in pend:
        t = ev["tenant_id"]; d = ev["driver_id"]; typ = ev["type"]
        to_v = ev.get("to_vehicle_id"); from_v = ev.get("from_vehicle_id")
        cur = await get_active(db, t, d)
        try:
            if typ == EV_TAKE:
                if cur and cur.get("vehicle_id") == to_v:
                    await _finalize_event(db, ev["id"], RESULT_OK); stats["ok"] += 1
                elif cur is None:
                    occ = await get_active_by_vehicle(db, t, to_v)
                    if occ and occ.get("driver_id") != d:
                        await _finalize_event(db, ev["id"], RESULT_REJECTED,
                                              error_code="VEHICLE_OCCUPIED"); stats["rejected"] += 1
                    else:
                        r = await take(db, tenant_id=t, driver_id=d, vehicle_id=to_v,
                                       actor_id=ev.get("actor_id") or "reconciler",
                                       actor_role=ev.get("actor_role") or "system",
                                       request_id=None)
                        stats["replayed"] += 1 if r.get("result") == "ok" else 0
                        if r.get("result") == "ok":
                            await _finalize_event(db, ev["id"], RESULT_OK)
                        else:
                            await _finalize_event(db, ev["id"], RESULT_REJECTED,
                                                  error_code=r.get("reason"))
                            stats["rejected"] += 1
                else:
                    stats["ambiguous"] += 1
            elif typ in (EV_END, EV_FORCE):
                # cible = plus d'affectation ACTIVE sur from_v pour ce chauffeur
                still = await get_active(db, t, d)
                if not still or still.get("vehicle_id") != from_v:
                    await _finalize_event(db, ev["id"], RESULT_OK); stats["ok"] += 1
                else:
                    res = await db.vehicle_assignments.update_one(
                        {"tenant_id": t, "driver_id": d, "status": STATUS_ACTIVE,
                         "vehicle_id": from_v},
                        {"$set": {"status": STATUS_ENDED, "ended_at": _now(),
                                  "ended_by": ev.get("actor_id"),
                                  "end_reason": ev.get("reason"), "updated_at": _now()}})
                    if res.modified_count == 1:
                        await _finalize_event(db, ev["id"], RESULT_OK); stats["replayed"] += 1
                    else:
                        stats["ambiguous"] += 1
            elif typ == EV_CHANGE:
                if cur and cur.get("vehicle_id") == to_v:
                    await _finalize_event(db, ev["id"], RESULT_OK); stats["ok"] += 1
                elif cur and cur.get("vehicle_id") == from_v:
                    occ = await get_active_by_vehicle(db, t, to_v)
                    if occ and occ.get("driver_id") != d:
                        await _finalize_event(db, ev["id"], RESULT_REJECTED,
                                              error_code="VEHICLE_OCCUPIED"); stats["rejected"] += 1
                    else:
                        try:
                            res = await db.vehicle_assignments.update_one(
                                {"tenant_id": t, "driver_id": d, "status": STATUS_ACTIVE,
                                 "vehicle_id": from_v},
                                {"$set": {"vehicle_id": to_v, "previous_vehicle_id": from_v,
                                          "segment_started_at": _now(), "updated_at": _now()}})
                            if res.modified_count == 1:
                                await _finalize_event(db, ev["id"], RESULT_OK); stats["replayed"] += 1
                            else:
                                stats["ambiguous"] += 1
                        except DuplicateKeyError:
                            await _finalize_event(db, ev["id"], RESULT_REJECTED,
                                                  error_code="VEHICLE_OCCUPIED"); stats["rejected"] += 1
                else:
                    stats["ambiguous"] += 1
            else:
                stats["ambiguous"] += 1
        except Exception as e:  # jamais bloquer la boucle
            logger.warning("reconcile event %s ambiguous: %s", ev.get("id"), type(e).__name__)
            stats["ambiguous"] += 1
    if stats["ambiguous"]:
        logger.warning("vehicle_assignment reconcile: %s ambiguous PENDING left", stats["ambiguous"])
    return stats
