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

router = APIRouter(tags=["identification"])


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
    try:
        return await ble_engine.claim_driving(
            db, driver_id, payload.vehicle_id, actor=user.get("email", "?"),
            client_timestamp=payload.client_timestamp)
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.post("/driver/stop")
async def driver_stop(user=Depends(get_current_user)):
    """« Je m'arrête » — clôture volontaire de la session active du chauffeur.
    Idempotent : sans session active → réponse propre (pas d'erreur 500).
    Un chauffeur ne peut clôturer que SA session, dans SON tenant."""
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    return await ble_engine.stop_driving(db, driver_id, actor=user.get("email", "?"))


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
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}
    if await gate.kill_switch_active(db):
        return {"state": pm.UNKNOWN, "allowed": False, "reason": gate.R_KILL_SWITCH,
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}
    sess = await ble_engine.get_current_session(db, driver_id)
    if not sess or not sess.get("vehicle_id"):
        return {"state": pm.UNKNOWN, "allowed": False, "reason": gate.R_NO_VEHICLE,
                "vehicle_id": None, "tracker_id": None, "last_transition_at": None,
                "private_odometer_supported": False}
    vehicle_id = sess["vehicle_id"]
    vehicle = await db.vehicles.find_one({"id": vehicle_id, "tenant_id": tenant_id}, {"_id": 0}) or {}
    tracker_id = vehicle.get("navixy_tracker_id")
    model = pm.resolve_model(vehicle.get("model"))
    vc = await pm.resolve_vehicle_capability(db, tracker_id, model)
    decision = await gate.can_use_private_mode(
        db, tenant_id=tenant_id, tenant_doc=get_tenant_doc(tenant_id),
        vehicle_doc=vehicle, capability=vc,
    )
    st = await pm.get_mode_state(db, vehicle_id)
    # Si une bascule est en attente de confirmation, tenter de la résoudre (télémétrie, READ-ONLY).
    if st.get("state") == pm.PENDING_CONFIRMATION:
        st = await pm.resolve_pending_confirmation(db, vehicle_id, tenant_id)
    # capacité odomètre privé : field_validated -> km privés garantis (jamais inventés)
    private_odo_ok = bool(vc and getattr(vc, "field_validated", False))
    return {
        "state": st.get("state", pm.UNKNOWN),
        "pending": st.get("state") == pm.PENDING_CONFIRMATION,
        "confirmation_source": st.get("confirmation_source"),
        "allowed": decision["allowed"],
        "reason": decision["reason"],
        "vehicle_id": vehicle_id,
        "tracker_id": tracker_id,
        "vehicle_plate": vehicle.get("plate"),
        "private_odometer_supported": private_odo_ok,
        "private_distance_km": st.get("private_distance_km"),
        "last_transition_at": st.get("updated_at"),
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
    # Refus d'autorisation -> code HTTP explicite (jamais un simple 500).
    if res.get("ok") is False and res.get("allowed") is False and res.get("http"):
        raise HTTPException(res["http"], res.get("reason") or "PRIVATE_MODE_NOT_ALLOWED")
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
    period: str = Query("today", regex="^(today|month)$"),
    user=Depends(get_current_user),
):
    """Km Pro / Km Privé du chauffeur pour SON véhicule actif, sur la période demandée.

    - Source = trajets réels (`trips`), agrégés par classification. AUCUN calcul GPS mobile.
    - Scoping strict : véhicule de la session active du chauffeur + son tenant.
    - Si pas de véhicule actif -> valeurs None (l'app affiche « — », jamais une fausse valeur).
    Retour : {period, vehicle_id, pro_km, private_km, available}.
    """
    db = get_db()
    tenant_id = user.get("tenant_id") or "default"
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")

    sess = await ble_engine.get_current_session(db, driver_id)
    vehicle_id = sess.get("vehicle_id") if sess else None
    now = datetime.now(timezone.utc)
    _MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                  "août", "septembre", "octobre", "novembre", "décembre"]
    period_label = (f"{_MONTHS_FR[now.month - 1].capitalize()} {now.year}"
                    if period == "month" else "Aujourd'hui")
    if not vehicle_id:
        return {"period": period, "period_label": period_label, "vehicle_id": None,
                "pro_km": None, "private_km": None, "available": False}

    # Bornes de période (UTC).
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_iso = start.isoformat()

    # Trajets du VÉHICULE ACTIF, tenant scopé, sur la période.
    q = {"tenant_id": tenant_id, "vehicle_id": vehicle_id, "start_time": {"$gte": start_iso}}
    trips = await db.trips.find(
        q, {"_id": 0, "distance_km": 1, "classification": 1}).limit(20000).to_list(20000)

    pro = round(sum((t.get("distance_km") or 0) for t in trips
                    if t.get("classification") == "professional"), 1)
    priv = round(sum((t.get("distance_km") or 0) for t in trips
                     if t.get("classification") == "personal"), 1)
    return {"period": period, "period_label": period_label, "vehicle_id": vehicle_id,
            "pro_km": pro, "private_km": priv, "available": True}




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
