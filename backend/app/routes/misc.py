"""Catch-all router for endpoints that don't belong to a single domain:

- /bootstrap                  — admin seed/reseed
- /navixy/*                   — Navixy sync + scheduler
- /assignments                — driver ↔ vehicle, time-aware
- /drivers /vehicles /geofences /groups /companies — master data
- /trips /trips/{id}/classify — trip listing and manual reclassification
- /trips/{id}/track           — Navixy track/read with local cache
- /audit-log                  — admin audit trail

Kept together for now to avoid a `/routes/admin.py` + `/routes/master_data.py`
+ `/routes/trips.py` explosion. Can be split further later if needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.assignments import (
    add_assignment,
    list_assignments,
    reassign_all_trips,
    remove_assignment,
)
from app.auth import get_current_user, require_roles
from app.db import get_db
from app.navixy_client import (
    NavixyError,
    is_configured as navixy_configured,
    read_track_points as navixy_read_track,
)
from app.navixy_sync import sync_navixy
from app.rules import apply_rules_to_all
from app.scheduler import (
    get_state as get_sched_state,
    reconfigure as reconfig_sched,
    trigger_now as trigger_sched,
)

from app.routes._helpers import (
    apply_privacy,
    fallback_points,
    filter_trips_query,
    get_settings_doc,
)

router = APIRouter(tags=["misc"])


# ---------- Bootstrap ----------
@router.post("/bootstrap")
async def bootstrap(force: bool = False, user=Depends(require_roles("admin"))):
    """Seed mock data and run rule engine."""
    from app.mock_navixy import seed_mock_data
    db = get_db()
    await seed_mock_data(force=force)
    await get_settings_doc(db)
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


# ---------- Assignments ----------
class AssignmentIn(BaseModel):
    vehicle_id: str
    driver_id: str
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    is_primary: bool = False


@router.get("/assignments")
async def assignments_list(
    vehicle_id: Optional[str] = None, driver_id: Optional[str] = None,
    user=Depends(get_current_user),
):
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
async def assignments_create(
    payload: AssignmentIn, user=Depends(require_roles("admin", "manager")),
):
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
async def assignments_delete(
    assignment_id: str, user=Depends(require_roles("admin", "manager")),
):
    db = get_db()
    ok = await remove_assignment(db, assignment_id)
    if not ok:
        raise HTTPException(404, "Affectation introuvable")
    reassigned = await reassign_all_trips(db)
    return {"ok": True, "trips_reassigned": reassigned}


# ---------- Master data ----------
@router.get("/drivers")
async def list_drivers(user=Depends(get_current_user)):
    db = get_db()
    return await db.drivers.find({"tenant_id": "default"}, {"_id": 0}).to_list(500)


@router.get("/vehicles")
async def list_vehicles(user=Depends(get_current_user)):
    db = get_db()
    return await db.vehicles.find({"tenant_id": "default"}, {"_id": 0}).to_list(500)


class VehicleModeIn(BaseModel):
    mode: str  # always_pro | always_perso | mixte


@router.put("/vehicles/{vehicle_id}/mode")
async def set_vehicle_mode(
    vehicle_id: str, payload: VehicleModeIn,
    user=Depends(require_roles("admin", "manager")),
):
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
    return await db.geofences.find({"tenant_id": "default"}, {"_id": 0}).to_list(500)


@router.get("/groups")
async def list_groups(user=Depends(get_current_user)):
    """Distinct fleet groups derived from the first token of vehicle plates."""
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
    settings = await get_settings_doc(db)
    q = await filter_trips_query(
        db, user, start, end, driver_id, vehicle_id, classification,
        group=group, company=company,
    )
    trips = await db.trips.find(q, {"_id": 0}).sort("start_time", -1).to_list(limit)
    trips = [apply_privacy(t, settings, user["role"]) for t in trips]
    return {"trips": trips, "settings_mode": settings.get("mode")}


class ClassifyIn(BaseModel):
    classification: str  # 'professional' | 'personal'


@router.put("/trips/{trip_id}/classify")
async def classify_trip_route(
    trip_id: str, payload: ClassifyIn,
    user=Depends(require_roles("admin", "manager")),
):
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


# ---------- Trip GPS polyline (Navixy track/read with local cache) ----------
@router.get("/trips/{trip_id}/track")
async def trip_track(
    trip_id: str, refresh: bool = False,
    user=Depends(get_current_user),
):
    """Return the polyline of a trip as a list of `[lng, lat]` points.

    **Strict privacy invariant**: in masked mode, personal trips never
    return GPS points, even cached. → 403.
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
        pts = fallback_points(trip)
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
        pts = fallback_points(trip)
        return {"trip_id": trip_id, "points": pts, "source": "fallback_no_dates", "count": len(pts)}

    try:
        raw = await navixy_read_track(
            int(tracker_id), f, t,
            track_id=trip.get("navixy_trip_id"),
            simplify=True, point_limit=300,
        )
    except NavixyError as e:
        pts = fallback_points(trip)
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
        points = fallback_points(trip)
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


# ---------- Audit log ----------
@router.get("/audit-log")
async def audit_log(limit: int = 100, user=Depends(require_roles("admin"))):
    db = get_db()
    return await db.audit_log.find({}, {"_id": 0}).sort("at", -1).to_list(limit)
