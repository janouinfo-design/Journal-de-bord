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
    if f and trip_iso < f:
        return False
    if t and trip_iso >= t:
        return False
    return True


async def _resolve_driver_for_trip_v1(
    db, vehicle_id: str, trip_start_iso: str,
) -> Optional[str]:
    """Legacy resolver V1, preserved exactly for historical/admin flows.

    KNOWN_LIMITATION: legacy assignments remain intentionally scoped to
    tenant_id="default" through list_assignments(). Multi-tenant legacy
    resolution is outside Volet 2. The V2 modern resolver never silently reads
    vehicle_assignment_events from tenant "default" when the vehicle tenant is
    missing or different.

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

    # 2) Primary
    for a in asgs:
        if a.get("is_primary") and _covers_primary(trip_start_iso, a):
            return a["driver_id"]

    # 3) Fail-closed : aucune affectation datée couvrante ET aucun primary ->
    #    on NE choisit JAMAIS arbitrairement une ancienne affectation (asgs[0]).
    #    Règle d'identité : la résolution repose uniquement sur des relations
    #    valides (fenêtre datée ou primary), jamais sur un repli aveugle.
    return None


def _parse_modern_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp for modern assignment events; invalid => unknown."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reconstruct_modern_segments(events: list[dict]):
    """Rebuild per-driver modern vehicle segments in strict [start, end).

    Only successful events are supplied by the caller. TAKEN/RELEASED and
    CHANGED are understood. Any malformed/unknown transition is recorded as a
    conflict for the affected driver/vehicle instead of being guessed or
    repaired. Open segments keep end=None.
    """
    modern_since: dict[str, datetime] = {}
    open_by_driver: dict[str, tuple[str, datetime]] = {}
    segments: list[dict] = []
    conflict_drivers: set[str] = set()
    conflict_vehicle_since: dict[str, datetime] = {}

    def mark_conflict(driver_id: str, at: datetime, *vehicle_ids: Optional[str]):
        conflict_drivers.add(driver_id)
        for vid in vehicle_ids:
            if not vid:
                continue
            prev = conflict_vehicle_since.get(vid)
            if prev is None or at < prev:
                conflict_vehicle_since[vid] = at

    sortable = []
    for event in events:
        at = _parse_modern_ts(event.get("at"))
        driver_id = event.get("driver_id")
        if not at or not driver_id:
            continue
        sortable.append((at, str(event.get("id") or ""), event))

    for at, _event_id, event in sorted(sortable, key=lambda row: (row[0], row[1])):
        driver_id = event["driver_id"]
        modern_since.setdefault(driver_id, at)
        event_type = event.get("type")
        from_vehicle = event.get("from_vehicle_id")
        to_vehicle = event.get("to_vehicle_id")
        current = open_by_driver.get(driver_id)

        if event_type == "VEHICLE_TAKEN":
            if not to_vehicle or current is not None:
                mark_conflict(
                    driver_id, at,
                    current[0] if current else None,
                    to_vehicle,
                )
                continue
            open_by_driver[driver_id] = (to_vehicle, at)
            continue

        if event_type == "VEHICLE_RELEASED":
            if not from_vehicle or current is None or current[0] != from_vehicle:
                mark_conflict(
                    driver_id, at,
                    current[0] if current else None,
                    from_vehicle,
                )
                continue
            segments.append({
                "driver_id": driver_id,
                "vehicle_id": current[0],
                "start": current[1],
                "end": at,
            })
            del open_by_driver[driver_id]
            continue

        if event_type == "VEHICLE_CHANGED":
            if (
                not from_vehicle
                or not to_vehicle
                or current is None
                or current[0] != from_vehicle
            ):
                mark_conflict(
                    driver_id, at,
                    current[0] if current else None,
                    from_vehicle,
                    to_vehicle,
                )
                continue
            segments.append({
                "driver_id": driver_id,
                "vehicle_id": current[0],
                "start": current[1],
                "end": at,
            })
            open_by_driver[driver_id] = (to_vehicle, at)
            continue

        # FORCE/future/unknown events are deliberately not invented here.
        # Their existence establishes modern authority (modern_since) but the
        # transition itself is ambiguous => fail-closed for affected relations.
        mark_conflict(
            driver_id, at,
            current[0] if current else None,
            from_vehicle,
            to_vehicle,
        )

    for driver_id, (vehicle_id, start) in open_by_driver.items():
        segments.append({
            "driver_id": driver_id,
            "vehicle_id": vehicle_id,
            "start": start,
            "end": None,
        })

    # Un conflit à l'instant T ne doit JAMAIS invalider rétroactivement une
    # relation moderne déjà prouvée AVANT T. On NE supprime donc PAS en masse les
    # segments valides d'un chauffeur en conflit : la neutralisation se fait
    # uniquement À PARTIR de l'instant du conflit, via `conflict_vehicle_since`
    # (le resolver renvoie None pour tout trajet dont trip_start >= conflict_since
    # sur le véhicule concerné). Les segments valides antérieurs au conflit
    # restent couvrants (ex. un ancien trajet auto-classifié n'est jamais réécrit
    # par un événement incohérent survenu plus tard).
    #
    # Seul ajustement : on BORNE les segments OUVERTS (end=None) d'un chauffeur en
    # conflit à l'instant de conflit de LEUR véhicule, pour éviter qu'un segment
    # « jusqu'à +inf » ne couvre au-delà du point d'incohérence.
    if conflict_drivers:
        bounded: list[dict] = []
        for segment in segments:
            if (
                segment["driver_id"] in conflict_drivers
                and segment.get("end") is None
            ):
                cs = conflict_vehicle_since.get(segment["vehicle_id"])
                if cs is not None and cs > segment["start"]:
                    segment = {**segment, "end": cs}
            bounded.append(segment)
        segments = bounded

    return segments, modern_since, conflict_drivers, conflict_vehicle_since


async def resolve_driver_for_trip(db, vehicle_id: str, trip_start_iso: str) -> Optional[str]:
    """Volet 2 multi-source resolver: V1 unless modern authority is proven.

    Modern authority is scoped by the real vehicle tenant. A unique modern
    [start, end) segment wins. Once the V1 candidate driver has a modern_since
    boundary, absence of a covering modern segment at/after that boundary is
    fail-closed (None): there is no legacy fallback.
    """
    legacy_driver = await _resolve_driver_for_trip_v1(
        db, vehicle_id, trip_start_iso,
    )

    trip_start = _parse_modern_ts(trip_start_iso)
    if trip_start is None:
        return legacy_driver

    vehicle = await db.vehicles.find_one(
        {"id": vehicle_id},
        {"_id": 0, "tenant_id": 1},
    )
    tenant_id = vehicle.get("tenant_id") if vehicle else None
    if not tenant_id:
        # Tenant moderne non prouvé : ne jamais lire silencieusement "default".
        return legacy_driver

    events = await db.vehicle_assignment_events.find(
        {"tenant_id": tenant_id, "result": "OK"},
        {
            "_id": 0,
            "id": 1,
            "tenant_id": 1,
            "driver_id": 1,
            "type": 1,
            "from_vehicle_id": 1,
            "to_vehicle_id": 1,
            "at": 1,
            "result": 1,
        },
    ).sort("at", 1).to_list(10000)

    if not events:
        return legacy_driver

    segments, modern_since, _conflict_drivers, conflict_vehicle_since = (
        _reconstruct_modern_segments(events)
    )

    conflict_since = conflict_vehicle_since.get(vehicle_id)
    if conflict_since is not None and trip_start >= conflict_since:
        return None

    covering = [
        segment for segment in segments
        if segment["vehicle_id"] == vehicle_id
        and trip_start >= segment["start"]
        and (segment["end"] is None or trip_start < segment["end"])
    ]

    if len(covering) > 1:
        return None
    if len(covering) == 1:
        return covering[0]["driver_id"]

    if not legacy_driver:
        return None

    boundary = modern_since.get(legacy_driver)
    if boundary is None or trip_start < boundary:
        return legacy_driver

    # Candidate legacy already under modern authority, but no modern segment
    # covers this vehicle/time: fail-closed, never fall back to stale legacy.
    return None


async def driver_vehicle_ids(db, driver_id: str) -> list[str]:
    """All vehicles ever assigned to this driver — used for chauffeur visibility."""
    asgs = await db.assignments.find(
        {"driver_id": driver_id, "tenant_id": "default"},
        {"_id": 0, "vehicle_id": 1},
    ).to_list(1000)
    return list({a["vehicle_id"] for a in asgs})


async def reassign_all_trips(db):
    """Recompute driver_id on every trip using legacy V1 only."""
    drivers = {d["id"]: d async for d in db.drivers.find({}, {"_id": 0})}
    n = 0
    async for t in db.trips.find({}, {"_id": 0}):
        new_driver = await _resolve_driver_for_trip_v1(
            db, t["vehicle_id"], t.get("start_time", ""),
        )
        if new_driver and new_driver != t.get("driver_id"):
            name = drivers.get(new_driver, {}).get("name") or t.get("driver_name")
            await db.trips.update_one(
                {"id": t["id"]},
                {"$set": {"driver_id": new_driver, "driver_name": name}},
            )
            n += 1
    return n
