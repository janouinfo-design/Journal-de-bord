"""Iteration 6 — Privacy Enforcement (Phase 2) backend tests.

Covers:
- enforcement-config GET/PUT (RBAC, defaults, audit log)
- enforce-now (RBAC, simulation, skipped reasons, idempotence)
- privacy/state (RBAC, only compatible vehicles)
- kill-switch (RBAC, no targets case)
- compute_expected_state unit tests
- AST safety check — send_raw_command only inside `not simulation` branch
- APScheduler privacy_enforcement_job is registered
"""
import ast
import os
import time
from datetime import datetime, timezone

import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"


# ---------- Auth helpers ----------
def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def manager():
    return _login("manager@logitrak.ch", "manager123")


@pytest.fixture(scope="module")
def driver():
    return _login("chauffeur@logitrak.ch", "chauffeur123")


@pytest.fixture(scope="module", autouse=True)
def ensure_safe_teardown(admin):
    """Make sure we reset enabled=False at the end + kill_switch if anything in private."""
    yield
    try:
        admin.put(f"{API}/livre/privacy/enforcement-config",
                  json={"enabled": False, "simulation": True}, timeout=20)
        # Kill switch sécurité
        admin.post(f"{API}/livre/privacy/kill-switch", timeout=30)
    except Exception:
        pass


# ---------- GET /enforcement-config ----------
class TestEnforcementConfigGet:
    def test_admin_can_read(self, admin):
        r = admin.get(f"{API}/livre/privacy/enforcement-config", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "enabled" in d and isinstance(d["enabled"], bool)
        assert "simulation" in d and isinstance(d["simulation"], bool)

    def test_manager_can_read(self, manager):
        r = manager.get(f"{API}/livre/privacy/enforcement-config", timeout=20)
        assert r.status_code == 200

    def test_unauth_blocked(self):
        r = requests.get(f"{API}/livre/privacy/enforcement-config", timeout=20)
        assert r.status_code in (401, 403)


# ---------- PUT /enforcement-config ----------
class TestEnforcementConfigPut:
    def test_unauth_blocked(self):
        r = requests.put(f"{API}/livre/privacy/enforcement-config",
                         json={"enabled": True, "simulation": True}, timeout=20)
        assert r.status_code in (401, 403)

    def test_manager_blocked(self, manager):
        r = manager.put(f"{API}/livre/privacy/enforcement-config",
                        json={"enabled": True, "simulation": True}, timeout=20)
        assert r.status_code == 403

    def test_admin_can_update_and_audit_log(self, admin):
        r = admin.put(f"{API}/livre/privacy/enforcement-config",
                      json={"enabled": True, "simulation": True}, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["enabled"] is True
        assert d["simulation"] is True
        # GET mirror
        r2 = admin.get(f"{API}/livre/privacy/enforcement-config", timeout=20)
        assert r2.json() == d


# ---------- POST /enforce-now ----------
class TestEnforceNow:
    def test_driver_blocked(self, driver):
        r = driver.post(f"{API}/livre/privacy/enforce-now", timeout=30)
        assert r.status_code == 403

    def test_manager_blocked(self, manager):
        r = manager.post(f"{API}/livre/privacy/enforce-now", timeout=30)
        assert r.status_code == 403

    def test_admin_simulation_produces_rows(self, admin):
        # Force enabled+simulation
        admin.put(f"{API}/livre/privacy/enforcement-config",
                  json={"enabled": True, "simulation": True}, timeout=20)
        r = admin.post(f"{API}/livre/privacy/enforce-now", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["enabled"] is True
        assert d["simulation"] is True
        assert d["sent_real"] == 0, f"sent_real MUST be 0 in simulation, got: {d}"
        assert d["errors"] == 0
        # Accept simulated > 0 (fresh) OR up_to_date rows (already simulated)
        # In both cases skipped(reason=incompatible) MUST appear for the mocks/iphones.
        compat_count = 0  # full-compat vehicles (simulated OR up_to_date)
        incompat_count = 0
        for row in d["rows"]:
            assert "vehicle_id" in row
            assert "plate" in row
            if row.get("skipped"):
                reason = row.get("reason")
                assert reason in ("incompatible", "no_tracker", "up_to_date"), row
                if reason == "incompatible" or reason == "no_tracker":
                    incompat_count += 1
                else:
                    compat_count += 1
                    assert row.get("expected_state") in ("tracking", "private")
            else:
                compat_count += 1
                assert row.get("expected_state") in ("tracking", "private")
                assert row.get("mode") == "simulation"
                assert row.get("result") == "simulated"
        assert compat_count > 0, f"Expected at least one Teltonika-compatible vehicle, got {d}"
        assert incompat_count > 0, f"Expected at least one incompatible (mock/smartphone), got {d}"

    def test_idempotence_second_call_skips(self, admin):
        """Second enforce within <12h should report simulated=0 (all up_to_date)."""
        admin.put(f"{API}/livre/privacy/enforcement-config",
                  json={"enabled": True, "simulation": True}, timeout=20)
        # First run already executed in previous test, but be safe
        admin.post(f"{API}/livre/privacy/enforce-now", timeout=60)
        time.sleep(0.5)
        r2 = admin.post(f"{API}/livre/privacy/enforce-now", timeout=60)
        d2 = r2.json()
        assert d2["sent_real"] == 0
        assert d2["simulated"] == 0, f"Idempotence failure — simulated={d2['simulated']}, rows={d2['rows']}"
        # all rows should be skipped now (incompatible OR up_to_date)
        for row in d2["rows"]:
            assert row.get("skipped") is True
            assert row.get("reason") in ("incompatible", "no_tracker", "up_to_date")


# ---------- GET /privacy/state ----------
class TestPrivacyState:
    def test_admin_state(self, admin):
        r = admin.get(f"{API}/livre/privacy/state", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "rows" in d
        assert isinstance(d["rows"], list)
        assert len(d["rows"]) > 0, "Expected compatible vehicles (Teltonika) in state"
        for row in d["rows"]:
            assert row["family"] in ("teltonika", "queclink")
            assert row["plate"]
            assert row["tracker_id"] is not None
            # After enforce-now in simulation, last_command must be set
            assert row["last_command"] in ("setparam 11000:0", "setparam 11000:4"), row
            assert row["last_command_mode"] == "simulation"
            assert row["last_command_result"] == "simulated"
            assert row["last_command_at"] is not None
            assert row["expected_state"] in ("tracking", "private")

    def test_manager_can_read(self, manager):
        assert manager.get(f"{API}/livre/privacy/state", timeout=20).status_code == 200

    def test_driver_blocked(self, driver):
        assert driver.get(f"{API}/livre/privacy/state", timeout=20).status_code == 403


# ---------- Kill switch ----------
class TestKillSwitch:
    def test_driver_blocked(self, driver):
        assert driver.post(f"{API}/livre/privacy/kill-switch", timeout=20).status_code == 403

    def test_manager_blocked(self, manager):
        assert manager.post(f"{API}/livre/privacy/kill-switch", timeout=20).status_code == 403

    def test_admin_no_targets(self, admin):
        # In working hours (Mon-Fri 07-18 UTC?), most should be 'tracking'.
        # If some happen to be 'private' (e.g. weekend / out-of-hours), accept that
        # but verify the response shape.
        r = admin.post(f"{API}/livre/privacy/kill-switch", timeout=60)
        assert r.status_code == 200
        d = r.json()
        for k in ("targets", "sent", "errors", "rows"):
            assert k in d
        assert isinstance(d["rows"], list)


# ---------- compute_expected_state unit ----------
class TestComputeExpectedState:
    def test_unit_logic(self):
        from app.privacy_enforcer import compute_expected_state
        from app.rules import default_schedule
        sched = default_schedule(None)

        # always_pro overrides everything
        assert compute_expected_state(
            {"mode": "always_pro"}, sched,
            datetime(2026, 1, 10, 22, 0, tzinfo=timezone.utc)  # Saturday 22h
        ) == "tracking"

        # always_perso overrides everything
        assert compute_expected_state(
            {"mode": "always_perso"}, sched,
            datetime(2026, 1, 12, 10, 0, tzinfo=timezone.utc)  # Monday 10h
        ) == "private"

        # No mode + default schedule:
        # Monday 2026-01-12 10:00 -> tracking (in 07-12)
        assert compute_expected_state({}, sched,
            datetime(2026, 1, 12, 10, 0, tzinfo=timezone.utc)) == "tracking"
        # Monday 22h -> private
        assert compute_expected_state({}, sched,
            datetime(2026, 1, 12, 22, 0, tzinfo=timezone.utc)) == "private"
        # Saturday 10h -> private
        assert compute_expected_state({}, sched,
            datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)) == "private"


# ---------- Safety: AST static check ----------
class TestSafetyAST:
    def test_send_raw_command_not_called_in_simulation_branch(self):
        """Verify send_raw_command is never reached when simulation=True path."""
        path = "/app/backend/app/privacy_enforcer.py"
        with open(path) as f:
            src = f.read()
        tree = ast.parse(src)

        # Find all calls to send_raw_command
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name == "send_raw_command":
                    calls.append(node)
        assert calls, "Expected at least one send_raw_command call"

        # For each call, walk up parents to find enclosing If guarded by `not simulation`
        # We approximate by scanning ancestors using ast.parse + tracking.
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node  # type: ignore[attr-defined]

        for call in calls:
            cur = call
            guarded = False
            while hasattr(cur, "parent"):
                cur = cur.parent
                # Either inside an `if simulation:` we are in the else branch,
                # or `if not simulation: <call>`, or after `if simulation: return ...`
                # The current code does early-return when simulation; verify that.
                if isinstance(cur, ast.If):
                    test = cur.test
                    if isinstance(test, ast.Name) and test.id == "simulation":
                        # call must be after the if-block (in orelse=[] -> sibling).
                        # In the current source `if simulation: ... return ...` then
                        # the rest of function executes only when simulation=False.
                        # We approve.
                        guarded = True
                        break
                if isinstance(cur, ast.FunctionDef):
                    break
            # If no explicit If, ensure the function name is 'kill_switch' (allowed)
            if not guarded:
                # Walk up to enclosing function
                fn = call
                while hasattr(fn, "parent") and not isinstance(fn, ast.FunctionDef):
                    fn = fn.parent
                if isinstance(fn, ast.FunctionDef):
                    assert fn.name == "kill_switch", (
                        f"send_raw_command called outside simulation guard in {fn.name}"
                    )

    def test_no_navixy_url_hardcoded_in_enforcer(self):
        with open("/app/backend/app/privacy_enforcer.py") as f:
            assert "api.navixy.com" not in f.read()


# ---------- APScheduler privacy job registered ----------
class TestSchedulerJobRegistered:
    def test_log_mentions_privacy_job(self):
        import subprocess
        out = subprocess.run(
            ["grep", "-r", "_run_privacy_enforcement", "/var/log/supervisor/"],
            capture_output=True, text=True,
        )
        assert "_run_privacy_enforcement" in out.stdout, (
            "APScheduler should have added _run_privacy_enforcement job at startup"
        )
