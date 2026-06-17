"""Phase 2 — Tracker privacy enforcement.

Periodic job that, for each compatible vehicle:
1. Computes the expected privacy state ('private' or 'tracking') based on
   the current time, the vehicle mode and the driver schedule.
2. Compares with the last known state stored in `db.tracker_privacy_state`.
3. If they differ — or if the last command is older than the refresh interval —
   sends a raw command via Navixy `tracker/raw_command/send`.

**Safety nets**
- `privacy_simulation_mode` (default True): no Navixy call, only audit log.
- 24h timeout: every 'private' command is auto-renewed every 12h; if for any
  reason the enforcer stops running, the tracker reverts to tracking after
  ~24h (depends on tracker firmware timeout config; we also re-affirm via
  scheduler). When the user disables enforcement, a 'wake' command is sent
  immediately to every previously-private tracker.
- Only vehicles classified as `full` (Teltonika FMx, Queclink) receive
  commands. Others are skipped with status='skipped_incompatible'.

Teltonika FMC130 / FMC230 / FMC003 command mapping (param ID 11000 = Sleep Mode):
- `setparam 11000:4`  -> Deep Sleep (silent — no GPS/GSM transmission)
- `setparam 11000:0`  -> Disabled    (normal tracking)

Note: trackers count odometer internally in deep sleep, so total km are preserved.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.navixy_client import send_raw_command, NavixyError, is_configured
from app.privacy_scan import classify_model
from app.rules import _get_schedule_for, _parse_hm, _in_any_period

logger = logging.getLogger(__name__)

# Refresh cadence — re-emit the same command after this delay even if state matches.
REAFFIRM_AFTER = timedelta(hours=12)
# Hard ceiling — if a 'private' state is older than this and was never refreshed,
# the next enforcement cycle considers it stale and re-emits.
PRIVATE_MAX_AGE = timedelta(hours=24)

# Command templates per vendor family.
COMMANDS = {
    "teltonika": {
        "private":  "setparam 11000:4",  # Deep Sleep
        "tracking": "setparam 11000:0",  # No Sleep
    },
    "queclink": {
        "private":  "AT+GTCFG=,privacy_mode=1",
        "tracking": "AT+GTCFG=,privacy_mode=0",
    },
}


def _family_key(model: Optional[str]) -> Optional[str]:
    info = classify_model(model)
    if info["status"] != "full":
        return None
    family = (info["family"] or "").lower()
    if "teltonika" in family:
        return "teltonika"
    if "queclink" in family:
        return "queclink"
    return None


def compute_expected_state(vehicle: dict, schedule: dict, now: Optional[datetime] = None) -> str:
    """Return 'tracking' or 'private' for the given vehicle at `now`.

    Mirrors `rules.classify_trip` but for the *current* moment instead of a trip.
    """
    now = now or datetime.now(timezone.utc)
    mode = (vehicle or {}).get("mode")
    if mode == "always_pro":
        return "tracking"
    if mode == "always_perso":
        return "private"

    weekday = now.weekday()
    day_cfg = None
    for d in (schedule or {}).get("days", []):
        if d.get("day") == weekday:
            day_cfg = d
            break
    if not day_cfg or day_cfg.get("type") == "personal":
        return "private"

    minute = now.hour * 60 + now.minute
    return "tracking" if _in_any_period(minute, day_cfg.get("periods", [])) else "private"


async def _get_enforcement_config(db) -> dict:
    s = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    return {
        "enabled": bool(s.get("privacy_enforcement_enabled", False)),
        "simulation": bool(s.get("privacy_simulation_mode", True)),
    }


async def _audit(db, vehicle_id: str, action: str, payload: dict) -> None:
    await db.audit_log.insert_one({
        "ts": datetime.now(timezone.utc).isoformat(),
        "scope": "tracker_privacy",
        "vehicle_id": vehicle_id,
        "action": action,
        **payload,
    })


async def _get_state(db, vehicle_id: str) -> Optional[dict]:
    return await db.tracker_privacy_state.find_one({"vehicle_id": vehicle_id}, {"_id": 0})


async def _save_state(db, doc: dict) -> None:
    await db.tracker_privacy_state.update_one(
        {"vehicle_id": doc["vehicle_id"]},
        {"$set": doc},
        upsert=True,
    )


async def _enforce_one(db, vehicle: dict, simulation: bool, force: bool = False) -> dict:
    family = _family_key(vehicle.get("model"))
    base = {
        "vehicle_id": vehicle["id"],
        "plate": vehicle.get("plate"),
        "tracker_id": vehicle.get("navixy_tracker_id"),
        "skipped": False,
    }
    if not family:
        return {**base, "skipped": True, "reason": "incompatible"}
    if not vehicle.get("navixy_tracker_id"):
        return {**base, "skipped": True, "reason": "no_tracker"}

    # Resolve schedule for the vehicle's current driver (if any)
    driver_id = vehicle.get("current_driver_id")
    schedule = await _get_schedule_for(db, driver_id)
    expected = compute_expected_state(vehicle, schedule)

    state = await _get_state(db, vehicle["id"]) or {}
    now = datetime.now(timezone.utc)
    last_ts_raw = state.get("last_command_at")
    try:
        last_ts = datetime.fromisoformat(last_ts_raw) if last_ts_raw else None
    except Exception:
        last_ts = None

    need_command = (
        force
        or state.get("expected_state") != expected
        or last_ts is None
        or (now - last_ts) >= REAFFIRM_AFTER
    )

    if not need_command:
        return {**base, "skipped": True, "reason": "up_to_date",
                "expected_state": expected, "current_state": state.get("current_state")}

    command = COMMANDS[family][expected]

    new_state = {
        "vehicle_id": vehicle["id"],
        "tracker_id": vehicle.get("navixy_tracker_id"),
        "family": family,
        "expected_state": expected,
        "current_state": expected,  # optimistic — Navixy ACK is reliable enough
        "last_command_at": now.isoformat(),
        "last_command": command,
        "last_command_mode": "simulation" if simulation else "real",
        "last_command_result": "pending",
        "last_command_error": None,
        "expiry_at": (now + PRIVATE_MAX_AGE).isoformat() if expected == "private" else None,
    }

    audit_payload = {
        "expected_state": expected,
        "command": command,
        "family": family,
        "simulation": simulation,
        "tracker_id": vehicle.get("navixy_tracker_id"),
    }

    if simulation:
        new_state["last_command_result"] = "simulated"
        await _save_state(db, new_state)
        await _audit(db, vehicle["id"], "simulate_command", audit_payload)
        return {**base, "expected_state": expected, "command": command,
                "mode": "simulation", "result": "simulated"}

    # Real call
    if not is_configured():
        new_state["last_command_result"] = "error"
        new_state["last_command_error"] = "Clé d'intégration LOGITRAK non configurée"
        await _save_state(db, new_state)
        await _audit(db, vehicle["id"], "send_command_skipped",
                     {**audit_payload, "error": "no_hash"})
        return {**base, "expected_state": expected, "command": command,
                "mode": "real", "result": "error", "error": "Clé d'intégration LOGITRAK non configurée"}

    try:
        resp = await send_raw_command(int(vehicle["navixy_tracker_id"]), command, reliable=True)
        new_state["last_command_result"] = "success"
        new_state["last_command_id"] = resp.get("command_id")
        await _save_state(db, new_state)
        await _audit(db, vehicle["id"], "send_command",
                     {**audit_payload, "navixy_command_id": resp.get("command_id")})
        return {**base, "expected_state": expected, "command": command,
                "mode": "real", "result": "success",
                "navixy_command_id": resp.get("command_id")}
    except NavixyError as e:
        new_state["last_command_result"] = "error"
        new_state["last_command_error"] = str(e)
        await _save_state(db, new_state)
        await _audit(db, vehicle["id"], "send_command_error",
                     {**audit_payload, "error": str(e)})
        return {**base, "expected_state": expected, "command": command,
                "mode": "real", "result": "error", "error": str(e)}


async def enforce_all_vehicles(db) -> dict:
    """Main entry point — called by APScheduler and the 'Enforce now' button."""
    cfg = await _get_enforcement_config(db)
    if not cfg["enabled"]:
        return {"enabled": False, "executed": 0, "rows": []}
    vehicles = await db.vehicles.find({"tenant_id": "default"}, {"_id": 0}).to_list(1000)
    rows = []
    sent = simulated = skipped = errors = 0
    for v in vehicles:
        r = await _enforce_one(db, v, simulation=cfg["simulation"])
        rows.append(r)
        if r.get("skipped"):
            skipped += 1
        elif r.get("mode") == "simulation":
            simulated += 1
        elif r.get("result") == "success":
            sent += 1
        elif r.get("result") == "error":
            errors += 1
    return {
        "enabled": True,
        "simulation": cfg["simulation"],
        "executed": sent + simulated,
        "sent_real": sent,
        "simulated": simulated,
        "skipped": skipped,
        "errors": errors,
        "rows": rows,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }


async def kill_switch(db) -> dict:
    """Emergency: force every previously-private tracker back to 'tracking' immediately.

    This bypasses the enforce/simulation gates. ALWAYS sends real commands (no
    simulation) because the goal is to recover a healthy state.
    Returns a per-vehicle summary.
    """
    states = await db.tracker_privacy_state.find({}, {"_id": 0}).to_list(1000)
    targets = [s for s in states if s.get("expected_state") == "private"]
    rows = []
    sent = errors = 0
    for st in targets:
        v = await db.vehicles.find_one({"id": st["vehicle_id"]}, {"_id": 0})
        if not v:
            continue
        family = _family_key(v.get("model"))
        if not family or not v.get("navixy_tracker_id"):
            rows.append({"vehicle_id": v["id"], "skipped": True, "reason": "incompatible"})
            continue
        cmd = COMMANDS[family]["tracking"]
        payload = {"command": cmd, "family": family, "tracker_id": v["navixy_tracker_id"],
                   "expected_state": "tracking", "kill_switch": True}
        try:
            resp = await send_raw_command(int(v["navixy_tracker_id"]), cmd, reliable=True)
            now = datetime.now(timezone.utc).isoformat()
            await _save_state(db, {
                "vehicle_id": v["id"], "tracker_id": v["navixy_tracker_id"],
                "family": family, "expected_state": "tracking", "current_state": "tracking",
                "last_command_at": now, "last_command": cmd, "last_command_mode": "real",
                "last_command_result": "success", "last_command_id": resp.get("command_id"),
                "expiry_at": None, "last_command_error": None,
            })
            await _audit(db, v["id"], "kill_switch_wake", payload)
            rows.append({"vehicle_id": v["id"], "result": "success", "command": cmd})
            sent += 1
        except NavixyError as e:
            await _audit(db, v["id"], "kill_switch_error", {**payload, "error": str(e)})
            rows.append({"vehicle_id": v["id"], "result": "error", "error": str(e)})
            errors += 1
    return {"targets": len(targets), "sent": sent, "errors": errors, "rows": rows,
            "ran_at": datetime.now(timezone.utc).isoformat()}


async def list_states(db) -> list[dict]:
    """Read-only view of current per-vehicle privacy state for the UI."""
    states = {s["vehicle_id"]: s async for s in db.tracker_privacy_state.find({}, {"_id": 0})}
    vehicles = await db.vehicles.find({"tenant_id": "default"}, {"_id": 0}).to_list(1000)
    out = []
    for v in vehicles:
        family = _family_key(v.get("model"))
        if not family:
            continue  # only show compatible vehicles
        s = states.get(v["id"]) or {}
        out.append({
            "vehicle_id": v["id"],
            "plate": v.get("plate"),
            "tracker_id": v.get("navixy_tracker_id"),
            "family": family,
            "expected_state": s.get("expected_state"),
            "current_state": s.get("current_state"),
            "last_command": s.get("last_command"),
            "last_command_at": s.get("last_command_at"),
            "last_command_mode": s.get("last_command_mode"),
            "last_command_result": s.get("last_command_result"),
            "last_command_error": s.get("last_command_error"),
            "expiry_at": s.get("expiry_at"),
        })
    return out
