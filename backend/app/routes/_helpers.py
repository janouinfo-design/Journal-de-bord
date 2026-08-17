"""Shared helpers used across all sub-routers.

Kept in a dedicated module to avoid circular imports between sibling routers.
NO route definitions here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.assignments import driver_vehicle_ids
from app.rules import default_settings


# ---------- Generic ----------
def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def filename(prefix: str, fmt: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.{fmt}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Settings ----------
async def get_settings_doc(db) -> dict:
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


# ---------- Privacy mask ----------
def apply_privacy(trip: dict, settings: dict, role: str) -> dict:
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


# ---------- Trips query builder ----------
async def filter_trips_query(db, user, start: Optional[str], end: Optional[str],
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


# ---------- Driver resolution ----------
async def resolve_driver_id_for_user(db, user: dict) -> Optional[str]:
    """Map an authenticated user to a driver.id.

    Admins/managers may pass `driver_id` explicitly in the payload (handled by callers).
    """
    if user.get("role") == "driver":
        drv = await db.drivers.find_one(
            {"$or": [{"email": user.get("email")}, {"user_id": user.get("id")}]},
            {"_id": 0, "id": 1},
        )
        if drv:
            return drv["id"]
    for cand in (user.get("driver_id"), user.get("id")):
        if cand and await db.drivers.find_one({"id": cand}, {"_id": 1}):
            return cand
    return None


# ---------- Trip GPS polyline fallback ----------
def fallback_points(trip: dict) -> list[list[float]]:
    """Two-point fallback when Navixy track/read is unavailable."""
    pts = []
    sl, sg = trip.get("start_lat"), trip.get("start_lng")
    el, eg = trip.get("end_lat"), trip.get("end_lng")
    if isinstance(sl, (int, float)) and isinstance(sg, (int, float)):
        pts.append([sg, sl])
    if isinstance(el, (int, float)) and isinstance(eg, (int, float)):
        pts.append([eg, el])
    return pts


# ---------- Schedule normalisation ----------
def normalize_schedule(driver_id: Optional[str], days: list[dict]) -> dict:
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
