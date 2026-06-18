"""BLE driver identification — tags, detections, sessions, dashboard, settings."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, require_roles
from app.db import get_db
from app import ble_engine

from app.routes._helpers import resolve_driver_id_for_user

router = APIRouter(tags=["ble"])


# ---------- Tags ----------
@router.get("/ble/tags")
async def ble_tags_list(user=Depends(require_roles("admin", "manager"))):
    return await ble_engine.list_tags(get_db())


@router.post("/ble/tags")
async def ble_tags_upsert(payload: dict, user=Depends(require_roles("admin"))):
    if not payload.get("vehicle_id") or not payload.get("identifier"):
        raise HTTPException(400, "vehicle_id et identifier sont requis")
    return await ble_engine.upsert_tag(get_db(), payload)


@router.delete("/ble/tags/{tag_id}")
async def ble_tags_delete(tag_id: str, user=Depends(require_roles("admin"))):
    ok = await ble_engine.delete_tag(get_db(), tag_id)
    if not ok:
        raise HTTPException(404, "Tag introuvable")
    return {"deleted": True}


# ---------- Detections & simulation ----------
@router.post("/ble/detections")
async def ble_ingest(payload: dict, user=Depends(get_current_user)):
    """Ingestion endpoint for the chauffeur PWA / native app.

    Payload accepts either a single detection or `{"detections": [...]}`.
    """
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    items = payload.get("detections")
    if items is None:
        items = [payload]
    if not items:
        raise HTTPException(400, "Aucune détection fournie")
    results = []
    for it in items:
        if not it.get("identifier"):
            continue
        results.append(await ble_engine.ingest_detection(db, driver_id, it))
    return {"count": len(results), "results": results}


@router.post("/ble/simulate")
async def ble_simulate(payload: dict, user=Depends(require_roles("admin"))):
    """Admin tool: simulate a detection for a given driver."""
    db = get_db()
    driver_id = payload.get("driver_id") or await resolve_driver_id_for_user(db, user)
    if not driver_id or not payload.get("identifier"):
        raise HTTPException(400, "driver_id et identifier sont requis")
    rssi = int(payload.get("rssi") or -55)
    return await ble_engine.simulate_detection(db, driver_id, payload["identifier"], rssi)


# ---------- Sessions ----------
@router.get("/ble/sessions")
async def ble_sessions(
    limit: int = 200, status: Optional[str] = None,
    start: Optional[str] = None, end: Optional[str] = None,
    user=Depends(require_roles("admin", "manager")),
):
    return await ble_engine.list_sessions(get_db(), limit=limit, status=status, start=start, end=end)


@router.put("/ble/sessions/{session_id}")
async def ble_session_amend(session_id: str, patch: dict,
                            user=Depends(require_roles("admin", "manager"))):
    try:
        return await ble_engine.amend_session(get_db(), session_id, patch, actor=user.get("email", "?"))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.post("/ble/sessions/{session_id}/resolve")
async def ble_session_resolve(session_id: str, payload: dict,
                              user=Depends(require_roles("admin"))):
    """Admin manually resolves a multi-driver BLE conflict.

    Body: `{winner_driver_id: <driver-id>, source?: 'page'|'header_inbox'}`.
    """
    winner = (payload or {}).get("winner_driver_id")
    source = (payload or {}).get("source") or "page"
    if not winner:
        raise HTTPException(400, "winner_driver_id requis")
    try:
        return await ble_engine.resolve_conflict(
            get_db(), session_id, winner,
            actor=user.get("email", "?"), source=source,
        )
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))


# ---------- Dashboard & settings ----------
@router.get("/ble/dashboard")
async def ble_dashboard(start: Optional[str] = None, end: Optional[str] = None,
                        user=Depends(require_roles("admin", "manager"))):
    return await ble_engine.dashboard_kpis(get_db(), start=start, end=end)


@router.get("/ble/settings")
async def ble_settings_get(user=Depends(require_roles("admin", "manager"))):
    return await ble_engine.get_ble_settings(get_db())


@router.put("/ble/settings")
async def ble_settings_put(payload: dict, user=Depends(require_roles("admin"))):
    db = get_db()
    allowed = {k for k in ble_engine.DEFAULT_SETTINGS}
    update = {k: payload[k] for k in payload if k in allowed}
    if not update:
        raise HTTPException(400, "Aucun champ valide")
    await db.settings.update_one({"id": "default"}, {"$set": update}, upsert=True)
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble_settings", "action": "update",
        "actor": user.get("email"), "payload": update,
    })
    return await ble_engine.get_ble_settings(db)
