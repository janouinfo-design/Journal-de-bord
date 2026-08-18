"""Notification preferences + dispatcher endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.notifications_service import (
    dispatch,
    event_catalog_public,
    get_preferences,
    set_preferences,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications/catalog")
async def notifications_catalog(user=Depends(get_current_user)):
    """List of supported events + default channels — used by the preferences UI."""
    return {"events": event_catalog_public()}


@router.get("/notifications/preferences")
async def notifications_get_prefs(user=Depends(get_current_user)):
    """Get the current user's notification preferences (push/email/sms per event)."""
    return await get_preferences(get_db(), user["id"])


@router.put("/notifications/preferences")
async def notifications_put_prefs(payload: dict, user=Depends(get_current_user)):
    """Update the current user's notification preferences."""
    return await set_preferences(get_db(), user["id"], payload or {})


@router.post("/notifications/test")
async def notifications_test(payload: dict, user=Depends(require_roles("admin"))):
    """Admin-only: trigger a test notification for a known event.

    Body: `{event: 'ble.conflict'|..., user_ids?: [], driver_ids?: [], payload?: {...}}`
    """
    event = (payload or {}).get("event")
    if not event:
        raise HTTPException(400, "event requis")
    return await dispatch(
        event,
        (payload or {}).get("payload") or {"vehicle_plate": "TEST-99", "session_id": "test"},
        user_ids=(payload or {}).get("user_ids"),
        driver_ids=(payload or {}).get("driver_ids"),
    )


@router.get("/notifications/inbox")
async def notifications_inbox(unread_only: bool = False, limit: int = 30,
                              user=Depends(get_current_user)):
    """Centre de notifications in-app de l'utilisateur courant (isolé par tenant)."""
    db = get_db()
    q: dict = {"user_id": user["id"]}
    if unread_only:
        q["read"] = False
    items = await db.user_notifications.find(
        q, {"_id": 0, "tenant_id": 0, "dedup_key": 0}) \
        .sort("created_at", -1).to_list(max(1, min(limit, 100)))
    unread = await db.user_notifications.count_documents({"user_id": user["id"], "read": False})
    return {"items": items, "unread": unread}


@router.post("/notifications/inbox/{notif_id}/read")
async def notifications_mark_read(notif_id: str, user=Depends(get_current_user)):
    r = await get_db().user_notifications.update_one(
        {"id": notif_id, "user_id": user["id"]},
        {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}})
    if r.matched_count == 0:
        raise HTTPException(404, "Notification introuvable")
    return {"ok": True}


@router.post("/notifications/inbox/read-all")
async def notifications_mark_all_read(user=Depends(get_current_user)):
    r = await get_db().user_notifications.update_many(
        {"user_id": user["id"], "read": False},
        {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}})
    return {"ok": True, "updated": r.modified_count}
