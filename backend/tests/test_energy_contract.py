"""TESTS CONTRACTUELS Energy → Journal v1 — MOCK/FIXTURE UNIQUEMENT.

Ces tests valident la capacité du Journal à CONSOMMER et AFFICHER le contrat
Energy (statuts, null≠0, isolation, RBAC). Ils n'utilisent JAMAIS le module
Énergie réel : campagne « REAL ENERGY » à faire quand ENERGY_API_BASE_URL
sera configurée.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}

METRIC_KEYS = {"value", "unit", "availability", "measurement_type", "source", "timestamp"}


def _login(creds) -> dict:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text[:200]}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def driver_h():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def admin_b_h():
    return _login(ADMIN_B)


@pytest.fixture(scope="module")
def default_trip_ids(admin_h):
    r = requests.get(f"{API}/livre/trips", params={"classification": "professional"},
                     headers=admin_h, timeout=20)
    assert r.status_code == 200
    trips = r.json()["trips"]
    assert trips, "aucun trajet pro dans le tenant default"
    return [t["id"] for t in trips[:3]]


# ---------------------------------------------------------------------------
# E2E — Energy NON CONNECTÉ (défaut : ENERGY_API_BASE_URL absente)
# ---------------------------------------------------------------------------
def test_status_not_connected(admin_h):
    r = requests.get(f"{API}/livre/energy/status", headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    if body["mode"] == "fixture":
        pytest.skip("ENERGY_API_MODE=fixture actif dans l'environnement")
    assert body["connected"] is False
    assert body["mode"] == "not_connected"
    assert body["base_url_configured"] is False


def test_trips_unavailable_never_zero(admin_h, default_trip_ids):
    r = requests.post(f"{API}/livre/energy/trips",
                      json={"trip_ids": default_trip_ids}, headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == len(default_trip_ids)
    if body["mode"] == "fixture":
        pytest.skip("fixture mode — couvert par les tests unitaires")
    for env in body["results"]:
        assert env["availability"] == "UNAVAILABLE"
        assert env["reason"] == "energy_not_connected"
        assert env["electric"] is None and env["fuel"] is None  # jamais 0 inventé


def test_overview_rbac_and_shape(admin_h, driver_h):
    r = requests.get(f"{API}/livre/energy/overview", headers=driver_h, timeout=15)
    assert r.status_code == 403, "chauffeur ne doit pas voir la vue d'ensemble énergie"
    r = requests.get(f"{API}/livre/energy/overview", headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    fleet = body["fleet"]
    for k in ("vehicles_total", "powertrain_set", "tank_capacity_set", "battery_capacity_set"):
        assert isinstance(fleet[k], int)
    if body["mode"] == "not_connected":
        assert body["energy"]["availability"] == "UNAVAILABLE"
        assert body["energy"]["metrics"] is None


def test_trips_requires_auth_and_ids(admin_h):
    r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": []},
                      headers=admin_h, timeout=15)
    assert r.status_code == 400
    r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": ["x"]}, timeout=15)
    assert r.status_code in (401, 403)


def test_driver_cannot_read_foreign_trip(driver_h, admin_h):
    """Chauffeur : trajet d'un autre conducteur/véhicule → trip_not_found."""
    r = requests.get(f"{API}/livre/trips", params={"classification": "professional"},
                     headers=admin_h, timeout=20)
    all_trips = r.json()["trips"]
    rd = requests.get(f"{API}/livre/trips", headers=driver_h, timeout=20)
    own_ids = {t["id"] for t in rd.json()["trips"]}
    foreign = next((t for t in all_trips if t["id"] not in own_ids), None)
    if not foreign:
        pytest.skip("aucun trajet étranger disponible pour ce test")
    r = requests.post(f"{API}/livre/energy/trips",
                      json={"trip_ids": [foreign["id"]]}, headers=driver_h, timeout=15)
    assert r.status_code == 200
    env = r.json()["results"][0]
    assert env["reason"] == "trip_not_found"
    assert env["electric"] is None and env["fuel"] is None


def test_tenant_isolation(admin_b_h, default_trip_ids):
    """Admin tenant B : trajet du tenant default → trip_not_found."""
    r = requests.post(f"{API}/livre/energy/trips",
                      json={"trip_ids": [default_trip_ids[0]]}, headers=admin_b_h, timeout=15)
    assert r.status_code == 200
    assert r.json()["results"][0]["reason"] == "trip_not_found"


# ---------------------------------------------------------------------------
# UNITAIRES FIXTURE — contrat v1 (MOCK explicite, jamais présenté comme réel)
# ---------------------------------------------------------------------------
def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _ids_covering_all_scenarios():
    from app import energy_client
    found: dict[int, str] = {}
    i = 0
    while len(found) < 8 and i < 5000:
        tid = f"fixture-trip-{i}"
        found.setdefault(energy_client.fixture_scenario_index(tid), tid)
        i += 1
    assert len(found) == 8
    return found


def _assert_metric_contract(m: dict):
    assert set(m.keys()) == METRIC_KEYS
    assert m["availability"] in ("AVAILABLE", "STALE", "UNAVAILABLE")
    if m["availability"] == "UNAVAILABLE":
        assert m["value"] is None, "inconnu = null, JAMAIS 0"


def test_fixture_covers_all_contract_cases(monkeypatch):
    monkeypatch.setenv("ENERGY_API_MODE", "fixture")
    from app import energy_client
    ids = _ids_covering_all_scenarios()
    items = [{"trip_id": tid, "distance_km": 57.8} for tid in ids.values()]
    resp = _run(energy_client.trip_energy_batch(items))
    assert resp["mode"] == "fixture" and resp["connected"] is True
    by_scenario = {energy_client.fixture_scenario_index(r["trip_id"]): r
                   for r in resp["results"]}
    for env in resp["results"]:
        assert env["contract_version"] == "1.0"
        assert env["mode"] == "fixture"
        for section in ("electric", "fuel"):
            if env.get(section):
                for m in env[section].values():
                    _assert_metric_contract(m)
    # 0 : thermique MESURÉ OBD
    ice = by_scenario[0]
    assert ice["powertrain"] == "ICE"
    assert ice["fuel"]["fuel_liters"]["measurement_type"] == "MEASURED"
    assert ice["fuel"]["fuel_liters"]["source"] == "OBD"
    # 1 : thermique ESTIMÉ
    assert by_scenario[1]["fuel"]["consumption_l_100km"]["measurement_type"] == "ESTIMATED"
    # 2 : BEV MESURÉ avec SoC
    bev = by_scenario[2]
    assert bev["powertrain"] == "BEV"
    assert bev["electric"]["soc_start_pct"]["value"] == 82
    assert bev["electric"]["soc_end_pct"]["value"] == 64
    # 3 : BEV référence — jamais présenté mesuré, SoC indisponible
    ref = by_scenario[3]
    assert ref["electric"]["consumption_kwh_100km"]["measurement_type"] == "REFERENCE"
    assert ref["electric"]["consumption_kwh_100km"]["source"] == "VEHICLE_SPEC"
    assert ref["electric"]["soc_start_pct"]["availability"] == "UNAVAILABLE"
    assert ref["electric"]["soc_start_pct"]["value"] is None
    # 4 : PHEV partiel — deux énergies SÉPARÉES, carburant indisponible
    phev = by_scenario[4]
    assert phev["powertrain"] == "PHEV"
    assert phev["electric"]["energy_kwh"]["availability"] == "AVAILABLE"
    assert phev["fuel"]["fuel_liters"]["availability"] == "UNAVAILABLE"
    assert phev["fuel"]["fuel_liters"]["value"] is None
    # 5 : STALE
    assert by_scenario[5]["availability"] == "STALE"
    assert by_scenario[5]["electric"]["energy_kwh"]["availability"] == "STALE"
    # 6 : aucune donnée
    assert by_scenario[6]["availability"] == "UNAVAILABLE"
    assert by_scenario[6]["reason"] == "no_data"
    # 7 : valeur null explicite
    nul = by_scenario[7]
    assert nul["availability"] == "AVAILABLE"
    assert nul["fuel"]["fuel_liters"]["value"] is None
    assert nul["fuel"]["fuel_liters"]["availability"] == "UNAVAILABLE"


def test_fixture_fleet_summary_contract(monkeypatch):
    monkeypatch.setenv("ENERGY_API_MODE", "fixture")
    from app import energy_client
    s = _run(energy_client.fleet_summary("2026-06-01", "2026-06-15"))
    assert s["mode"] == "fixture"
    for m in s["metrics"].values():
        _assert_metric_contract(m)


def test_default_mode_is_disconnected(monkeypatch):
    monkeypatch.delenv("ENERGY_API_MODE", raising=False)
    monkeypatch.delenv("ENERGY_API_BASE_URL", raising=False)
    from app import energy_client
    assert energy_client.mode() == "not_connected"
    resp = _run(energy_client.trip_energy_batch([{"trip_id": "t1"}]))
    assert resp["connected"] is False
    env = resp["results"][0]
    assert env["reason"] == "energy_not_connected"
    assert env["electric"] is None and env["fuel"] is None
