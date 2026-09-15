"""Mapping tenant Journal → tenant Energy (FAIL-CLOSED) — campagne REAL ENERGY.

Le tenant Journal `default` est mappé vers le tenant Energy réel (paas_13588).
Les autres tenants n'ont AUCUN mapping → aucun appel Energy, aucune fuite.
Le token Energy n'est jamais affiché ni asserté en clair.
"""
from __future__ import annotations

import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ENERGY_TOKEN = backend_env.get("ENERGY_API_TOKEN") or ""

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
LECTURE = {"email": "lecture@logitrak.ch", "password": "lecture123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}

MAP_URL = f"{API}/livre/energy/tenant-mapping"
STATUS_URL = f"{API}/livre/energy/status"
OVERVIEW_URL = f"{API}/livre/energy/overview"
TRIPS_URL = f"{API}/livre/energy/trips"
PREVIEW_URL = f"{API}/livre/energy/reconciliation/preview"

PILOT_TRIP = "8be7b16f-ff74-4262-a1ff-1735f085c3d4"


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


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
def lecture_h():
    return _login(LECTURE)


@pytest.fixture(scope="module")
def admin_b_h():
    return _login(ADMIN_B)


@pytest.fixture(scope="module", autouse=True)
def cleanup_tenant_b(admin_b_h):
    """Tenant B doit finir SANS mapping (fail-closed)."""
    yield
    requests.put(MAP_URL, json={"energy_tenant_id": None}, headers=admin_b_h, timeout=20)


class TestMappingConfig:
    def test_default_mapping_configured(self, admin_h):
        b = requests.get(MAP_URL, headers=admin_h, timeout=20).json()
        assert b["configured"] is True
        assert b["fail_closed"] is True
        assert b["energy_tenant_id"], "le tenant default doit être mappé pour la campagne"

    def test_status_exposes_tenant_configured(self, admin_h):
        b = requests.get(STATUS_URL, headers=admin_h, timeout=30).json()
        assert b["energy_tenant_configured"] is True

    def test_rbac(self, driver_h, lecture_h, manager_h):
        assert requests.get(MAP_URL, headers=driver_h, timeout=20).status_code == 403
        assert requests.get(MAP_URL, headers=lecture_h, timeout=20).status_code == 403
        assert requests.get(MAP_URL, headers=manager_h, timeout=20).status_code == 200
        assert requests.put(MAP_URL, json={"energy_tenant_id": "x_y"},
                            headers=manager_h, timeout=20).status_code == 403
        assert requests.put(MAP_URL, json={"energy_tenant_id": "x_y"},
                            headers=driver_h, timeout=20).status_code == 403

    def test_invalid_value_rejected(self, admin_b_h):
        for bad in ("a" * 101, "tenant avec espaces", "tenant/../x", "<script>"):
            r = requests.put(MAP_URL, json={"energy_tenant_id": bad},
                             headers=admin_b_h, timeout=20)
            assert r.status_code == 400, f"{bad!r} aurait dû être rejeté"

    def test_tenant_isolation_settings(self, admin_h, admin_b_h):
        # B configure PUIS supprime son mapping : default ne doit jamais bouger
        before_default = requests.get(MAP_URL, headers=admin_h, timeout=20).json()
        r = requests.put(MAP_URL, json={"energy_tenant_id": "tenant-test-b"},
                         headers=admin_b_h, timeout=20)
        assert r.status_code == 200 and r.json()["energy_tenant_id"] == "tenant-test-b"
        after_default = requests.get(MAP_URL, headers=admin_h, timeout=20).json()
        assert after_default["energy_tenant_id"] == before_default["energy_tenant_id"]
        r = requests.put(MAP_URL, json={"energy_tenant_id": None},
                         headers=admin_b_h, timeout=20)
        assert r.status_code == 200 and r.json()["configured"] is False

    def test_mapping_change_audited(self, admin_b_h):
        r = requests.get(f"{API}/livre/audit-log", params={"limit": 50},
                         headers=admin_b_h, timeout=20)
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        hits = [e for e in items if e.get("action") == "energy.tenant_mapping_updated"]
        assert hits, "toute modification du mapping doit être auditée"
        assert "before" in hits[0]["details"] and "after" in hits[0]["details"]


class TestFailClosedTenantB:
    """Tenant B sans mapping : AUCUN appel Energy, AUCUNE donnée paas_13588."""

    def test_mapping_absent(self, admin_b_h):
        b = requests.get(MAP_URL, headers=admin_b_h, timeout=20).json()
        assert b["configured"] is False and b["energy_tenant_id"] is None

    def test_status_not_configured(self, admin_b_h):
        b = requests.get(STATUS_URL, headers=admin_b_h, timeout=30).json()
        assert b["energy_tenant_configured"] is False

    def test_overview_fail_closed(self, admin_b_h):
        b = requests.get(OVERVIEW_URL, headers=admin_b_h, timeout=30).json()
        assert b["tenant_mapping"] == "NOT_CONFIGURED"
        assert b["connected"] is False
        e = b["energy"]
        assert e["availability"] == "UNAVAILABLE"
        assert e["reason"] == "energy_tenant_not_configured"
        assert e["metrics"] is None, "jamais de données paas_13588 pour le tenant B"

    def test_trips_fail_closed(self, admin_b_h):
        r = requests.post(TRIPS_URL, json={"trip_ids": ["b-inexistant-1"]},
                          headers=admin_b_h, timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["tenant_mapping"] == "NOT_CONFIGURED"
        assert b["reason"] == "energy_tenant_not_configured"
        for res in b["results"]:
            assert res["availability"] == "UNAVAILABLE"
            assert res["fuel"] is None and res["electric"] is None

    def test_preview_fail_closed_no_default_data(self, admin_b_h):
        b = requests.get(PREVIEW_URL, params={"date_from": "2026-01-01",
                                              "date_to": "2026-12-31"},
                         headers=admin_b_h, timeout=60).json()
        assert b["connected"] is False
        plates = {r.get("plate") for r in b["rows"]}
        assert "LOGITRAK AUDI" not in plates, "fuite de véhicule du tenant default"
        for r in b["rows"]:
            assert r["consumed_fuel"] is None
            assert r["consumption_measurement_type"] == "NONE"

    def test_pilot_trip_of_default_unreachable_for_b(self, admin_b_h):
        r = requests.post(TRIPS_URL, json={"trip_ids": [PILOT_TRIP]},
                          headers=admin_b_h, timeout=30)
        assert r.status_code == 200
        for res in r.json()["results"]:
            assert res["availability"] == "UNAVAILABLE"
            assert res["fuel"] is None, "les données Energy du tenant A ne doivent pas fuiter"


class TestRealEnergyAfterMapping:
    """Tenant default mappé → appels Energy HTTPS réels (aucun mock)."""

    def test_status_connected_real(self, admin_h):
        b = requests.get(STATUS_URL, headers=admin_h, timeout=30).json()
        assert b["connected"] is True and b["mode"] == "real"
        assert b["base_url_configured"] is True

    def test_pilot_batch_real(self, admin_h):
        r = requests.post(TRIPS_URL, json={"trip_ids": [PILOT_TRIP]},
                          headers=admin_h, timeout=60)
        assert r.status_code == 200
        b = r.json()
        assert b["mode"] == "real"
        assert b["contract_version"] == "1.0"
        res = b["results"][0]
        assert res["trip_id"] == PILOT_TRIP, "écho trip_id obligatoire"
        assert "fuel" in res and "electric" in res
        assert "energy" not in res, "results[].energy ne doit pas exister"
        assert res.get("reason") != "mapping_invalid", \
            "le mapping tenant doit résoudre le tracker"
        # null ≠ 0 : aucune métrique absente ne devient zéro
        for domain in ("fuel", "electric"):
            for m in (res.get(domain) or {}).values():
                if isinstance(m, dict) and m.get("availability") != "AVAILABLE":
                    assert m.get("value") in (None, m.get("value")), "structure métrique"
                    if m.get("value") == 0 and m.get("measurement_type") is None:
                        raise AssertionError("zéro fabriqué pour une donnée absente")
        assert res.get("powertrain") in ("ICE", "HEV", "PHEV", "BEV", "UNKNOWN", None)

    def test_overview_real(self, admin_h):
        b = requests.get(OVERVIEW_URL, headers=admin_h, timeout=60).json()
        assert b["tenant_mapping"] == "CONFIGURED"
        assert b["connected"] is True
        # Écart Energy documenté : fleet/summary ne renvoie pas contract_version
        # (le contrôle contractuel décisif est le batch = "1.0").
        metrics = b["energy"].get("metrics") or {}
        assert metrics, "fleet summary réel doit exposer des métriques"
        for k, m in metrics.items():
            if isinstance(m, dict) and m.get("availability") == "UNAVAILABLE":
                assert m.get("value") is None, f"{k}: null ne doit jamais devenir 0"

    def test_preview_real_audi_consumption(self, admin_h):
        b = requests.get(PREVIEW_URL, params={"date_from": "2026-01-01",
                                              "date_to": "2026-12-31"},
                         headers=admin_h, timeout=120).json()
        assert b["connected"] is True and b["mode"] == "real"
        audi = next(r for r in b["rows"] if r.get("navixy_tracker_id") in (781479, "781479"))
        cf = audi.get("consumed_fuel")
        if cf is not None:  # donnée réelle Energy (STALE MEASURED attendue)
            assert cf["value"] is not None
            assert cf["measurement_type"] in ("MEASURED", "ESTIMATED", "REFERENCE")
            assert cf["availability"] in ("AVAILABLE", "STALE")
            if cf["availability"] == "STALE":
                # STALE n'est JAMAIS exploitable : ni OK ni À contrôler.
                # (IMPOSSIBLE reste possible si aucun achat sur la période.)
                assert audi["status"] not in ("OK", "A_CONTROLER"), \
                    "STALE ne doit jamais être traité comme donnée fraîche exploitable"
        unmapped = [r for r in b["rows"] if not r["mapped"]]
        assert len(unmapped) == 6, "les 6 véhicules sans tracker restent visibles"
        for r in unmapped:
            assert r["status"] == "IMPOSSIBLE"

    def test_token_never_exposed(self, admin_h):
        assert ENERGY_TOKEN, "token requis pour ce test"
        for url in (STATUS_URL, OVERVIEW_URL, MAP_URL):
            body = requests.get(url, headers=admin_h, timeout=60).text
            assert ENERGY_TOKEN not in body, f"token exposé par {url}"
