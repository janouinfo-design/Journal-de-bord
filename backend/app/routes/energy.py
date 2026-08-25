"""Routes Énergie — Journal = CONSOMMATEUR du module Énergie (projet séparé).

Aucun calcul métier ici : les valeurs viennent du contrat Energy → Journal v1
via app.energy_client. Donnée absente → UNAVAILABLE (jamais 0, jamais de fallback).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

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
    ids = [i for i in payload.trip_ids if i][:MAX_BATCH]
    if not ids:
        raise HTTPException(400, "trip_ids requis (1 à 100 identifiants)")
    tid = _tenant_or_400()
    db = get_db()
    q = await filter_trips_query(db, user, None, None, None, None, None)
    q["id"] = {"$in": ids}
    trips = await db.trips.find(
        q, {"_id": 0, "id": 1, "vehicle_id": 1, "start_time": 1, "end_time": 1,
            "distance_km": 1}).to_list(MAX_BATCH)
    veh_ids = list({t.get("vehicle_id") for t in trips if t.get("vehicle_id")})
    vehicles = await db.vehicles.find(
        {"id": {"$in": veh_ids}},
        {"_id": 0, "id": 1, "plate": 1, "navixy_tracker_id": 1, "vin": 1}).to_list(len(veh_ids) or 1) \
        if veh_ids else []
    vby = {v["id"]: v for v in vehicles}
    items = [{
        "trip_id": t["id"],
        "vehicle_id": t.get("vehicle_id"),
        "vehicle_plate": vby.get(t.get("vehicle_id"), {}).get("plate"),
        "navixy_tracker_id": vby.get(t.get("vehicle_id"), {}).get("navixy_tracker_id"),
        "vin": vby.get(t.get("vehicle_id"), {}).get("vin"),
        "start_time": t.get("start_time"),
        "end_time": t.get("end_time"),
        "distance_km": t.get("distance_km"),
    } for t in trips]
    resp = await energy_client.trip_energy_batch(items, tenant_id=tid)
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
    tid = get_effective_tenant_id()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1).isoformat()
    energy = await energy_client.fleet_summary(month_start, today.isoformat(), tenant_id=tid)
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


@router.get("/reconciliation/preview")
async def reconciliation_preview(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user=Depends(require_roles("admin", "manager")),
):
    """MODÈLE PRÉPARATOIRE achats vs consommation — AUCUNE alerte émise.
    Litres achetés = transactions cartes (commercial). Consommation = module
    Énergie uniquement (priorité MEASURED > ESTIMATED > REFERENCE, sinon NONE).
    Fiabilité : MEASURED→EXPLOITABLE, ESTIMATED/REFERENCE→INDICATIF, NONE→IMPOSSIBLE."""
    tid = _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    dfrom = date_from or today.replace(day=1).isoformat()
    dto = date_to or today.isoformat()
    vehicles = await db.vehicles.find(
        {}, {"_id": 0, "id": 1, "plate": 1, "navixy_tracker_id": 1, "vin": 1}).to_list(1000)
    txs = await db.fuel_transactions.find(
        {"tx_datetime": {"$gte": dfrom, "$lte": dto + "T23:59:59"}},
        {"_id": 0, "vehicle_id": 1, "quantity": 1, "unit": 1, "amount_chf": 1}).to_list(100000)
    purchased: dict = {}
    for tx in txs:
        vid = tx.get("vehicle_id")
        if not vid:
            continue
        p = purchased.setdefault(vid, {"liters": 0.0, "kwh": 0.0, "amount_chf": 0.0, "tx_count": 0})
        qty = tx.get("quantity") or 0
        if tx.get("unit") == "L":
            p["liters"] += qty
        elif tx.get("unit") == "kWh":
            p["kwh"] += qty
        p["amount_chf"] += tx.get("amount_chf") or 0
        p["tx_count"] += 1
    status = await energy_client.get_status()
    rows = []
    for v in vehicles:
        summ = await energy_client.vehicle_energy_summary(v, dfrom, dto, tenant_id=tid)
        metrics = summ.get("metrics") or {}
        consumed = energy_client.best_metric(metrics.get("fuel_liters_total"))
        buy = purchased.get(v["id"], {"liters": 0.0, "kwh": 0.0, "amount_chf": 0.0, "tx_count": 0})
        gap_l = gap_pct = None
        if consumed is not None:
            gap_l = round(buy["liters"] - consumed["value"], 2)
            if buy["liters"] > 0:
                gap_pct = round(gap_l / buy["liters"] * 100, 1)
        mt = consumed.get("measurement_type") if consumed else None
        reliability = ("EXPLOITABLE" if mt == "MEASURED"
                       else "INDICATIF" if mt in ("ESTIMATED", "REFERENCE")
                       else "IMPOSSIBLE")
        rows.append({
            "vehicle_id": v["id"],
            "plate": v.get("plate"),
            "purchased": {"liters": round(buy["liters"], 2), "kwh": round(buy["kwh"], 2),
                          "amount_chf": round(buy["amount_chf"], 2), "tx_count": buy["tx_count"]},
            "consumed_fuel": consumed,
            "consumption_measurement_type": mt or "NONE",
            "gap_l": gap_l,
            "gap_pct": gap_pct,
            "reliability": reliability,
        })
    return {"preview": True, "alerting": "disabled",
            "connected": status.get("connected", False), "mode": status.get("mode"),
            "period": {"from": dfrom, "to": dto}, "rows": rows}
