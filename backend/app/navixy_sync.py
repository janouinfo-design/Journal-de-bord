"""Sync Navixy → local MongoDB collections.

Strategy:
- tracker/list  → vehicles (plate from label, mode='mixte' default)
- employee/list → drivers (link via tracker_id when available)
- zone/list     → geofences (type inferred from label keywords)
- track/list    → trips (per tracker, chunked by 7 days). Pulled for last N days.

Trips are upserted by `navixy_track_id`. Manual classifications (auto_classified=False)
are preserved across syncs (we only update non-classification fields).
"""
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.navixy_client import (
    list_trackers, list_employees, list_zones, list_tracks,
)
from app.rules import apply_rules_to_all

logger = logging.getLogger(__name__)

# Heuristic mapping of zone labels → semantic type for the rule engine.
PRO_KEYWORDS = ("dépôt", "depot", "entrepôt", "entrepot", "chantier",
                "atelier", "garage", "client", "bureau", "depôt", "site")
PERSO_KEYWORDS = ("domicile", "home", "maison", "perso", "privé", "prive")


def _detect_zone_type(label: str) -> str:
    s = (label or "").lower()
    for kw in PRO_KEYWORDS:
        if kw in s:
            if "entrep" in s: return "entrepot"
            if "chantier" in s: return "chantier"
            if "depot" in s or "dépôt" in s or "depôt" in s: return "depot"
            return "client"
    for kw in PERSO_KEYWORDS:
        if kw in s:
            return "domicile"
    return "client"  # safer default (treat zone as professional)


def _full_name(emp: dict) -> str:
    parts = [emp.get("first_name") or "", emp.get("middle_name") or "", emp.get("last_name") or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or f"Employé #{emp.get('id')}"


def _point_in_zone(lat: float, lng: float, zone: dict) -> bool:
    """Approximate match via bounding box (works for any zone shape)."""
    b = zone.get("bounds") or {}
    nw = b.get("nw") or {}
    se = b.get("se") or {}
    if not nw or not se:
        return False
    lat_lo, lat_hi = sorted([nw.get("lat", 0), se.get("lat", 0)])
    lng_lo, lng_hi = sorted([nw.get("lng", 0), se.get("lng", 0)])
    return (lat_lo <= lat <= lat_hi) and (lng_lo <= lng <= lng_hi)


async def sync_navixy(days: int = 30, force_reclassify: bool = True) -> dict:
    """Pull trackers, employees, zones, and tracks from Navixy.

    Returns a summary dict with counts.
    """
    from app.db import get_db
    db = get_db()
    summary = {
        "trackers": 0, "drivers": 0, "zones": 0,
        "trips_new": 0, "trips_updated": 0, "trackers_with_data": 0,
        "errors": [],
    }

    # ----- Trackers -----
    trackers = await list_trackers()
    tracker_by_id: dict[int, dict] = {}
    for t in trackers:
        navixy_id = t["id"]
        tracker_by_id[navixy_id] = t
        existing = await db.vehicles.find_one({"navixy_tracker_id": navixy_id})
        plate = (t.get("label") or f"Tracker {navixy_id}").strip()
        model = (t.get("source") or {}).get("model") or ""
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
        summary["trackers"] += 1

    # ----- Employees / Drivers -----
    employees = await list_employees()
    driver_by_tracker: dict[int, dict] = {}
    for e in employees:
        navixy_id = e["id"]
        name = _full_name(e)
        existing = await db.drivers.find_one({"navixy_employee_id": navixy_id})
        if existing:
            await db.drivers.update_one(
                {"navixy_employee_id": navixy_id},
                {"$set": {"name": name, "email": e.get("email") or existing.get("email")}},
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
        summary["drivers"] += 1
        if e.get("tracker_id"):
            driver_by_tracker[e["tracker_id"]] = driver_doc
            await db.vehicles.update_one(
                {"navixy_tracker_id": e["tracker_id"]},
                {"$set": {"assigned_driver_id": driver_doc["id"]}},
            )

    # ----- Zones -----
    zones_raw = await list_zones()
    zones_local: list[dict] = []
    for z in zones_raw:
        navixy_id = z["id"]
        ztype = _detect_zone_type(z.get("label", ""))
        b = z.get("bounds") or {}
        nw = b.get("nw") or {}
        se = b.get("se") or {}
        lat = (nw.get("lat", 0) + se.get("lat", 0)) / 2 if nw and se else 0
        lng = (nw.get("lng", 0) + se.get("lng", 0)) / 2 if nw and se else 0
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
            await db.geofences.update_one({"navixy_zone_id": navixy_id},
                                          {"$set": {"name": z.get("label"), "type": ztype, "bounds": b}})
            existing.update(doc)
            zones_local.append(existing)
        else:
            await db.geofences.insert_one(doc)
            zones_local.append(doc)
        summary["zones"] += 1

    # ----- Tracks -----
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    def _fmt(d: datetime) -> str:
        return d.strftime("%Y-%m-%d %H:%M:%S")

    def _classify_point(lat: float, lng: float) -> str:
        for z in zones_local:
            if _point_in_zone(lat, lng, z):
                return z["type"]
        return "unknown"

    for tracker_id, t in tracker_by_id.items():
        vehicle = await db.vehicles.find_one({"navixy_tracker_id": tracker_id})
        if not vehicle:
            continue
        driver_doc = driver_by_tracker.get(tracker_id)
        # Chunk by 7 days (Navixy span limit)
        cursor = start_dt
        had_any = False
        while cursor < end_dt:
            chunk_end = min(cursor + timedelta(days=7), end_dt)
            try:
                resp = await list_tracks(tracker_id, _fmt(cursor), _fmt(chunk_end))
            except Exception as ex:
                summary["errors"].append(f"track/list tracker={tracker_id}: {ex}")
                cursor = chunk_end
                continue
            for tr in resp.get("list", []):
                navixy_track_id = tr["id"]
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
                start_zone = _classify_point(start_lat, start_lng)
                end_zone = _classify_point(end_lat, end_lng)
                # Heuristic fuel estimate: avg 8.5L/100km
                length_km = float(tr.get("length", 0) or 0)
                fuel_l = round(length_km * 0.085, 2)

                doc = {
                    "tenant_id": "default",
                    "driver_id": (driver_doc or {}).get("id"),
                    "driver_name": (driver_doc or {}).get("name") or vehicle.get("plate"),
                    "vehicle_id": vehicle["id"],
                    "vehicle_plate": vehicle["plate"],
                    "navixy_track_id": navixy_track_id,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "start_address": tr.get("start_address", ""),
                    "start_lat": start_lat, "start_lng": start_lng,
                    "start_zone_type": start_zone,
                    "end_address": tr.get("end_address", ""),
                    "end_lat": end_lat, "end_lng": end_lng,
                    "end_zone_type": end_zone,
                    "distance_km": round(length_km, 1),
                    "duration_min": dur_min,
                    "fuel_l": fuel_l,
                    "avg_speed": float(tr.get("avg_speed", 0) or 0),
                    "max_speed": float(tr.get("max_speed", 0) or 0),
                }

                existing = await db.trips.find_one({"navixy_track_id": navixy_track_id})
                if existing:
                    # Preserve manual classifications
                    update = {**doc}
                    if not existing.get("auto_classified", True):
                        update.pop("driver_id", None)  # keep modified driver/vehicle as-is
                    await db.trips.update_one({"navixy_track_id": navixy_track_id}, {"$set": update})
                    summary["trips_updated"] += 1
                else:
                    doc.update({
                        "id": str(uuid.uuid4()),
                        "classification": None,
                        "auto_classified": True,
                        "modified_by": None,
                        "modified_at": None,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    await db.trips.insert_one(doc)
                    summary["trips_new"] += 1
                had_any = True
            cursor = chunk_end
        if had_any:
            summary["trackers_with_data"] += 1

    if force_reclassify:
        summary["reclassified"] = await apply_rules_to_all(db)

    logger.info("Navixy sync done: %s", summary)
    return summary


def _normalize_navixy_date(s: str) -> str:
    """Navixy returns 'YYYY-MM-DD HH:MM:SS' (server tz, treated as UTC)."""
    if not s:
        return ""
    if "T" in s:
        return s
    return s.replace(" ", "T") + "+00:00"


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))
