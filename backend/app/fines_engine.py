"""Driver auto-identification engine — used by the Fines module Phase 2.

Given a vehicle + a timestamp, returns the most probable driver by cross-
referencing three sources of truth in the database:

    1. BLE sessions   — highest trust (~95%)   collection `driver_sessions`
    2. GPS trips      — high trust    (~85%)   collection `trips`
    3. Assignments    — fallback      (~60%)   collection `assignments`

The function is read-only — it does not mutate any document. The caller
(`fines.py`) is responsible for persisting the result on the fine record.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List, Dict


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Tolerate trailing Z (Mongo stores ISO 8601 with offset or Z)
        if isinstance(s, datetime):
            return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
        s = s.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _covers(start: Optional[str], end: Optional[str], ts: datetime) -> bool:
    """Return True if the window [start, end] contains `ts`. Open-ended end (None) is allowed."""
    sd = _parse_dt(start)
    if sd and ts < sd:
        return False
    ed = _parse_dt(end)
    if ed and ts > ed:
        return False
    return True


async def identify_driver(
    db,
    vehicle_id: str,
    infraction_at: str,
) -> Dict:
    """Cross-reference BLE / GPS / assignments to identify the driver.

    Returns a dict :
        {
          "driver_id": "..." | None,
          "driver_name": "..." | None,
          "confidence": 0-100,
          "sources": ["BLE", "GPS", "Assignment"],
          "candidates": [{driver_id, driver_name, confidence, source}, ...],
          "reason": "no_vehicle" | "no_match" | "ok"
        }
    """
    out = {
        "driver_id": None, "driver_name": None, "confidence": 0,
        "sources": [], "candidates": [], "reason": "no_match",
    }
    if not vehicle_id or not infraction_at:
        out["reason"] = "missing_input"
        return out
    ts = _parse_dt(infraction_at)
    if not ts:
        out["reason"] = "invalid_datetime"
        return out

    candidates: List[Dict] = []

    # ---------- 1. BLE session ----------
    # Pull recent sessions for the vehicle and filter in Python (Mongo $expr would
    # be heavier; the collection is small enough).
    ble = await db.driver_sessions.find(
        {"tenant_id": "default", "vehicle_id": vehicle_id,
         "status": {"$in": ["automatic", "confirmed", "manual", "closed", "pending"]}},
        {"_id": 0},
    ).sort("started_at", -1).to_list(200)
    for s in ble:
        if _covers(s.get("started_at"), s.get("ended_at"), ts):
            candidates.append({
                "driver_id": s.get("driver_id"),
                "source": "BLE",
                "confidence": 95,
                "detail": f"Session {s.get('status')} #{(s.get('id') or '')[:8]}",
            })
            break  # one BLE match is enough

    # ---------- 2. GPS trip ----------
    trip = await db.trips.find_one(
        {"tenant_id": "default", "vehicle_id": vehicle_id,
         "start_time": {"$lte": ts.isoformat()},
         "end_time": {"$gte": ts.isoformat()}},
        {"_id": 0, "driver_id": 1, "driver_name": 1, "id": 1,
         "start_time": 1, "end_time": 1},
    )
    if trip and trip.get("driver_id"):
        candidates.append({
            "driver_id": trip["driver_id"],
            "source": "GPS",
            "confidence": 85,
            "detail": f"Trajet #{(trip.get('id') or '')[:8]}",
            "trip_id": trip.get("id"),
        })

    # ---------- 3. Assignment ----------
    # Find any assignment matching the vehicle whose time window contains `ts`.
    asgs = await db.assignments.find(
        {"tenant_id": "default", "vehicle_id": vehicle_id},
        {"_id": 0},
    ).to_list(50)
    for a in asgs:
        if _covers(a.get("from_date"), a.get("to_date"), ts):
            candidates.append({
                "driver_id": a.get("driver_id"),
                "source": "Assignment",
                "confidence": 60 if a.get("is_primary") else 45,
                "detail": "Affectation principale" if a.get("is_primary") else "Affectation",
            })
            break

    if not candidates:
        return out

    # ---------- Resolve names + aggregate ----------
    driver_ids = list({c["driver_id"] for c in candidates if c.get("driver_id")})
    drivers_by_id = {}
    if driver_ids:
        async for d in db.drivers.find(
            {"id": {"$in": driver_ids}}, {"_id": 0, "id": 1, "name": 1},
        ):
            drivers_by_id[d["id"]] = d["name"]
    for c in candidates:
        c["driver_name"] = drivers_by_id.get(c.get("driver_id"))

    # Group by driver_id, summing confidence with caps
    by_driver: Dict[str, Dict] = {}
    for c in candidates:
        did = c["driver_id"]
        if not did:
            continue
        bucket = by_driver.setdefault(did, {
            "driver_id": did,
            "driver_name": c.get("driver_name"),
            "confidence": 0,
            "sources": [],
        })
        bucket["sources"].append(c["source"])
        # Take max single-source score, then boost by 5 per extra agreeing source
        bucket["confidence"] = max(bucket["confidence"], c["confidence"])

    # Apply the multi-source bonus and cap at 98
    for b in by_driver.values():
        if len(b["sources"]) > 1:
            b["confidence"] = min(98, b["confidence"] + 5 * (len(b["sources"]) - 1))

    ranked = sorted(by_driver.values(), key=lambda b: -b["confidence"])
    winner = ranked[0]
    return {
        "driver_id": winner["driver_id"],
        "driver_name": winner["driver_name"],
        "confidence": winner["confidence"],
        "sources": winner["sources"],
        "candidates": candidates,
        "ranked": ranked,
        "reason": "ok",
    }
