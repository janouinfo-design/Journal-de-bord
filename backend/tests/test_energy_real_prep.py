"""Préparation REAL ENERGY — tests de robustesse SANS le module Énergie réel.

REAL ENERGY : NON TESTÉ — URL MANQUANTE. Ces tests simulent les pannes
(réseau, HTTP 5xx, payload invalide, réponse partielle) avec des doubles
techniques locaux, JAMAIS présentés comme le service Energy réel.
Couvre aussi : priorité MEASURED>ESTIMATED>REFERENCE>NONE, étiquetage fiscal
ESTIMATED des litres legacy, et le modèle préparatoire de rapprochement
achats vs consommation (aucune alerte).
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


def _login(creds) -> dict:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def driver_h():
    return _login(DRIVER)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Doubles techniques httpx (simulation de pannes — PAS le service Energy réel)
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status=200, body=None):
        self._status = status
        self._body = body
        self.content = b"x"

    def raise_for_status(self):
        if self._status >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    last_post_kwargs = None

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        _FakeClient.last_post_kwargs = k
        return self._resp

    async def get(self, *a, **k):
        return self._resp


def _patch_real_mode(monkeypatch, resp):
    from app import energy_client
    monkeypatch.setenv("ENERGY_API_BASE_URL", "http://energy.test.invalid")
    monkeypatch.delenv("ENERGY_API_MODE", raising=False)
    monkeypatch.setattr(energy_client.httpx, "AsyncClient",
                        lambda **kw: _FakeClient(resp))
    return energy_client


ITEMS = [{"trip_id": "t-1", "vehicle_id": "v-1", "distance_km": 40.0},
         {"trip_id": "t-2", "vehicle_id": "v-2", "distance_km": 12.5}]


class TestRealModeFailures:
    def test_http_error_5xx(self, monkeypatch):
        ec = _patch_real_mode(monkeypatch, _FakeResp(status=500))
        resp = _run(ec.trip_energy_batch(ITEMS, tenant_id="default"))
        assert resp["connected"] is False and resp["mode"] == "real"
        for env in resp["results"]:
            assert env["reason"] == "energy_unreachable"
            assert env["electric"] is None and env["fuel"] is None

    def test_invalid_payload(self, monkeypatch):
        ec = _patch_real_mode(monkeypatch, _FakeResp(body={"foo": "bar"}))
        resp = _run(ec.trip_energy_batch(ITEMS, tenant_id="default"))
        assert resp["connected"] is True
        for env in resp["results"]:
            assert env["reason"] == "energy_invalid_response"
            assert env["electric"] is None and env["fuel"] is None

    def test_invalid_json(self, monkeypatch):
        ec = _patch_real_mode(monkeypatch, _FakeResp(body=ValueError("not json")))
        resp = _run(ec.trip_energy_batch(ITEMS, tenant_id="default"))
        assert resp["connected"] is False
        assert all(e["reason"] == "energy_unreachable" for e in resp["results"])

    def test_partial_response_never_zero(self, monkeypatch):
        body = {"contract_version": "1.0", "results": [
            {"trip_id": "t-1", "availability": "AVAILABLE", "powertrain": "ICE",
             "electric": None, "fuel": {"fuel_liters": {
                 "value": 3.2, "unit": "L", "availability": "AVAILABLE",
                 "measurement_type": "MEASURED", "source": "OBD", "timestamp": "2026-06-01T00:00:00Z"}}}]}
        ec = _patch_real_mode(monkeypatch, _FakeResp(body=body))
        resp = _run(ec.trip_energy_batch(ITEMS, tenant_id="default"))
        assert resp["results"][0]["trip_id"] == "t-1"
        assert resp["results"][0]["fuel"]["fuel_liters"]["value"] == 3.2
        missing = resp["results"][1]
        assert missing["trip_id"] == "t-2"
        assert missing["reason"] == "missing_in_energy_response"
        assert missing["fuel"] is None, "réponse partielle : jamais un 0 inventé"

    def test_malformed_envelope_sanitized(self, monkeypatch):
        body = {"results": [
            {"trip_id": "t-1", "availability": "SOMETHING_WRONG"},
            {"no_trip_id": True}]}
        ec = _patch_real_mode(monkeypatch, _FakeResp(body=body))
        resp = _run(ec.trip_energy_batch(ITEMS, tenant_id="default"))
        assert resp["results"][0]["reason"] == "energy_invalid_response"
        assert resp["results"][1]["reason"] == "missing_in_energy_response"

    def test_tenant_and_vin_transmitted(self, monkeypatch):
        body = {"results": []}
        ec = _patch_real_mode(monkeypatch, _FakeResp(body=body))
        items = [{"trip_id": "t-9", "vehicle_id": "v-9", "vin": None,
                  "navixy_tracker_id": 123, "distance_km": 5.0}]
        _run(ec.trip_energy_batch(items, tenant_id="tenant-xyz"))
        sent = _FakeClient.last_post_kwargs
        assert sent["json"]["tenant_id"] == "tenant-xyz"
        assert sent["headers"].get("X-Tenant-Id") == "tenant-xyz"
        assert "vin" in sent["json"]["trips"][0]
        assert sent["json"]["trips"][0]["navixy_tracker_id"] == 123

    def test_network_refused(self, monkeypatch):
        # Port local fermé — simulation réseau, PAS une URL Energy inventée
        from app import energy_client
        monkeypatch.setenv("ENERGY_API_BASE_URL", "http://127.0.0.1:1")
        monkeypatch.delenv("ENERGY_API_MODE", raising=False)
        resp = _run(energy_client.trip_energy_batch(ITEMS))
        assert resp["connected"] is False
        assert all(e["reason"] == "energy_unreachable" for e in resp["results"])
        status = _run(energy_client.get_status())
        assert status["connected"] is False


# ---------------------------------------------------------------------------
# Priorité centralisée MEASURED > ESTIMATED > REFERENCE > NONE
# ---------------------------------------------------------------------------
class TestConsumptionPriority:
    def _m(self, value, mt, availability="AVAILABLE"):
        return {"value": value, "unit": "L", "availability": availability,
                "measurement_type": mt, "source": "OBD", "timestamp": None}

    def test_measured_wins(self):
        from app.energy_client import best_metric
        best = best_metric(self._m(10, "ESTIMATED"), self._m(9, "MEASURED"),
                           self._m(11, "REFERENCE"))
        assert best["measurement_type"] == "MEASURED" and best["value"] == 9

    def test_estimated_over_reference(self):
        from app.energy_client import best_metric
        best = best_metric(self._m(11, "REFERENCE"), self._m(10, "ESTIMATED"))
        assert best["measurement_type"] == "ESTIMATED"

    def test_none_never_zero(self):
        from app.energy_client import best_metric
        assert best_metric(None) is None
        assert best_metric(self._m(None, "MEASURED")) is None
        assert best_metric(self._m(5, "MEASURED", availability="UNAVAILABLE")) is None

    def test_stale_still_usable_but_flagged(self):
        from app.energy_client import best_metric
        best = best_metric(self._m(7, "MEASURED", availability="STALE"))
        assert best is not None and best["availability"] == "STALE"


# ---------------------------------------------------------------------------
# Fiscalité — les litres legacy doivent être identifiables ESTIMATED partout
# ---------------------------------------------------------------------------
class TestFiscalLabeling:
    def test_legacy_meta_constant(self):
        from app.navixy_sync import LEGACY_FUEL_META, FUEL_L_PER_KM
        assert FUEL_L_PER_KM == 0.085
        assert LEGACY_FUEL_META["measurement_type"] == "ESTIMATED"
        assert LEGACY_FUEL_META["source"] == "LOGITRAK_HISTORICAL"

    def test_pdf_note_constant(self):
        from app.reports import FUEL_ESTIMATED_NOTE
        assert "Estimé" in FUEL_ESTIMATED_NOTE
        assert "8,5 L/100 km" in FUEL_ESTIMATED_NOTE

    def test_dashboard_exposes_fuel_meta(self, admin_h):
        r = requests.get(f"{API}/livre/dashboard", headers=admin_h, timeout=30)
        assert r.status_code == 200
        meta = r.json()["fuel_meta"]
        assert meta["measurement_type"] == "ESTIMATED"
        assert meta["source"] == "LOGITRAK_HISTORICAL"

    def test_trips_expose_fuel_meta(self, admin_h):
        r = requests.get(f"{API}/livre/trips", params={"limit": 1}, headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.json()["fuel_l_meta"]["measurement_type"] == "ESTIMATED"

    def test_csv_export_labeled_estimated(self, admin_h):
        r = requests.get(f"{API}/livre/reports/export",
                         params={"classification": "professional", "fmt": "csv"},
                         headers=admin_h, timeout=60)
        assert r.status_code == 200
        assert "Carburant estimé (L)" in r.content.decode("utf-8-sig", errors="replace")

    def test_swiss_pdf_generates(self, admin_h):
        r = requests.get(f"{API}/livre/reports/tax-swiss", params={"year": 2026},
                         headers=admin_h, timeout=60)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert len(r.content) > 1000

    def test_swiss_pdf_rows_labeled(self):
        import inspect
        from app import reports
        src = inspect.getsource(reports.swiss_tax_report_pdf)
        assert "Estimé*" in src, "les lignes carburant du PDF fiscal doivent porter — Estimé*"
        assert "FUEL_ESTIMATED_NOTE" in src


# ---------------------------------------------------------------------------
# Rapprochement achats vs consommation — MODÈLE préparatoire, AUCUNE alerte
# ---------------------------------------------------------------------------
class TestReconciliationPreview:
    def test_admin_preview_structure(self, admin_h):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
                         headers=admin_h, timeout=60)
        assert r.status_code == 200
        b = r.json()
        assert b["preview"] is True and b["alerting"] == "disabled"
        assert isinstance(b["rows"], list) and b["rows"]
        for row in b["rows"]:
            assert row["purchased"]["liters"] >= 0
            assert row["reliability"] in ("EXPLOITABLE", "INDICATIF", "IMPOSSIBLE")
            if b["mode"] == "not_connected":
                assert row["consumed_fuel"] is None
                assert row["consumption_measurement_type"] == "NONE"
                assert row["gap_l"] is None, "NONE → rapprochement impossible, jamais 0"
                assert row["reliability"] == "IMPOSSIBLE"
        if b["mode"] == "not_connected":
            assert b["connected"] is False

    def test_purchases_present_for_period(self, admin_h):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
                         headers=admin_h, timeout=60)
        total_l = sum(row["purchased"]["liters"] for row in r.json()["rows"])
        assert total_l > 0, "les 28 transactions L existantes doivent apparaître côté achats"

    def test_driver_forbidden(self, driver_h):
        r = requests.get(f"{API}/livre/energy/reconciliation/preview",
                         headers=driver_h, timeout=30)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Fixtures étendues : HEV + powertrain inconnu (unitaires, env monkeypatché)
# ---------------------------------------------------------------------------
class TestExtendedFixtures:
    def test_ten_scenarios_exist(self, monkeypatch):
        monkeypatch.setenv("ENERGY_API_MODE", "fixture")
        from app import energy_client
        found = set()
        for i in range(20000):
            found.add(energy_client.fixture_scenario_index(f"x-{i}"))
            if len(found) == 10:
                break
        assert found == set(range(10))

    def test_hev_and_unknown(self, monkeypatch):
        monkeypatch.setenv("ENERGY_API_MODE", "fixture")
        from app import energy_client
        ids = {}
        i = 0
        while len(ids) < 10 and i < 20000:
            tid = f"x-{i}"
            ids.setdefault(energy_client.fixture_scenario_index(tid), tid)
            i += 1
        resp = _run(energy_client.trip_energy_batch(
            [{"trip_id": ids[8], "distance_km": 50}, {"trip_id": ids[9], "distance_km": 50}]))
        hev, unk = resp["results"]
        assert hev["powertrain"] == "HEV"
        assert hev["electric"]["energy_kwh"]["value"] is not None
        assert hev["fuel"]["fuel_liters"]["value"] is not None
        assert unk["powertrain"] == "UNKNOWN"
        assert unk["electric"] is None and unk["fuel"] is None
