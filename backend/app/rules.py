"""Auto-classification rule engine.

Simplified model (Iteration 4):
- Vehicle mode override: always_pro / always_perso wins
- Otherwise, per-day schedule: each day is 'work' or 'personal'.
  When 'work', up to 3 enabled time periods define WHEN it is professional.
  Everything outside those periods is personal.
  When 'personal', the whole day is personal.
- Schedules are stored in `db.schedules`. A schedule with driver_id=None is the
  default; per-driver overrides are looked up by driver_id and fall back to default.
"""
from datetime import datetime
from typing import Optional


def _parse_hm(s: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _in_any_period(minute_of_day: int, periods: list[dict]) -> bool:
    for p in periods or []:
        if not p.get("enabled"):
            continue
        f = _parse_hm(p.get("from", "00:00"))
        t = _parse_hm(p.get("to", "00:00"))
        if t <= f:
            continue
        if f <= minute_of_day < t:
            return True
    return False


def classify_trip(trip: dict, vehicle: Optional[dict], settings: dict, schedule: dict) -> str:
    """Return 'professional' or 'personal'.

    `schedule` is a dict with shape: { days: [ {day: 0..6, type: 'work'|'personal',
    periods: [ {enabled, from, to}, ... ] }, ... ] }
    """
    # Vehicle mode override (highest priority)
    if vehicle:
        vmode = vehicle.get("mode")
        if vmode == "always_pro":
            return "professional"
        if vmode == "always_perso":
            return "personal"

    try:
        start_dt = datetime.fromisoformat(trip["start_time"].replace("Z", "+00:00"))
    except Exception:
        return "professional"

    weekday = start_dt.weekday()  # 0=Mon ... 6=Sun
    day_cfg = None
    for d in schedule.get("days", []):
        if d.get("day") == weekday:
            day_cfg = d
            break
    if not day_cfg or day_cfg.get("type") == "personal":
        return "personal"

    minute_of_day = start_dt.hour * 60 + start_dt.minute
    return "professional" if _in_any_period(minute_of_day, day_cfg.get("periods", [])) else "personal"


async def _get_schedule_for(db, driver_id: Optional[str]) -> dict:
    """Resolve schedule: per-driver override OR default."""
    if driver_id:
        s = await db.schedules.find_one({"driver_id": driver_id}, {"_id": 0})
        if s:
            return s
    s = await db.schedules.find_one({"driver_id": None}, {"_id": 0})
    if not s:
        s = default_schedule(driver_id=None)
        await db.schedules.insert_one(dict(s))
    return s


async def apply_rules_to_all(db):
    """Reclassify auto-classified trips using the current settings + schedules."""
    settings = await db.settings.find_one({"id": "default"}, {"_id": 0}) or default_settings()
    vehicles = {v["id"]: v async for v in db.vehicles.find({}, {"_id": 0})}
    default_sched = await _get_schedule_for(db, None)
    # Cache per-driver schedules
    cache: dict = {}
    updated = 0
    async for trip in db.trips.find({"auto_classified": True}, {"_id": 0}):
        drv = trip.get("driver_id")
        if drv in cache:
            sched = cache[drv]
        elif drv:
            sched = await db.schedules.find_one({"driver_id": drv}, {"_id": 0}) or default_sched
            cache[drv] = sched
        else:
            sched = default_sched
        cls = classify_trip(trip, vehicles.get(trip["vehicle_id"]), settings, sched)
        if trip.get("classification") != cls:
            await db.trips.update_one(
                {"id": trip["id"]},
                {"$set": {"classification": cls}},
            )
            updated += 1
    return updated


def default_settings() -> dict:
    return {
        "id": "default",
        "mode": "mixte",  # mixte = visible / masked = anonymisé
    }


def default_schedule(driver_id: Optional[str] = None) -> dict:
    """Default schedule: Mon-Fri = work 07:00-12:00 and 13:00-18:00; Sat/Sun = personal."""
    days = []
    for i in range(7):
        if i < 5:  # Mon..Fri
            days.append({
                "day": i,
                "type": "work",
                "periods": [
                    {"enabled": True, "from": "07:00", "to": "12:00"},
                    {"enabled": True, "from": "13:00", "to": "18:00"},
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                ],
            })
        else:
            days.append({
                "day": i,
                "type": "personal",
                "periods": [
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                ],
            })
    return {
        "id": f"sched-{driver_id or 'default'}",
        "tenant_id": "default",
        "driver_id": driver_id,
        "days": days,
    }
