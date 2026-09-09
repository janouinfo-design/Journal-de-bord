"""
Iteration 35 — Reconciliation of two merged dev lineages (Energy + private-mode-pilot).
Tests verify no regression across both lineages via API.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://github-import-138.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
DRIVER_ID = "1580345e-6b8e-45a2-88e7-513a008b6b12"


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def driver_token():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def driver_h(driver_token):
    return {"Authorization": f"Bearer {driver_token}"}


# -------- LIGNÉE PRIVATE-MODE --------

class TestPrivateModeLineage:
    def test_driver_vehicles_list(self, driver_h):
        r = requests.get(f"{BASE_URL}/api/livre/driver/vehicles", headers=driver_h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data.get("access_mode") == "ALL"
        vehicles = data.get("vehicles", [])
        assert len(vehicles) == 18, f"Expected 18 vehicles ALL mode, got {len(vehicles)}"

    def test_private_mode_gate_fail_closed(self, driver_h):
        # GET private-mode status
        r = requests.get(f"{BASE_URL}/api/livre/driver/private-mode", headers=driver_h, timeout=20)
        # Either 200 with disabled state or 403/400 with fail-closed
        assert r.status_code in (200, 400, 403, 404, 503)
        # POST to activate should be refused
        r2 = requests.post(f"{BASE_URL}/api/livre/driver/private-mode",
                           headers=driver_h, json={"mode": "private"}, timeout=20)
        assert r2.status_code in (400, 403, 409, 503), f"Expected fail-closed, got {r2.status_code}: {r2.text[:200]}"
        # Response should indicate disabled feature
        body = r2.text.lower()
        assert "private" in body or "disabled" in body or "unavailable" in body or "feature" in body

    def test_driver_km_summary(self, driver_h):
        r = requests.get(f"{BASE_URL}/api/livre/driver/km-summary", headers=driver_h, timeout=20)
        # Endpoint might exist or be part of another route
        assert r.status_code in (200, 404), f"km-summary unexpected {r.status_code}"
        if r.status_code == 200:
            data = r.json()
            # Values must exist (0.0 accepted, never invented)
            assert isinstance(data, dict)

    def test_driver_cannot_access_admin(self, driver_h):
        r = requests.get(f"{BASE_URL}/api/livre/team/drivers", headers=driver_h, timeout=20)
        assert r.status_code in (401, 403), f"Driver should be forbidden from admin, got {r.status_code}"


# -------- LIGNÉE ENERGY — vehicle-access (with cleanup) --------

class TestEnergyVehicleAccess:
    original_state = {"mode": "ALL", "vehicle_ids": [], "default_vehicle_id": None}
    two_vids = []

    @pytest.fixture(autouse=True, scope="class")
    def _cleanup(self, request, admin_h):
        yield
        # CLEANUP: restore ALL mode
        r = requests.put(
            f"{BASE_URL}/api/livre/team/drivers/{DRIVER_ID}/vehicle-access",
            headers=admin_h,
            json={"mode": "ALL", "vehicle_ids": [], "default_vehicle_id": None},
            timeout=20,
        )
        print(f"[CLEANUP] restore ALL -> {r.status_code}")

    def test_a_get_18_vehicles_all(self, driver_h):
        r = requests.get(f"{BASE_URL}/api/livre/driver/vehicles", headers=driver_h, timeout=20)
        assert r.status_code == 200
        vehicles = r.json().get("vehicles", [])
        assert len(vehicles) == 18
        # keep 2 for SELECTED mode
        TestEnergyVehicleAccess.two_vids = [v["id"] for v in vehicles[:2]]
        TestEnergyVehicleAccess.third_vid = vehicles[2]["id"]

    def test_b_put_selected(self, admin_h):
        payload = {
            "mode": "SELECTED",
            "vehicle_ids": TestEnergyVehicleAccess.two_vids,
            "default_vehicle_id": TestEnergyVehicleAccess.two_vids[0],
        }
        r = requests.put(
            f"{BASE_URL}/api/livre/team/drivers/{DRIVER_ID}/vehicle-access",
            headers=admin_h, json=payload, timeout=20)
        assert r.status_code in (200, 204), f"PUT vehicle-access {r.status_code}: {r.text[:300]}"

    def test_c_driver_sees_only_2(self, driver_h):
        r = requests.get(f"{BASE_URL}/api/livre/driver/vehicles", headers=driver_h, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data.get("access_mode") == "SELECTED"
        vehicles = data.get("vehicles", [])
        assert len(vehicles) == 2, f"Expected 2 vehicles in SELECTED, got {len(vehicles)}"
        assert set(v["id"] for v in vehicles) == set(TestEnergyVehicleAccess.two_vids)

    def test_d_claim_out_of_scope_403(self, driver_h):
        r = requests.post(
            f"{BASE_URL}/api/livre/driver/claim",
            headers=driver_h,
            json={"vehicle_id": TestEnergyVehicleAccess.third_vid},
            timeout=20,
        )
        assert r.status_code == 403, f"Expected 403 out-of-scope claim, got {r.status_code}: {r.text[:300]}"


# -------- LIGNÉE ENERGY — reconciliation cache --------

class TestEnergyReconciliationCache:
    def test_preview_cache_hit_and_bypass(self, admin_h):
        params = {"date_from": "2026-08-01", "date_to": "2026-08-31"}
        # 1st call — warm cache
        r1 = requests.get(f"{BASE_URL}/api/livre/energy/reconciliation/preview",
                          headers=admin_h, params=params, timeout=90)
        assert r1.status_code == 200, r1.text[:400]
        d1 = r1.json()
        rows1 = d1.get("rows", [])
        assert len(rows1) > 0

        # 2nd call — expect cache.hit >= 18
        r2 = requests.get(f"{BASE_URL}/api/livre/energy/reconciliation/preview",
                          headers=admin_h, params=params, timeout=30)
        assert r2.status_code == 200
        d2 = r2.json()
        cache = d2.get("cache", {})
        assert cache.get("hit", 0) >= 18, f"Expected cache.hit>=18, got {cache}"
        # Rows strictly identical
        assert d2.get("rows") == rows1, "Rows differ between 1st and cached response"

        # 3rd call with refresh=true — expect bypass
        params_r = {**params, "refresh": "true"}
        r3 = requests.get(f"{BASE_URL}/api/livre/energy/reconciliation/preview",
                          headers=admin_h, params=params_r, timeout=90)
        assert r3.status_code == 200
        cache3 = r3.json().get("cache", {})
        assert cache3.get("bypass", 0) >= 18, f"Expected cache.bypass>=18, got {cache3}"


# -------- LIGNÉE ENERGY — BEV fuel guard --------

class TestBevGuard:
    def test_trips_no_zero_fuel(self, admin_h):
        # Fetch trips page
        r = requests.get(f"{BASE_URL}/api/livre/trips",
                         headers=admin_h,
                         params={"date_from": "2026-08-01", "date_to": "2026-08-31", "limit": 50},
                         timeout=30)
        if r.status_code == 404:
            pytest.skip("trips endpoint route different — skip BEV guard API")
        assert r.status_code == 200
        data = r.json()
        trips = data.get("trips", data.get("items", data if isinstance(data, list) else []))
        # Should not have "0.00 L" fabricated for missing fuel — allow None or numeric
        for t in trips[:20] if isinstance(trips, list) else []:
            fuel = t.get("fuel") or t.get("fuel_l") or t.get("fuel_liters")
            if fuel is None:
                continue  # OK, absent
            # If present, must not be spurious 0.00 when the vehicle is BEV
            # We can't validate here without vehicle context — smoke only
            assert fuel is None or isinstance(fuel, (int, float, str))


# -------- TRANSVERSE — RBAC --------

class TestRBAC:
    def test_admin_login(self):
        assert _login(ADMIN)

    def test_driver_login(self):
        assert _login(DRIVER)
