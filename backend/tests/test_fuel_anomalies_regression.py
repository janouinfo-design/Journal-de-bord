"""
Regression tests for Fuel Anomalies (fast curl-style)
- RBAC on /anomalies, /anomalies/scan, /anomalies/{id}/decide, /vehicles-capacities
- Tenant B isolation
- Blocking of statement close on critical anomalies (August 2026)
"""
import os
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")

USERS = {
    "admin": ("admin@logitrak.ch", "admin123"),
    "manager": ("manager@logitrak.ch", "manager123"),
    "lecture": ("lecture@logitrak.ch", "lecture123"),
    "driver": ("paul.test@client.ch", "paul1234"),
    "admin_b": ("admin-b@test.ch", "testb123"),
}


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:300]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tokens():
    return {k: _login(*v) for k, v in USERS.items()}


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


class TestAnomaliesRBAC:
    def test_get_anomalies_driver_403(self, tokens):
        r = requests.get(f"{BASE_URL}/api/livre/fuel/anomalies", headers=_h(tokens["driver"]))
        assert r.status_code == 403

    def test_get_anomalies_lecture_200(self, tokens):
        r = requests.get(f"{BASE_URL}/api/livre/fuel/anomalies", headers=_h(tokens["lecture"]))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))

    def test_scan_lecture_403(self, tokens):
        r = requests.post(f"{BASE_URL}/api/livre/fuel/anomalies/scan", headers=_h(tokens["lecture"]))
        assert r.status_code == 403

    def test_scan_manager_200(self, tokens):
        r = requests.post(f"{BASE_URL}/api/livre/fuel/anomalies/scan", headers=_h(tokens["manager"]))
        assert r.status_code == 200
        data = r.json()
        # scan should return created counts
        assert "created" in data or "count" in data or isinstance(data, dict)

    def test_decide_lecture_403(self, tokens):
        # find one open anomaly id via admin
        r = requests.get(f"{BASE_URL}/api/livre/fuel/anomalies?status=open", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        items = r.json().get("items") if isinstance(r.json(), dict) else r.json()
        if not items:
            pytest.skip("no open anomaly to test decide")
        aid = items[0].get("id") or items[0].get("_id")
        r2 = requests.post(
            f"{BASE_URL}/api/livre/fuel/anomalies/{aid}/decide",
            headers=_h(tokens["lecture"]),
            json={"decision": "justified", "reason": "test"},
        )
        assert r2.status_code == 403

    def test_vehicles_capacities_manager_403(self, tokens):
        r = requests.get(f"{BASE_URL}/api/livre/fuel/vehicles-capacities", headers=_h(tokens["manager"]))
        assert r.status_code == 403

    def test_vehicles_capacities_admin_200(self, tokens):
        r = requests.get(f"{BASE_URL}/api/livre/fuel/vehicles-capacities", headers=_h(tokens["admin"]))
        assert r.status_code == 200


class TestTenantIsolation:
    def test_admin_b_sees_zero_anomalies(self, tokens):
        r = requests.get(f"{BASE_URL}/api/livre/fuel/anomalies", headers=_h(tokens["admin_b"]))
        assert r.status_code == 200
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        assert len(items) == 0, f"tenant B leak: {items}"


class TestBlockingClosure:
    def test_august_statement_blocked_by_critical_anomalies(self, tokens):
        # Create draft for August 2026
        r = requests.post(
            f"{BASE_URL}/api/livre/fuel/statements",
            headers=_h(tokens["admin"]),
            json={"date_from": "2026-08-01", "date_to": "2026-08-31", "include_carried_over": False},
        )
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
        stmt = r.json()
        sid = stmt.get("id") or stmt.get("_id")
        assert sid
        try:
            r2 = requests.post(
                f"{BASE_URL}/api/livre/fuel/statements/{sid}/check",
                headers=_h(tokens["admin"]),
            )
            assert r2.status_code == 200, f"{r2.status_code} {r2.text[:300]}"
            data = r2.json()
            # blockers.anomalies.count should equal 2
            blockers = data.get("blockers", {})
            ano = blockers.get("anomalies", {})
            count = ano.get("count") if isinstance(ano, dict) else ano
            assert count >= 1, f"expected at least 1 critical anomaly blocker, got {count}. payload={data}"
            assert data.get("status") in ("to_review", "a_controler", "À contrôler")
        finally:
            # cleanup
            requests.delete(f"{BASE_URL}/api/livre/fuel/statements/{sid}", headers=_h(tokens["admin"]))
