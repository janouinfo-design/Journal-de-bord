"""Écran Rapprochement achats ↔ consommation — tests backend.

Mode par défaut : Energy NON CONNECTÉ (aucune URL réelle — REAL ENERGY NON TESTÉ).
Les seuils utilisés dans les tests unitaires sont des valeurs FIXTURE/TEST
uniquement, jamais des seuils métier de production.
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

PARAMS_YEAR = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


def _login(creds) -> dict:
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
def admin_b_h():
    return _login(ADMIN_B)


@pytest.fixture(scope="module")
def preview(admin_h):
    r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                     params=PARAMS_YEAR, headers=admin_h, timeout=90)
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Statuts métier centralisés (unitaires) — seuils = FIXTURE/TEST uniquement
# ---------------------------------------------------------------------------
class TestStatusLogic:
    def _measured(self, value=100.0, availability="AVAILABLE"):
        return {"value": value, "unit": "L", "availability": availability,
                "measurement_type": "MEASURED", "source": "OBD", "timestamp": None}

    def _status(self, *a, **k):
        from app.routes.energy import _reconciliation_status
        return _reconciliation_status(*a, **k)

    def test_unmapped_impossible(self):
        s, reason = self._status(False, 5, self._measured(), 1.0, 1.0, None)
        assert s == "IMPOSSIBLE" and "tracker Navixy" in reason

    def test_no_consumption_impossible(self):
        s, reason = self._status(True, 5, None, None, None, None)
        assert s == "IMPOSSIBLE" and "Consommation indisponible" in reason

    def test_no_purchase_impossible(self):
        s, reason = self._status(True, 0, self._measured(), None, None, None)
        assert s == "IMPOSSIBLE" and "Aucun achat" in reason

    def test_estimated_indicatif_even_with_big_gap(self):
        m = {**self._measured(), "measurement_type": "ESTIMATED"}
        s, reason = self._status(True, 5, m, 80.0, 80.0, 10)  # seuil 10 = TEST
        assert s == "INDICATIF", "ESTIMATED ne doit JAMAIS devenir une anomalie fiable"
        assert "indicatif" in reason.lower()

    def test_reference_indicatif(self):
        m = {**self._measured(), "measurement_type": "REFERENCE"}
        s, reason = self._status(True, 5, m, 2.0, 2.0, None)
        assert s == "INDICATIF" and "référence" in reason.lower()

    def test_stale_measured_indicatif(self):
        s, reason = self._status(True, 5, self._measured(availability="STALE"), 2.0, 2.0, None)
        assert s == "INDICATIF" and "périmée" in reason

    def test_measured_no_threshold_ok_no_alert(self):
        s, reason = self._status(True, 5, self._measured(), 50.0, 50.0, None)
        assert s == "OK"
        assert "Aucun seuil configuré" in reason

    def test_measured_within_test_threshold_ok(self):
        s, _ = self._status(True, 5, self._measured(), 5.0, 5.0, 10)  # seuil 10 = TEST
        assert s == "OK"

    def test_measured_beyond_test_threshold_a_controler(self):
        s, reason = self._status(True, 5, self._measured(), 25.0, 25.0, 10)  # seuil 10 = TEST
        assert s == "A_CONTROLER"
        assert "Aucune alerte automatique" in reason

    def test_measured_gap_none_impossible_not_zero(self):
        s, _ = self._status(True, 5, self._measured(), None, None, None)
        assert s == "IMPOSSIBLE", "IMPOSSIBLE ne doit pas être assimilé à un écart zéro"


# ---------------------------------------------------------------------------
# E2E — Energy NON CONNECTÉ (défaut)
# ---------------------------------------------------------------------------
class TestPreviewE2E:
    def test_shape_and_flags(self, preview):
        assert preview["preview"] is True
        assert preview["alerting"] == "disabled"
        assert preview["thresholds"]["configured"] is False
        assert preview["thresholds"]["percent"] is None
        assert preview["thresholds"]["liters"] is None
        assert len(preview["rows"]) == 18

    def test_all_impossible_when_disconnected(self, preview):
        if preview["mode"] == "fixture":
            pytest.skip("mode fixture actif")
        if preview["connected"]:
            # Energy réel connecté : invariants permanents — jamais de zéro fabriqué
            for row in preview["rows"]:
                assert row["status_reason"]
                cf = row["consumed_fuel"]
                if cf is None:
                    assert row["consumption_measurement_type"] == "NONE"
                else:
                    assert cf["value"] is not None, "métrique retenue → valeur réelle, jamais 0 fabriqué"
                    assert cf["availability"] in ("AVAILABLE", "STALE")
                if row["gap_l"] is None:
                    assert row["gap_pct"] is None
            return
        assert preview["connected"] is False
        for row in preview["rows"]:
            assert row["status"] == "IMPOSSIBLE"
            assert row["status_reason"]
            assert row["gap_l"] is None and row["gap_pct"] is None
            assert row["consumed_fuel"] is None
            assert row["consumption_measurement_type"] == "NONE"

    def test_unmapped_vehicles_visible_with_reason(self, preview):
        unmapped = [r for r in preview["rows"] if not r["mapped"]]
        assert len(unmapped) == 6, "les 6 véhicules sans tracker doivent rester visibles"
        for r in unmapped:
            assert "tracker Navixy" in r["status_reason"]
            assert r["status"] == "IMPOSSIBLE"

    def test_powertrain_never_inferred(self, preview):
        """Le powertrain vient UNIQUEMENT de vehicles.fuel_type (source prouvée),
        jamais du modèle/label. Depuis le lot Motorisations réelles (26/08/2026),
        2 véhicules sont PROUVÉS essence via le garage Navixy → ICE."""
        import pymongo, os
        mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
        vmap = {v["id"]: v.get("fuel_type") for v in
                mc[os.environ["DB_NAME"]].vehicles.find({"tenant_id": "default"},
                                                        {"_id": 0, "id": 1, "fuel_type": 1})}
        mc.close()
        from app.navixy_sync import powertrain_from_fuel_type
        for r in preview["rows"]:
            expected = powertrain_from_fuel_type(vmap.get(r["vehicle_id"]))
            assert r["powertrain"] == expected, \
                f"{r['plate']}: powertrain {r['powertrain']} ≠ fuel_type prouvé ({expected})"

    def test_purchases_aggregated_with_sources(self, preview):
        with_buy = [r for r in preview["rows"] if r["purchased"]["tx_count"] > 0]
        assert with_buy, "les 28 transactions existantes doivent produire des achats"
        total_l = sum(r["purchased"]["liters"] for r in preview["rows"])
        assert total_l > 0
        for r in with_buy:
            assert sum(r["purchased"]["sources"].values()) == r["purchased"]["tx_count"]

    def test_vehicle_filter(self, admin_h, preview):
        vid = preview["rows"][0]["vehicle_id"]
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params={**PARAMS_YEAR, "vehicle_id": vid},
                         headers=admin_h, timeout=30)
        rows = r.json()["rows"]
        assert len(rows) == 1 and rows[0]["vehicle_id"] == vid

    def test_empty_period(self, admin_h):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params={"date_from": "2020-01-01", "date_to": "2020-01-31"},
                         headers=admin_h, timeout=90)
        rows = r.json()["rows"]
        assert all(row["purchased"]["tx_count"] == 0 for row in rows)
        assert all(row["gap_l"] is None for row in rows)


# ---------------------------------------------------------------------------
# Sécurité — RBAC + isolation tenant
# ---------------------------------------------------------------------------
class TestSecurity:
    def test_driver_forbidden(self, driver_h):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         headers=driver_h, timeout=30)
        assert r.status_code == 403

    def test_manager_allowed(self, manager_h):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params=PARAMS_YEAR, headers=manager_h, timeout=90)
        assert r.status_code == 200

    def test_unauthenticated(self):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview", timeout=30)
        assert r.status_code in (401, 403)

    def test_tenant_isolation(self, admin_b_h, preview):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params=PARAMS_YEAR, headers=admin_b_h, timeout=90)
        assert r.status_code == 200
        plates_b = {row["plate"] for row in r.json()["rows"]}
        plates_default = {row["plate"] for row in preview["rows"]}
        assert not (plates_b & plates_default), "aucune plaque du tenant default chez tenant B"

    def test_tenant_b_cannot_read_default_vehicle_by_param(self, admin_b_h, preview):
        vid = preview["rows"][0]["vehicle_id"]
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params={**PARAMS_YEAR, "vehicle_id": vid},
                         headers=admin_b_h, timeout=30)
        assert r.status_code == 200
        assert r.json()["rows"] == [], "paramètre manipulé : le véhicule du tenant default ne doit pas fuiter"
