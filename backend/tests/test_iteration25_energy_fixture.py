"""Iteration 25 — Energy → Journal v1 en mode ENERGY_API_MODE=fixture (E2E API réelle).

Modules couverts : /api/livre/energy/status, /api/livre/energy/trips,
/api/livre/energy/overview (RBAC + isolation tenant) + non-régression carburant.
Les données énergie sont des FIXTURES contractuelles (mock explicite).
"""
from __future__ import annotations

import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}

METRIC_KEYS = {"value", "unit", "availability", "measurement_type", "source", "timestamp"}


def _login(creds) -> dict:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text[:200]}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _current_energy_mode():
    try:
        h = _login(ADMIN)
        return requests.get(f"{API}/livre/energy/status", headers=h, timeout=15).json().get("mode")
    except Exception:  # noqa: BLE001
        return None


if _current_energy_mode() != "fixture":
    pytest.skip("Campagne fixture — nécessite ENERGY_API_MODE=fixture dans backend/.env",
                allow_module_level=True)


@pytest.fixture(scope="module")
def admin_h():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def manager_h():
    return _login(MANAGER)


@pytest.fixture(scope="module")
def driver_h():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def admin_b_h():
    return _login(ADMIN_B)


@pytest.fixture(scope="module")
def trip_ids(admin_h):
    r = requests.get(f"{API}/livre/trips", params={"classification": "professional"},
                     headers=admin_h, timeout=30)
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()["trips"]][:60]
    assert len(ids) >= 8, f"pas assez de trajets pour couvrir les scénarios: {len(ids)}"
    return ids


def _assert_metric(m: dict, ctx: str):
    assert set(m.keys()) == METRIC_KEYS, f"{ctx}: clés {sorted(m.keys())}"
    assert m["availability"] in ("AVAILABLE", "STALE", "UNAVAILABLE"), ctx
    if m["availability"] == "UNAVAILABLE":
        assert m["value"] is None, f"{ctx}: inconnu doit être null, jamais 0 ({m['value']})"


# --- /energy/status -------------------------------------------------------
class TestEnergyStatus:
    def test_status_fixture_mode_with_warning(self, admin_h):
        r = requests.get(f"{API}/livre/energy/status", headers=admin_h, timeout=20)
        assert r.status_code == 200
        b = r.json()
        assert b["mode"] == "fixture", f"mode attendu fixture, reçu {b['mode']}"
        assert b["connected"] is True
        assert b["base_url_configured"] is False
        assert b.get("warning"), "warning explicite manquant en mode fixture"
        assert "Fixture" in b["warning"] or "fixture" in b["warning"].lower()
        assert b["contract_version"] == "1.0"

    def test_status_accessible_to_driver(self, driver_h):
        r = requests.get(f"{API}/livre/energy/status", headers=driver_h, timeout=20)
        assert r.status_code == 200
        assert r.json()["mode"] == "fixture"


# --- /energy/trips --------------------------------------------------------
class TestEnergyTrips:
    def test_envelopes_contract_and_scenario_coverage(self, admin_h, trip_ids):
        r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": trip_ids},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["mode"] == "fixture" and b["connected"] is True
        assert b["contract_version"] == "1.0"
        assert len(b["results"]) == len(trip_ids)
        assert [e["trip_id"] for e in b["results"]] == trip_ids, "ordre non préservé"

        powertrains, availabilities, mtypes, sources = set(), set(), set(), set()
        reasons = set()
        null_seen = False
        soc_pairs = []
        phev_split = False
        for env in b["results"]:
            assert env["mode"] == "fixture"
            assert env["contract_version"] == "1.0"
            assert env["availability"] in ("AVAILABLE", "STALE", "UNAVAILABLE")
            availabilities.add(env["availability"])
            if env.get("reason"):
                reasons.add(env["reason"])
            if env.get("powertrain"):
                powertrains.add(env["powertrain"])
            for section in ("electric", "fuel"):
                data = env.get(section)
                if not data:
                    continue
                for k, m in data.items():
                    _assert_metric(m, f"{env['trip_id']}.{section}.{k}")
                    if m["measurement_type"]:
                        mtypes.add(m["measurement_type"])
                    if m["source"]:
                        sources.add(m["source"])
                    if m["value"] is None:
                        null_seen = True
            el = env.get("electric") or {}
            if el.get("soc_start_pct", {}).get("value") is not None:
                soc_pairs.append((el["soc_start_pct"]["value"], el["soc_end_pct"]["value"]))
            if env.get("powertrain") == "PHEV" and env.get("electric") and env.get("fuel"):
                phev_split = True

        assert {"ICE", "BEV", "PHEV"} <= powertrains, f"powertrains vus: {powertrains}"
        assert "STALE" in availabilities, "aucun scénario PÉRIMÉ (STALE) retourné"
        assert "UNAVAILABLE" in availabilities
        assert {"MEASURED", "ESTIMATED", "REFERENCE"} <= mtypes, f"types: {mtypes}"
        assert {"OBD", "CAN", "ENERGY_MODEL", "VEHICLE_SPEC"} <= sources, f"sources: {sources}"
        assert "no_data" in reasons, f"reasons: {reasons}"
        assert null_seen, "aucune métrique null (inconnu) rencontrée"
        assert (82, 64) in soc_pairs, f"SoC BEV mesuré 82→64 absent: {soc_pairs[:6]}"
        assert phev_split, "aucun PHEV avec électrique + carburant séparés"

    def test_unknown_trip_id_returns_trip_not_found(self, admin_h):
        r = requests.post(f"{API}/livre/energy/trips",
                          json={"trip_ids": ["TEST_does_not_exist"]},
                          headers=admin_h, timeout=20)
        assert r.status_code == 200
        env = r.json()["results"][0]
        assert env["reason"] == "trip_not_found"
        assert env["availability"] == "UNAVAILABLE"
        assert env["electric"] is None and env["fuel"] is None

    def test_driver_gets_own_trips_200(self, driver_h):
        r = requests.get(f"{API}/livre/trips", headers=driver_h, timeout=30)
        assert r.status_code == 200
        own = [t["id"] for t in r.json()["trips"]][:5]
        if not own:
            pytest.skip("DATA: le chauffeur Jean Dupont n'a aucun trajet "
                        "(0 driver_id + 0 assignment en base) — RBAC 'ses trajets' non vérifiable")
        r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": own},
                          headers=driver_h, timeout=20)
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == len(own)
        assert all(e.get("reason") != "trip_not_found" for e in results)

    def test_empty_ids_400(self, admin_h):
        r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": []},
                          headers=admin_h, timeout=20)
        assert r.status_code == 400

    def test_unauthenticated_rejected(self):
        r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": ["x"]}, timeout=20)
        assert r.status_code in (401, 403)


# --- Isolation tenant -----------------------------------------------------
class TestTenantIsolation:
    def test_tenant_b_cannot_read_default_trip(self, admin_b_h, trip_ids):
        r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": trip_ids[:3]},
                          headers=admin_b_h, timeout=20)
        assert r.status_code == 200
        for env in r.json()["results"]:
            assert env["reason"] == "trip_not_found", env
            assert env["electric"] is None and env["fuel"] is None

    def test_driver_cannot_read_foreign_trip(self, driver_h, admin_h):
        all_trips = requests.get(f"{API}/livre/trips",
                                 params={"classification": "professional"},
                                 headers=admin_h, timeout=30).json()["trips"]
        own = {t["id"] for t in requests.get(f"{API}/livre/trips", headers=driver_h,
                                             timeout=30).json()["trips"]}
        foreign = next((t["id"] for t in all_trips if t["id"] not in own), None)
        if not foreign:
            pytest.skip("aucun trajet étranger")
        r = requests.post(f"{API}/livre/energy/trips", json={"trip_ids": [foreign]},
                          headers=driver_h, timeout=20)
        assert r.status_code == 200
        assert r.json()["results"][0]["reason"] == "trip_not_found"


# --- /energy/overview -----------------------------------------------------
class TestEnergyOverview:
    def test_overview_admin_fixture(self, admin_h):
        r = requests.get(f"{API}/livre/energy/overview", headers=admin_h, timeout=20)
        assert r.status_code == 200
        b = r.json()
        assert b["mode"] == "fixture" and b["connected"] is True
        fleet = b["fleet"]
        assert fleet["vehicles_total"] == 18, f"attendu 18 véhicules, reçu {fleet['vehicles_total']}"
        assert fleet["powertrain_set"] == 0, f"powertrain_set attendu 0, reçu {fleet['powertrain_set']}"
        for k in ("tank_capacity_set", "battery_capacity_set"):
            assert isinstance(fleet[k], int)
        energy = b["energy"]
        assert energy["mode"] == "fixture"
        assert energy["availability"] == "AVAILABLE"
        assert energy["metrics"], "metrics fixture absentes"
        for k, m in energy["metrics"].items():
            _assert_metric(m, f"fleet.{k}")
        assert energy["metrics"]["thermal_consumption_l_100km"]["value"] == 8.4
        assert b["period"]["from"] and b["period"]["to"]

    def test_overview_manager_allowed(self, manager_h):
        r = requests.get(f"{API}/livre/energy/overview", headers=manager_h, timeout=20)
        assert r.status_code == 200

    def test_overview_driver_forbidden(self, driver_h):
        r = requests.get(f"{API}/livre/energy/overview", headers=driver_h, timeout=20)
        assert r.status_code == 403


# --- Non-régression carburant (approvisionnements) ------------------------
class TestFuelRegression:
    @pytest.mark.parametrize("path,params", [
        ("/livre/fuel/widget", None),
        ("/livre/fuel/overview", None),
        ("/livre/fuel/transactions", {"limit": 5}),
        ("/livre/fuel/cards", None),
        ("/livre/fuel/statements", None),
        ("/livre/fuel/anomalies", None),
        ("/livre/dashboard", None),
    ])
    def test_endpoint_ok(self, admin_h, path, params):
        r = requests.get(f"{API}{path}", headers=admin_h, params=params, timeout=30)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        assert "_id" not in str(r.json())[:5000] or '"_id"' not in r.text
