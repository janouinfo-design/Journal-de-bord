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
from app.navixy_client import is_configured as navixy_configured, NavixyError
from app.navixy_sync import sync_navixy
from app.scheduler import get_state as get_sched_state, reconfigure as reconfig_sched, trigger_now as trigger_sched
from app.assignments import (
    list_assignments, add_assignment, remove_assignment,
    reassign_all_trips, driver_vehicle_ids,
)


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
    return s


def _apply_privacy(trip: dict, settings: dict, role: str) -> dict:
    """Mode B masks personal trip details for managers (not admins)."""
    if settings.get("mode") != "B":
        return trip
    if role == "admin":
        return trip
    if trip.get("classification") == "personal":
        return {
            "id": trip["id"],
            "driver_name": trip.get("driver_name"),
            "vehicle_plate": trip.get("vehicle_plate"),
            "start_time": trip.get("start_time"),
            "end_time": trip.get("end_time"),
            "distance_km": trip.get("distance_km"),
            "duration_min": trip.get("duration_min"),
            "classification": "personal",
            "masked": True,
        }
    return trip


async def _filter_trips_query(db, user, start: Optional[str], end: Optional[str],
                              driver_id: Optional[str], vehicle_id: Optional[str],
                              classification: Optional[str]) -> dict:
    q: dict = {"tenant_id": "default"}
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

    # Drivers can only see their own trips (own driver_id + trips on any vehicle ever assigned to them)
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
        raise HTTPException(400, "NAVIXY_HASH non configuré dans .env")
    if days < 1 or days > 365:
        raise HTTPException(400, "days doit être entre 1 et 365")
    try:
        return await sync_navixy(days=days, force_reclassify=True)
    except NavixyError as e:
        raise HTTPException(502, f"Navixy API: {e}")
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
        raise HTTPException(400, "NAVIXY_HASH non configuré")
    try:
        return await trigger_sched()
    except NavixyError as e:
        raise HTTPException(502, f"Navixy API: {e}")


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
    if payload.mode not in ("A", "B", "C"):
        raise HTTPException(400, "Mode invalide")
    db = get_db()
    new = {"id": "default", "mode": payload.mode}
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


# ---------- Dashboard ----------
@router.get("/dashboard")
async def dashboard(
    start: Optional[str] = None,
    end: Optional[str] = None,
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await _get_settings(db)
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, None)
    trips = await db.trips.find(q, {"_id": 0}).to_list(10000)

    pro_km = sum(t["distance_km"] for t in trips if t.get("classification") == "professional")
    perso_km = sum(t["distance_km"] for t in trips if t.get("classification") == "personal")
    total_km = pro_km + perso_km
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
    per_driver = defaultdict(lambda: {"pro_km": 0, "perso_km": 0, "pro_time": 0, "perso_time": 0, "vehicle_plate": ""})
    for t in trips:
        key = (t["driver_id"], t.get("driver_name"))
        d = per_driver[key]
        d["vehicle_plate"] = t.get("vehicle_plate")
        if t.get("classification") == "professional":
            d["pro_km"] += t["distance_km"]
            d["pro_time"] += t.get("duration_min", 0)
        else:
            d["perso_km"] += t["distance_km"]
            d["perso_time"] += t.get("duration_min", 0)
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
            "pct_pro": round(v["pro_km"] / total * 100, 1) if total else 0,
            "pct_perso": round(v["perso_km"] / total * 100, 1) if total else 0,
        })
    table.sort(key=lambda r: -r["total_km"])

    return {
        "settings_mode": settings.get("mode"),
        "kpi": {
            "pro_km": round(pro_km, 1),
            "perso_km": round(perso_km, 1),
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
    limit: int = 500,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await _get_settings(db)
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, classification)
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
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await _get_settings(db)
    q = await _filter_trips_query(db, user, start, end, driver_id, vehicle_id, classification)
    trips = await db.trips.find(q, {"_id": 0}).sort("start_time", -1).to_list(20000)

    # Privacy mode B for managers — personal report becomes minimal
    is_masked = (classification == "personal" and settings.get("mode") == "B" and user["role"] != "admin")
    if is_masked:
        trips = [{
            "start_time": t["start_time"], "end_time": t["end_time"],
            "driver_name": t.get("driver_name", ""), "vehicle_plate": t.get("vehicle_plate", ""),
            "start_address": "—", "end_address": "—",
            "distance_km": t.get("distance_km", 0), "duration_min": t.get("duration_min", 0),
            "fuel_l": 0, "avg_speed": 0, "max_speed": 0,
        } for t in trips]

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
