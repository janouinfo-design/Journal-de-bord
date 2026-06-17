"""Iteration 5 — Privacy Phase 1: tracker compatibility scan (read-only)."""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-classifier-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def manager_session():
    return _login("manager@logitrak.ch", "manager123")


@pytest.fixture(scope="module")
def driver_session():
    return _login("chauffeur@logitrak.ch", "chauffeur123")


# ---- Access control ----
def test_admin_can_access(admin_session):
    r = admin_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and "counters" in body


def test_manager_can_access(manager_session):
    r = manager_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    assert r.status_code == 200


def test_driver_forbidden(driver_session):
    r = driver_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    assert r.status_code == 403


def test_unauthenticated_401():
    r = requests.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    assert r.status_code == 401


# ---- Schema, counters, row content ----
def test_counters_sum_and_row_schema(admin_session):
    r = admin_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    c = body["counters"]
    assert c["total"] == len(rows)
    assert c["full"] + c["partial"] + c["none"] + c["unknown"] == c["total"]
    assert c["total"] >= 1

    required = {"vehicle_id", "plate", "model", "navixy_tracker_id",
                "status", "family", "recommended_command", "error"}
    for row in rows:
        assert required.issubset(row.keys()), f"Missing keys: {required - set(row.keys())}"
        assert row["status"] in ("full", "partial", "none", "unknown")
        assert isinstance(row["family"], str)


def test_model_classification_mapping(admin_session):
    r = admin_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    body = r.json()
    rows = body["rows"]

    teltonika_subs = ("telfm", "teltonika", "fmc", "fmb")
    smartphone_subs = ("iosnavixy", "navixymobile", "xgps")
    mock_models = {"Mercedes Sprinter", "VW Crafter", "Renault Trafic",
                   "Ford Transit", "Citroën Jumpy", "Iveco Daily"}

    full_count = partial_count = 0
    smartphone_count = 0
    mock_unknown_count = 0

    for row in rows:
        model = (row.get("model") or "").lower()
        # (a) Teltonika family
        if any(sub in model for sub in teltonika_subs):
            assert row["status"] == "full", f"{row['model']} should be full got {row['status']}"
            assert row["family"].startswith("Teltonika"), f"family={row['family']}"
            assert row["recommended_command"] is not None
            assert "setparam" in row["recommended_command"].lower()
            full_count += 1
        # (b) Smartphones
        elif any(sub in model for sub in smartphone_subs):
            assert row["status"] == "none", f"{row['model']} should be none"
            assert "Smartphone" in row["family"], f"family={row['family']}"
            smartphone_count += 1
        # (c) Mock vehicles
        elif row.get("model") in mock_models:
            assert row["status"] == "unknown", f"{row['model']} should be unknown got {row['status']}"
            assert row["family"].startswith("Modèle non répertorié"), f"family={row['family']}"
            mock_unknown_count += 1

    # Sanity: at least some categories present
    assert full_count >= 1, "expected at least 1 Teltonika full"
    # smartphones and mock are optional based on fleet but if present must match


def test_single_vehicle_endpoint(admin_session):
    r = admin_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    rows = r.json()["rows"]
    assert rows
    vid = rows[0]["vehicle_id"]
    r2 = admin_session.get(f"{API}/livre/privacy/tracker-compatibility/{vid}", timeout=20)
    assert r2.status_code == 200
    body = r2.json()
    assert body["vehicle_id"] == vid
    assert body["status"] in ("full", "partial", "none", "unknown")


def test_single_vehicle_404(admin_session):
    r = admin_session.get(f"{API}/livre/privacy/tracker-compatibility/nonexistent-vid-xyz", timeout=20)
    assert r.status_code == 404


# ---- Phase 1 guarantee: idempotent, no side effects ----
def test_no_side_effects_after_two_scans(admin_session):
    # We can't directly read DB, but trips and audit_log are exposed via APIs.
    audit_before = admin_session.get(f"{API}/livre/audit-log?limit=500", timeout=20).json()
    trips_before = admin_session.get(f"{API}/livre/trips?limit=1", timeout=20).json()

    admin_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)
    admin_session.get(f"{API}/livre/privacy/tracker-compatibility", timeout=20)

    audit_after = admin_session.get(f"{API}/livre/audit-log?limit=500", timeout=20).json()
    trips_after = admin_session.get(f"{API}/livre/trips?limit=1", timeout=20).json()

    assert len(audit_before) == len(audit_after), "scan should not write to audit_log"
    # settings_mode shouldn't change
    assert trips_before.get("settings_mode") == trips_after.get("settings_mode")


def test_privacy_scan_module_has_no_outbound_command_imports():
    """Static check: privacy_scan.py must not import or call any command-sending function.

    We only check executable code (imports + non-comment, non-docstring lines).
    """
    import ast
    src_path = "/app/backend/app/privacy_scan.py"
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    tree = ast.parse(src)

    # 1) Check imports — no command-send import allowed
    forbidden_names = ("raw_command_send", "send_command", "send_raw_command", "command_send")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name not in forbidden_names, \
                    f"forbidden import: {alias.name} from {node.module}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(fn in alias.name for fn in forbidden_names), \
                    f"forbidden import: {alias.name}"

    # 2) Strip docstrings and comments, then check no call references a command path
    src_no_docstrings = re.sub(r'"""[\s\S]*?"""', '', src)
    src_no_docstrings = re.sub(r"'''[\s\S]*?'''", '', src_no_docstrings)
    # remove single-line comments
    src_no_comments = "\n".join(
        line.split("#", 1)[0] if line.strip().startswith("#") else line
        for line in src_no_docstrings.splitlines()
    )
    forbidden_runtime = [r"raw_command/send", r"command/send",
                         r"\.send_command\b", r"\braw_command_send\b"]
    for pat in forbidden_runtime:
        assert not re.search(pat, src_no_comments), \
            f"privacy_scan.py runtime code contains forbidden ref: {pat}"
