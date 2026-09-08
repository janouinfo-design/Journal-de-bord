"""Routes Énergie — Journal = CONSOMMATEUR du module Énergie (projet séparé).

Aucun calcul métier ici : les valeurs viennent du contrat Energy → Journal v1
via app.energy_client. Donnée absente → UNAVAILABLE (jamais 0, jamais de fallback).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app import energy_cache, energy_client
from app.auth import require_roles
from app.db import get_db
from app.navixy_sync import powertrain_from_fuel_type
from app.routes._helpers import filter_trips_query, get_settings_doc
from app.tenant_context import get_effective_tenant_id

router = APIRouter(prefix="/energy", tags=["energy"])

READ_ROLES = ("admin", "manager", "lecture_seule")
TRIP_ROLES = ("admin", "manager", "lecture_seule", "driver")
MAX_BATCH = 100

# Motorisation : mapping canonique unique du projet (app.navixy_sync) —
# uniquement depuis la donnée prouvée vehicles.fuel_type, JAMAIS déduite
# du nom/modèle. Non prouvée → UNKNOWN.
def _powertrain(fuel_type) -> str:
    return powertrain_from_fuel_type(fuel_type)


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


async def _resolve_energy_tenant(db) -> Optional[str]:
    """Correspondance tenant Journal → tenant Energy (settings, FAIL-CLOSED).
    Aucune valeur configurée → AUCUN appel Energy. Jamais de fallback global,
    jamais le tenant par défaut d'Energy, jamais hérité d'un autre tenant."""
    settings = await get_settings_doc(db)
    et = settings.get("energy_tenant_id")
    return et.strip() if isinstance(et, str) and et.strip() else None


@router.get("/status")
async def energy_status(user=Depends(require_roles(*TRIP_ROLES))):
    _tenant_or_400()
    status = await energy_client.get_status()
    et = await _resolve_energy_tenant(get_db())
    return {**status, "base_url_configured": energy_client.is_configured(),
            "energy_tenant_configured": et is not None}


class EnergyTenantMappingIn(BaseModel):
    energy_tenant_id: Optional[str] = None


@router.get("/tenant-mapping")
async def get_energy_tenant_mapping(user=Depends(require_roles("admin", "manager"))):
    _tenant_or_400()
    et = await _resolve_energy_tenant(get_db())
    return {"energy_tenant_id": et, "configured": et is not None, "fail_closed": True}


@router.put("/tenant-mapping")
async def put_energy_tenant_mapping(payload: EnergyTenantMappingIn,
                                    user=Depends(require_roles("admin"))):
    """Correspondance tenant Journal → tenant Energy. Admin uniquement, audité.
    null/vide = mapping supprimé → fail-closed (aucun appel Energy)."""
    tid = _tenant_or_400()
    db = get_db()
    old = await _resolve_energy_tenant(db)
    new = payload.energy_tenant_id
    if new is not None:
        new = new.strip() or None
    if new is not None and (len(new) > 100 or not re.match(r"^[A-Za-z0-9_.:-]+$", new)):
        raise HTTPException(400, "Identifiant tenant Energy invalide")
    await db.settings.update_one({"id": "default"},
                                 {"$set": {"energy_tenant_id": new}}, upsert=True)
    from app.audit import log_audit
    await log_audit("energy.tenant_mapping_updated", user, {
        "journal_tenant_id": tid, "before": old, "after": new, "result": "ok"})
    return {"energy_tenant_id": new, "configured": new is not None, "fail_closed": True}


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
    et = await _resolve_energy_tenant(db)
    if et is None:
        mode = "real" if energy_client.is_configured() else "not_connected"
        return {"connected": False, "mode": mode,
                "tenant_mapping": "NOT_CONFIGURED",
                "reason": "energy_tenant_not_configured",
                "contract_version": energy_client.CONTRACT_VERSION,
                "results": [energy_client._unavailable_trip(i, "energy_tenant_not_configured")
                            for i in ids]}
    resp = await energy_client.trip_energy_batch(items, tenant_id=et)
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
    et = await _resolve_energy_tenant(db)
    if et is None:
        energy = {"availability": "UNAVAILABLE", "reason": "energy_tenant_not_configured",
                  "contract_version": energy_client.CONTRACT_VERSION, "metrics": None}
    else:
        energy = await energy_client.fleet_summary(month_start, today.isoformat(), tenant_id=et)
    vehicles_total = await db.vehicles.count_documents({})
    powertrain_set = await db.vehicles.count_documents(
        {"fuel_type": {"$exists": True, "$nin": [None, ""]}})
    tank_set = await db.vehicles.count_documents(
        {"tank_capacity_l": {"$exists": True, "$ne": None}})
    battery_set = await db.vehicles.count_documents(
        {"battery_capacity_kwh": {"$exists": True, "$ne": None}})
    status = await energy_client.get_status()
    return {
        "connected": status.get("connected", False) and et is not None,
        "mode": status.get("mode"),
        "tenant_mapping": "CONFIGURED" if et else "NOT_CONFIGURED",
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
    refresh: bool = False,
    user=Depends(require_roles("admin", "manager", "lecture_seule")),
):
    """Rapprochement achats vs consommation — DIAGNOSTIC/PREVIEW, AUCUNE alerte.
    Achats = transactions cartes (commercial). Consommation = module Énergie
    uniquement (priorité MEASURED > ESTIMATED > REFERENCE, sinon NONE).
    Statuts centralisés : OK / A_CONTROLER / INDICATIF / IMPOSSIBLE.
    Réponses Energy cachées 60 s (mémoire, par tenant) ; refresh=true = bypass
    réel (appels Energy refaits puis cache mis à jour)."""
    tid = _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    dfrom = date_from or today.replace(day=1).isoformat()
    dto = date_to or today.isoformat()
    rows, thresholds, status_svc, cache_info = await _build_reconciliation(
        db, tid, dfrom, dto, vehicle_id, bypass_cache=refresh)
    return {"preview": True, "alerting": "disabled",
            "connected": status_svc.get("connected", False), "mode": status_svc.get("mode"),
            "period": {"from": dfrom, "to": dto},
            "thresholds": thresholds,
            "cache": {"ttl_seconds": energy_cache.TTL_SECONDS, "persistent": False,
                      **cache_info},
            "rows": rows}


async def _build_reconciliation(db, tid: str, dfrom: str, dto: str,
                                vehicle_id: Optional[str] = None,
                                bypass_cache: bool = False):
    """Source de vérité UNIQUE du rapprochement (écran + exports Excel/PDF).
    Les réponses Energy brutes sont cachées 60 s (clé tenant Journal + tenant
    Energy + véhicule/ref + période) ; le rapprochement est TOUJOURS recalculé
    localement avec les achats/seuils actuels. Aucune valeur cachée modifiée."""
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
    energy_tenant = await _resolve_energy_tenant(db)
    cache_info = {"hit": 0, "miss": 0, "expired": 0, "bypass": 0}

    async def _cached(key, fetch, cacheable=None):
        """Réponse Energy brute via cache éphémère — valeur JAMAIS modifiée."""
        if bypass_cache:
            energy_cache.mark_bypass(key)
            cache_info["bypass"] += 1
        else:
            state, cached = energy_cache.lookup(key)
            cache_info[state.lower()] += 1
            if state == "HIT":
                return cached
        fresh = await fetch()
        if cacheable is None or cacheable(fresh):
            energy_cache.store(key, fresh)
        return fresh

    # Health non tenant-specific (comportement livré inchangé) — clé isolée par tenant.
    status_svc = await _cached(
        energy_cache.make_key(tid, energy_tenant or "", "-", "-", "-", "status"),
        energy_client.get_status,
        cacheable=lambda s: bool(s.get("connected")))
    if energy_tenant is None:
        status_svc = {**status_svc, "connected": False,
                      "tenant_mapping": "NOT_CONFIGURED",
                      "reason": "energy_tenant_not_configured"}
    else:
        status_svc = {**status_svc, "tenant_mapping": "CONFIGURED"}
    rows = []
    for v in vehicles:
        mapped = bool(v.get("navixy_tracker_id"))
        if energy_tenant is None:
            summ = {"availability": "UNAVAILABLE",
                    "reason": "energy_tenant_not_configured", "metrics": None}
        else:
            ref = v.get("navixy_tracker_id") or v["id"]
            summ = await _cached(
                energy_cache.make_key(tid, energy_tenant, f"{v['id']}|{ref}",
                                      dfrom, dto, "vehicle_summary"),
                lambda v=v: energy_client.vehicle_energy_summary(
                    v, dfrom, dto, tenant_id=energy_tenant))
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
    return rows, thresholds, status_svc, cache_info


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
# Préparation des alertes « À contrôler » — AUCUN ENVOI (e-mail / SMS / push).
# Verrou par tenant : real_energy_validated=false → activation refusée (409).
# AUCUN endpoint ne permet de passer real_energy_validated à true : seule une
# campagne REAL ENERGY réellement validée (phase future) pourra le faire.
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALERTS_LOCK_REASON = ("Activation refusée : la campagne REAL ENERGY n'a pas été validée "
                      "pour ce client. Les alertes restent désactivées.")
ALERTS_PREVIEW_NOTE = "APERÇU — AUCUN MESSAGE ENVOYÉ"


class ReconciliationAlertsIn(BaseModel):
    enabled: Optional[bool] = None
    recipients: Optional[list[str]] = None


def _alerts_config_payload(settings: dict) -> dict:
    validated = settings.get("real_energy_validated") is True
    return {
        "enabled": settings.get("reconciliation_alerts_enabled") is True,
        "real_energy_validated": validated,
        "recipients": settings.get("reconciliation_alert_recipients") or [],
        "dispatch": "disabled",
        "can_enable": validated,
        "lock_reason": None if validated else ALERTS_LOCK_REASON,
        "preview_note": ALERTS_PREVIEW_NOTE,
    }


@router.get("/reconciliation/alerts/config")
async def get_reconciliation_alerts_config(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    return _alerts_config_payload(await get_settings_doc(get_db()))


@router.put("/reconciliation/alerts/config")
async def put_reconciliation_alerts_config(payload: ReconciliationAlertsIn,
                                           user=Depends(require_roles("admin", "manager"))):
    """real_energy_validated n'est JAMAIS accepté en écriture ici (ni ailleurs).
    enabled=true → 409 tant que la campagne REAL ENERGY n'est pas validée."""
    tid = _tenant_or_400()
    db = get_db()
    old = await get_settings_doc(db)
    validated = old.get("real_energy_validated") is True
    if payload.enabled is True and not validated:
        raise HTTPException(409, ALERTS_LOCK_REASON)
    updates: dict = {}
    if payload.enabled is not None:
        updates["reconciliation_alerts_enabled"] = bool(payload.enabled) and validated
    if payload.recipients is not None:
        if len(payload.recipients) > 20:
            raise HTTPException(400, "Maximum 20 destinataires")
        clean: list[str] = []
        for r in payload.recipients:
            e = (r or "").strip().lower()
            if not _EMAIL_RE.match(e):
                raise HTTPException(400, f"Adresse e-mail invalide : {r}")
            if e not in clean:
                clean.append(e)
        updates["reconciliation_alert_recipients"] = clean
    if updates:
        await db.settings.update_one({"id": "default"}, {"$set": updates}, upsert=True)
        from app.audit import log_audit
        await log_audit("energy.reconciliation_alerts.config_update", user, {
            "tenant_id": tid,
            "old": {"enabled": old.get("reconciliation_alerts_enabled") is True,
                    "recipients": old.get("reconciliation_alert_recipients") or []},
            "new": updates,
            "dispatch": "disabled"})
    return _alerts_config_payload(await get_settings_doc(db))


def _alert_candidates(rows, dfrom: str, dto: str) -> list[dict]:
    """Candidats d'alerte — uniquement les écarts MEASURED exploitables au statut
    A_CONTROLER. ESTIMATED / REFERENCE / STALE / NONE / non mappé : JAMAIS candidats.
    Anti-doublonnage : dedup_key = véhicule + période."""
    out = []
    for r in rows:
        if r.get("status") != "A_CONTROLER":
            continue
        if r.get("consumption_measurement_type") != "MEASURED":
            continue
        if not r.get("mapped"):
            continue
        out.append({
            "dedup_key": f"recon-alert:{r['vehicle_id']}:{dfrom}:{dto}",
            "vehicle_id": r["vehicle_id"],
            "plate": r.get("plate"),
            "model": r.get("model"),
            "period_from": dfrom,
            "period_to": dto,
            "gap_l": r.get("gap_l"),
            "gap_pct": r.get("gap_pct"),
            "measurement_type": "MEASURED",
            "status_reason": r.get("status_reason"),
        })
    return out


@router.post("/reconciliation/alerts/candidates/generate")
async def generate_alert_candidates(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    user=Depends(require_roles("admin", "manager")),
):
    """Génère les candidats d'alerte en base (dédupliqués véhicule+période).
    PRÉPARATION uniquement : rien n'est transmis à notifications_service/SMTP."""
    tid = _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    dfrom = date_from or today.replace(day=1).isoformat()
    dto = date_to or today.isoformat()
    rows, _, status_svc, _ = await _build_reconciliation(db, tid, dfrom, dto, vehicle_id)
    cands = _alert_candidates(rows, dfrom, dto)
    created = duplicates = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for c in cands:
        try:
            await db.reconciliation_alert_candidates.insert_one({
                **c, "id": str(uuid.uuid4()), "created_at": now_iso,
                "mode": status_svc.get("mode"),
                "dispatched": False, "dispatch": "disabled", "preview_only": True})
            created += 1
        except DuplicateKeyError:
            duplicates += 1
    from app.audit import log_audit
    await log_audit("energy.reconciliation_alerts.candidates_generate", user, {
        "period": {"from": dfrom, "to": dto}, "candidates": len(cands),
        "created": created, "duplicates": duplicates, "dispatch": "disabled"})
    return {"preview": True, "dispatch": "disabled", "note": ALERTS_PREVIEW_NOTE,
            "mode": status_svc.get("mode"),
            "period": {"from": dfrom, "to": dto},
            "candidates": len(cands), "created": created, "duplicates": duplicates}


@router.get("/reconciliation/alerts/candidates")
async def list_alert_candidates(user=Depends(require_roles(*READ_ROLES))):
    _tenant_or_400()
    db = get_db()
    items = await db.reconciliation_alert_candidates.find(
        {}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {"preview": True, "dispatch": "disabled", "note": ALERTS_PREVIEW_NOTE,
            "total": len(items), "items": items}


# ---------------------------------------------------------------------------
# Exports Excel + PDF — mêmes règles et même calcul que l'écran (source unique)
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
    rows, meta, filters_applied = await _export_dataset(
        db, tid, dfrom, dto, vehicle_id, group, powertrain, measurement, reliability, status)
    from app.reports import reconciliation_to_xlsx
    data = reconciliation_to_xlsx(rows, meta)
    from app.audit import log_audit
    await log_audit("energy.reconciliation.export", user, {
        "format": "xlsx", "period": {"from": dfrom, "to": dto}, "rows": len(rows),
        "filters": filters_applied})
    fname = f"rapprochement_carburant_{dfrom}_{dto}.xlsx"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


async def _export_dataset(db, tid, dfrom, dto, vehicle_id, group, powertrain,
                          measurement, reliability, status):
    """Jeu de données commun Excel/PDF — source unique _build_reconciliation
    (réutilise le même cache Energy que le preview)."""
    rows, thresholds, status_svc, _ = await _build_reconciliation(db, tid, dfrom, dto, vehicle_id)
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
    return rows, meta, filters_applied


@router.get("/reconciliation/export.pdf")
async def export_reconciliation_pdf(
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
    """Export PDF — EXACTEMENT la même source et les mêmes 7 filtres que l'écran
    et l'Excel. null → « — » (jamais 0), L et kWh séparés, paginé, audité."""
    tid = _tenant_or_400()
    db = get_db()
    today = datetime.now(timezone.utc).date()
    dfrom = date_from or today.replace(day=1).isoformat()
    dto = date_to or today.isoformat()
    rows, meta, filters_applied = await _export_dataset(
        db, tid, dfrom, dto, vehicle_id, group, powertrain, measurement, reliability, status)
    from app.reports import reconciliation_to_pdf
    data = reconciliation_to_pdf(rows, meta)
    from app.audit import log_audit
    await log_audit("energy.reconciliation.export", user, {
        "format": "pdf", "period": {"from": dfrom, "to": dto}, "rows": len(rows),
        "filters": filters_applied})
    fname = f"rapprochement_carburant_{dfrom}_{dto}.pdf"
    return Response(
        data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
