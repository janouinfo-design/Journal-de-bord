"""Adaptateur du module Énergie (projet Emergent séparé) — contrat Energy → Journal v1.

Journal de bord NE CALCULE AUCUNE valeur énergie (pas de L/100 km, kWh/100 km,
SoC, fuel_used, energy_used, capabilities). Ce client consomme le contrat et
retransmet les réponses telles quelles. Donnée absente → UNAVAILABLE, jamais 0.

Modes :
- ENERGY_API_BASE_URL absente           → service NON CONNECTÉ (tout UNAVAILABLE,
  reason=energy_not_connected). Journal fonctionne normalement sans Energy.
- ENERGY_API_BASE_URL configurée        → appels HTTP réels au contrat v1.
- ENERGY_API_MODE=fixture (tests seuls) → fixtures contractuelles déterministes,
  marquées mode='fixture' — JAMAIS présentées comme des données réelles.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

import httpx

CONTRACT_VERSION = "1.0"
AVAILABILITY = ("AVAILABLE", "STALE", "UNAVAILABLE")
MEASUREMENT_TYPES = ("MEASURED", "ESTIMATED", "REFERENCE")
METRIC_KEYS = ("value", "unit", "availability", "measurement_type", "source", "timestamp")
HTTP_TIMEOUT = 10.0


def _base_url() -> str:
    return (os.environ.get("ENERGY_API_BASE_URL") or "").rstrip("/")


def _token() -> str:
    return os.environ.get("ENERGY_API_TOKEN") or ""


def is_fixture_mode() -> bool:
    return (os.environ.get("ENERGY_API_MODE") or "").lower() == "fixture"


def is_configured() -> bool:
    return bool(_base_url())


def mode() -> str:
    if is_fixture_mode():
        return "fixture"
    return "real" if is_configured() else "not_connected"


def metric(value, unit, availability, measurement_type=None, source=None, timestamp=None) -> dict:
    return {"value": value, "unit": unit, "availability": availability,
            "measurement_type": measurement_type, "source": source, "timestamp": timestamp}


def unavailable_metric(unit) -> dict:
    return metric(None, unit, "UNAVAILABLE")


def _unavailable_trip(trip_id: str, reason: str) -> dict:
    return {"trip_id": trip_id, "availability": "UNAVAILABLE", "reason": reason,
            "powertrain": None, "electric": None, "fuel": None,
            "contract_version": CONTRACT_VERSION}


# ---------------------------------------------------------------------------
# Fixtures contractuelles (tests d'affichage uniquement — jamais du réel)
# ---------------------------------------------------------------------------
def fixture_scenario_index(trip_id: str) -> int:
    return int(hashlib.sha256((trip_id or "").encode()).hexdigest(), 16) % 8


def _fixture_trip(item: dict) -> dict:
    trip_id = item.get("trip_id") or ""
    dist = float(item.get("distance_km") or 55.7)
    now = datetime.now(timezone.utc).isoformat()
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    idx = fixture_scenario_index(trip_id)
    base = {"trip_id": trip_id, "availability": "AVAILABLE", "reason": None,
            "contract_version": CONTRACT_VERSION}

    if idx == 0:  # Thermique MESURÉ (OBD)
        return {**base, "powertrain": "ICE", "electric": None, "fuel": {
            "fuel_liters": metric(round(dist * 0.071, 1), "L", "AVAILABLE", "MEASURED", "OBD", now),
            "consumption_l_100km": metric(7.1, "L/100km", "AVAILABLE", "MEASURED", "OBD", now)}}
    if idx == 1:  # Thermique ESTIMÉ (modèle Energy)
        return {**base, "powertrain": "ICE", "electric": None, "fuel": {
            "fuel_liters": metric(round(dist * 0.082, 1), "L", "AVAILABLE", "ESTIMATED", "ENERGY_MODEL", now),
            "consumption_l_100km": metric(8.2, "L/100km", "AVAILABLE", "ESTIMATED", "ENERGY_MODEL", now)}}
    if idx == 2:  # BEV MESURÉ (SoC CAN + OBD)
        return {**base, "powertrain": "BEV", "fuel": None, "electric": {
            "soc_start_pct": metric(82, "%", "AVAILABLE", "MEASURED", "CAN", now),
            "soc_end_pct": metric(64, "%", "AVAILABLE", "MEASURED", "CAN", now),
            "energy_kwh": metric(round(dist * 0.176, 1), "kWh", "AVAILABLE", "MEASURED", "OBD", now),
            "consumption_kwh_100km": metric(17.6, "kWh/100km", "AVAILABLE", "MEASURED", "OBD", now)}}
    if idx == 3:  # BEV sans OBD — référence + estimation (jamais présenté comme mesuré)
        return {**base, "powertrain": "BEV", "fuel": None, "electric": {
            "soc_start_pct": unavailable_metric("%"),
            "soc_end_pct": unavailable_metric("%"),
            "energy_kwh": metric(round(dist * 0.178, 1), "kWh", "AVAILABLE", "ESTIMATED", "ENERGY_MODEL", now),
            "consumption_kwh_100km": metric(17.8, "kWh/100km", "AVAILABLE", "REFERENCE", "VEHICLE_SPEC", now)}}
    if idx == 4:  # PHEV partiel — électrique mesuré, carburant indisponible (séparés)
        return {**base, "powertrain": "PHEV", "electric": {
            "soc_start_pct": metric(74, "%", "AVAILABLE", "MEASURED", "CAN", now),
            "soc_end_pct": metric(41, "%", "AVAILABLE", "MEASURED", "CAN", now),
            "energy_kwh": metric(round(dist * 0.09, 1), "kWh", "AVAILABLE", "MEASURED", "OBD", now),
            "consumption_kwh_100km": metric(9.0, "kWh/100km", "AVAILABLE", "MEASURED", "OBD", now)},
            "fuel": {"fuel_liters": unavailable_metric("L"),
                     "consumption_l_100km": unavailable_metric("L/100km")}}
    if idx == 5:  # BEV STALE — données périmées
        return {**base, "availability": "STALE", "powertrain": "BEV", "fuel": None, "electric": {
            "soc_start_pct": metric(91, "%", "STALE", "MEASURED", "CAN", stale_ts),
            "soc_end_pct": metric(78, "%", "STALE", "MEASURED", "CAN", stale_ts),
            "energy_kwh": metric(round(dist * 0.17, 1), "kWh", "STALE", "MEASURED", "OBD", stale_ts),
            "consumption_kwh_100km": metric(17.0, "kWh/100km", "STALE", "MEASURED", "OBD", stale_ts)}}
    if idx == 6:  # Aucune donnée
        return _unavailable_trip(trip_id, "no_data")
    # idx == 7 — valeur null explicite (inconnu ≠ 0)
    return {**base, "powertrain": "ICE", "electric": None, "fuel": {
        "fuel_liters": metric(None, "L", "UNAVAILABLE"),
        "consumption_l_100km": metric(None, "L/100km", "UNAVAILABLE")}}


def _fixture_fleet_summary() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {"availability": "AVAILABLE", "mode": "fixture", "contract_version": CONTRACT_VERSION,
            "metrics": {
                "thermal_consumption_l_100km": metric(8.4, "L/100km", "AVAILABLE", "MEASURED", "OBD", now),
                "electric_consumption_kwh_100km": metric(17.9, "kWh/100km", "AVAILABLE", "MEASURED", "OBD", now),
                "fuel_liters_total": metric(412.6, "L", "AVAILABLE", "MEASURED", "OBD", now),
                "electric_kwh_total": metric(188.4, "kWh", "AVAILABLE", "MEASURED", "OBD", now),
                "obd_coverage_pct": metric(62.0, "%", "AVAILABLE", "ESTIMATED", "ENERGY_MODEL", now),
                "vehicles_with_data": metric(11, "véhicules", "AVAILABLE", "ESTIMATED", "ENERGY_MODEL", now),
            }}


# ---------------------------------------------------------------------------
# API publique du client
# ---------------------------------------------------------------------------
async def get_status() -> dict:
    m = mode()
    if m == "fixture":
        return {"connected": True, "mode": "fixture", "contract_version": CONTRACT_VERSION,
                "warning": "Fixtures contractuelles — données de démonstration, PAS le module Énergie réel"}
    if m == "not_connected":
        return {"connected": False, "mode": "not_connected",
                "reason": "ENERGY_API_BASE_URL non configurée — module Énergie non connecté",
                "contract_version": CONTRACT_VERSION}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(f"{_base_url()}/api/energy/v1/health", headers=_headers())
            r.raise_for_status()
            body = r.json() if r.content else {}
            return {"connected": True, "mode": "real",
                    "contract_version": body.get("contract_version") or CONTRACT_VERSION}
    except Exception as ex:  # noqa: BLE001
        return {"connected": False, "mode": "real", "reason": f"Module Énergie injoignable : {ex}",
                "contract_version": CONTRACT_VERSION}


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if _token():
        h["Authorization"] = f"Bearer {_token()}"
    return h


async def trip_energy_batch(items: list[dict]) -> dict:
    """items: [{trip_id, vehicle_id, vehicle_plate, navixy_tracker_id,
    start_time, end_time, distance_km}] → réponses contractuelles par trajet."""
    m = mode()
    if m == "fixture":
        results = [{**_fixture_trip(it), "mode": "fixture"} for it in items]
        return {"connected": True, "mode": "fixture",
                "contract_version": CONTRACT_VERSION, "results": results}
    if m == "not_connected":
        results = [{**_unavailable_trip(it.get("trip_id"), "energy_not_connected"), "mode": "not_connected"}
                   for it in items]
        return {"connected": False, "mode": "not_connected",
                "contract_version": CONTRACT_VERSION, "results": results}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(f"{_base_url()}/api/energy/v1/trips/energy:batch",
                                  json={"contract_version": CONTRACT_VERSION, "trips": items},
                                  headers=_headers())
            r.raise_for_status()
            body = r.json()
            results = [{**env, "mode": "real"} for env in (body.get("results") or [])]
            return {"connected": True, "mode": "real",
                    "contract_version": body.get("contract_version") or CONTRACT_VERSION,
                    "results": results}
    except Exception:  # noqa: BLE001 — Energy injoignable ≠ erreur Journal
        results = [{**_unavailable_trip(it.get("trip_id"), "energy_unreachable"), "mode": "real"}
                   for it in items]
        return {"connected": False, "mode": "real",
                "contract_version": CONTRACT_VERSION, "results": results}


async def fleet_summary(date_from: str, date_to: str) -> dict:
    m = mode()
    if m == "fixture":
        return _fixture_fleet_summary()
    if m == "not_connected":
        return {"availability": "UNAVAILABLE", "reason": "energy_not_connected",
                "mode": "not_connected", "contract_version": CONTRACT_VERSION, "metrics": None}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(f"{_base_url()}/api/energy/v1/fleet/summary",
                                 params={"from": date_from, "to": date_to}, headers=_headers())
            r.raise_for_status()
            return {**r.json(), "mode": "real"}
    except Exception:  # noqa: BLE001
        return {"availability": "UNAVAILABLE", "reason": "energy_unreachable",
                "mode": "real", "contract_version": CONTRACT_VERSION, "metrics": None}
