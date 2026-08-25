"""Routes Énergie — Journal = CONSOMMATEUR du module Énergie (projet séparé).

Aucun calcul métier ici : les valeurs viennent du contrat Energy → Journal v1
via app.energy_client. Donnée absente → UNAVAILABLE (jamais 0, jamais de fallback).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app import energy_client
from app.auth import require_roles
from app.db import get_db
from app.routes._helpers import filter_trips_query, get_settings_doc
from app.tenant_context import get_effective_tenant_id

router = APIRouter(prefix="/energy", tags=["energy"])

READ_ROLES = ("admin", "manager", "lecture_seule")
TRIP_ROLES = ("admin", "manager", "lecture_seule", "driver")
MAX_BATCH = 100

# Motorisation : uniquement depuis la donnée prouvée vehicles.fuel_type —
# JAMAIS déduite du nom/modèle. Non prouvée → UNKNOWN.
_POWERTRAIN_FROM_FUEL_TYPE = {
    "diesel": "ICE", "essence": "ICE", "petrol": "ICE",
    "hybrid": "HEV", "hev": "HEV", "phev": "PHEV",
    "electric": "BEV", "bev": "BEV",
}


def _powertrain(fuel_type) -> str:
    return _POWERTRAIN_FROM_FUEL_TYPE.get((fuel_type or "").lower(), "UNKNOWN")


def _reconciliation_status(mapped: bool, tx_count: int, consumed,
                           gap_l, gap_pct, threshold_pct=None, threshold_l=None):
    """Statuts métier centralisés — OK / A_CONTROLER / INDICATIF / IMPOSSIBLE.
    IMPOSSIBLE n'est JAMAIS assimilé à un écart zéro. Le seuil ne s'applique
    QUE sur MEASURED exploitable (jamais ESTIMATED/REFERENCE/NONE/non mappé)."""
    if not mapped:
        return "IMPOSSIBLE", "Véhicule sans tracker Navixy associé. Rapprochement impossible."
    if consumed is None:
        return "IMPOSSIBLE", "Consommation indisponible pour cette période. Rapprochement impossible."
    if tx_count == 0:
        return "IMPOSSIBLE", "Aucun achat de carburant sur la période. Rapprochement impossible."
    mt = consumed.get("measurement_type")
    if consumed.get("availability") == "STALE":
        return "INDICATIF", "Consommation mesurée mais périmée (STALE). Écart affiché à titre indicatif uniquement."
    if mt == "ESTIMATED":
        return "INDICATIF", "Consommation estimée. Écart affiché à titre indicatif uniquement."
    if mt == "REFERENCE":
        return "INDICATIF", "Consommation de référence. Rapprochement informatif uniquement."
    if mt == "MEASURED":
        if gap_l is None:
            return "IMPOSSIBLE", "Écart non calculable (données incompatibles). Rapprochement impossible."
        base = f"Consommation mesurée. Écart de {gap_l:+.1f} L entre achats et consommation."
        exceeded = []
        if threshold_pct is not None and gap_pct is not None and abs(gap_pct) > threshold_pct:
            exceeded.append(f"{gap_pct:+.1f} % > seuil {threshold_pct} %")
        if threshold_l is not None and abs(gap_l) > threshold_l:
            exceeded.append(f"{abs(gap_l):.1f} L > seuil {threshold_l} L")
        if exceeded:
            return "A_CONTROLER", (f"{base} Au-delà du seuil configuré ({' ; '.join(exceeded)}). "
                                   "Aucune alerte automatique émise.")
        if threshold_pct is None and threshold_l is None:
            return "OK", f"{base} Aucun seuil configuré — rapprochement en mode diagnostic."
        return "OK", f"{base} Écart dans les limites configurées."
    return "IMPOSSIBLE", "Type de mesure inconnu. Rapprochement impossible."


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
    vehicle_id: Optional[str] = None,
    user=Depends(require_roles("admin", "manager", "lecture_seule")),
):
    """Rapprochement achats vs consommation — DIAGNOSTIC/PREVIEW, AUCUNE alerte.
    Achats = transactions cartes (commercial). Consommation = module Énergie
    uniquement (priorité MEASURED > ESTIMATED > REFERENCE, sinon NONE).
    Statuts centralisés : OK / A_CONTROLER / INDICATIF / IMPOSSIBLE."""
    tid = _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    dfrom = date_from or today.replace(day=1).isoformat()
    dto = date_to or today.isoformat()
    rows, thresholds, status_svc = await _build_reconciliation(db, tid, dfrom, dto, vehicle_id)
    return {"preview": True, "alerting": "disabled",
            "connected": status_svc.get("connected", False), "mode": status_svc.get("mode"),
            "period": {"from": dfrom, "to": dto},
            "thresholds": thresholds,
            "rows": rows}


async def _build_reconciliation(db, tid: str, dfrom: str, dto: str,
                                vehicle_id: Optional[str] = None):
    """Source de vérité UNIQUE du rapprochement (écran + export Excel)."""
    vq = {"id": vehicle_id} if vehicle_id else {}
    vehicles = await db.vehicles.find(
        vq, {"_id": 0, "id": 1, "plate": 1, "model": 1,
             "navixy_tracker_id": 1, "vin": 1, "fuel_type": 1}).to_list(1000)
    txq = {"tx_datetime": {"$gte": dfrom, "$lte": dto + "T23:59:59"}}
    if vehicle_id:
        txq["vehicle_id"] = vehicle_id
    txs = await db.fuel_transactions.find(
        txq, {"_id": 0, "vehicle_id": 1, "quantity": 1, "unit": 1,
              "amount_chf": 1, "source": 1}).to_list(100000)
    purchased: dict = {}
    for tx in txs:
        vid = tx.get("vehicle_id")
        if not vid:
            continue
        p = purchased.setdefault(vid, {"liters": 0.0, "kwh": 0.0, "amount_chf": 0.0,
                                       "tx_count": 0, "sources": {}})
        qty = tx.get("quantity") or 0
        if tx.get("unit") == "L":
            p["liters"] += qty
        elif tx.get("unit") == "kWh":
            p["kwh"] += qty
        p["amount_chf"] += tx.get("amount_chf") or 0
        p["tx_count"] += 1
        src = tx.get("source") or "inconnu"
        p["sources"][src] = p["sources"].get(src, 0) + 1
    settings = await get_settings_doc(db)
    threshold_pct = settings.get("reconciliation_threshold_percent")
    threshold_l = settings.get("reconciliation_threshold_liters")
    status_svc = await energy_client.get_status()
    rows = []
    for v in vehicles:
        mapped = bool(v.get("navixy_tracker_id"))
        summ = await energy_client.vehicle_energy_summary(v, dfrom, dto, tenant_id=tid)
        metrics = summ.get("metrics") or {}
        consumed = energy_client.best_metric(metrics.get("fuel_liters_total"))
        consumed_electric = energy_client.best_metric(metrics.get("energy_kwh_total"))
        buy = purchased.get(v["id"], {"liters": 0.0, "kwh": 0.0, "amount_chf": 0.0,
                                      "tx_count": 0, "sources": {}})
        gap_l = gap_pct = None
        if consumed is not None and buy["tx_count"] > 0:
            gap_l = round(buy["liters"] - consumed["value"], 2)
            if buy["liters"] > 0:
                gap_pct = round(gap_l / buy["liters"] * 100, 1)
        mt = consumed.get("measurement_type") if consumed else None
        status, reason = _reconciliation_status(
            mapped, buy["tx_count"], consumed, gap_l, gap_pct, threshold_pct, threshold_l)
        reliability = ("EXPLOITABLE" if mt == "MEASURED"
                       else "INDICATIF" if mt in ("ESTIMATED", "REFERENCE")
                       else "IMPOSSIBLE")
        rows.append({
            "vehicle_id": v["id"],
            "plate": v.get("plate"),
            "model": v.get("model"),
            "navixy_tracker_id": v.get("navixy_tracker_id"),
            "mapped": mapped,
            "powertrain": _powertrain(v.get("fuel_type")),
            "purchased": {"liters": round(buy["liters"], 2), "kwh": round(buy["kwh"], 2),
                          "amount_chf": round(buy["amount_chf"], 2),
                          "tx_count": buy["tx_count"], "sources": buy["sources"]},
            "consumed_fuel": consumed,
            "consumed_electric": consumed_electric,
            "consumption_measurement_type": mt or "NONE",
            "gap_l": gap_l,
            "gap_pct": gap_pct,
            "reliability": reliability,
            "status": status,
            "status_reason": reason,
        })
    thresholds = {"percent": threshold_pct, "liters": threshold_l,
                  "configured": threshold_pct is not None or threshold_l is not None,
                  "note": "Écran diagnostic/preview — alertes automatiques désactivées"}
    return rows, thresholds, status_svc


# ---------------------------------------------------------------------------
# Paramètres du rapprochement — stockés dans le doc settings (isolé par tenant
# via le proxy Mongo). Aucune valeur par défaut métier : null = aucun seuil.
# ---------------------------------------------------------------------------
class ReconciliationSettingsIn(BaseModel):
    threshold_percent: Optional[float] = None
    threshold_liters: Optional[float] = None


@router.get("/reconciliation/settings")
async def get_reconciliation_settings(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    settings = await get_settings_doc(get_db())
    return {"threshold_percent": settings.get("reconciliation_threshold_percent"),
            "threshold_liters": settings.get("reconciliation_threshold_liters"),
            "alerting": "disabled"}


@router.put("/reconciliation/settings")
async def put_reconciliation_settings(payload: ReconciliationSettingsIn,
                                      user=Depends(require_roles("admin", "manager"))):
    """RBAC aligné sur PUT /livre/settings existant (admin + manager).
    Le seuil sert uniquement au calcul du statut — AUCUNE alerte émise."""
    tid = _tenant_or_400()
    p, l = payload.threshold_percent, payload.threshold_liters
    if p is not None and not (0 < p <= 100):
        raise HTTPException(400, "Seuil % invalide — attendu strictement entre 0 et 100")
    if l is not None and not (0 < l <= 100000):
        raise HTTPException(400, "Seuil litres invalide — attendu strictement positif")
    db = get_db()
    old = await get_settings_doc(db)
    await db.settings.update_one(
        {"id": "default"},
        {"$set": {"reconciliation_threshold_percent": p,
                  "reconciliation_threshold_liters": l}},
        upsert=True)
    from app.audit import log_audit
    await log_audit("energy.reconciliation_settings.update", user, {
        "tenant_id": tid,
        "old": {"threshold_percent": old.get("reconciliation_threshold_percent"),
                "threshold_liters": old.get("reconciliation_threshold_liters")},
        "new": {"threshold_percent": p, "threshold_liters": l}})
    return {"threshold_percent": p, "threshold_liters": l, "alerting": "disabled"}


# ---------------------------------------------------------------------------
# Export Excel — mêmes règles et même calcul que l'écran (source unique)
# ---------------------------------------------------------------------------
def _apply_recon_filters(rows, group, powertrain, measurement, reliability, status):
    out = rows
    if group:
        out = [r for r in out if (r.get("plate") or "").split(" ")[0] == group]
    if powertrain:
        out = [r for r in out if r["powertrain"] == powertrain]
    if measurement:
        out = [r for r in out if r["consumption_measurement_type"] == measurement]
    if reliability:
        out = [r for r in out if r["reliability"] == reliability]
    if status:
        out = [r for r in out if r["status"] == status]
    return out


@router.get("/reconciliation/export.xlsx")
async def export_reconciliation(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    group: Optional[str] = None,
    powertrain: Optional[str] = None,
    measurement: Optional[str] = None,
    reliability: Optional[str] = None,
    status: Optional[str] = None,
    user=Depends(require_roles("admin", "manager", "lecture_seule")),
):
    tid = _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    dfrom = date_from or today.replace(day=1).isoformat()
    dto = date_to or today.isoformat()
    rows, thresholds, status_svc = await _build_reconciliation(db, tid, dfrom, dto, vehicle_id)
    rows = _apply_recon_filters(rows, group, powertrain, measurement, reliability, status)
    from app.db import get_raw_db
    t = await get_raw_db().tenants.find_one({"id": tid}, {"_id": 0, "name": 1})
    filters_applied = {k: v for k, v in {
        "véhicule": vehicle_id, "groupe": group, "motorisation": powertrain,
        "type de mesure": measurement, "fiabilité": reliability, "statut": status,
    }.items() if v}
    meta = {
        "tenant": (t or {}).get("name") or tid,
        "period_from": dfrom, "period_to": dto,
        "generated_at": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        "filters": [f"{k} = {v}" for k, v in filters_applied.items()],
        "mode": status_svc.get("mode"),
        "connected": status_svc.get("connected", False),
        "thresholds": thresholds,
    }
    from app.reports import reconciliation_to_xlsx
    data = reconciliation_to_xlsx(rows, meta)
    from app.audit import log_audit
    await log_audit("energy.reconciliation.export", user, {
        "period": {"from": dfrom, "to": dto}, "rows": len(rows),
        "filters": filters_applied})
    fname = f"rapprochement_carburant_{dfrom}_{dto}.xlsx"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
