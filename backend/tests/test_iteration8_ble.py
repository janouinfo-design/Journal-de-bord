"""Iteration 8 — BLE driver identification (Phase A MVP) backend tests.

Covers:
- /api/livre/ble/tags CRUD (admin write, manager read, driver blocked)
- /api/livre/ble/detections ingestion (session, confidence, ignored cases)
- /api/livre/driver/manual-mode (override propagation, errors)
- classify_trip priority cascade (mobile_override > vehicle.mode > geofence > schedule)
- /api/livre/ble/simulate (admin)
- /api/livre/ble/sessions list + amend
- /api/livre/ble/dashboard
- /api/livre/ble/settings GET/PUT
- Privacy invariant non-regression
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


# --------- session fixtures (cookie based auth) ---------
def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="session")
def admin_s():
    return _login(ADMIN)


@pytest.fixture(scope="session")
def manager_s():
    return _login(MANAGER)


@pytest.fixture(scope="session")
def driver_s():
    return _login(DRIVER)


@pytest.fixture(scope="session")
def driver_anon_session():
    """A plain session with no auth — to test unauthenticated access."""
    return requests.Session()


# --------- helpers ---------
@pytest.fixture(scope="session")
def vehicles(admin_s):
    r = admin_s.get(f"{API}/livre/vehicles", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def drivers_list(admin_s):
    r = admin_s.get(f"{API}/livre/drivers", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def audi_vehicle(vehicles):
    for v in vehicles:
        if "AUDI" in (v.get("plate") or "").upper() or "AUDI" in (v.get("model") or "").upper():
            return v
    return vehicles[0]


@pytest.fixture(scope="session")
def driver_record(drivers_list):
    # mock seed: first driver mapped to DRIVER_EMAIL
    target = None
    for d in drivers_list:
        if (d.get("email") or "").lower() == DRIVER["email"].lower():
            target = d
            break
    return target or drivers_list[0]


# ---- 1. BLE Tags CRUD + RBAC ----
class TestBleTagsCRUD:
    def test_admin_upsert_bus35_tag(self, admin_s, audi_vehicle):
        payload = {"vehicle_id": audi_vehicle["id"], "identifier": "BUS35"}
        r = admin_s.post(f"{API}/livre/ble/tags", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["identifier"] == "BUS35"
        assert data["vehicle_id"] == audi_vehicle["id"]
        assert "id" in data

    def test_get_tags_admin(self, admin_s):
        r = admin_s.get(f"{API}/livre/ble/tags", timeout=15)
        assert r.status_code == 200
        tags = r.json()
        assert any(t["identifier"] == "BUS35" for t in tags), "BUS35 not present after upsert"

    def test_get_tags_manager_ok(self, manager_s):
        r = manager_s.get(f"{API}/livre/ble/tags", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_manager_cannot_post_tag(self, manager_s, audi_vehicle):
        r = manager_s.post(f"{API}/livre/ble/tags",
                           json={"vehicle_id": audi_vehicle["id"], "identifier": "TESTX"},
                           timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code}"

    def test_driver_blocked_get_tag(self, driver_s):
        r = driver_s.get(f"{API}/livre/ble/tags", timeout=15)
        assert r.status_code == 403

    def test_admin_delete_then_recreate(self, admin_s, audi_vehicle):
        # create a temp tag
        tmp_id = f"TEST_{uuid.uuid4().hex[:6]}"
        r = admin_s.post(f"{API}/livre/ble/tags",
                         json={"vehicle_id": audi_vehicle["id"], "identifier": tmp_id},
                         timeout=15)
        assert r.status_code == 200, r.text
        tag_id = r.json()["id"]
        rd = admin_s.delete(f"{API}/livre/ble/tags/{tag_id}", timeout=15)
        assert rd.status_code == 200
        # manager cannot delete
        rd2 = admin_s.post(f"{API}/livre/ble/tags",
                           json={"vehicle_id": audi_vehicle["id"], "identifier": tmp_id},
                           timeout=15)
        new_id = rd2.json()["id"]
        # ensure BUS35 still alive at the end
        listing = admin_s.get(f"{API}/livre/ble/tags").json()
        assert any(t["identifier"] == "BUS35" for t in listing)


# ---- 2. Detection ingestion ----
class TestBleDetections:
    def test_driver_send_5_detections_opens_session(self, driver_s):
        results = []
        for i in range(5):
            r = driver_s.post(f"{API}/livre/ble/detections",
                              json={"identifier": "BUS35", "rssi": -60, "platform": "pwa"},
                              timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            res_list = body.get("results") if isinstance(body, dict) else body
            results.extend(res_list)
            time.sleep(0.4)
        last = results[-1]
        assert last.get("ignored") is False, f"unexpected ignored result: {last}"
        assert last.get("confidence", 0) > 0
        sess = last.get("session") or {}
        assert sess.get("status") in ("open", "automatic", "pending", "manual")

    def test_admin_can_see_session(self, admin_s, driver_record):
        r = admin_s.get(f"{API}/livre/ble/sessions", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        # at least one active session for our driver
        mine = [s for s in rows if s.get("driver_id") == driver_record.get("id")]
        assert mine, f"no session for driver {driver_record.get('id')} in {len(rows)} rows"
        s0 = mine[0]
        assert s0.get("driver_name")
        assert s0.get("vehicle_plate") or s0.get("vehicle_model")

    def test_rssi_below_floor_ignored(self, driver_s):
        r = driver_s.post(f"{API}/livre/ble/detections",
                          json={"identifier": "BUS35", "rssi": -95, "platform": "pwa"},
                          timeout=15)
        assert r.status_code == 200
        body = r.json()
        item = (body.get("results") or [{}])[0] if isinstance(body, dict) else body[0]
        assert item.get("ignored") is True
        assert item.get("reason") == "rssi_below_floor"

    def test_unknown_tag_ignored(self, driver_s):
        r = driver_s.post(f"{API}/livre/ble/detections",
                          json={"identifier": "GHOST", "rssi": -50, "platform": "pwa"},
                          timeout=15)
        assert r.status_code == 200
        body = r.json()
        item = (body.get("results") or [{}])[0] if isinstance(body, dict) else body[0]
        assert item.get("ignored") is True
        assert item.get("reason") == "unknown_tag"


# ---- 3. Manual override (driver app PRO / PRIVÉ) ----
class TestDriverManualMode:
    def test_personal_override(self, driver_s):
        r = driver_s.post(f"{API}/livre/driver/manual-mode",
                          json={"mode": "personal"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        sess = body.get("session") or {}
        assert sess.get("mobile_override") == "personal"
        assert sess.get("status") == "manual"

    def test_professional_override(self, driver_s):
        r = driver_s.post(f"{API}/livre/driver/manual-mode",
                          json={"mode": "professional"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        sess = body.get("session") or {}
        assert sess.get("mobile_override") == "professional"

    def test_invalid_mode(self, driver_s):
        r = driver_s.post(f"{API}/livre/driver/manual-mode",
                          json={"mode": "garbage"}, timeout=15)
        assert r.status_code == 400

    def test_disabled_returns_403(self, admin_s, driver_s):
        # disable override globally
        r = admin_s.put(f"{API}/livre/ble/settings",
                        json={"allow_driver_override": False}, timeout=15)
        assert r.status_code == 200
        try:
            r2 = driver_s.post(f"{API}/livre/driver/manual-mode",
                               json={"mode": "personal"}, timeout=15)
            assert r2.status_code == 403, f"expected 403 got {r2.status_code} {r2.text}"
        finally:
            admin_s.put(f"{API}/livre/ble/settings",
                        json={"allow_driver_override": True}, timeout=15)


# ---- 4. classify_trip cascade (unit-level via Python import) ----
class TestClassifyCascade:
    """Tests the deterministic priority cascade directly via the module."""

    def _schedule(self):
        # work Mon-Fri 07-12 13-18 — same as default_schedule
        days = []
        for i in range(7):
            if i < 5:
                days.append({"day": i, "type": "work",
                             "periods": [{"enabled": True, "from": "07:00", "to": "12:00"},
                                         {"enabled": True, "from": "13:00", "to": "18:00"}]})
            else:
                days.append({"day": i, "type": "personal", "periods": []})
        return {"days": days}

    def test_mobile_override_beats_everything(self):
        from app.rules import classify_trip
        trip = {"mobile_override": "personal",
                "start_time": "2026-01-12T10:00:00+00:00",
                "geofence_classification": "professional"}
        vehicle = {"mode": "always_pro"}
        out = classify_trip(trip, vehicle, {}, self._schedule())
        assert out == "personal"

    def test_vehicle_mode_when_no_override(self):
        from app.rules import classify_trip
        trip = {"start_time": "2026-01-12T10:00:00+00:00",
                "geofence_classification": "personal"}
        vehicle = {"mode": "always_pro"}
        assert classify_trip(trip, vehicle, {}, self._schedule()) == "professional"

    def test_geofence_when_no_mobile_and_no_vehicle_mode(self):
        from app.rules import classify_trip
        trip = {"start_time": "2026-01-12T10:00:00+00:00",
                "geofence_classification": "personal"}
        vehicle = {"mode": None}
        assert classify_trip(trip, vehicle, {}, self._schedule()) == "personal"

    def test_schedule_fallback_work_hours(self):
        from app.rules import classify_trip
        trip = {"start_time": "2026-01-12T10:00:00+00:00"}  # Mon 10:00
        vehicle = {"mode": None}
        assert classify_trip(trip, vehicle, {}, self._schedule()) == "professional"

    def test_schedule_fallback_weekend(self):
        from app.rules import classify_trip
        trip = {"start_time": "2026-01-10T10:00:00+00:00"}  # Saturday
        vehicle = {"mode": None}
        assert classify_trip(trip, vehicle, {}, self._schedule()) == "personal"


# ---- 5. /ble/simulate ----
class TestBleSimulate:
    def test_admin_simulate(self, admin_s, driver_record):
        r = admin_s.post(f"{API}/livre/ble/simulate",
                         json={"driver_id": driver_record["id"],
                               "identifier": "BUS35", "rssi": -50},
                         timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ignored") is False
        assert body.get("session", {}).get("driver_id") == driver_record["id"]

    def test_manager_simulate_forbidden(self, manager_s, driver_record):
        r = manager_s.post(f"{API}/livre/ble/simulate",
                           json={"driver_id": driver_record["id"], "identifier": "BUS35"},
                           timeout=15)
        assert r.status_code == 403


# ---- 6. Sessions list + amend + dashboard ----
class TestSessionsAdmin:
    def test_list_sessions_with_filter(self, admin_s):
        r = admin_s.get(f"{API}/livre/ble/sessions?status=manual", timeout=15)
        assert r.status_code == 200
        for s in r.json():
            assert s.get("status") == "manual"

    def test_driver_cannot_list_sessions(self, driver_s):
        r = driver_s.get(f"{API}/livre/ble/sessions", timeout=15)
        assert r.status_code == 403

    def test_amend_session_admin_then_manager(self, admin_s, manager_s, driver_s):
        # get any session
        rows = admin_s.get(f"{API}/livre/ble/sessions").json()
        assert rows, "no sessions in DB"
        sid = rows[0]["id"]
        r = admin_s.put(f"{API}/livre/ble/sessions/{sid}",
                        json={"status": "confirmed"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "confirmed"

        # manager can also amend
        r2 = manager_s.put(f"{API}/livre/ble/sessions/{sid}",
                           json={"status": "manual"}, timeout=15)
        assert r2.status_code == 200, r2.text

        # driver cannot
        r3 = driver_s.put(f"{API}/livre/ble/sessions/{sid}",
                          json={"status": "cancelled"}, timeout=15)
        assert r3.status_code == 403

    def test_dashboard_kpis(self, admin_s):
        r = admin_s.get(f"{API}/livre/ble/dashboard", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_sessions", "auto_identified", "pending_validation",
                  "manual_set", "conflicts", "forced_pro", "forced_perso",
                  "success_rate", "avg_detections_per_session"):
            assert k in d, f"missing key {k}"

    def test_dashboard_driver_forbidden(self, driver_s):
        r = driver_s.get(f"{API}/livre/ble/dashboard", timeout=15)
        assert r.status_code == 403


# ---- 7. Settings GET/PUT ----
class TestBleSettings:
    def test_get_settings_admin(self, admin_s):
        r = admin_s.get(f"{API}/livre/ble/settings", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("ble_enabled", "ble_min_duration_s", "ble_min_rssi",
                  "ble_min_confidence", "allow_driver_override"):
            assert k in d

    def test_get_settings_manager(self, manager_s):
        r = manager_s.get(f"{API}/livre/ble/settings", timeout=15)
        assert r.status_code == 200

    def test_put_settings_manager_forbidden(self, manager_s):
        r = manager_s.put(f"{API}/livre/ble/settings",
                          json={"ble_min_rssi": -80}, timeout=15)
        assert r.status_code == 403


# ---- 8. Privacy invariant (non-regression) ----
class TestPrivacyInvariant:
    def test_masked_mode_keeps_personal_masked(self, admin_s, manager_s):
        # Force masked mode
        r = admin_s.put(f"{API}/livre/settings",
                        json={"mode": "masked"}, timeout=15)
        assert r.status_code == 200, r.text
        try:
            r2 = manager_s.get(f"{API}/livre/trips?classification=personal", timeout=15)
            assert r2.status_code == 200, r2.text
            body = r2.json()
            trips = body if isinstance(body, list) else (body.get("trips") or body.get("items") or [])
            if trips:
                t = trips[0]
                allowed = {"id", "distance_km", "classification", "masked"}
                leak = [k for k in t.keys() if k not in allowed and t.get(k) is not None]
                assert not leak, f"masked personal trip leaks fields: {leak}"
                assert t.get("masked") is True
        finally:
            admin_s.put(f"{API}/livre/settings", json={"mode": "mixte"}, timeout=15)

    def test_ble_sessions_not_masked(self, manager_s):
        r = manager_s.get(f"{API}/livre/ble/sessions", timeout=15)
        assert r.status_code == 200
        for s in r.json():
            # sessions must keep driver/vehicle context even in masked mode
            assert "driver_id" in s


# ---- 9. Driver PWA current-session ----
class TestDriverCurrentSession:
    def test_driver_can_query_current_session(self, driver_s):
        r = driver_s.get(f"{API}/livre/driver/current-session", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session" in body
