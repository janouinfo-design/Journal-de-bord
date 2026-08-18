"""Multi-tenant isolation + Super-Admin API tests (iteration 13)."""
import os
import uuid
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"

SUPER = {"email": "superadmin@logitrak.ch", "password": os.environ["SUPERADMIN_PASSWORD"]}
ADMIN_A = {"email": "admin@logitrak.ch", "password": "admin123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}


def _login(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {creds['email']} -> {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok, tenant=None):
    h = {"Authorization": f"Bearer {tok}"}
    if tenant:
        h["X-Tenant-Id"] = tenant
    return h


@pytest.fixture(scope="module")
def super_tok():
    return _login(SUPER)


@pytest.fixture(scope="module")
def admin_a_tok():
    return _login(ADMIN_A)


@pytest.fixture(scope="module")
def admin_b_tok():
    return _login(ADMIN_B)


# ---------- Auth / me ----------
def test_superadmin_me_has_role():
    tok = _login(SUPER)
    r = requests.get(f"{BASE}/auth/me", headers=_h(tok))
    assert r.status_code == 200
    j = r.json()
    j = j.get("user", j)
    assert j["role"] == "superadmin"


def test_bad_login_creates_audit(super_tok):
    r = requests.post(f"{BASE}/auth/login", json={"email": "admin@logitrak.ch", "password": "WRONG"})
    assert r.status_code in (400, 401)
    # good login too (already done in fixture)
    r2 = requests.get(f"{BASE}/admin/audit", params={"action": "auth.login"}, headers=_h(super_tok))
    assert r2.status_code == 200
    rows = r2.json()
    actions = {row["action"] for row in rows}
    assert "auth.login" in actions
    assert "auth.login_failed" in actions


# ---------- Super-admin API ----------
def test_admin_tenants_list(super_tok):
    r = requests.get(f"{BASE}/admin/tenants", headers=_h(super_tok))
    assert r.status_code == 200
    tenants = r.json()
    ids = {t["id"] for t in tenants}
    assert "default" in ids
    names = {t["name"] for t in tenants}
    assert any("Test B" in n or "test b" in n.lower() for n in names)
    # stats present
    for t in tenants:
        assert "stats" in t and "users" in t["stats"]


def test_admin_tenants_forbidden_for_normal_admin(admin_a_tok):
    r = requests.get(f"{BASE}/admin/tenants", headers=_h(admin_a_tok))
    assert r.status_code == 403


def test_admin_users_forbidden_for_normal_admin(admin_a_tok):
    r = requests.get(f"{BASE}/admin/users", headers=_h(admin_a_tok))
    assert r.status_code == 403


def test_tenant_create_edit_and_default_cannot_be_suspended(super_tok):
    # Create
    name = f"TEST_Tenant_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{BASE}/admin/tenants", json={"name": name}, headers=_h(super_tok))
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    # Edit name
    r2 = requests.patch(f"{BASE}/admin/tenants/{tid}",
                        json={"name": name + "_edited"}, headers=_h(super_tok))
    assert r2.status_code == 200
    assert r2.json()["name"].endswith("_edited")
    # Suspend
    r3 = requests.patch(f"{BASE}/admin/tenants/{tid}",
                        json={"status": "suspended"}, headers=_h(super_tok))
    assert r3.status_code == 200
    assert r3.json()["status"] == "suspended"
    # Reactivate
    r4 = requests.patch(f"{BASE}/admin/tenants/{tid}",
                        json={"status": "active"}, headers=_h(super_tok))
    assert r4.status_code == 200 and r4.json()["status"] == "active"
    # Default tenant cannot be suspended
    r5 = requests.patch(f"{BASE}/admin/tenants/default",
                        json={"status": "suspended"}, headers=_h(super_tok))
    assert r5.status_code == 400


def test_admin_users_crud(super_tok):
    email = f"test_user_{uuid.uuid4().hex[:6]}@test.ch"
    # find default tenant
    tenants = requests.get(f"{BASE}/admin/tenants", headers=_h(super_tok)).json()
    default_id = next(t["id"] for t in tenants if t["id"] == "default")
    # create
    r = requests.post(f"{BASE}/admin/users",
                      json={"email": email, "password": "pw123456", "name": "Test User",
                            "role": "driver", "tenant_id": default_id},
                      headers=_h(super_tok))
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    # patch role
    r2 = requests.patch(f"{BASE}/admin/users/{uid}",
                        json={"role": "manager"}, headers=_h(super_tok))
    assert r2.status_code == 200 and r2.json()["role"] == "manager"
    # delete
    r3 = requests.delete(f"{BASE}/admin/users/{uid}", headers=_h(super_tok))
    assert r3.status_code == 200 and r3.json()["deleted"] is True


def test_superadmin_cannot_be_deleted(super_tok):
    users = requests.get(f"{BASE}/admin/users", headers=_h(super_tok)).json()
    sa = next(u for u in users if u["role"] == "superadmin")
    r = requests.delete(f"{BASE}/admin/users/{sa['id']}", headers=_h(super_tok))
    assert r.status_code == 400


# ---------- Isolation ----------
def test_isolation_fines_admin_b_sees_only_own(admin_b_tok):
    r = requests.get(f"{BASE}/livre/fines", headers=_h(admin_b_tok))
    assert r.status_code == 200
    data = r.json()
    items = data.get("rows", data.get("items", data if isinstance(data, list) else []))
    # Admin B has 0 or 1 fine (TEST-B-001)
    assert len(items) <= 1
    for f in items:
        # Verify no logitrak fine ids
        assert f.get("tenant_id") != "default"


def test_isolation_users_admin_b_sees_only_own(admin_b_tok):
    r = requests.get(f"{BASE}/auth/users", headers=_h(admin_b_tok))
    if r.status_code == 404:
        pytest.skip("no /auth/users endpoint")
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        users = r.json()
        emails = {u["email"] for u in users}
        assert "admin@logitrak.ch" not in emails
        assert all("logitrak.ch" not in e or e == "admin-b@test.ch" for e in emails)


def test_admin_a_still_sees_all_data(admin_a_tok):
    # 4627 trips exact-ish, 5 fines
    r = requests.get(f"{BASE}/livre/fines", headers=_h(admin_a_tok))
    assert r.status_code == 200
    data = r.json()
    items = data.get("rows", data.get("items", data if isinstance(data, list) else []))
    assert len(items) >= 5, f"Expected >=5 fines for Logitrak, got {len(items)}"

    r2 = requests.get(f"{BASE}/livre/dashboard", headers=_h(admin_a_tok))
    assert r2.status_code == 200
    dash = r2.json()
    # sanity: contains some numeric KPI
    assert isinstance(dash, dict) and len(dash) > 0


def test_direct_access_to_other_tenant_fine_returns_404(admin_a_tok, admin_b_tok):
    # Get one Logitrak fine id
    r = requests.get(f"{BASE}/livre/fines", headers=_h(admin_a_tok))
    items = r.json().get("rows", r.json().get("items", []))
    if not items:
        pytest.skip("no fines available")
    fine_id = items[0]["id"]
    # admin_b tries to fetch
    r2 = requests.get(f"{BASE}/livre/fines/{fine_id}", headers=_h(admin_b_tok))
    assert r2.status_code == 404, f"Expected 404 got {r2.status_code}: {r2.text[:200]}"


# ---------- Superadmin X-Tenant-Id switching ----------
def test_superadmin_can_view_as_tenant(super_tok):
    r = requests.get(f"{BASE}/livre/fines", headers=_h(super_tok, tenant="default"))
    assert r.status_code == 200
    items = r.json().get("rows", r.json().get("items", []))
    assert len(items) >= 5


def test_audit_endpoint_filters(super_tok):
    r = requests.get(f"{BASE}/admin/audit", params={"action": "tenant.create"},
                     headers=_h(super_tok))
    assert r.status_code == 200
    rows = r.json()
    for row in rows:
        assert "tenant.create" in row["action"]
