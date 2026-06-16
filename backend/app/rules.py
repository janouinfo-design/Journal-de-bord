"""Auto-classification rule engine.

Rules priority:
1) Vehicle mode: always_pro / always_perso => override
2) Geofence-based: depot/entrepot/chantier/client => pro; domicile => perso
3) Time-based: weekday 07:00-18:00 => pro, else perso; weekend => perso
"""
from datetime import datetime
from typing import Optional


PRO_ZONE_TYPES = {"depot", "entrepot", "chantier", "client"}
PERSO_ZONE_TYPES = {"domicile", "personal"}


def classify_trip(trip: dict, vehicle: Optional[dict], settings: dict) -> str:
    """Return 'professional' or 'personal'."""
    mode = settings.get("mode", "A")

    # Mode C: tout est pro
    if mode == "C":
        return "professional"

    # Vehicle mode override
    if vehicle:
        vmode = vehicle.get("mode")
        if vmode == "always_pro":
            return "professional"
        if vmode == "always_perso":
            return "personal"

    rules = settings.get("rules", {})

    # Geofence rule
    if rules.get("geofence_enabled", True):
        start_z = trip.get("start_zone_type")
        end_z = trip.get("end_zone_type")
        if start_z in PRO_ZONE_TYPES or end_z in PRO_ZONE_TYPES:
            return "professional"
        if start_z in PERSO_ZONE_TYPES and end_z in PERSO_ZONE_TYPES:
            return "personal"

    # Time-based rule
    if rules.get("time_enabled", True):
        try:
            start_dt = datetime.fromisoformat(trip["start_time"].replace("Z", "+00:00"))
        except Exception:
            return "professional"
        weekday = start_dt.weekday()  # 0=Mon...6=Sun
        if weekday in (rules.get("weekend_days", [5, 6])):
            return "personal"
        start_h = rules.get("work_start_hour", 7)
        end_h = rules.get("work_end_hour", 18)
        if start_h <= start_dt.hour < end_h:
            return "professional"
        return "personal"

    return "professional"


async def apply_rules_to_all(db):
    """Reclassify any trips that are still auto-classified (not user-modified)."""
    settings = await db.settings.find_one({"id": "default"}, {"_id": 0}) or default_settings()
    vehicles = {v["id"]: v async for v in db.vehicles.find({}, {"_id": 0})}
    updated = 0
    async for trip in db.trips.find({"auto_classified": True}, {"_id": 0}):
        cls = classify_trip(trip, vehicles.get(trip["vehicle_id"]), settings)
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
        "mode": "A",  # A=visible, B=masqué, C=100% pro
        "rules": {
            "time_enabled": True,
            "geofence_enabled": True,
            "work_start_hour": 7,
            "work_end_hour": 18,
            "weekend_days": [5, 6],  # Saturday, Sunday
        },
    }
