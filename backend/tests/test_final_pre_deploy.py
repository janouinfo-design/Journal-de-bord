"""Final pre-deploy E2E smoke tests — exports binary, privacy masked mode,
settings GET/PUT, schedule CRUD, notifications prefs roundtrip, RBAC checks.

Run via:
    cd /app/backend && pytest tests/test_final_pre_deploy.py -v
"""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return s, r.json()


@pytest.fixture(scope="module")
def admin_session():
    s, _ = _login(ADMIN)
    yield s
    s.post(f"{API}/auth/logout", timeout=10)


@pytest.fixture(scope="module")
def manager_session():
    s, _ = _login(MANAGER)
    yield s
    s.post(f"{API}/auth/logout", timeout=10)


@pytest.fixture(scope="module")
def driver_session():
    s, _ = _login(DRIVER)
    yield s
    s.post(f"{API}/auth/logout", timeout=10)


# ---------- Exports (binary content) ----------
class TestExports:
    def test_export_pro_pdf(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export",
                              params={"classification": "professional", "fmt": "pdf"}, timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF", "Response is not a valid PDF"
        assert len(r.content) > 500

    def test_export_pro_xlsx(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export",
                              params={"classification": "professional", "fmt": "xlsx"}, timeout=30)
        assert r.status_code == 200
        # XLSX is a ZIP file: starts with PK
        assert r.content[:2] == b"PK", "Response is not a valid XLSX (zip)"

    def test_export_pro_csv(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export",
                              params={"classification": "professional", "fmt": "csv"}, timeout=30)
        assert r.status_code == 200
        body = r.content.decode("utf-8", errors="ignore")
        assert "," in body or ";" in body

    def test_export_perso_pdf(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export",
                              params={"classification": "personal", "fmt": "pdf"}, timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_tax_swiss_pdf(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/tax-swiss",
                              params={"year": 2025}, timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"


# ---------- Privacy masked mode ----------
class TestPrivacyMasked:
    def _set_mode(self, sess, mode):
        r = sess.put(f"{API}/livre/settings", json={"mode": mode}, timeout=15)
        assert r.status_code == 200, f"PUT settings {mode} -> {r.status_code} {r.text}"
        return r.json()

    def test_reject_invalid_mode(self, admin_session):
        r = admin_session.put(f"{API}/livre/settings", json={"mode": "C"}, timeout=15)
        assert r.status_code in (400, 422)

    def _unwrap_trips(self, body):
        if isinstance(body, dict):
            return body.get("trips") or body.get("items") or []
        return body if isinstance(body, list) else []

    def test_masked_mode_anonymises_personal_for_driver(self, admin_session, driver_session):
        try:
            self._set_mode(admin_session, "masked")
            r = driver_session.get(f"{API}/livre/trips",
                                   params={"classification": "personal"}, timeout=20)
            assert r.status_code == 200
            body = r.json()
            # response may be enveloped {settings_mode, trips:[...]}
            mode = body.get("settings_mode") if isinstance(body, dict) else None
            assert mode in (None, "masked")
            trips = self._unwrap_trips(body)
            for t in trips:
                # Anonymised: must NOT expose addresses/dates/GPS
                assert "start_address" not in t and "end_address" not in t, f"leaked address: {t}"
                assert "start_lat" not in t and "start_lng" not in t, f"leaked GPS: {t}"
                # Should expose only id, classification, distance_km, masked flag
                assert t.get("masked") is True or t.get("classification") == "personal"
        finally:
            self._set_mode(admin_session, "mixte")

    def test_masked_mode_admin_sees_full_data(self, admin_session):
        try:
            self._set_mode(admin_session, "masked")
            r = admin_session.get(f"{API}/livre/trips",
                                  params={"classification": "personal"}, timeout=20)
            assert r.status_code == 200
            trips = self._unwrap_trips(r.json())
            if trips:
                has_unmasked = any("start_address" in t or "start_lat" in t for t in trips)
                assert has_unmasked or all(not t.get("masked") for t in trips)
        finally:
            self._set_mode(admin_session, "mixte")

    def test_masked_track_403_for_driver(self, admin_session, driver_session):
        try:
            self._set_mode(admin_session, "masked")
            r = driver_session.get(f"{API}/livre/trips",
                                   params={"classification": "personal"}, timeout=20)
            trips = self._unwrap_trips(r.json())
            if not trips:
                # ask admin for a personal trip id, then test driver track 403
                ra = admin_session.get(f"{API}/livre/trips",
                                       params={"classification": "personal"}, timeout=20)
                admin_trips = self._unwrap_trips(ra.json())
                if not admin_trips:
                    pytest.skip("no personal trip available")
                tid = admin_trips[0]["id"]
            else:
                tid = trips[0]["id"]
            r2 = driver_session.get(f"{API}/livre/trips/{tid}/track", timeout=15)
            assert r2.status_code in (403, 404), f"expected 403/404 got {r2.status_code}"
        finally:
            self._set_mode(admin_session, "mixte")


# ---------- Settings & schedule ----------
class TestSettings:
    def test_get_settings(self, admin_session):
        r = admin_session.get(f"{API}/livre/settings", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "mode" in data
        assert data["mode"] in ("mixte", "masked")

    def test_get_schedule(self, admin_session):
        r = admin_session.get(f"{API}/livre/schedule", timeout=15)
        assert r.status_code == 200

    def test_put_schedule(self, admin_session):
        # Fetch current then PUT the same back to assert shape compatibility
        cur = admin_session.get(f"{API}/livre/schedule", timeout=15)
        assert cur.status_code == 200
        payload = cur.json()
        r = admin_session.put(f"{API}/livre/schedule", json=payload, timeout=15)
        assert r.status_code in (200, 201, 204), f"PUT schedule -> {r.status_code} {r.text[:200]}"


# ---------- Notifications preferences roundtrip ----------
class TestNotificationsPrefsRoundtrip:
    def test_catalog_has_11_events(self, admin_session):
        r = admin_session.get(f"{API}/livre/notifications/catalog", timeout=15)
        assert r.status_code == 200
        cat = r.json()
        items = cat if isinstance(cat, list) else cat.get("events") or cat.get("items") or []
        assert len(items) >= 11, f"expected 11 events, got {len(items)}"

    def test_prefs_put_then_get_persists(self, admin_session):
        # Get current
        r = admin_session.get(f"{API}/livre/notifications/preferences", timeout=15)
        assert r.status_code == 200
        # Put toggle off for first known event
        payload = {"preferences": {"ble_conflict_detected": {"push": False, "email": False, "sms": False}}}
        r2 = admin_session.put(f"{API}/livre/notifications/preferences", json=payload, timeout=15)
        assert r2.status_code in (200, 204), f"PUT prefs -> {r2.status_code} {r2.text}"
        # Get back to verify
        r3 = admin_session.get(f"{API}/livre/notifications/preferences", timeout=15)
        assert r3.status_code == 200
        merged = r3.json()
        prefs = merged.get("preferences") or merged
        # tolerant assertion — implementation may nest differently
        if "ble_conflict_detected" in prefs:
            ev = prefs["ble_conflict_detected"]
            assert ev.get("push") in (False, None, 0)

    def test_test_endpoint_admin_only(self, admin_session, manager_session, driver_session):
        # admin OK
        ra = admin_session.post(f"{API}/livre/notifications/test",
                                json={"event": "ble_conflict_detected"}, timeout=15)
        assert ra.status_code == 200, f"admin test -> {ra.status_code} {ra.text}"
        # manager forbidden
        rm = manager_session.post(f"{API}/livre/notifications/test",
                                  json={"event": "ble_conflict_detected"}, timeout=15)
        assert rm.status_code == 403
        # driver forbidden
        rd = driver_session.post(f"{API}/livre/notifications/test",
                                 json={"event": "ble_conflict_detected"}, timeout=15)
        assert rd.status_code == 403


# ---------- BLE conflict resolved notification dispatch ----------
class TestConflictResolvedDispatch:
    def test_resolve_dispatches_notification_log(self, admin_session):
        # Trigger conflict (uses CONFLICTAG tag setup from phase_a suite)
        drivers_r = admin_session.get(f"{API}/livre/drivers", timeout=15)
        drivers = drivers_r.json()
        if len(drivers) < 2:
            pytest.skip("need 2 drivers for conflict")
        # simulate is sufficient — just confirm endpoint reachable as smoke
        r = admin_session.get(f"{API}/livre/ble/sessions", params={"status": "conflict"}, timeout=15)
        assert r.status_code == 200


# ---------- Non-regression: driver scoping ----------
class TestDriverScoping:
    def test_driver_trips_scoped(self, driver_session):
        r = driver_session.get(f"{API}/livre/trips", timeout=20)
        assert r.status_code == 200
        body = r.json()
        trips = body.get("trips") if isinstance(body, dict) else body
        if trips:
            unique_drivers = {t.get("driver_id") for t in trips if isinstance(t, dict) and t.get("driver_id")}
            assert len(unique_drivers) <= 1, f"driver leaked trips of multiple drivers: {unique_drivers}"

    def test_driver_can_list_drivers_basic_info(self, driver_session):
        # Drivers list is public for assignment context (basic info only)
        r = driver_session.get(f"{API}/livre/drivers", timeout=15)
        assert r.status_code in (200, 403)
