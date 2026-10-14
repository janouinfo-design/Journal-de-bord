"""Vehicle ↔ Driver assignments (many-to-many, time-aware).

A single vehicle can be driven by multiple drivers over time. A driver can
also drive multiple vehicles. Each assignment is a row:
  { id, vehicle_id, driver_id, from_date, to_date, is_primary, source }

- `from_date` / `to_date` are ISO datetimes; `to_date=None` means "open-ended"
- `is_primary` = the default driver for trips outside any other assignment window
- `source` = 'navixy' | 'manual'

resolve_driver_for_trip() returns the driver_id that owns a given trip.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional


async def list_assignments(db, vehicle_id: Optional[str] = None):
    q = {"tenant_id": "default"}
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    return await db.assignments.find(q, {"_id": 0}).sort("from_date", -1).to_list(1000)


async def add_assignment(db, vehicle_id: str, driver_id: str,
                         from_date: Optional[str] = None,
                         to_date: Optional[str] = None,
                         is_primary: bool = False,
                         source: str = "manual") -> dict:
    if is_primary:
        # Only one primary per vehicle
        await db.assignments.update_many(
            {"vehicle_id": vehicle_id, "is_primary": True},
            {"$set": {"is_primary": False}},
        )
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": "default",
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "from_date": from_date,
        "to_date": to_date,
        "is_primary": bool(is_primary),
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.assignments.insert_one(dict(doc))
    return doc


async def remove_assignment(db, assignment_id: str) -> bool:
    res = await db.assignments.delete_one({"id": assignment_id})
    return res.deleted_count > 0


async def ensure_primary_from_navixy(db, vehicle_id: str, driver_id: str):
    """Idempotent: create a primary assignment if none exists for this vehicle."""
    if not driver_id:
        return
    existing_primary = await db.assignments.find_one(
        {"vehicle_id": vehicle_id, "is_primary": True}, {"_id": 0},
    )
    if existing_primary:
        if existing_primary.get("driver_id") != driver_id:
            await db.assignments.update_one(
                {"id": existing_primary["id"]},
                {"$set": {"driver_id": driver_id, "source": "navixy"}},
            )
        return
    await add_assignment(db, vehicle_id, driver_id,
                         from_date=None, to_date=None,
                         is_primary=True, source="navixy")


def _in_window(trip_iso: str, asg: dict) -> bool:
    if not trip_iso:
        return False
    f, t = asg.get("from_date"), asg.get("to_date")
    if f and trip_iso < f:
        return False
    if t and trip_iso > t:
        return False
    return True


def _covers_primary(trip_iso: str, asg: dict) -> bool:
    """Couverture d'un PRIMARY en convention [start, end) (fin EXCLUSIVE).

    Volet 1 (Design B) : le primary devient TIME-AWARE. Un primary open-ended
    (from_date=None, to_date=None) couvre tout -> comportement actuel INCHANGÉ.
    Un primary fermé (to_date défini) ne couvre PLUS à partir de to_date (exclusif),
    ce qui permettra (Volet 2/3) de neutraliser un primary stale via un cutover.

    NB convention : `_in_window` (étape non-primary) reste en [from, to] inclusif
    (hors périmètre Volet 1) ; l'harmonisation globale [start, end) est prévue au Volet 2.
    """
    if not trip_iso:
        return False
    f, t = asg.get("from_date"), asg.get("to_date")
    if f and trip_iso < f:          # début INCLUSIF : trip == from -> couvert
        return False
    if t and trip_iso >= t:         # fin EXCLUSIVE : trip == to -> NON couvert
        return False
    return True


async def resolve_driver_for_trip(db, vehicle_id: str, trip_start_iso: str) -> Optional[str]:
    """Return the driver_id active for `vehicle_id` at `trip_start_iso`.

    Resolution order:
    1) Most specific assignment whose window covers the trip date (excluding primary)
    2) Primary assignment for the vehicle
    3) None (fail-closed : jamais de repli arbitraire sur asgs[0])
    """
    asgs = await list_assignments(db, vehicle_id=vehicle_id)
    if not asgs:
        return None

    # 1) Non-primary matching window — pick the one with the latest from_date
    matches = [
        a for a in asgs
        if not a.get("is_primary") and _in_window(trip_start_iso, a)
    ]
    if matches:
        matches.sort(key=lambda a: a.get("from_date") or "", reverse=True)
        return matches[0]["driver_id"]

    # 2) Primary — TIME-AWARE (Volet 1) : respecté uniquement si sa fenêtre [start, end)
    #    couvre le trajet. Un primary open-ended (from/to=None) couvre tout (inchangé) ;
    #    un primary fermé (to_date) ne couvre plus à partir de to_date (exclusif).
    for a in asgs:
        if a.get("is_primary") and _covers_primary(trip_start_iso, a):
            return a["driver_id"]

    # 3) Fail-closed : aucune affectation datée couvrante ET aucun primary ->
    #    on NE choisit JAMAIS arbitrairement une ancienne affectation (asgs[0]).
    #    Règle d'identité : la résolution repose uniquement sur des relations
    #    valides (fenêtre datée ou primary), jamais sur un repli aveugle.
    return None


async def driver_vehicle_ids(db, driver_id: str) -> list[str]:
    """All vehicles ever assigned to this driver — used for chauffeur visibility."""
    asgs = await db.assignments.find(
        {"driver_id": driver_id, "tenant_id": "default"},
        {"_id": 0, "vehicle_id": 1},
    ).to_list(1000)
    return list({a["vehicle_id"] for a in asgs})


async def reassign_all_trips(db):
    """Recompute driver_id on every trip based on current assignments."""
    drivers = {d["id"]: d async for d in db.drivers.find({}, {"_id": 0})}
    n = 0
    async for t in db.trips.find({}, {"_id": 0}):
        new_driver = await resolve_driver_for_trip(db, t["vehicle_id"], t.get("start_time", ""))
        if new_driver and new_driver != t.get("driver_id"):
            name = drivers.get(new_driver, {}).get("name") or t.get("driver_name")
            await db.trips.update_one(
                {"id": t["id"]},
                {"$set": {"driver_id": new_driver, "driver_name": name}},
            )
            n += 1
    return n
