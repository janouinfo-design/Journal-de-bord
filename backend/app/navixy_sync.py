"""Sync Navixy → local MongoDB collections.

Strategy:
- tracker/list  → vehicles (plate from label, mode='mixte' default)
- employee/list → drivers (link via tracker_id when available)
- zone/list     → geofences (type inferred from label keywords)
- track/list    → trips (per tracker, chunked by 7 days). Pulled for last N days.

Trips are upserted by `navixy_track_id`. Manual classifications
(auto_classified=False) are preserved across syncs.

Refactored in iteration 26 (22/06/2026): the previously monolithic 200-line
`sync_navixy()` was split into 4 phase helpers (`_sync_trackers`,
`_sync_employees`, `_sync_zones`, `_sync_tracks`) plus 2 trip-level helpers
(`_build_trip_doc`, `_upsert_trip`) for readability and unit-testability.
External signature unchanged: `sync_navixy(days, force_reclassify) -> dict`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.assignments import ensure_primary_from_navixy, resolve_driver_for_trip
from app.navixy_client import (
    list_employees, list_trackers, list_tracks, list_zones,
)
from app.rules import apply_rules_to_all

logger = logging.getLogger(__name__)

# Heuristic mapping of zone labels → semantic type for the rule engine.
PRO_KEYWORDS = ("dépôt", "depot", "entrepôt", "entrepot", "chantier",
                "atelier", "garage", "client", "bureau", "depôt", "site")
PERSO_KEYWORDS = ("domicile", "home", "maison", "perso", "privé", "prive")

# Heuristic fuel estimate: 8.5 L / 100 km
FUEL_L_PER_KM = 0.085

# Navixy track/list span limit
TRACK_CHUNK_DAYS = 7


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _detect_zone_type(label: str) -> str:
    s = (label or "").lower()
    for kw in PRO_KEYWORDS:
        if kw in s:
            if "entrep" in s:
                return "entrepot"
            if "chantier" in s:
                return "chantier"
            if "depot" in s or "dépôt" in s or "depôt" in s:
                return "depot"
            return "client"
    for kw in PERSO_KEYWORDS:
        if kw in s:
            return "domicile"
    return "client"  # safer default (treat zone as professional)


def _full_name(emp: dict) -> str:
    parts = [emp.get("first_name"), emp.get("middle_name"), emp.get("last_name")]
    name = " ".join(p for p in parts if p)
    return name or emp.get("email") or f"Employee {emp.get('id')}"


def _point_in_zone(lat: float, lng: float, zone: dict) -> bool:
    b = zone.get("bounds") or {}
    nw = b.get("nw") or {}
    se = b.get("se") or {}
    if not nw or not se:
        return False
    lat_lo, lat_hi = sorted([nw.get("lat", 0), se.get("lat", 0)])
    lng_lo, lng_hi = sorted([nw.get("lng", 0), se.get("lng", 0)])
    return (lat_lo <= lat <= lat_hi) and (lng_lo <= lng <= lng_hi)


def _normalize_navixy_date(s: str) -> str:
    """Navixy returns 'YYYY-MM-DD HH:MM:SS' (server tz, treated as UTC)."""
    if not s:
        return ""
    if "T" in s:
        return s
    return s.replace(" ", "T") + "+00:00"


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _zone_centroid(b: dict) -> tuple[float, float]:
    nw = b.get("nw") or {}
    se = b.get("se") or {}
    if not nw or not se:
        return 0.0, 0.0
    return (nw.get("lat", 0) + se.get("lat", 0)) / 2, (nw.get("lng", 0) + se.get("lng", 0)) / 2


def _classify_point(lat: float, lng: float, zones_local: list[dict]) -> str:
    for z in zones_local:
        if _point_in_zone(lat, lng, z):
            return z["type"]
    return "unknown"


# ---------------------------------------------------------------------------
# Phase 1 — Trackers / Vehicles
# ---------------------------------------------------------------------------
async def _sync_trackers(db) -> tuple[int, dict[int, dict]]:
    """Upsert vehicles from Navixy trackers. Returns (count, tracker_by_id)."""
    trackers = await list_trackers()
    tracker_by_id: dict[int, dict] = {}
    for t in trackers:
        navixy_id = t["id"]
        tracker_by_id[navixy_id] = t
        plate = (t.get("label") or f"Tracker {navixy_id}").strip()
        model = (t.get("source") or {}).get("model") or ""
        existing = await db.vehicles.find_one({"navixy_tracker_id": navixy_id})
        if existing:
            await db.vehicles.update_one(
                {"navixy_tracker_id": navixy_id},
                {"$set": {"plate": plate, "model": model}},
            )
        else:
            await db.vehicles.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": "default",
                "plate": plate, "model": model,
                "mode": "mixte",
                "navixy_tracker_id": navixy_id,
                "assigned_driver_id": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    return len(trackers), tracker_by_id


# ---------------------------------------------------------------------------
# Phase 2 — Employees / Drivers
# ---------------------------------------------------------------------------
async def _sync_employees(db) -> tuple[int, dict[int, dict]]:
    """Upsert drivers from Navixy employees + ensure primary assignment when a
    tracker is linked. Returns (count, driver_by_tracker)."""
    employees = await list_employees()
    driver_by_tracker: dict[int, dict] = {}
    for e in employees:
        navixy_id = e["id"]
        name = _full_name(e)
        existing = await db.drivers.find_one({"navixy_employee_id": navixy_id})
        if existing:
            await db.drivers.update_one(
                {"navixy_employee_id": navixy_id},
                {"$set": {"name": name,
                          "email": e.get("email") or existing.get("email")}},
            )
            driver_doc = await db.drivers.find_one({"navixy_employee_id": navixy_id})
        else:
            driver_doc = {
                "id": str(uuid.uuid4()),
                "tenant_id": "default",
                "name": name,
                "email": e.get("email") or "",
                "navixy_employee_id": navixy_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.drivers.insert_one(driver_doc)

        if e.get("tracker_id"):
            driver_by_tracker[e["tracker_id"]] = driver_doc
            vehicle = await db.vehicles.find_one(
                {"navixy_tracker_id": e["tracker_id"]}, {"_id": 0},
            )
            if vehicle:
                await ensure_primary_from_navixy(db, vehicle["id"], driver_doc["id"])
    return len(employees), driver_by_tracker


# ---------------------------------------------------------------------------
# Phase 3 — Zones / Geofences
# ---------------------------------------------------------------------------
async def _sync_zones(db) -> tuple[int, list[dict]]:
    """Upsert geofences from Navixy zones. Returns (count, zones_local list
    used by the track classifier)."""
    zones_raw = await list_zones()
    zones_local: list[dict] = []
    for z in zones_raw:
        navixy_id = z["id"]
        ztype = _detect_zone_type(z.get("label", ""))
        b = z.get("bounds") or {}
        lat, lng = _zone_centroid(b)
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "name": z.get("label"),
            "type": ztype,
            "lat": lat, "lng": lng,
            "radius_m": 200,
            "bounds": b,
            "navixy_zone_id": navixy_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        existing = await db.geofences.find_one({"navixy_zone_id": navixy_id})
        if existing:
            await db.geofences.update_one(
                {"navixy_zone_id": navixy_id},
                {"$set": {"name": z.get("label"), "type": ztype, "bounds": b}},
            )
            existing.update(doc)
            zones_local.append(existing)
        else:
            await db.geofences.insert_one(doc)
            zones_local.append(doc)
    return len(zones_raw), zones_local


# ---------------------------------------------------------------------------
# Phase 4 — Tracks / Trips
# ---------------------------------------------------------------------------
async def _build_trip_doc(
    db, vehicle: dict, tr: dict, zones_local: list[dict],
) -> dict:
    """Translate a Navixy track payload into a local `trips` document."""
    start_iso = _normalize_navixy_date(tr["start_date"])
    end_iso = _normalize_navixy_date(tr["end_date"])
    dur_min = max(int((_parse(end_iso) - _parse(start_iso)).total_seconds() / 60), 0)
    bounds = tr.get("bounds") or {}
    nw = bounds.get("nw") or {}
    se = bounds.get("se") or {}
    start_lat = nw.get("lat", 0)
    start_lng = nw.get("lng", 0)
    end_lat = se.get("lat", 0)
    end_lng = se.get("lng", 0)
    length_km = float(tr.get("length", 0) or 0)

    # Resolve driver via assignments (time-aware many-to-many)
    resolved_driver_id = await resolve_driver_for_trip(db, vehicle["id"], start_iso)
    resolved_driver_name = None
    if resolved_driver_id:
        dd = await db.drivers.find_one({"id": resolved_driver_id}, {"_id": 0})
        if dd:
            resolved_driver_name = dd["name"]

    return {
        "tenant_id": "default",
        "driver_id": resolved_driver_id,
        "driver_name": resolved_driver_name or vehicle.get("plate"),
        "vehicle_id": vehicle["id"],
        "vehicle_plate": vehicle["plate"],
        "navixy_track_id": tr["id"],
        "start_time": start_iso,
        "end_time": end_iso,
        "start_address": tr.get("start_address", ""),
        "start_lat": start_lat, "start_lng": start_lng,
        "start_zone_type": _classify_point(start_lat, start_lng, zones_local),
        "end_address": tr.get("end_address", ""),
        "end_lat": end_lat, "end_lng": end_lng,
        "end_zone_type": _classify_point(end_lat, end_lng, zones_local),
        "distance_km": round(length_km, 1),
        "duration_min": dur_min,
        "fuel_l": round(length_km * FUEL_L_PER_KM, 2),
        "avg_speed": float(tr.get("avg_speed", 0) or 0),
        "max_speed": float(tr.get("max_speed", 0) or 0),
    }


async def _upsert_trip(db, doc: dict) -> str:
    """Insert or update a trip by navixy_track_id. Returns 'new' or 'updated'.

    Manual classifications (auto_classified=False) are preserved: we do NOT
    overwrite the driver_id chosen by the user on a manually-edited trip.
    """
    navixy_track_id = doc["navixy_track_id"]
    existing = await db.trips.find_one({"navixy_track_id": navixy_track_id})
    if existing:
        update = {**doc}
        if not existing.get("auto_classified", True):
            update.pop("driver_id", None)
        await db.trips.update_one({"navixy_track_id": navixy_track_id}, {"$set": update})
        if doc.get("end_time"):
            from app.ble_engine import mark_sessions_trip_end
            await mark_sessions_trip_end(db, {**doc, "id": existing.get("id")})
        return "updated"
    doc.update({
        "id": str(uuid.uuid4()),
        "classification": None,
        "auto_classified": True,
        "modified_by": None,
        "modified_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.trips.insert_one(doc)
    if doc.get("end_time"):
        from app.ble_engine import mark_sessions_trip_end
        await mark_sessions_trip_end(db, doc)
    return "new"


async def _sync_tracks_for_vehicle(
    db, vehicle: dict, tracker_id: int,
    start_dt: datetime, end_dt: datetime,
    zones_local: list[dict], errors: list[str],
) -> tuple[int, int, bool]:
    """Pull tracks for a single tracker, chunked by TRACK_CHUNK_DAYS.

    Returns (new_count, updated_count, had_any_track).
    """
    new_count = 0
    updated_count = 0
    had_any = False
    cursor = start_dt
    while cursor < end_dt:
        chunk_end = min(cursor + timedelta(days=TRACK_CHUNK_DAYS), end_dt)
        try:
            resp = await list_tracks(tracker_id, _fmt(cursor), _fmt(chunk_end))
        except Exception as ex:  # noqa: BLE001 — we want the full error message
            errors.append(f"track/list tracker={tracker_id}: {ex}")
            cursor = chunk_end
            continue
        for tr in resp.get("list", []):
            doc = await _build_trip_doc(db, vehicle, tr, zones_local)
            status = await _upsert_trip(db, doc)
            if status == "new":
                new_count += 1
            else:
                updated_count += 1
            had_any = True
        cursor = chunk_end
    return new_count, updated_count, had_any


async def _sync_tracks(
    db, tracker_by_id: dict[int, dict], zones_local: list[dict], days: int,
) -> dict:
    """Iterate every tracker and pull its tracks for the last `days` days."""
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    counts = {"trips_new": 0, "trips_updated": 0, "trackers_with_data": 0,
              "errors": []}
    for tracker_id in tracker_by_id:
        vehicle = await db.vehicles.find_one({"navixy_tracker_id": tracker_id})
        if not vehicle:
            continue
        new_c, upd_c, had_any = await _sync_tracks_for_vehicle(
            db, vehicle, tracker_id, start_dt, end_dt, zones_local, counts["errors"],
        )
        counts["trips_new"] += new_c
        counts["trips_updated"] += upd_c
        if had_any:
            counts["trackers_with_data"] += 1
    return counts


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def sync_navixy(days: int = 30, force_reclassify: bool = True) -> dict:
    """Pull trackers, employees, zones, and tracks from Navixy. Idempotent.

    The function delegates each domain to a phase helper to keep this
    orchestrator readable. External signature & returned summary keys are
    unchanged (relied on by /api/livre/navixy/sync).
    """
    from app.db import get_db
    db = get_db()

    trackers_count, tracker_by_id = await _sync_trackers(db)
    drivers_count, _driver_by_tracker = await _sync_employees(db)
    zones_count, zones_local = await _sync_zones(db)
    tracks_summary = await _sync_tracks(db, tracker_by_id, zones_local, days)

    summary: dict[str, Any] = {
        "trackers": trackers_count,
        "drivers": drivers_count,
        "zones": zones_count,
        **tracks_summary,
    }

    if force_reclassify:
        summary["reclassified"] = await apply_rules_to_all(db)

    logger.info("Navixy sync done: %s", summary)
    return summary
