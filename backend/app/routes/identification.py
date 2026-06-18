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
