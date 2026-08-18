"""Global settings, schedules and privacy enforcement controls."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.emailer import is_smtp_configured, send_test_email
from app.privacy_enforcer import enforce_all_vehicles, kill_switch, list_states
from app.privacy_scan import scan_all_vehicles, scan_vehicle
from app.rules import apply_rules_to_all, _get_schedule_for

from app.routes._helpers import get_settings_doc, normalize_schedule

router = APIRouter(tags=["settings"])


# ---------- Global settings ----------
class SettingsIn(BaseModel):
    mode: str  # A | B | C (legacy) — current values: mixte | masked


@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    db = get_db()
    return await get_settings_doc(db)


@router.put("/settings")
async def update_settings(payload: SettingsIn, user=Depends(require_roles("admin", "manager"))):
    mode = payload.mode
    if mode in ("A", "B"):
        mode = {"A": "mixte", "B": "masked"}[mode]
    if mode == "C":
        raise HTTPException(
            400,
            "Mode C supprimé — utilisez le mode véhicule 'Toujours professionnel' à la place",
        )
    if mode not in ("mixte", "masked"):
        raise HTTPException(400, "Mode invalide")
    db = get_db()
    new = {"id": "default", "mode": mode}
    await db.settings.update_one({"id": "default"}, {"$set": new}, upsert=True)
    await apply_rules_to_all(db)
    from app.audit import log_audit
    await log_audit("settings.update", user, {"mode": mode})
    return new


# ---------- SMTP (test d'envoi) ----------
@router.get("/settings/smtp-status")
async def smtp_status(user=Depends(require_roles("admin"))):
    return {
        "configured": is_smtp_configured(),
        "host": os.environ.get("SMTP_HOST") or None,
        "port": int(os.environ.get("SMTP_PORT") or 587),
        "from_addr": os.environ.get("SMTP_FROM") or None,
        "user_set": bool(os.environ.get("SMTP_USER")),
    }


class SmtpTestIn(BaseModel):
    to: Optional[EmailStr] = None


@router.post("/settings/smtp-test")
async def smtp_test(payload: SmtpTestIn, user=Depends(require_roles("admin"))):
    from app.audit import log_audit
    if not is_smtp_configured():
        missing = [k for k in ("SMTP_HOST", "SMTP_FROM") if not os.environ.get(k)]
        raise HTTPException(
            400,
            f"SMTP non configuré — renseignez {', '.join(missing)} dans le fichier .env du serveur "
            "puis redémarrez le backend (docker compose restart backend)")
    to = (payload.to or user["email"]).lower()
    try:
        await send_test_email(to)
    except Exception as e:
        await log_audit("settings.smtp_test", user, {"to": to, "ok": False, "error": str(e)[:300]})
        raise HTTPException(502, f"Échec de l'envoi SMTP : {e}")
    await log_audit("settings.smtp_test", user, {"to": to, "ok": True})
    return {"sent": True, "to": to}


# ---------- Schedules (per-day work periods) ----------
class ScheduleIn(BaseModel):
    driver_id: Optional[str] = None
    days: list[dict]


@router.get("/schedule")
async def get_schedule(driver_id: Optional[str] = None, user=Depends(get_current_user)):
    db = get_db()
    return await _get_schedule_for(db, driver_id)


@router.put("/schedule")
async def put_schedule(payload: ScheduleIn, user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    doc = normalize_schedule(payload.driver_id, payload.days)
    await db.schedules.update_one(
        {"driver_id": payload.driver_id},
        {"$set": doc},
        upsert=True,
    )
    await apply_rules_to_all(db)
    return doc


@router.delete("/schedule")
async def delete_schedule(driver_id: str, user=Depends(require_roles("admin", "manager"))):
    """Delete a per-driver override (cannot delete default)."""
    if not driver_id:
        raise HTTPException(400, "driver_id requis")
    db = get_db()
    await db.schedules.delete_one({"driver_id": driver_id})
    await apply_rules_to_all(db)
    return {"ok": True}


@router.get("/schedule/drivers-with-override")
async def drivers_with_override(user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    rows = await db.schedules.find(
        {"driver_id": {"$ne": None}}, {"_id": 0, "driver_id": 1},
    ).to_list(500)
    return [r["driver_id"] for r in rows]


# ---------- Privacy Phase 1 — Tracker compatibility scan ----------
@router.get("/privacy/tracker-compatibility")
async def privacy_tracker_compat(user=Depends(require_roles("admin", "manager"))):
    """Scan every vehicle's tracker and report whether a privacy/sleep command exists.

    PHASE 1 ONLY: discovery — no command is ever sent.
    """
    db = get_db()
    return await scan_all_vehicles(db)


@router.get("/privacy/tracker-compatibility/{vehicle_id}")
async def privacy_tracker_compat_one(
    vehicle_id: str, user=Depends(require_roles("admin", "manager")),
):
    db = get_db()
    v = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Véhicule introuvable")
    return await scan_vehicle(db, v)


# ---------- Privacy Phase 2 — Enforcement (real or simulated) ----------
@router.get("/privacy/enforcement-config")
async def privacy_enforcement_config(user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    s = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    return {
        "enabled": bool(s.get("privacy_enforcement_enabled", False)),
        "simulation": bool(s.get("privacy_simulation_mode", True)),
    }


@router.put("/privacy/enforcement-config")
async def privacy_enforcement_config_update(
    payload: dict, user=Depends(require_roles("admin")),
):
    db = get_db()
    update = {}
    if "enabled" in payload:
        update["privacy_enforcement_enabled"] = bool(payload["enabled"])
    if "simulation" in payload:
        update["privacy_simulation_mode"] = bool(payload["simulation"])
    if not update:
        raise HTTPException(400, "Aucun champ à mettre à jour")
    await db.settings.update_one({"id": "default"}, {"$set": update}, upsert=True)
    await db.audit_log.insert_one({
        "ts": datetime.now(timezone.utc).isoformat(),
        "scope": "tracker_privacy",
        "action": "config_update",
        "actor": user.get("email"),
        "payload": update,
    })
    s = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    return {
        "enabled": bool(s.get("privacy_enforcement_enabled", False)),
        "simulation": bool(s.get("privacy_simulation_mode", True)),
    }


@router.get("/privacy/state")
async def privacy_state(user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    return {"rows": await list_states(db)}


@router.post("/privacy/enforce-now")
async def privacy_enforce_now(user=Depends(require_roles("admin"))):
    db = get_db()
    return await enforce_all_vehicles(db)


@router.post("/privacy/kill-switch")
async def privacy_kill_switch(user=Depends(require_roles("admin"))):
    db = get_db()
    return await kill_switch(db)
