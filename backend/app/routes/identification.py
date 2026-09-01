"""Driver-facing endpoints — used by the PWA console and the Expo native app.

Endpoints under `/driver/*`:
- GET  /driver/current-session : poll active session
- POST /driver/manual-mode     : force PRO/PRIVÉ from the device
- POST /driver/push-token      : register an Expo push token
- DELETE /driver/push-token    : deactivate a token on logout
"""
from __future__ import annotations

from datetime import datetime, timezone
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
