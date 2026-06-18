"""Phase A regression suite — auth/refresh, push-token, BLE conflicts & WebSocket.

Run via:
    cd /app/backend && pytest tests/test_phase_a_regression.py -v

Covers (in order):
- /auth/refresh: success, invalid, expired, missing, rotation
- /livre/driver/push-token: register, idempotent update, delete, RBAC
- BLE conflict detection between two drivers on the same vehicle
- Admin /ble/sessions/{id}/resolve — winner kept, loser closed
- RBAC: driver/manager cannot resolve, only admin can
- WebSocket /livre/realtime: receives conflict_detected and conflict_resolved
- Non-regression: /auth/me, /livre/dashboard, /livre/trips, /livre/ble/sessions, /livre/ble/dashboard
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from urllib.parse import urlparse

import jwt
import pytest
import requests
from websocket import create_connection  # websocket-client

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}

JWT_SECRET = os.environ.get("JWT_SECRET")


# ---------- helpers ----------
def _login(creds: dict) -> tuple[requests.Session, dict]:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.status_code} {r.text}"
    return s, r.json()


@pytest.fixture(scope="module")
def admin_pair():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def manager_pair():
    return _login(MANAGER)


@pytest.fixture(scope="module")
def driver_pair():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def admin_s(admin_pair):
    return admin_pair[0]


@pytest.fixture(scope="module")
def manager_s(manager_pair):
    return manager_pair[0]


@pytest.fixture(scope="module")
def driver_s(driver_pair):
    return driver_pair[0]


# ============================================================
# 1. /auth/refresh
# ============================================================
class TestAuthRefresh:
    def test_login_returns_refresh_token(self, driver_pair):
        _, body = driver_pair
        assert body.get("access_token")
        assert body.get("refresh_token"), "login must return refresh_token for native app"
        assert body.get("user", {}).get("email") == DRIVER["email"]

    def test_refresh_with_body_token_succeeds(self, driver_pair):
        _, body = driver_pair
        r = requests.post(
            f"{API}/auth/refresh",
            json={"refresh_token": body["refresh_token"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("access_token")
        assert data.get("refresh_token")
        # token must be a fresh signed JWT for the same user
        assert data["user"]["email"] == DRIVER["email"]

    def test_refresh_rotates_token(self, driver_pair):
        """Two consecutive refreshes must produce two distinct access tokens."""
        _, body = driver_pair
        r1 = requests.post(f"{API}/auth/refresh",
                           json={"refresh_token": body["refresh_token"]}, timeout=15)
        time.sleep(1.1)  # JWT exp resolution is per-second
        r2 = requests.post(f"{API}/auth/refresh",
                           json={"refresh_token": body["refresh_token"]}, timeout=15)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["access_token"] != r2.json()["access_token"]

    def test_refresh_with_invalid_token(self):
        r = requests.post(f"{API}/auth/refresh",
                          json={"refresh_token": "not-a-real-jwt"}, timeout=15)
        assert r.status_code == 401
        assert "invalide" in r.json().get("detail", "").lower()

    def test_refresh_missing_token(self):
        r = requests.post(f"{API}/auth/refresh", json={}, timeout=15)
        assert r.status_code == 401
        assert "manquant" in r.json().get("detail", "").lower()

    def test_refresh_with_expired_token(self):
        """Expired refresh tokens are rejected with 401 'expiré'."""
        if not JWT_SECRET:
            pytest.skip("JWT_SECRET not exposed to test environment")
        # Forge an already-expired refresh token
        expired = jwt.encode(
            {"sub": "fake-user", "type": "refresh", "exp": int(time.time()) - 60},
            JWT_SECRET, algorithm="HS256",
        )
        r = requests.post(f"{API}/auth/refresh",
                          json={"refresh_token": expired}, timeout=15)
        assert r.status_code == 401
        assert "expir" in r.json().get("detail", "").lower()

    def test_refresh_wrong_token_type(self):
        """A token with type='access' must NOT be accepted as refresh."""
        if not JWT_SECRET:
            pytest.skip("JWT_SECRET not exposed to test environment")
        forged = jwt.encode(
            {"sub": "x", "type": "access", "exp": int(time.time()) + 3600},
            JWT_SECRET, algorithm="HS256",
        )
        r = requests.post(f"{API}/auth/refresh",
                          json={"refresh_token": forged}, timeout=15)
        assert r.status_code == 401
        # Either user-not-found OR type-invalid is acceptable
        assert r.json().get("detail")

    def test_access_token_works_after_refresh(self, driver_pair):
        _, body = driver_pair
        r = requests.post(f"{API}/auth/refresh",
                          json={"refresh_token": body["refresh_token"]}, timeout=15)
        assert r.status_code == 200
        new_access = r.json()["access_token"]
        me = requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {new_access}"}, timeout=15)
        assert me.status_code == 200, me.text
        assert me.json()["user"]["email"] == DRIVER["email"]


# ============================================================
# 2. /livre/driver/push-token
# ============================================================
class TestPushToken:
    @pytest.fixture(autouse=True)
    def _cleanup(self, driver_s):
        yield
        # Best-effort: remove tokens created during the test
        try:
            for t in ("ExponentPushToken[REG_AAA]",
                      "ExponentPushToken[REG_BBB]",
                      "ExponentPushToken[OTHER]"):
                driver_s.delete(f"{API}/livre/driver/push-token",
                                params={"token": t}, timeout=10)
        except Exception:
            pass

    def test_register_token_driver(self, driver_s):
        r = driver_s.post(f"{API}/livre/driver/push-token",
                          json={"token": "ExponentPushToken[REG_AAA]",
                                "platform": "ios", "device_id": "dev-1"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"]
        assert d["token"] == "ExponentPushToken[REG_AAA]"
        assert d["active"]

    def test_register_idempotent_update(self, driver_s):
        # First register
        driver_s.post(f"{API}/livre/driver/push-token",
                      json={"token": "ExponentPushToken[REG_BBB]",
                            "platform": "ios"}, timeout=15)
        # Re-register same token, different platform
        r = driver_s.post(f"{API}/livre/driver/push-token",
                          json={"token": "ExponentPushToken[REG_BBB]",
                                "platform": "android"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["active"]

    def test_register_token_invalid_short(self, driver_s):
        r = driver_s.post(f"{API}/livre/driver/push-token",
                          json={"token": "x"}, timeout=15)
        assert r.status_code == 400

    def test_unauthenticated_rejected(self):
        r = requests.post(f"{API}/livre/driver/push-token",
                          json={"token": "ExponentPushToken[ANY]"}, timeout=15)
        assert r.status_code == 401

    def test_delete_token(self, driver_s):
        driver_s.post(f"{API}/livre/driver/push-token",
                      json={"token": "ExponentPushToken[REG_AAA]",
                            "platform": "ios"}, timeout=15)
        r = driver_s.delete(f"{API}/livre/driver/push-token",
                            params={"token": "ExponentPushToken[REG_AAA]"}, timeout=15)
        assert r.status_code == 200

    def test_delete_unknown_token_404(self, driver_s):
        r = driver_s.delete(f"{API}/livre/driver/push-token",
                            params={"token": "ExponentPushToken[NOPE_404]"}, timeout=15)
        assert r.status_code == 404

    def test_admin_can_also_register(self, admin_s):
        r = admin_s.post(f"{API}/livre/driver/push-token",
                        json={"token": "ExponentPushToken[OTHER]",
                              "platform": "expo"}, timeout=15)
        assert r.status_code == 200
        admin_s.delete(f"{API}/livre/driver/push-token",
                       params={"token": "ExponentPushToken[OTHER]"}, timeout=10)


# ============================================================
# 3. BLE conflict detection (two drivers on the same vehicle)
# ============================================================
@pytest.fixture(scope="module")
def vehicles(admin_s):
    r = admin_s.get(f"{API}/livre/vehicles", timeout=15)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def drivers_list(admin_s):
    r = admin_s.get(f"{API}/livre/drivers", timeout=15)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def conflict_vehicle(admin_s, vehicles):
    """Pick a vehicle and ensure it has a BLE tag CONFLICTAG bound to it."""
    v = vehicles[0]
    admin_s.post(f"{API}/livre/ble/tags",
                 json={"vehicle_id": v["id"], "identifier": "CONFLICTAG"}, timeout=15)
    return v


@pytest.fixture(scope="module")
def two_drivers(drivers_list):
    if len(drivers_list) < 2:
        pytest.skip("Mock data must include at least 2 drivers")
    return drivers_list[0], drivers_list[1]


class TestBleConflict:
    def test_admin_can_simulate_two_drivers_on_same_vehicle(
        self, admin_s, conflict_vehicle, two_drivers,
    ):
        d1, d2 = two_drivers
        # Inject 3 strong detections per driver on the same tag,
        # close in time, equal RSSI → should trigger conflict.
        for _ in range(3):
            r1 = admin_s.post(f"{API}/livre/ble/simulate",
                              json={"driver_id": d1["id"],
                                    "identifier": "CONFLICTAG",
                                    "rssi": -55}, timeout=15)
            r2 = admin_s.post(f"{API}/livre/ble/simulate",
                              json={"driver_id": d2["id"],
                                    "identifier": "CONFLICTAG",
                                    "rssi": -55}, timeout=15)
            assert r1.status_code == 200 and r2.status_code == 200
            time.sleep(0.2)

    def test_conflict_flagged_on_sessions(self, admin_s, two_drivers):
        # Allow a brief moment for the conflict-detection coroutine to settle
        time.sleep(0.5)
        r = admin_s.get(f"{API}/livre/ble/sessions?status=conflict&limit=100",
                        timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        d1, d2 = two_drivers
        involved = [s for s in rows
                    if s.get("driver_id") in (d1["id"], d2["id"])]
        assert involved, f"expected at least one session in conflict for {d1['id']}/{d2['id']}"

    def test_manager_cannot_resolve(self, manager_s, admin_s, two_drivers):
        rows = admin_s.get(f"{API}/livre/ble/sessions?status=conflict&limit=100").json()
        if not rows:
            pytest.skip("no conflict session to resolve")
        sid = rows[0]["id"]
        d1, _ = two_drivers
        r = manager_s.post(f"{API}/livre/ble/sessions/{sid}/resolve",
                           json={"winner_driver_id": d1["id"]}, timeout=15)
        assert r.status_code == 403, f"manager must NOT resolve, got {r.status_code}"

    def test_driver_cannot_resolve(self, driver_s, admin_s, two_drivers):
        rows = admin_s.get(f"{API}/livre/ble/sessions?status=conflict&limit=100").json()
        if not rows:
            pytest.skip("no conflict session to resolve")
        sid = rows[0]["id"]
        d1, _ = two_drivers
        r = driver_s.post(f"{API}/livre/ble/sessions/{sid}/resolve",
                          json={"winner_driver_id": d1["id"]}, timeout=15)
        assert r.status_code == 403

    def test_admin_resolves_conflict(self, admin_s, two_drivers):
        rows = admin_s.get(f"{API}/livre/ble/sessions?status=conflict&limit=100").json()
        if not rows:
            pytest.skip("no conflict session to resolve")
        d1, _ = two_drivers
        d1_conflicts = [s for s in rows if s.get("driver_id") == d1["id"]]
        if not d1_conflicts:
            pytest.skip("no conflict session owned by d1")
        # Pass any d1 conflict session id; the engine resolves by (vehicle_id, winner)
        sid = d1_conflicts[0]["id"]

        r = admin_s.post(f"{API}/livre/ble/sessions/{sid}/resolve",
                         json={"winner_driver_id": d1["id"], "source": "header_inbox"},
                         timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        winner_id = body.get("winner_session_id")
        assert winner_id, "API must return winner_session_id"
        assert body.get("final_status") in ("confirmed", "pending", "manual")

        # The winning session must now be visible with the resolved fields populated
        listed = admin_s.get(f"{API}/livre/ble/sessions?limit=500", timeout=15).json()
        winner = next((s for s in listed if s["id"] == winner_id), None)
        assert winner, "winning session must remain visible"
        assert winner.get("driver_id") == d1["id"]
        assert winner.get("status") in ("confirmed", "pending", "manual")
        assert winner.get("resolved_by")
        assert winner.get("resolved_winner") == d1["id"]

    def test_resolve_missing_winner_returns_400(self, admin_s):
        rows = admin_s.get(f"{API}/livre/ble/sessions?limit=10").json()
        if not rows:
            pytest.skip("no sessions")
        sid = rows[0]["id"]
        r = admin_s.post(f"{API}/livre/ble/sessions/{sid}/resolve",
                         json={}, timeout=15)
        assert r.status_code == 400


# ============================================================
# 4. WebSocket /livre/realtime
# ============================================================
def _ws_url() -> str:
    parsed = urlparse(BASE_URL)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/api/livre/realtime"


@contextmanager
def _ws(session: requests.Session, timeout: float = 4.0):
    """Open a cookie-authenticated WebSocket. Closes on exit."""
    cookies = session.cookies.get_dict()
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    ws = create_connection(_ws_url(),
                           header=[f"Cookie: {cookie_header}"],
                           timeout=timeout)
    try:
        yield ws
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _drain_until(ws, want_type: str, max_seconds: float = 8.0):
    """Read messages until we see one of `want_type` or time out."""
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        try:
            ws.settimeout(deadline - time.time())
            raw = ws.recv()
        except Exception:
            return None
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if msg.get("type") == want_type:
            return msg
    return None


class TestRealtimeWebSocket:
    def test_unauthenticated_ws_closes(self):
        try:
            ws = create_connection(_ws_url(), timeout=4.0)
            ws.close()
            pytest.fail("WS should refuse unauthenticated handshake")
        except Exception:
            # Either rejected during handshake or auto-closed → acceptable
            pass

    def test_admin_receives_conflict_detected(
        self, admin_s, conflict_vehicle, two_drivers,
    ):
        d1, d2 = two_drivers
        with _ws(admin_s) as ws:
            # consume hello
            try:
                ws.settimeout(2.0)
                ws.recv()  # hello
            except Exception:
                pass

            # Trigger fresh conflict
            for _ in range(3):
                admin_s.post(f"{API}/livre/ble/simulate",
                             json={"driver_id": d1["id"],
                                   "identifier": "CONFLICTAG",
                                   "rssi": -55}, timeout=15)
                admin_s.post(f"{API}/livre/ble/simulate",
                             json={"driver_id": d2["id"],
                                   "identifier": "CONFLICTAG",
                                   "rssi": -55}, timeout=15)
                time.sleep(0.15)

            msg = _drain_until(ws, "conflict_detected", max_seconds=10.0)
            assert msg is not None, "expected conflict_detected event"
            assert msg["data"].get("vehicle_id") == conflict_vehicle["id"]
            drivers_in_event = msg["data"].get("drivers") or []
            assert set([d1["id"], d2["id"]]).issubset(set(drivers_in_event)), \
                f"both drivers should appear in event, got {drivers_in_event}"

    def test_admin_receives_conflict_resolved(self, admin_s, two_drivers):
        d1, _ = two_drivers
        # Find a still-conflicting session OWNED BY d1 (the future winner)
        def _find_d1_conflict():
            rows = admin_s.get(
                f"{API}/livre/ble/sessions?status=conflict&limit=100", timeout=15,
            ).json()
            return next((s for s in rows if s.get("driver_id") == d1["id"]), None)

        target = _find_d1_conflict()
        if not target:
            # Re-trigger a conflict to have something to resolve
            d1_again, d2 = two_drivers
            for _ in range(3):
                admin_s.post(f"{API}/livre/ble/simulate",
                             json={"driver_id": d1_again["id"],
                                   "identifier": "CONFLICTAG",
                                   "rssi": -55}, timeout=15)
                admin_s.post(f"{API}/livre/ble/simulate",
                             json={"driver_id": d2["id"],
                                   "identifier": "CONFLICTAG",
                                   "rssi": -55}, timeout=15)
                time.sleep(0.15)
            time.sleep(0.5)
            target = _find_d1_conflict()
        if not target:
            pytest.skip("could not produce a conflict involving d1")
        sid = target["id"]

        with _ws(admin_s) as ws:
            try:
                ws.settimeout(2.0)
                ws.recv()
            except Exception:
                pass
            r = admin_s.post(f"{API}/livre/ble/sessions/{sid}/resolve",
                             json={"winner_driver_id": d1["id"]}, timeout=15)
            assert r.status_code == 200, r.text

            msg = _drain_until(ws, "conflict_resolved", max_seconds=10.0)
            assert msg is not None, "expected conflict_resolved event"
            assert msg["data"].get("winner_driver_id") == d1["id"]
            assert msg["data"].get("winner_session_id"), "event must include winner_session_id"


# ============================================================
# 5. Non-regression: existing endpoints still work
# ============================================================
class TestNonRegression:
    def test_auth_me(self, admin_s):
        r = admin_s.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["email"] == ADMIN["email"]

    def test_livre_dashboard(self, admin_s):
        r = admin_s.get(f"{API}/livre/dashboard", timeout=15)
        assert r.status_code == 200
        d = r.json()
        # Heuristic: should expose at least some KPI keys
        assert isinstance(d, dict)
        assert len(d) > 0

    def test_livre_trips(self, admin_s):
        r = admin_s.get(f"{API}/livre/trips?classification=professional", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, (list, dict))

    def test_livre_drivers(self, admin_s):
        r = admin_s.get(f"{API}/livre/drivers", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_livre_vehicles(self, admin_s):
        r = admin_s.get(f"{API}/livre/vehicles", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_ble_sessions_admin(self, admin_s):
        r = admin_s.get(f"{API}/livre/ble/sessions?limit=10", timeout=15)
        assert r.status_code == 200

    def test_ble_dashboard(self, admin_s):
        r = admin_s.get(f"{API}/livre/ble/dashboard", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_sessions", "conflicts", "success_rate"):
            assert k in d

    def test_driver_current_session_still_works(self, driver_s):
        r = driver_s.get(f"{API}/livre/driver/current-session", timeout=15)
        assert r.status_code == 200
        assert "session" in r.json()

    def test_driver_manual_mode_still_works(self, driver_s):
        r = driver_s.post(f"{API}/livre/driver/manual-mode",
                          json={"mode": "professional"}, timeout=15)
        # 200 nominal; 403 if allow_driver_override was disabled by another test;
        # 404 if the engine could not find an open session at that exact moment.
        assert r.status_code in (200, 403, 404)

    def test_logout_then_me_returns_401(self):
        s, _ = _login(DRIVER)
        # Logout (clears cookies + deactivates push tokens)
        s.post(f"{API}/auth/logout", timeout=15)
        r = s.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401
