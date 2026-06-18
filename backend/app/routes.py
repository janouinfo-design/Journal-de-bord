"""Logitrak Livre de Bord API routes."""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.auth import get_current_user, require_roles
from app.db import get_db
from app.rules import classify_trip, apply_rules_to_all, default_settings, default_schedule, _get_schedule_for
from app.reports import trips_to_csv, trips_to_xlsx, trips_to_pdf, swiss_tax_report_pdf
from app.navixy_client import is_configured as navixy_configured, NavixyError, read_track_points as navixy_read_track
from app.navixy_sync import sync_navixy
from app.scheduler import get_state as get_sched_state, reconfigure as reconfig_sched, trigger_now as trigger_sched
from app.assignments import (
    list_assignments, add_assignment, remove_assignment,
    reassign_all_trips, driver_vehicle_ids,
)
from app.privacy_scan import scan_all_vehicles, scan_vehicle
from app.privacy_enforcer import (
    enforce_all_vehicles, kill_switch, list_states, compute_expected_state,
)
from app import ble_engine
from app.realtime import get_broadcaster
from fastapi import WebSocket, WebSocketDisconnect


router = APIRouter(prefix="/livre", tags=["livre-de-bord"])


# ---------- Helpers ----------
def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def _get_settings(db) -> dict:
    s = await db.settings.find_one({"id": "default"}, {"_id": 0})
    if not s:
        s = default_settings()
        await db.settings.insert_one(dict(s))
    s.pop("_id", None)
    # Migrate legacy mode codes
    legacy = {"A": "mixte", "B": "masked", "C": "mixte"}
    if s.get("mode") in legacy:
        s["mode"] = legacy[s["mode"]]
        await db.settings.update_one({"id": "default"}, {"$set": {"mode": s["mode"]}})
    return s


def _apply_privacy(trip: dict, settings: dict, role: str) -> dict:
    """Mode 'masked' fully anonymises personal trips for non-admins."""
    if settings.get("mode") != "masked":
        return trip
    if role == "admin":
        return trip
    if trip.get("classification") == "personal":
        # Total anonymisation — no date, no map, no addresses, no duration, no speed
        return {
            "id": trip["id"],
            "classification": "personal",
            "distance_km": trip.get("distance_km"),
            "masked": True,
        }
    return trip


async def _filter_trips_query(db, user, start: Optional[str], end: Optional[str],
                              driver_id: Optional[str], vehicle_id: Optional[str],
                              classification: Optional[str],
                              group: Optional[str] = None,
                              company: Optional[str] = None) -> dict:
    q: dict = {"tenant_id": "default"}
    if company and company not in ("Logitrak", "default"):
        q["tenant_id"] = company
    if start:
        q.setdefault("start_time", {})["$gte"] = start
    if end:
        q.setdefault("start_time", {})["$lte"] = end
    if driver_id:
        q["driver_id"] = driver_id
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    if classification:
        q["classification"] = classification

    if group:
        matching = await db.vehicles.find(
            {"plate": {"$regex": f"^{group} ", "$options": "i"}}, {"_id": 0, "id": 1},
        ).to_list(500)
        ids = [v["id"] for v in matching]
        if "vehicle_id" in q and isinstance(q["vehicle_id"], str):
            if q["vehicle_id"] not in ids:
                q["vehicle_id"] = "__none__"
        else:
            q["vehicle_id"] = {"$in": ids} if ids else "__none__"

    # Drivers can only see their own trips
    if user["role"] == "driver":
        driver = await db.drivers.find_one({"email": user["email"]}, {"_id": 0})
        if not driver:
            q["driver_id"] = "__none__"
        else:
            vehicle_ids = await driver_vehicle_ids(db, driver["id"])
            q["$or"] = [{"driver_id": driver["id"]}]
            if vehicle_ids:
                q["$or"].append({"vehicle_id": {"$in": vehicle_ids}})
    return q


# ---------- Bootstrap ----------
@router.post("/bootstrap")
async def bootstrap(force: bool = False, user=Depends(require_roles("admin"))):
    """Seed mock data and run rule engine."""
    from app.mock_navixy import seed_mock_data
    db = get_db()
    await seed_mock_data(force=force)
    await _get_settings(db)
    updated = await apply_rules_to_all(db)
    return {"ok": True, "trips_reclassified": updated}


# ---------- Navixy live sync ----------
@router.get("/navixy/status")
async def navixy_status(user=Depends(require_roles("admin", "manager"))):
    return {"configured": navixy_configured()}


@router.post("/navixy/sync")
async def navixy_sync_endpoint(days: int = 30, user=Depends(require_roles("admin"))):
    """Pull live data from Navixy: trackers, employees, zones, tracks."""
    if not navixy_configured():
        raise HTTPException(400, "Clé d'intégration LOGITRAK non configurée")
    if days < 1 or days > 365:
        raise HTTPException(400, "days doit être entre 1 et 365")
    try:
        return await sync_navixy(days=days, force_reclassify=True)
    except NavixyError as e:
        raise HTTPException(502, f"LOGITRAK : {e}")
    except Exception as e:
        raise HTTPException(500, f"Erreur de synchronisation: {e}")


# ---------- Scheduler ----------
class SchedulerIn(BaseModel):
    enabled: bool
    interval_min: int
    days: int


@router.get("/navixy/scheduler")
async def scheduler_get(user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    state = await get_sched_state(db)
    state["configured"] = navixy_configured()
    return state


@router.put("/navixy/scheduler")
async def scheduler_put(payload: SchedulerIn, user=Depends(require_roles("admin"))):
    try:
        new_state = await reconfig_sched(payload.enabled, payload.interval_min, payload.days)
    except ValueError as e:
        raise HTTPException(400, str(e))
    new_state["configured"] = navixy_configured()
    return new_state


@router.post("/navixy/scheduler/run-now")
async def scheduler_run_now(user=Depends(require_roles("admin"))):
    if not navixy_configured():
        raise HTTPException(400, "Clé d'intégration LOGITRAK non configurée")
    try:
        return await trigger_sched()
    except NavixyError as e:
        raise HTTPException(502, f"LOGITRAK : {e}")


# ---------- Assignments (driver ↔ vehicle, time-aware) ----------
class AssignmentIn(BaseModel):
    vehicle_id: str
    driver_id: str
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    is_primary: bool = False


@router.get("/assignments")
async def assignments_list(vehicle_id: Optional[str] = None, driver_id: Optional[str] = None,
                           user=Depends(get_current_user)):
    db = get_db()
    rows = await list_assignments(db, vehicle_id=vehicle_id)
    if driver_id:
        rows = [r for r in rows if r["driver_id"] == driver_id]
    # Driver can only see assignments concerning them
    if user["role"] == "driver":
        own = await db.drivers.find_one({"email": user["email"]}, {"_id": 0})
        if not own:
            return []
        rows = [r for r in rows if r["driver_id"] == own["id"]]
    return rows


@router.post("/assignments")
async def assignments_create(payload: AssignmentIn,
                             user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    veh = await db.vehicles.find_one({"id": payload.vehicle_id}, {"_id": 0})
    if not veh:
        raise HTTPException(404, "Véhicule introuvable")
    drv = await db.drivers.find_one({"id": payload.driver_id}, {"_id": 0})
    if not drv:
        raise HTTPException(404, "Chauffeur introuvable")
    if payload.from_date and payload.to_date and payload.from_date > payload.to_date:
        raise HTTPException(400, "Plage de dates invalide")
    doc = await add_assignment(
        db, payload.vehicle_id, payload.driver_id,
        from_date=payload.from_date, to_date=payload.to_date,
        is_primary=payload.is_primary, source="manual",
    )
    reassigned = await reassign_all_trips(db)
    return {"assignment": doc, "trips_reassigned": reassigned}


@router.delete("/assignments/{assignment_id}")
async def assignments_delete(assignment_id: str,
                             user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    ok = await remove_assignment(db, assignment_id)
    if not ok:
        raise HTTPException(404, "Affectation introuvable")
    reassigned = await reassign_all_trips(db)
    return {"ok": True, "trips_reassigned": reassigned}


# ---------- Settings ----------
class SettingsIn(BaseModel):
    mode: str  # A | B | C


@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    db = get_db()
    return await _get_settings(db)


@router.put("/settings")
async def update_settings(payload: SettingsIn, user=Depends(require_roles("admin", "manager"))):
    mode = payload.mode
    # Backward-compat aliases
    if mode in ("A", "B"):
        mode = {"A": "mixte", "B": "masked"}[mode]
    if mode == "C":
        raise HTTPException(400, "Mode C supprimé — utilisez le mode véhicule 'Toujours professionnel' à la place")
    if mode not in ("mixte", "masked"):
        raise HTTPException(400, "Mode invalide")
    db = get_db()
    new = {"id": "default", "mode": mode}
    await db.settings.update_one({"id": "default"}, {"$set": new}, upsert=True)
    await apply_rules_to_all(db)
    return new


# ---------- Schedules (per-day work periods) ----------
class PeriodIn(BaseModel):
    enabled: bool
    from_: str = ""  # alias to avoid Python keyword
    to: str = "00:00"

    class Config:
        fields = {"from_": "from"}


class DayIn(BaseModel):
    day: int  # 0..6 (Mon..Sun)
    type: str  # 'work' | 'personal'
    periods: list[dict] = []


class ScheduleIn(BaseModel):
    driver_id: Optional[str] = None  # null = default for all
    days: list[dict]


def _normalize_schedule(driver_id: Optional[str], days: list[dict]) -> dict:
    """Validate and normalize a schedule payload."""
    if not isinstance(days, list) or len(days) != 7:
        raise HTTPException(400, "Le planning doit contenir 7 jours")
    out_days = []
    seen = set()
    for d in days:
        idx = d.get("day")
        if idx not in range(7) or idx in seen:
            raise HTTPException(400, f"Jour invalide: {idx}")
        seen.add(idx)
        dtype = d.get("type", "work")
        if dtype not in ("work", "personal"):
            raise HTTPException(400, "type doit être 'work' ou 'personal'")
        periods = d.get("periods") or []
        if len(periods) > 3:
            raise HTTPException(400, "Maximum 3 plages par jour")
        norm_periods = []
        for p in periods[:3]:
            norm_periods.append({
                "enabled": bool(p.get("enabled")),
                "from": str(p.get("from", "00:00")),
                "to": str(p.get("to", "00:00")),
            })
        while len(norm_periods) < 3:
            norm_periods.append({"enabled": False, "from": "00:00", "to": "00:00"})
        out_days.append({"day": idx, "type": dtype, "periods": norm_periods})
    out_days.sort(key=lambda x: x["day"])
    return {
        "id": f"sched-{driver_id or 'default'}",
        "tenant_id": "default",
        "driver_id": driver_id,
        "days": out_days,
    }


@router.get("/schedule")
async def get_schedule(driver_id: Optional[str] = None, user=Depends(get_current_user)):
    db = get_db()
    s = await _get_schedule_for(db, driver_id)
    return s


@router.put("/schedule")
async def put_schedule(payload: ScheduleIn, user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    doc = _normalize_schedule(payload.driver_id, payload.days)
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
    rows = await db.schedules.find({"driver_id": {"$ne": None}}, {"_id": 0, "driver_id": 1}).to_list(500)
    return [r["driver_id"] for r in rows]


# ---------- Master data ----------
@router.get("/drivers")
async def list_drivers(user=Depends(get_current_user)):
    db = get_db()
    rows = await db.drivers.find({"tenant_id": "default"}, {"_id": 0}).to_list(500)
    return rows


@router.get("/vehicles")
async def list_vehicles(user=Depends(get_current_user)):
    db = get_db()
    rows = await db.vehicles.find({"tenant_id": "default"}, {"_id": 0}).to_list(500)
    return rows


class VehicleModeIn(BaseModel):
    mode: str  # always_pro | always_perso | mixte


@router.put("/vehicles/{vehicle_id}/mode")
async def set_vehicle_mode(vehicle_id: str, payload: VehicleModeIn,
                           user=Depends(require_roles("admin", "manager"))):
    if payload.mode not in ("always_pro", "always_perso", "mixte"):
        raise HTTPException(400, "Mode invalide")
    db = get_db()
    res = await db.vehicles.update_one({"id": vehicle_id}, {"$set": {"mode": payload.mode}})
    if res.matched_count == 0:
        raise HTTPException(404, "Véhicule introuvable")
    await apply_rules_to_all(db)
    return {"ok": True}


@router.get("/geofences")
async def list_geofences(user=Depends(get_current_user)):
    db = get_db()
    rows = await db.geofences.find({"tenant_id": "default"}, {"_id": 0}).to_list(500)
    return rows


@router.get("/groups")
async def list_groups(user=Depends(get_current_user)):
    """Distinct fleet groups derived from the first token of vehicle plates (e.g. 'GE')."""
    db = get_db()
    rows = await db.vehicles.find({"tenant_id": "default"}, {"_id": 0, "plate": 1}).to_list(1000)
    groups = sorted({(r.get("plate") or "").split(" ")[0] for r in rows if r.get("plate")})
    return [{"id": g, "name": g} for g in groups if g]


@router.get("/companies")
async def list_companies(user=Depends(get_current_user)):
    """Distinct tenants/companies. Currently mono-tenant — exposed for future multi-tenant."""
    db = get_db()
    tenants = await db.vehicles.distinct("tenant_id")
    companies = sorted({t for t in tenants if t})
    label_map = {"default": "Logitrak"}
    return [{"id": c, "name": label_map.get(c, c)} for c in companies]


# ---------- Privacy Phase 1 — Tracker compatibility scan (no command sent) ----------
@router.get("/privacy/tracker-compatibility")
async def privacy_tracker_compat(user=Depends(require_roles("admin", "manager"))):
    """Scan every vehicle's tracker and report whether a privacy/sleep command exists.

    PHASE 1 ONLY: discovery — no command is ever sent. Returns
    `{rows: [{vehicle_id, plate, status, full_matches, partial_matches, error}],
       counters: {full, partial, none, unknown, total}}`.
    """
    db = get_db()
    return await scan_all_vehicles(db)


@router.get("/privacy/tracker-compatibility/{vehicle_id}")
async def privacy_tracker_compat_one(vehicle_id: str,
                                     user=Depends(require_roles("admin", "manager"))):
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
async def privacy_enforcement_config_update(payload: dict,
                                            user=Depends(require_roles("admin"))):
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


# ---------- BLE driver identification ----------
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


async def _resolve_driver_id_for_user(db, user: dict) -> Optional[str]:
    """Map an authenticated user to a driver.id. Admins/managers may pass
    `driver_id` explicitly in the payload (handled by callers)."""
    if user.get("role") == "driver":
        # Try a few mapping strategies
        drv = await db.drivers.find_one(
            {"$or": [{"email": user.get("email")}, {"user_id": user.get("id")}]},
            {"_id": 0, "id": 1},
        )
        if drv:
            return drv["id"]
    return user.get("driver_id") or user.get("id")


@router.post("/ble/detections")
async def ble_ingest(payload: dict, user=Depends(get_current_user)):
    """Ingestion endpoint for the chauffeur PWA / future native app.

    Payload accepts either a single detection or `{"detections": [...]}`.
    """
    db = get_db()
    driver_id = await _resolve_driver_id_for_user(db, user)
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
    driver_id = payload.get("driver_id") or await _resolve_driver_id_for_user(db, user)
    if not driver_id or not payload.get("identifier"):
        raise HTTPException(400, "driver_id et identifier sont requis")
    rssi = int(payload.get("rssi") or -55)
    return await ble_engine.simulate_detection(db, driver_id, payload["identifier"], rssi)


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
    The winning session keeps `status='confirmed'` (or 'pending' if
    confidence < threshold); other involved sessions are closed.
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


# ---------- Realtime WebSocket ----------
@router.websocket("/realtime")
async def realtime_ws(ws: WebSocket):
    """In-memory pub/sub of identification events for the current tenant.

    Auth is done by reading the same `session` cookie used by REST. We accept
    any authenticated user (admin/manager/driver); messages are JSON
    `{type, data, ts}`. The frontend hook handles reconnection.
    """
    # Authenticate from cookie
    from app.auth import get_user_from_request  # local import to avoid cycles
    try:
        user = await get_user_from_request(ws)
    except Exception:
        user = None
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    broadcaster = get_broadcaster()
    await broadcaster.join(ws, tenant_id="default")
    try:
        # Send a hello ping
        await ws.send_text('{"type":"hello","data":{"ok":true},"ts":""}')
        while True:
            # We just keep the connection alive; clients may send pings.
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong","data":{},"ts":""}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await broadcaster.leave(ws, tenant_id="default")


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


# Driver-facing endpoints (used by the PWA console)
@router.get("/driver/current-session")
async def driver_current_session(user=Depends(get_current_user)):
    db = get_db()
    driver_id = await _resolve_driver_id_for_user(db, user)
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
    driver_id = await _resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    try:
        return await ble_engine.driver_set_mode(db, driver_id, mode, actor=user.get("email", "?"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


# ---------- Mobile push notifications (Expo Push) ----------
class PushTokenIn(BaseModel):
    token: str
    platform: Optional[str] = None  # "ios" | "android" | "expo" (free-form)
    device_id: Optional[str] = None


@router.post("/driver/push-token")
async def register_push_token(payload: PushTokenIn, user=Depends(get_current_user)):
    """Register or refresh the Expo push token for the authenticated user.

    Behaviour:
    - Upsert keyed by `(user_id, token)` so multiple devices can coexist.
    - If a different user previously registered the same token, the new
      registration wins (token follows the device, not the user).
    - Re-registering reactivates a previously deactivated token.
    """
    if not payload.token or len(payload.token) < 10:
        raise HTTPException(400, "Push token invalide")
    db = get_db()
    driver_id = await _resolve_driver_id_for_user(db, user)
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


# ---------- Notification preferences ----------
from app.notifications_service import (
    get_preferences as _notif_get_prefs,
    set_preferences as _notif_set_prefs,
    event_catalog_public as _notif_catalog,
    dispatch as _notif_dispatch,
)


@router.get("/notifications/catalog")
async def notifications_catalog(user=Depends(get_current_user)):
    """List of supported events + default channels — used by the preferences UI."""
    return {"events": _notif_catalog()}


@router.get("/notifications/preferences")
async def notifications_get_prefs(user=Depends(get_current_user)):
    """Get the current user's notification preferences (push/email/sms per event)."""
    return await _notif_get_prefs(get_db(), user["id"])


@router.put("/notifications/preferences")
async def notifications_put_prefs(payload: dict, user=Depends(get_current_user)):
    """Update the current user's notification preferences."""
    return await _notif_set_prefs(get_db(), user["id"], payload or {})


@router.post("/notifications/test")
async def notifications_test(payload: dict, user=Depends(require_roles("admin"))):
    """Admin-only: trigger a test notification for a known event.

    Body: `{event: 'ble.conflict'|..., user_ids?: [], driver_ids?: [], payload?: {...}}`
    """
    event = (payload or {}).get("event")
    if not event:
        raise HTTPException(400, "event requis")
    return await _notif_dispatch(
        event,
        (payload or {}).get("payload") or {"vehicle_plate": "TEST-99", "session_id": "test"},
        user_ids=(payload or {}).get("user_ids"),
        driver_ids=(payload or {}).get("driver_ids"),
    )


# ---------- Trip GPS polyline (Navixy track/read with local cache) ----------
def _fallback_points(trip: dict) -> list[list[float]]:
    """Two-point fallback when Navixy track/read is unavailable."""
    pts = []
    sl, sg = trip.get("start_lat"), trip.get("start_lng")
    el, eg = trip.get("end_lat"), trip.get("end_lng")
    if isinstance(sl, (int, float)) and isinstance(sg, (int, float)):
        pts.append([sg, sl])
    if isinstance(el, (int, float)) and isinstance(eg, (int, float)):
        pts.append([eg, el])
    return pts


@router.get("/trips/{trip_id}/track")
async def trip_track(trip_id: str, refresh: bool = False,
                     user=Depends(get_current_user)):
    """Return the polyline of a trip as a list of `[lng, lat]` points.

    **Strict privacy invariant** (applied here regardless of role):
    if `settings.mode == "masked"` and `trip.classification == "personal"`,
    GPS points MUST NOT be loaded, cached or returned. → 403.

    Cache strategy: `db.trip_tracks` keyed by `trip_id`. Trips are immutable
    once closed, so we cache permanently (use `?refresh=true` to force).
    """
    db = get_db()
    trip = await db.trips.find_one({"id": trip_id, "tenant_id": "default"}, {"_id": 0})
    if not trip:
        raise HTTPException(404, "Trajet introuvable")

    settings = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    if settings.get("mode") == "masked" and trip.get("classification") == "personal":
        raise HTTPException(403, "Trajet personnel masqué — points GPS non disponibles")

    if not refresh:
        cached = await db.trip_tracks.find_one({"trip_id": trip_id}, {"_id": 0})
        if cached and cached.get("points"):
            return {"trip_id": trip_id, "points": cached["points"],
                    "source": cached.get("source", "cache"),
                    "fetched_at": cached.get("fetched_at"),
                    "count": len(cached["points"])}

    vehicle = await db.vehicles.find_one({"id": trip.get("vehicle_id")}, {"_id": 0}) or {}
    tracker_id = vehicle.get("navixy_tracker_id")
    if not tracker_id or not navixy_configured():
        pts = _fallback_points(trip)
        return {"trip_id": trip_id, "points": pts,
                "source": "fallback_no_tracker" if not tracker_id else "fallback_no_navixy",
                "count": len(pts)}

    def _fmt(iso):
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")) \
                .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    f, t = _fmt(trip.get("start_time")), _fmt(trip.get("end_time"))
    if not f or not t:
        pts = _fallback_points(trip)
        return {"trip_id": trip_id, "points": pts, "source": "fallback_no_dates", "count": len(pts)}

    try:
        raw = await navixy_read_track(
            int(tracker_id), f, t,
            track_id=trip.get("navixy_trip_id"),
            simplify=True, point_limit=300,
        )
    except NavixyError as e:
        pts = _fallback_points(trip)
        # Negative cache for 1 hour to avoid hammering
        await db.trip_tracks.update_one(
            {"trip_id": trip_id},
            {"$set": {"trip_id": trip_id, "tenant_id": "default", "points": pts,
                      "source": "fallback_navixy_error", "error": str(e)[:200],
                      "fetched_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        return {"trip_id": trip_id, "points": pts, "source": "fallback_navixy_error",
                "error": str(e), "count": len(pts)}

    points = [[p["lng"], p["lat"]] for p in raw
              if isinstance(p.get("lng"), (int, float)) and isinstance(p.get("lat"), (int, float))]
    if not points:
        points = _fallback_points(trip)
        src = "fallback_no_points"
    else:
        src = "navixy"

    await db.trip_tracks.update_one(
        {"trip_id": trip_id},
        {"$set": {"trip_id": trip_id, "tenant_id": "default",
                  "points": points, "source": src,
                  "fetched_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"trip_id": trip_id, "points": points, "source": src, "count": len(points)}


# ---------- Dashboard ----------
@router.get("/dashboard")
async def dashboard(
    start: Optional[str] = None,
    end: Optional[str] = None,
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    group: Optional[str] = None,
    company: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await _get_settings(db)
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, None, group=group, company=company)
    trips = await db.trips.find(q, {"_id": 0}).to_list(20000)

    pro_km = sum(t["distance_km"] for t in trips if t.get("classification") == "professional")
    perso_km = sum(t["distance_km"] for t in trips if t.get("classification") == "personal")
    unclassified_km = sum(t["distance_km"] for t in trips if t.get("classification") not in ("professional", "personal"))
    total_km = pro_km + perso_km + unclassified_km
    pro_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "professional")
    perso_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "personal")
    pro_time = sum(t.get("duration_min", 0) for t in trips if t.get("classification") == "professional")
    perso_time = sum(t.get("duration_min", 0) for t in trips if t.get("classification") == "personal")

    # Daily breakdown (last 30 days)
    daily = defaultdict(lambda: {"pro": 0, "perso": 0})
    for t in trips:
        try:
            d = _parse_iso(t["start_time"]).date().isoformat()
        except Exception:
            continue
        if t.get("classification") == "professional":
            daily[d]["pro"] += t["distance_km"]
        else:
            daily[d]["perso"] += t["distance_km"]
    daily_series = sorted(
        [{"date": d, "pro": round(v["pro"], 1), "perso": round(v["perso"], 1)} for d, v in daily.items()],
        key=lambda x: x["date"],
    )[-30:]

    # Per driver breakdown
    per_driver = defaultdict(lambda: {"pro_km": 0, "perso_km": 0, "pro_time": 0, "perso_time": 0,
                                       "pro_fuel": 0, "perso_fuel": 0, "vehicle_plate": ""})
    for t in trips:
        key = (t["driver_id"], t.get("driver_name"))
        d = per_driver[key]
        d["vehicle_plate"] = t.get("vehicle_plate")
        if t.get("classification") == "professional":
            d["pro_km"] += t["distance_km"]
            d["pro_time"] += t.get("duration_min", 0)
            d["pro_fuel"] += t.get("fuel_l", 0) or 0
        elif t.get("classification") == "personal":
            d["perso_km"] += t["distance_km"]
            d["perso_time"] += t.get("duration_min", 0)
            d["perso_fuel"] += t.get("fuel_l", 0) or 0
    table = []
    for (driver_id_v, name), v in per_driver.items():
        total = v["pro_km"] + v["perso_km"]
        table.append({
            "driver_id": driver_id_v,
            "driver_name": name,
            "vehicle_plate": v["vehicle_plate"],
            "pro_km": round(v["pro_km"], 1),
            "perso_km": round(v["perso_km"], 1),
            "total_km": round(total, 1),
            "pro_time": v["pro_time"],
            "perso_time": v["perso_time"],
            "pro_fuel": round(v["pro_fuel"], 2),
            "perso_fuel": round(v["perso_fuel"], 2),
            "pct_pro": round(v["pro_km"] / total * 100, 1) if total else 0,
            "pct_perso": round(v["perso_km"] / total * 100, 1) if total else 0,
        })
    table.sort(key=lambda r: -r["total_km"])

    return {
        "settings_mode": settings.get("mode"),
        "kpi": {
            "pro_km": round(pro_km, 1),
            "perso_km": round(perso_km, 1),
            "unclassified_km": round(unclassified_km, 1),
            "total_km": round(total_km, 1),
            "pct_pro": round(pro_km / total_km * 100, 1) if total_km else 0,
            "pct_perso": round(perso_km / total_km * 100, 1) if total_km else 0,
            "pro_fuel": round(pro_fuel, 2),
            "perso_fuel": round(perso_fuel, 2),
            "pro_time_min": pro_time,
            "perso_time_min": perso_time,
            "trips_count": len(trips),
        },
        "daily_series": daily_series,
        "table": table,
    }


# ---------- Trips ----------
@router.get("/trips")
async def list_trips(
    classification: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    group: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = 500,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await _get_settings(db)
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, classification,
                                  group=group, company=company)
    trips = await db.trips.find(q, {"_id": 0}).sort("start_time", -1).to_list(limit)
    trips = [_apply_privacy(t, settings, user["role"]) for t in trips]
    return {"trips": trips, "settings_mode": settings.get("mode")}


class ClassifyIn(BaseModel):
    classification: str  # 'professional' | 'personal'


@router.put("/trips/{trip_id}/classify")
async def classify_trip_route(trip_id: str, payload: ClassifyIn,
                              user=Depends(require_roles("admin", "manager"))):
    if payload.classification not in ("professional", "personal"):
        raise HTTPException(400, "Classification invalide")
    db = get_db()
    trip = await db.trips.find_one({"id": trip_id}, {"_id": 0})
    if not trip:
        raise HTTPException(404, "Trajet introuvable")

    old = trip.get("classification")
    await db.trips.update_one(
        {"id": trip_id},
        {"$set": {
            "classification": payload.classification,
            "auto_classified": False,
            "modified_by": user["email"],
            "modified_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    await db.audit_log.insert_one({
        "trip_id": trip_id,
        "user_email": user["email"],
        "old_classification": old,
        "new_classification": payload.classification,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


@router.get("/audit-log")
async def audit_log(limit: int = 100, user=Depends(require_roles("admin"))):
    db = get_db()
    rows = await db.audit_log.find({}, {"_id": 0}).sort("at", -1).to_list(limit)
    return rows


# ---------- Reports ----------
def _filename(prefix: str, fmt: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.{fmt}"


@router.get("/reports/export")
async def export_report(
    classification: str = Query(..., regex="^(professional|personal)$"),
    fmt: str = Query("pdf", regex="^(pdf|xlsx|csv)$"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    group: Optional[str] = None,
    company: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await _get_settings(db)
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, classification,
                                  group=group, company=company)
    trips = await db.trips.find(q, {"_id": 0}).sort("start_time", -1).to_list(20000)

    # Privacy mode 'masked' for managers — personal report contains no per-trip data
    is_masked = (classification == "personal" and settings.get("mode") == "masked" and user["role"] != "admin")
    if is_masked:
        # Return only an aggregate summary — no individual trips
        total_km = round(sum((t.get("distance_km") or 0) for t in trips), 1)
        pro_total = await db.trips.count_documents({**q, "classification": "professional"})
        all_q = dict(q); all_q.pop("classification", None)
        all_km_docs = await db.trips.find(all_q, {"_id": 0, "distance_km": 1, "classification": 1}).to_list(50000)
        total_all = round(sum((d.get("distance_km") or 0) for d in all_km_docs), 1)
        pct = round(total_km / total_all * 100, 1) if total_all else 0
        # One-line summary as the "trips" content
        trips = [{
            "start_time": start or "", "end_time": end or "",
            "driver_name": "—", "vehicle_plate": "—",
            "start_address": "—", "end_address": "—",
            "distance_km": total_km, "duration_min": 0,
            "fuel_l": 0, "avg_speed": 0, "max_speed": 0,
        }]
        label = f"Personnel (anonymisé · {pct}% sur la période)"
    else:
        label = "Professionnel" if classification == "professional" else "Personnel"
    title = f"Rapport {label} — Logitrak Livre de Bord"
    subtitle = ""
    if start or end:
        subtitle = f"Période : {start or '—'} → {end or '—'}"

    if fmt == "csv":
        data = trips_to_csv(trips, label)
        return Response(data, media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{_filename(classification, "csv")}"'})
    if fmt == "xlsx":
        data = trips_to_xlsx(trips, label, title)
        return Response(data,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{_filename(classification, "xlsx")}"'})
    data = trips_to_pdf(trips, label, title, subtitle)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(classification, "pdf")}"'})


@router.get("/reports/tax-swiss")
async def tax_swiss_report(
    year: int = Query(...),
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    start = f"{year}-01-01T00:00:00+00:00"
    end = f"{year}-12-31T23:59:59+00:00"
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, None)
    trips = await db.trips.find(q, {"_id": 0}).to_list(50000)

    pro_km = sum(t["distance_km"] for t in trips if t.get("classification") == "professional")
    perso_km = sum(t["distance_km"] for t in trips if t.get("classification") == "personal")
    total_km = pro_km + perso_km
    pro_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "professional")
    perso_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "personal")
    stats = {
        "pro_km": round(pro_km, 1),
        "perso_km": round(perso_km, 1),
        "total_km": round(total_km, 1),
        "pct_pro": round(pro_km / total_km * 100, 1) if total_km else 0,
        "pct_perso": round(perso_km / total_km * 100, 1) if total_km else 0,
        "pro_fuel": round(pro_fuel, 2),
        "perso_fuel": round(perso_fuel, 2),
    }

    owner = ""
    if driver_id:
        d = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
        if d: owner = d.get("name", "")
    if vehicle_id:
        v = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0})
        if v: owner = (owner + " — " if owner else "") + v.get("plate", "")

    data = swiss_tax_report_pdf(stats, year, owner)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="rapport_fiscal_suisse_{year}.pdf"'})
