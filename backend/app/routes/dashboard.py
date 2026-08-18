"""Dashboard endpoint — aggregated KPIs, daily series, per-driver table."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import get_db

from app.routes._helpers import (
    filter_trips_query,
    get_settings_doc,
    parse_iso,
)

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(
    start: Optional[str] = None,
    end: Optional[str] = None,
    driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    group: Optional[str] = None,
    company: Optional[str] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    settings = await get_settings_doc(db)
    q = await filter_trips_query(db, user, start, end, driver_id, vehicle_id, None,
                                 group=group, company=company)
    # Aggregation-only endpoint: project only the fields we actually consume
    # to keep the response small even on large fleets.
    projection = {
        "_id": 0, "distance_km": 1, "classification": 1, "fuel_l": 1,
        "duration_min": 1, "start_time": 1, "driver_id": 1,
        "driver_name": 1, "vehicle_plate": 1,
    }
    trips = await db.trips.find(q, projection).limit(10000).to_list(10000)

    pro_km = sum(t["distance_km"] for t in trips if t.get("classification") == "professional")
    perso_km = sum(t["distance_km"] for t in trips if t.get("classification") == "personal")
    unclassified_km = sum(
        t["distance_km"] for t in trips
        if t.get("classification") not in ("professional", "personal")
    )
    total_km = pro_km + perso_km + unclassified_km
    pro_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "professional")
    perso_fuel = sum(t.get("fuel_l", 0) for t in trips if t.get("classification") == "personal")
    pro_time = sum(t.get("duration_min", 0) for t in trips if t.get("classification") == "professional")
    perso_time = sum(t.get("duration_min", 0) for t in trips if t.get("classification") == "personal")

    # Daily breakdown (last 30 days)
    daily = defaultdict(lambda: {"pro": 0, "perso": 0})
    for t in trips:
        try:
            d = parse_iso(t["start_time"]).date().isoformat()
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
    per_driver = defaultdict(lambda: {"pro_km": 0, "perso_km": 0, "pro_time": 0, "perso_time": 0,
                                       "pro_fuel": 0, "perso_fuel": 0, "vehicle_plate": ""})
    for t in trips:
        key = (t["driver_id"], t.get("driver_name"))
        d = per_driver[key]
        d["vehicle_plate"] = t.get("vehicle_plate")
        if t.get("classification") == "professional":
            d["pro_km"] += t["distance_km"]
            d["pro_time"] += t.get("duration_min", 0)
            d["pro_fuel"] += t.get("fuel_l", 0) or 0
        elif t.get("classification") == "personal":
            d["perso_km"] += t["distance_km"]
            d["perso_time"] += t.get("duration_min", 0)
            d["perso_fuel"] += t.get("fuel_l", 0) or 0
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
            "pro_fuel": round(v["pro_fuel"], 2),
            "perso_fuel": round(v["perso_fuel"], 2),
            "pct_pro": round(v["pro_km"] / total * 100, 1) if total else 0,
            "pct_perso": round(v["perso_km"] / total * 100, 1) if total else 0,
        })
    table.sort(key=lambda r: -r["total_km"])

    return {
        "settings_mode": settings.get("mode"),
        "kpi": {
            "pro_km": round(pro_km, 1),
            "perso_km": round(perso_km, 1),
            "unclassified_km": round(unclassified_km, 1),
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
