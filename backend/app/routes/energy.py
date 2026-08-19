"""Routes Énergie — Journal = CONSOMMATEUR du module Énergie (projet séparé).

Aucun calcul métier ici : les valeurs viennent du contrat Energy → Journal v1
via app.energy_client. Donnée absente → UNAVAILABLE (jamais 0, jamais de fallback).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import energy_client
from app.auth import require_roles
from app.db import get_db
from app.routes._helpers import filter_trips_query
from app.tenant_context import get_effective_tenant_id

router = APIRouter(prefix="/energy", tags=["energy"])

READ_ROLES = ("admin", "manager", "lecture_seule")
TRIP_ROLES = ("admin", "manager", "lecture_seule", "driver")
MAX_BATCH = 100


def _tenant_or_400() -> str:
    tid = get_effective_tenant_id()
    if not tid:
        raise HTTPException(400, "Sélectionnez d'abord un client (en-tête X-Tenant-Id)")
    return tid


@router.get("/status")
async def energy_status(user=Depends(require_roles(*TRIP_ROLES))):
    _tenant_or_400()
    status = await energy_client.get_status()
    return {**status, "base_url_configured": energy_client.is_configured()}


class TripEnergyIn(BaseModel):
    trip_ids: list[str]


@router.post("/trips")
async def trips_energy(payload: TripEnergyIn, user=Depends(require_roles(*TRIP_ROLES))):
    """Journal transmet vehicle_id + start_time + end_time au module Énergie
    et affiche sa réponse. RBAC : chauffeur = uniquement ses propres trajets."""
    _tenant_or_400()
    ids = [i for i in payload.trip_ids if i][:MAX_BATCH]
    if not ids:
        raise HTTPException(400, "trip_ids requis (1 à 100 identifiants)")
    db = get_db()
    q = await filter_trips_query(db, user, None, None, None, None, None)
    q["id"] = {"$in": ids}
    trips = await db.trips.find(
        q, {"_id": 0, "id": 1, "vehicle_id": 1, "start_time": 1, "end_time": 1,
            "distance_km": 1}).to_list(MAX_BATCH)
    veh_ids = list({t.get("vehicle_id") for t in trips if t.get("vehicle_id")})
    vehicles = await db.vehicles.find(
        {"id": {"$in": veh_ids}},
        {"_id": 0, "id": 1, "plate": 1, "navixy_tracker_id": 1}).to_list(len(veh_ids) or 1) \
        if veh_ids else []
    vby = {v["id"]: v for v in vehicles}
    items = [{
        "trip_id": t["id"],
        "vehicle_id": t.get("vehicle_id"),
        "vehicle_plate": vby.get(t.get("vehicle_id"), {}).get("plate"),
        "navixy_tracker_id": vby.get(t.get("vehicle_id"), {}).get("navixy_tracker_id"),
        "start_time": t.get("start_time"),
        "end_time": t.get("end_time"),
        "distance_km": t.get("distance_km"),
    } for t in trips]
    resp = await energy_client.trip_energy_batch(items)
    found = {r.get("trip_id") for r in resp["results"]}
    for tid in ids:
        if tid not in found:
            resp["results"].append({
                "trip_id": tid, "availability": "UNAVAILABLE", "reason": "trip_not_found",
                "powertrain": None, "electric": None, "fuel": None,
                "contract_version": energy_client.CONTRACT_VERSION, "mode": resp["mode"]})
    order = {tid: i for i, tid in enumerate(ids)}
    resp["results"].sort(key=lambda r: order.get(r.get("trip_id"), 999))
    return resp


@router.get("/overview")
async def energy_overview(user=Depends(require_roles(*READ_ROLES))):
    """Vue d'ensemble énergie : consommations = module Énergie (ou UNAVAILABLE),
    flotte = comptages honnêtes Journal. Les approvisionnements (achats) restent
    servis par /livre/fuel/widget — concept distinct de la consommation réelle."""
    _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1).isoformat()
    energy = await energy_client.fleet_summary(month_start, today.isoformat())
    vehicles_total = await db.vehicles.count_documents({})
    powertrain_set = await db.vehicles.count_documents(
        {"fuel_type": {"$exists": True, "$nin": [None, ""]}})
    tank_set = await db.vehicles.count_documents(
        {"tank_capacity_l": {"$exists": True, "$ne": None}})
    battery_set = await db.vehicles.count_documents(
        {"battery_capacity_kwh": {"$exists": True, "$ne": None}})
    status = await energy_client.get_status()
    return {
        "connected": status.get("connected", False),
        "mode": status.get("mode"),
        "period": {"from": month_start, "to": today.isoformat()},
        "energy": energy,
        "fleet": {"vehicles_total": vehicles_total,
                  "powertrain_set": powertrain_set,
                  "tank_capacity_set": tank_set,
                  "battery_capacity_set": battery_set},
    }
