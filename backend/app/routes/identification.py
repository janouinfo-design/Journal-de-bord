"""Driver-facing endpoints — used by the PWA console and the Expo native app.

Endpoints under `/driver/*`:
- GET  /driver/current-session : poll active session
- POST /driver/manual-mode     : force PRO/PRIVÉ from the device
- POST /driver/push-token      : register an Expo push token
- DELETE /driver/push-token    : deactivate a token on logout
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import get_db
from app import ble_engine

from app.routes._helpers import resolve_driver_id_for_user
from app.vehicle_access import (get_authorized_vehicles_for_driver,
                                get_authorized_vehicle_ids_for_driver)

router = APIRouter(tags=["identification"])


def _private_odometer_supported(
    model,
    capability,
    tracker_id,
    *,
    generalized: bool,
) -> bool:
    """Disponibilité du compteur privé exposée à l'app chauffeur.

    Legacy : comportement historique inchangé (`field_validated`).
    Rollout compte+modèle : réutilise la validation technique centrale,
    fail-closed et propre au tracker.
    """
    if generalized:
        from app.odometer_capability import vehicle_private_profile_ready

        return vehicle_private_profile_ready(
            model,
            capability,
            tracker_id=tracker_id,
        )

    return bool(
        capability
        and getattr(capability, "field_validated", False)
    )


@router.get("/driver/vehicles")
async def driver_vehicles(user=Depends(get_current_user)):
    """Véhicules que le chauffeur connecté a le DROIT d'utiliser.

    Source d'autorité : vehicle_access (ALL/SELECTED/SINGLE) — tenant issu de
    l'identité authentifiée, jamais d'un paramètre client."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    acc, vehicles = await get_authorized_vehicles_for_driver(db, driver_id)
    return {"access_mode": acc["mode"],
            "default_vehicle_id": acc["default_vehicle_id"],
            "vehicles": [{"id": v["id"], "label": v.get("label"),
                          "plate": v.get("plate"), "model": v.get("model")}
                         for v in vehicles]}


@router.get("/driver/current-session")
async def driver_current_session(user=Depends(get_current_user)):
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    sess = await ble_engine.get_current_session(db, driver_id)
    return {"session": sess}


@router.get("/driver/fleet-tags")
async def driver_fleet_tags(user=Depends(get_current_user)):
    """Return all BLE tags registered for the tenant, enriched with vehicle info.

    Used by the chauffeur PWA to display the list of expected beacons (with a
    "Test this tag" button) without exposing admin-only fields.
    """
    db = get_db()
    tags = await db.ble_tags.find(
        {"tenant_id": "default"}, {"_id": 0},
    ).to_list(500)
    # Un chauffeur ne voit que les tags des véhicules de son périmètre autorisé.
    if user.get("role") == "driver":
        drv_id = await resolve_driver_id_for_user(db, user)
        if drv_id:
            allowed = set(await get_authorized_vehicle_ids_for_driver(db, drv_id))
            tags = [t for t in tags
                    if not t.get("vehicle_id") or t["vehicle_id"] in allowed]
    # Bulk-load vehicles to avoid N+1
    vids = list({t.get("vehicle_id") for t in tags if t.get("vehicle_id")})
    vehicles = {}
    if vids:
        async for v in db.vehicles.find(
            {"id": {"$in": vids}}, {"_id": 0, "id": 1, "plate": 1, "model": 1},
        ):
            vehicles[v["id"]] = v
    out = []
    for t in tags:
        v = vehicles.get(t.get("vehicle_id")) or {}
        out.append({
            "id": t.get("id"),
            "identifier": t.get("identifier"),
            "identifier_raw": t.get("identifier_raw") or t.get("identifier"),
            "label": t.get("label"),
            "vehicle_plate": v.get("plate"),
            "vehicle_model": v.get("model"),
        })
    # Sort by vehicle plate for readability
    out.sort(key=lambda x: (x.get("vehicle_plate") or "", x.get("identifier") or ""))
    return out


@router.post("/driver/manual-mode")
async def driver_manual_mode(payload: dict, user=Depends(get_current_user)):
    mode = payload.get("mode")
    if mode not in ("professional", "personal"):
        raise HTTPException(400, "mode doit être 'professional' ou 'personal'")
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    try:
        return await ble_engine.driver_set_mode(db, driver_id, mode, actor=user.get("email", "?"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


class ClaimIn(BaseModel):
    vehicle_id: str
    client_timestamp: Optional[str] = None


@router.post("/driver/claim")
async def driver_claim(payload: ClaimIn, user=Depends(get_current_user)):
    """« Je conduis » — confirmation explicite du conducteur (source APP).

    Atomique côté serveur : un seul conducteur actif par véhicule ; toute
    contradiction crée un conflit explicite, jamais un écrasement silencieux.
    """
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    # Source d'autorité : périmètre véhicules du chauffeur (403 hors périmètre,
    # même pour un véhicule du même tenant).
    authorized = await get_authorized_vehicle_ids_for_driver(db, driver_id)
    if payload.vehicle_id not in authorized:
        raise HTTPException(403, "Véhicule non autorisé pour ce chauffeur")
    try:
        result = await ble_engine.claim_driving(
            db, driver_id, payload.vehicle_id, actor=user.get("email", "?"),
            client_timestamp=payload.client_timestamp)
    except LookupError as e:
        raise HTTPException(404, str(e))

    # Projection de la session APP confirmée vers Navixy.
    # La session Journal reste autoritaire : une panne Navixy ne doit jamais
    # annuler ou invalider la confirmation locale.
    if result.get("status") == "confirmed":
        try:
            from app import navixy_driver_sync as nds
            session = result.get("session") or {}
            result["navixy_sync"] = await nds.sync_claim(
                db,
                driver_id,
                payload.vehicle_id,
                session_id=session.get("id"),
                actor=user.get("email", "?"),
            )
        except Exception:
            result["navixy_sync"] = {
                "status": "error",
                "error": "HOOK_FAILURE",
            }

    return result


@router.post("/driver/stop")
async def driver_stop(user=Depends(get_current_user)):
    """« Je m'arrête » — clôture volontaire de la session active du chauffeur.
    Idempotent : sans session active → réponse propre (pas d'erreur 500).
    Un chauffeur ne peut clôturer que SA session, dans SON tenant."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    result = await ble_engine.stop_driving(
        db, driver_id, actor=user.get("email", "?")
    )

    # Désaffectation Navixy uniquement après une vraie clôture APP.
    # sync_stop() vérifie également que Navixy contient encore CE chauffeur
    # avant toute tentative de désaffectation.
    if result.get("stopped"):
        try:
            from app import navixy_driver_sync as nds
            session = result.get("session") or {}
            vehicle_id = session.get("vehicle_id")
            if vehicle_id:
                result["navixy_sync"] = await nds.sync_stop(
                    db,
                    driver_id,
                    vehicle_id,
                    session_id=session.get("id"),
                    actor=user.get("email", "?"),
                )
        except Exception:
            result["navixy_sync"] = {
                "status": "error",
                "error": "HOOK_FAILURE",
            }

    return result


# ---------- Phase 2 — Bascule Privé / Professionnel (backend autoritaire) ----------
@router.get("/driver/private-mode")
async def driver_private_mode_get(user=Depends(get_current_user)):
    """État courant Privé/Professionnel du véhicule de la session du chauffeur.
    Retour : {state, allowed, reason, vehicle_id, tracker_id, last_transition_at, capability}.
    Aucune position exposée. Backend autoritaire (gate centrale fail-closed)."""
    from app import private_mode_engine as pm
    from app import private_mode_gate as gate
    from app.tenant_context import get_tenant_doc
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    # Fail-closed niveau 1/2 : feature globale + kill switch AVANT toute résolution.
    if not gate.feature_enabled():
        return {"state": pm.UNKNOWN, "allowed": False, "reason": gate.R_FEATURE_DISABLED,
                "can_switch": False, "can_switch_reason": gate.R_FEATURE_DISABLED,
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}
    if await gate.kill_switch_active(db):
        return {"state": pm.UNKNOWN, "allowed": False, "reason": gate.R_KILL_SWITCH,
                "can_switch": False, "can_switch_reason": gate.R_KILL_SWITCH,
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}
    sess = await ble_engine.get_current_session(db, driver_id)
    if not sess or not sess.get("vehicle_id"):
        return {"state": pm.UNKNOWN, "allowed": False, "reason": gate.R_NO_VEHICLE,
                "can_switch": False, "can_switch_reason": gate.R_NO_VEHICLE,
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}
    vehicle_id = sess["vehicle_id"]
    vehicle = await db.vehicles.find_one({"id": vehicle_id, "tenant_id": tenant_id}, {"_id": 0}) or {}
    tracker_id = vehicle.get("navixy_tracker_id")
    model = pm.resolve_model(vehicle.get("model"))
    vc = await pm.resolve_vehicle_capability(db, tracker_id, model)
    decision = await gate.can_use_private_mode(
        db, tenant_id=tenant_id, tenant_doc=get_tenant_doc(tenant_id),
        vehicle_doc=vehicle, capability=vc, driver_id=driver_id,
    )
    st = await pm.get_mode_state(db, vehicle_id)
    # Résolution READ-ONLY :
    # - transition PENDING normale ;
    # - récupération tardive d'un UNKNOWN/TIMEOUT récent si une preuve stricte
    #   (device response réellement exposée / télémétrie) est arrivée après le timeout.
    if pm.confirmation_resolution_needed(st):
        st = await pm.resolve_pending_confirmation(db, vehicle_id, tenant_id)
    # Capacité odomètre privé :
    # - legacy : preuve terrain historique `field_validated`;
    # - rollout compte+modèle : profil technique complet et propre au tracker.
    # Même source de vérité que la gate généralisée, jamais le modèle seul.
    private_odo_ok = _private_odometer_supported(
        model,
        vc,
        tracker_id,
        generalized=gate.account_model_gate_enabled(),
    )

    # --- can_switch : capacité d'ACTION (distincte de l'éligibilité `allowed`) ---
    # allowed  = chauffeur/véhicule éligible au pilote (gate fail-closed).
    # can_switch = le changement de mode est réellement exécutable MAINTENANT.
    # NOTE UX (finition boutons) : on NE bloque PLUS le switch pendant une transition
    # (PENDING/REQUESTED). Le blocage de 5 min était inutile et empêchait la
    # récupération rapide vers Professionnel après une demande Privé. Le backend
    # gère désormais le supersede (voir request_mode) : Professionnel reste TOUJOURS
    # actionnable. can_switch dépend donc uniquement de l'éligibilité + écriture device.
    allowed = decision["allowed"]
    state_now = st.get("state", pm.UNKNOWN)
    device_write = pm.device_write_enabled()
    can_switch = bool(allowed and device_write)
    if not allowed:
        can_switch_reason = decision["reason"]
    elif not device_write:
        can_switch_reason = gate.R_DEVICE_WRITE_DISABLED
    else:
        can_switch_reason = None
    # Message métier honnête si une commande est en attente de confirmation :
    # « Commande Privé/Professionnel envoyée » (jamais « actif »).
    pending_message = None
    if state_now == pm.PENDING_CONFIRMATION:
        rt = st.get("requested_target")
        pending_message = pm._command_sent_message(rt) if rt in (pm.PRIVATE, pm.BUSINESS) else None
    return {
        "state": state_now,
        "pending": st.get("state") == pm.PENDING_CONFIRMATION,
        "pending_message": pending_message,
        "confirmation_source": st.get("confirmation_source"),
        "allowed": allowed,
        "reason": decision["reason"],
        "can_switch": can_switch,
        "can_switch_reason": can_switch_reason,
        "vehicle_id": vehicle_id,
        "tracker_id": tracker_id,
        "vehicle_plate": vehicle.get("plate"),
        "private_odometer_supported": private_odo_ok,
        "private_distance_km": st.get("private_distance_km"),
        "last_transition_at": st.get("updated_at"),
        # --- Historique de transition (jamais perdu au timeout) ---
        "transition_result": st.get("transition_result"),       # CONFIRMED|TIMEOUT|None
        "requested_target": st.get("requested_target"),         # cible demandée si dispo
        "last_command": st.get("last_command"),                 # dernière commande envoyée
        "command_sent_at": st.get("command_sent_at"),           # horodatage envoi
        "odometer_snapshot_status": st.get("odometer_snapshot_status"),  # OK|UNAVAILABLE|INVALID
    }


class PrivateModeIn(BaseModel):
    mode: str  # "PRIVATE" | "BUSINESS"


@router.post("/driver/private-mode")
async def driver_private_mode_set(payload: PrivateModeIn, user=Depends(get_current_user)):
    """Intention métier de bascule : {"mode": "PRIVATE"|"BUSINESS"}.
    Le backend résout véhicule/tracker/capability, applique la commande (GATED) et confirme.
    Aucun tracker_id/raw command/tenant libre accepté depuis le frontend."""
    from app import private_mode_engine as pm
    mode = (payload.mode or "").upper()
    if mode not in (pm.PRIVATE, pm.BUSINESS):
        raise HTTPException(400, "mode doit être 'PRIVATE' ou 'BUSINESS'")
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    async def _resolve_session(_db, _drv):
        return await ble_engine.get_current_session(_db, _drv)

    tenant_id = user.get("tenant_id") or "default"
    res = await pm.request_mode(db, driver_id, mode, actor=user.get("email", "?"),
                                resolve_session=_resolve_session, tenant_id=tenant_id)
    # Refus d'ÉLIGIBILITÉ (gate) -> code HTTP explicite (jamais un simple 500).
    if res.get("ok") is False and res.get("allowed") is False and res.get("http"):
        raise HTTPException(res["http"], res.get("reason") or "PRIVATE_MODE_NOT_ALLOWED")
    # Refus de CAPACITÉ D'ACTION : écriture device coupée (DEVICE_WRITE=0). Garde-fou
    # backend (le frontend désactive normalement déjà le bouton via can_switch=False).
    # Aucun état transitoire n'a été créé ; l'état confirmé précédent est conservé.
    from app import private_mode_gate as _gate
    if res.get("ok") is False and res.get("reason") == _gate.R_DEVICE_WRITE_DISABLED:
        raise HTTPException(_gate.HTTP_BY_REASON[_gate.R_DEVICE_WRITE_DISABLED],
                            _gate.R_DEVICE_WRITE_DISABLED)
    # jamais de secret/raw device dans la réponse ; statuts métier uniquement
    return res


@router.get("/driver/my-vehicle")
async def driver_my_vehicle(user=Depends(get_current_user)):
    """Véhicule actuel (session en cours) ou dernier véhicule utilisé.
    Données réelles uniquement — aucun champ inventé (pas de SoC/carburant)."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    sess = await ble_engine.get_current_session(db, driver_id)
    current = bool(sess)
    if not sess:
        last = await db.driver_sessions.find_one(
            {"driver_id": driver_id}, {"_id": 0}, sort=[("started_at", -1)])
        if not last:
            return {"vehicle": None, "current": False, "session": None}
        vehicle = await db.vehicles.find_one({"id": last["vehicle_id"]}, {"_id": 0}) or {}
        sess = {**last, "vehicle": {"id": vehicle.get("id"), "plate": vehicle.get("plate"),
                                    "model": vehicle.get("model")}}
    return {"vehicle": sess.get("vehicle"), "current": current,
            "session": {k: sess.get(k) for k in (
                "id", "status", "started_at", "ended_at", "identification_source",
                "active_driver", "mobile_override", "confidence")}}


class SosIn(BaseModel):
    note: Optional[str] = None            # contexte libre saisi par le chauffeur (optionnel)
    share_location: Optional[bool] = True  # le chauffeur consent au partage de position (urgence)


@router.post("/driver/sos")
async def driver_sos(payload: SosIn, user=Depends(get_current_user)):
    """Déclenche une alerte SOS. Persiste l'alerte + notifie les gestionnaires/admins.

    Contexte capturé (si disponible) : chauffeur, véhicule actif, horodatage. La POSITION
    exacte n'est PAS calculée ici (backend n'a pas le GPS temps réel du device de façon fiable) ;
    on enregistre le véhicule/tracker pour que le gestionnaire localise via la plateforme.
    En cas de SOS, la sécurité prime : la position du véhicule peut être consultée par le
    gestionnaire même en mode Privé (décision produit ; l'app en informe le chauffeur).
    Anti-double-envoi : déduplication 60 s par chauffeur.
    """
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0, "name": 1}) or {}
    sess = await ble_engine.get_current_session(db, driver_id)
    vehicle_id = sess.get("vehicle_id") if sess else None
    vehicle = await db.vehicles.find_one(
        {"id": vehicle_id, "tenant_id": tenant_id}, {"_id": 0, "plate": 1, "navixy_tracker_id": 1}
    ) if vehicle_id else None

    now = datetime.now(timezone.utc)
    # Anti-double-envoi : une alerte active récente (<60s) pour ce chauffeur -> renvoyer l'existante.
    recent = await db.sos_alerts.find_one(
        {"tenant_id": tenant_id, "driver_id": driver_id, "status": "active",
         "created_at": {"$gte": (now - timedelta(seconds=60)).isoformat()}},
        {"_id": 0, "id": 1}, sort=[("created_at", -1)])
    if recent:
        return {"ok": True, "sos_id": recent["id"], "duplicate": True,
                "message": "Alerte déjà en cours d'envoi."}

    import uuid as _uuid
    sos_id = str(_uuid.uuid4())
    doc = {
        "id": sos_id, "tenant_id": tenant_id, "driver_id": driver_id,
        "driver_name": driver.get("name"),
        "vehicle_id": vehicle_id, "vehicle_plate": (vehicle or {}).get("plate"),
        "tracker_id": (vehicle or {}).get("navixy_tracker_id"),
        "note": (payload.note or "")[:500],
        "share_location": bool(payload.share_location),
        "status": "active", "created_at": now.isoformat(), "created_by": user.get("email"),
    }
    await db.sos_alerts.insert_one(doc)

    # Notifie les gestionnaires/admins via le pipeline existant (push/email/sms + in-app).
    try:
        from app import notifications_service as notif
        await notif.dispatch("sos.triggered", {
            "sos_id": sos_id, "driver_id": driver_id, "driver_name": driver.get("name"),
            "vehicle_id": vehicle_id, "vehicle_plate": (vehicle or {}).get("plate"),
            "has_location": bool(vehicle_id),
        }, tenant_id=tenant_id, dedup_key=f"sos:{sos_id}")
    except Exception:
        # l'alerte est persistée quoi qu'il arrive ; l'échec de notif ne casse pas le SOS
        pass

    return {"ok": True, "sos_id": sos_id, "duplicate": False,
            "vehicle_selected": bool(vehicle_id),
            "message": "Alerte SOS envoyée."}



@router.get("/driver/my-vehicles")
async def driver_my_vehicles(user=Depends(get_current_user)):
    """Véhicules AFFECTÉS au chauffeur (sélection manuelle, mode sans BLE).
    Ne retourne JAMAIS toute la flotte — uniquement les véhicules assignés au chauffeur,
    dans son tenant. Champs non sensibles seulement (aucune position)."""
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    from app.assignments import driver_vehicle_ids
    ids = await driver_vehicle_ids(db, driver_id)
    # Intersection avec le périmètre autorisé (vehicle_access ALL/SELECTED/SINGLE) :
    # jamais un véhicule hors périmètre, même s'il reste une assignment historique.
    allowed = set(await get_authorized_vehicle_ids_for_driver(db, driver_id))
    ids = [i for i in ids if i in allowed]
    if not ids:
        return {"vehicles": []}
    rows = await db.vehicles.find(
        {"id": {"$in": ids}, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "plate": 1, "model": 1},
    ).to_list(500)
    # ordre stable par plaque
    rows.sort(key=lambda v: (v.get("plate") or ""))
    return {"vehicles": rows}



@router.get("/driver/km-summary")
async def driver_km_summary(
    period: str = Query("today", regex="^(today|week|month)$"),
    user=Depends(get_current_user),
):
    """Km Pro / Km Privé du chauffeur pour SON véhicule actif, sur la période demandée.

    - Source = trajets réels (`trips`), agrégés par classification. AUCUN calcul GPS mobile.
    - Périodes (bornes en Europe/Zurich, timezone chauffeur — cf. mode Privé) :
        today = 00:00 (jour courant) -> maintenant
        week  = lundi 00:00 -> maintenant
        month = 1er du mois 00:00 -> maintenant
      Les bornes locales sont converties en UTC pour interroger `trips` (start_time ISO UTC).
    - Scoping strict : véhicule de la session active du chauffeur + son tenant.
    - Si pas de véhicule actif -> valeurs None (l'app affiche « — », jamais une fausse valeur).
    Retour : {period, period_label, vehicle_id, pro_km, private_km, available}.

    NOTE (km privés & AVL16) : `private_km` agrège ici les trajets classés « personal »
    disposant d'une distance. En mode Privé, la position GPS est masquée ; les km privés
    fiables proviennent de l'odomètre matériel (AVL16), pas des points GPS. Le branchement
    AVL16 -> km privés est un chantier BACKEND séparé (hors de ce ticket UI).
    """
    from zoneinfo import ZoneInfo
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    sess = await ble_engine.get_current_session(db, driver_id)
    vehicle_id = sess.get("vehicle_id") if sess else None

    # Instant courant en heure locale chauffeur (Europe/Zurich).
    _TZ = ZoneInfo("Europe/Zurich")
    now_local = datetime.now(timezone.utc).astimezone(_TZ)
    _MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                  "août", "septembre", "octobre", "novembre", "décembre"]
    if period == "month":
        period_label = f"{_MONTHS_FR[now_local.month - 1].capitalize()} {now_local.year}"
    elif period == "week":
        monday = now_local - timedelta(days=now_local.weekday())
        sunday = monday + timedelta(days=6)
        period_label = (f"{monday.day} – {sunday.day} {_MONTHS_FR[sunday.month - 1]}")
    else:
        period_label = "Aujourd'hui"

    if not vehicle_id:
        return {"period": period, "period_label": period_label, "vehicle_id": None,
                "pro_km": None, "private_km": None, "available": False}

    # Bornes de période en LOCAL (Europe/Zurich) puis converties en UTC pour la requête.
    if period == "today":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        base = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = base - timedelta(days=now_local.weekday())  # lundi 00:00 local
    else:  # month
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = datetime.now(timezone.utc)
    start_iso = start_utc.isoformat()

    # Km PRO = trajets professionnels réels (inchangé).
    q_pro = {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "start_time": {"$gte": start_iso}}
    trips_pro = await db.trips.find(
        q_pro, {"_id": 0, "distance_km": 1, "classification": 1}).limit(20000).to_list(20000)
    pro = round(sum((t.get("distance_km") or 0) for t in trips_pro
                    if t.get("classification") == "professional"), 1)

    # Km PRIVÉ = source AVL16 (sessions) avec CUTOVER + fallback GPS legacy (intervalles
    # disjoints, jamais de double comptage). Provenance explicite. Voir app.private_mileage.
    from app import private_mileage as _pm

    async def _gps_personal_km(s_utc, e_utc):
        """Fallback legacy : somme des trajets 'personal' (distance GPS) sur [s_utc, e_utc]."""
        qq = {"tenant_id": tenant_id, "vehicle_id": vehicle_id,
              "classification": "personal",
              "start_time": {"$gte": s_utc.isoformat(), "$lt": e_utc.isoformat()}}
        docs = await db.trips.find(qq, {"_id": 0, "distance_km": 1}).limit(20000).to_list(20000)
        return round(sum((d.get("distance_km") or 0) for d in docs), 1)

    agg = await _pm.aggregate_private_km(
        db, tenant_id=tenant_id, vehicle_id=vehicle_id,
        start_utc=start_utc, end_utc=end_utc, gps_fallback_km=_gps_personal_km)

    return {"period": period, "period_label": period_label, "vehicle_id": vehicle_id,
            "pro_km": pro, "private_km": agg["private_km"],
            "private_km_source": agg["private_km_source"], "available": True}




@router.get("/driver/vehicle/odometer")
async def driver_vehicle_odometer(
    vehicle_id: Optional[str] = Query(default=None),
    user=Depends(get_current_user),
):
    """Lecture READ-ONLY de l'odomètre matériel du véhicule (audit odomètre).

    Sécurité :
    - tenant scoping ('default') ;
    - anti-IDOR : si `vehicle_id` est fourni, il doit correspondre au véhicule de
      la session en cours du chauffeur (un chauffeur ne lit pas un véhicule tiers) ;
    - sinon, on utilise le véhicule de la session courante.

    Honnêteté des données :
    - jamais de 0 km fictif ; si indisponible -> {odometer_km: null, status: "UNAVAILABLE"}.
    - aucune estimation GPS : lecture du compteur Navixy uniquement.
    """
    from app.odometer_audit import read_vehicle_odometer

    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    # Véhicule de la session courante (source de vérité pour ce chauffeur).
    sess = await ble_engine.get_current_session(db, driver_id)
    current_vehicle_id = sess.get("vehicle_id") if sess else None

    target_vehicle_id = vehicle_id or current_vehicle_id
    if not target_vehicle_id:
        return {"vehicle_id": None, "odometer_km": None, "source": None,
                "status": "UNAVAILABLE", "reason": "no_active_vehicle"}

    # Anti-IDOR : refuser un véhicule qui n'est pas celui de la session du chauffeur.
    if vehicle_id and current_vehicle_id and vehicle_id != current_vehicle_id:
        raise HTTPException(403, "Accès refusé à ce véhicule")

    vehicle = await db.vehicles.find_one(
        {"id": target_vehicle_id, "tenant_id": "default"}, {"_id": 0})
    if not vehicle:
        raise HTTPException(404, "Véhicule introuvable")

    tracker_id = vehicle.get("navixy_tracker_id")
    reading = await read_vehicle_odometer(tracker_id)
    return {"vehicle_id": target_vehicle_id,
            "vehicle_plate": vehicle.get("plate"), **reading}



@router.get("/driver/my-profile")
async def driver_my_profile(user=Depends(get_current_user)):
    """Profil mobile : compte, tag BLE associé, dernière détection. Jamais de mot de passe."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0}) if driver_id else None
    last_det = None
    if driver_id:
        d = await db.ble_detections.find_one(
            {"driver_id": driver_id, "ignored": False}, {"_id": 0, "ts": 1},
            sort=[("ts", -1)])
        last_det = d.get("ts") if d else None
    return {
        "name": (driver or {}).get("name") or user.get("name"),
        "email": user.get("email"),
        "account_active": user.get("active", True) is not False,
        "must_change_password": bool(user.get("must_change_password")),
        "driver_active": ((driver or {}).get("active", True) is not False) if driver else None,
        "ble_tag_associated": bool((driver or {}).get("ble_id")),
        "last_ble_detection": last_det,
    }


# ---------- Mobile push notifications (Expo Push token registration) ----------
class PushTokenIn(BaseModel):
    token: str
    platform: Optional[str] = None  # "ios" | "android" | "expo"
    device_id: Optional[str] = None


@router.post("/driver/push-token")
async def register_push_token(payload: PushTokenIn, user=Depends(get_current_user)):
    """Register or refresh the Expo push token for the authenticated user.

    Behaviour:
    - Upsert keyed by `token` so multiple devices can coexist.
    - If a different user previously registered the same token, the new
      registration wins (token follows the device, not the user).
    - Re-registering reactivates a previously deactivated token.
    """
    if not payload.token or len(payload.token) < 10:
        raise HTTPException(400, "Push token invalide")
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "user_id": user["id"],
        "user_email": user.get("email"),
        "driver_id": driver_id,
        "tenant_id": "default",
        "token": payload.token,
        "platform": payload.platform,
        "device_id": payload.device_id,
        "active": True,
        "updated_at": now,
        "deactivated_at": None,
    }
    existing = await db.push_tokens.find_one({"token": payload.token}, {"_id": 0})
    if existing:
        await db.push_tokens.update_one(
            {"token": payload.token},
            {"$set": record},
        )
    else:
        record["created_at"] = now
        await db.push_tokens.insert_one(record)
    return {"ok": True, "token": payload.token, "active": True}


@router.delete("/driver/push-token")
async def delete_push_token(token: str = Query(...), user=Depends(get_current_user)):
    """Deactivate a push token (soft-delete). Used on explicit user logout."""
    db = get_db()
    res = await db.push_tokens.update_one(
        {"token": token, "user_id": user["id"]},
        {"$set": {"active": False,
                  "deactivated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Token introuvable")
    return {"ok": True}
