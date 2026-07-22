"""Tests backend pour la fonctionnalité « Se connecter comme… » (impersonation).

Couvre :
- Génération d'un token 60s (admin client, superadmin)
- Échange token → Bearer d'aperçu, usage unique, expiration
- get_current_user attache impersonated_by au user cible
- Audit log trace actor + effective user + note en français
- Garde-fous : self, superadmin cible, imbrication, manager 403, cross-tenant 404, tenant suspendu 403
- /impersonate/end + aucun Set-Cookie
- Régression : login, /livre/dashboard, /livre/team/users, /livre/team/drivers, SSO Navixy erreur.
"""
import os
import time
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin(): return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def manager(): return _login("manager@logitrak.ch", "manager123")


@pytest.fixture(scope="module")
def superadmin(): return _login("superadmin@logitrak.ch", "superadmin123")


@pytest.fixture(scope="module")
def admin_b(): return _login("admin-b@test.ch", "testb123")


def _find_user(sess, email):
    r = sess.get(f"{BASE}/livre/team/users", timeout=15)
    assert r.status_code == 200, r.text
    for u in r.json():
        if u["email"] == email:
            return u
    return None


# ============ Génération token (admin client) ============
class TestAdminImpersonateStart:
    def test_admin_start_returns_token(self, admin):
        u = _find_user(admin, "manager@logitrak.ch")
        assert u
        r = admin.post(f"{BASE}/livre/team/users/{u['id']}/impersonate", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["expires_in"] == 60
        assert isinstance(data["token"], str) and len(data["token"]) > 20
        assert data["target"]["email"] == "manager@logitrak.ch"
        assert data["target"]["role"] == "manager"

    def test_admin_cannot_impersonate_self(self, admin):
        me = admin.get(f"{BASE}/auth/me", timeout=10).json()["user"]
        r = admin.post(f"{BASE}/livre/team/users/{me['id']}/impersonate", timeout=15)
        assert r.status_code == 400

    def test_admin_cannot_impersonate_superadmin(self, admin, superadmin):
        # superadmin has tenant_id=None, not visible in admin's team users
        # We test by direct id lookup via raw admin listing → 404 (not in tenant)
        sa = superadmin.get(f"{BASE}/auth/me", timeout=10).json()["user"]
        r = admin.post(f"{BASE}/livre/team/users/{sa['id']}/impersonate", timeout=15)
        assert r.status_code == 404

    def test_manager_forbidden(self, manager):
        u = _find_user(_login("admin@logitrak.ch", "admin123"), "chauffeur@logitrak.ch")
        r = manager.post(f"{BASE}/livre/team/users/{u['id']}/impersonate", timeout=15)
        assert r.status_code == 403

    def test_admin_cannot_impersonate_other_tenant(self, admin_b, admin):
        # admin_b tries to impersonate a default-tenant user → 404
        default_user = _find_user(admin, "manager@logitrak.ch")
        r = admin_b.post(f"{BASE}/livre/team/users/{default_user['id']}/impersonate", timeout=15)
        assert r.status_code == 404


# ============ Échange (usage unique, expiration) ============
class TestImpersonateExchange:
    def test_exchange_returns_bearer_with_imp_claims(self, admin):
        u = _find_user(admin, "manager@logitrak.ch")
        r = admin.post(f"{BASE}/livre/team/users/{u['id']}/impersonate", timeout=15)
        token = r.json()["token"]

        # Aucun cookie ne doit être posé sur cet endpoint
        r2 = requests.post(f"{BASE}/auth/impersonate", json={"token": token}, timeout=15)
        assert r2.status_code == 200, r2.text
        # No auth-cookie must be set by backend (admin session must remain intact).
        # Cloudflare may add __cf_bm; we only forbid access_token/refresh_token cookies.
        cookies_set = "; ".join(v for k, v in r2.headers.items() if k.lower() == "set-cookie")
        assert "access_token=" not in cookies_set and "refresh_token=" not in cookies_set
        data = r2.json()
        assert data["user"]["email"] == "manager@logitrak.ch"
        assert "access_token" in data
        assert data["impersonation"]["actor_email"] == "admin@logitrak.ch"

        bearer = data["access_token"]
        # /auth/me avec Bearer → user cible + impersonated_by
        r3 = requests.get(f"{BASE}/auth/me",
                          headers={"Authorization": f"Bearer {bearer}"}, timeout=15)
        assert r3.status_code == 200
        me = r3.json()["user"]
        assert me["email"] == "manager@logitrak.ch"
        assert me["impersonated_by"]["email"] == "admin@logitrak.ch"
        assert me["impersonated_by"]["auth_source"] == "admin_client_impersonation"
        assert me["impersonated_by"]["session_id"]

        # Requête /livre/* scopée au tenant du user cible (default)
        r4 = requests.get(f"{BASE}/livre/dashboard",
                          headers={"Authorization": f"Bearer {bearer}"}, timeout=20)
        assert r4.status_code == 200

    def test_token_single_use(self, admin):
        u = _find_user(admin, "manager@logitrak.ch")
        token = admin.post(f"{BASE}/livre/team/users/{u['id']}/impersonate",
                           timeout=15).json()["token"]
        first = requests.post(f"{BASE}/auth/impersonate", json={"token": token}, timeout=15)
        assert first.status_code == 200
        second = requests.post(f"{BASE}/auth/impersonate", json={"token": token}, timeout=15)
        assert second.status_code == 401

    def test_invalid_token(self):
        r = requests.post(f"{BASE}/auth/impersonate", json={"token": "invalid-xxx"}, timeout=10)
        assert r.status_code == 401


# ============ Guard imbrication ============
class TestNestingGuard:
    def test_cannot_nest_impersonation(self, admin):
        # Impersonate an admin-role target? Only admin user is self. Try to impersonate manager
        # then use its bearer to impersonate driver → manager is not admin → 403 role guard first.
        # We need an admin-role target other than self. Create one via team/users.
        r = admin.post(f"{BASE}/livre/team/users", json={
            "email": "TEST_nested_admin@logitrak.ch",
            "password": "nested123", "name": "TEST Nested", "role": "admin"}, timeout=15)
        # cleanup regardless
        try:
            assert r.status_code == 200, r.text
            uid = r.json()["id"]
            tok = admin.post(f"{BASE}/livre/team/users/{uid}/impersonate",
                             timeout=15).json()["token"]
            data = requests.post(f"{BASE}/auth/impersonate", json={"token": tok},
                                 timeout=15).json()
            bearer = data["access_token"]
            # Try to nest impersonation
            chauffeur = _find_user(admin, "chauffeur@logitrak.ch")
            r2 = requests.post(f"{BASE}/livre/team/users/{chauffeur['id']}/impersonate",
                               headers={"Authorization": f"Bearer {bearer}"}, timeout=15)
            assert r2.status_code == 403
            assert "imbriquer" in r2.text.lower() or "imbriqu" in r2.text.lower()
        finally:
            # cleanup
            me_admin = admin.get(f"{BASE}/auth/me").json()["user"]
            for u in admin.get(f"{BASE}/livre/team/users").json():
                if u["email"] == "test_nested_admin@logitrak.ch":
                    admin.delete(f"{BASE}/livre/team/users/{u['id']}")


# ============ Superadmin cross-tenant + tenant suspendu ============
class TestSuperadminImpersonate:
    def test_superadmin_cross_tenant(self, superadmin, admin_b):
        # Trouver tenant B id
        tenants = superadmin.get(f"{BASE}/admin/tenants").json()
        tenant_b = next(t for t in tenants if t.get("name") == "Client Test B")
        # Set header + list users of tenant B
        headers = {"X-Tenant-Id": tenant_b["id"]}
        users = superadmin.get(f"{BASE}/livre/team/users", headers=headers).json()
        target = next(u for u in users if u["email"] == "admin-b@test.ch")
        r = superadmin.post(f"{BASE}/livre/team/users/{target['id']}/impersonate",
                            headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        data = requests.post(f"{BASE}/auth/impersonate", json={"token": tok}, timeout=15).json()
        bearer = data["access_token"]
        me = requests.get(f"{BASE}/auth/me",
                          headers={"Authorization": f"Bearer {bearer}"}).json()["user"]
        assert me["email"] == "admin-b@test.ch"
        assert me["tenant_id"] == tenant_b["id"]
        assert me["impersonated_by"]["auth_source"] == "super_admin_impersonation"

    def test_suspended_tenant_blocks_impersonation(self, superadmin):
        # Create a test tenant, then suspend it, then try to impersonate a user in it
        import uuid as _u
        name = f"TEST Suspend {_u.uuid4().hex[:6]}"
        r = superadmin.post(f"{BASE}/admin/tenants",
                            json={"name": name}, timeout=15)
        assert r.status_code == 200, r.text
        tenant = r.json()
        tid = tenant["id"]
        try:
            # Create a user in it (superadmin has X-Tenant-Id)
            headers = {"X-Tenant-Id": tid}
            ur = superadmin.post(f"{BASE}/livre/team/users", headers=headers, json={
                "email": f"test_susp_{_u.uuid4().hex[:6]}@x.ch",
                "password": "test1234", "name": "T Susp", "role": "manager"}, timeout=15)
            assert ur.status_code == 200, ur.text
            uid = ur.json()["id"]
            # Suspend tenant
            sr = superadmin.patch(f"{BASE}/admin/tenants/{tid}",
                                  json={"status": "suspended"}, timeout=15)
            assert sr.status_code == 200, sr.text
            # Now try to impersonate → 403
            r2 = superadmin.post(f"{BASE}/livre/team/users/{uid}/impersonate",
                                 headers=headers, timeout=15)
            assert r2.status_code == 403, r2.text
            assert "suspendu" in r2.text.lower()
        finally:
            # Cleanup: reactivate + delete tenant (best effort)
            try:
                superadmin.patch(f"{BASE}/admin/tenants/{tid}", json={"status": "active"})
                # Delete tenant if endpoint exists
                superadmin.delete(f"{BASE}/admin/tenants/{tid}")
            except Exception:
                pass


# ============ Impersonate end + audit ============
class TestImpersonateEndAndAudit:
    def test_impersonate_end_no_cookie_change(self, admin):
        u = _find_user(admin, "manager@logitrak.ch")
        tok = admin.post(f"{BASE}/livre/team/users/{u['id']}/impersonate").json()["token"]
        bearer = requests.post(f"{BASE}/auth/impersonate",
                               json={"token": tok}).json()["access_token"]
        r = requests.post(f"{BASE}/auth/impersonate/end",
                          headers={"Authorization": f"Bearer {bearer}"}, timeout=15)
        assert r.status_code == 200
        assert r.json().get("ended") is True
        cookies_set = "; ".join(v for k, v in r.headers.items() if k.lower() == "set-cookie")
        assert "access_token=" not in cookies_set and "refresh_token=" not in cookies_set

    def test_action_via_bearer_logs_impersonation_in_audit(self, admin, superadmin):
        # Perform a settings PUT via bearer, then check audit as superadmin
        u = _find_user(admin, "admin@logitrak.ch")  # self... skip
        target = _find_user(admin, "manager@logitrak.ch")
        tok = admin.post(f"{BASE}/livre/team/users/{target['id']}/impersonate").json()["token"]
        exch = requests.post(f"{BASE}/auth/impersonate", json={"token": tok}).json()
        bearer = exch["access_token"]
        session_id = exch["impersonation"]["session_id"]

        # Perform a settings GET/PUT — settings PUT requires admin, manager may 403.
        # Instead: dashboard GET is enough — but audit only fires on modifying. Let's try
        # /livre/settings PUT with the manager bearer.
        r = requests.get(f"{BASE}/livre/settings",
                         headers={"Authorization": f"Bearer {bearer}"}, timeout=15)
        if r.status_code == 200:
            body = r.json()
            put = requests.put(f"{BASE}/livre/settings",
                               headers={"Authorization": f"Bearer {bearer}"},
                               json=body, timeout=15)
            # Manager may or may not be authorized. If 200, check audit.
            if put.status_code == 200:
                # find audit entry with our session_id
                audit = superadmin.get(f"{BASE}/admin/audit", timeout=15).json()
                rows = audit if isinstance(audit, list) else audit.get("items", [])
                matched = [a for a in rows
                           if (a.get("impersonation") or {}).get("session_id") == session_id]
                assert matched, "No audit entry tagged with impersonation session_id"
                assert "aperçu" in (matched[0].get("note") or "").lower() or \
                       "se connecter comme" in (matched[0].get("note") or "").lower()

        # Always check that impersonate_start / impersonate_open were logged
        audit = superadmin.get(f"{BASE}/admin/audit", timeout=15).json()
        rows = audit if isinstance(audit, list) else audit.get("items", [])
        actions = {a.get("action") for a in rows}
        assert "user.impersonate_start" in actions
        assert "user.impersonate_open" in actions


# ============ Régression ============
class TestRegression:
    def test_login_admin(self, admin):
        r = admin.get(f"{BASE}/auth/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_dashboard(self, admin):
        assert admin.get(f"{BASE}/livre/dashboard", timeout=20).status_code == 200

    def test_team_users(self, admin):
        assert admin.get(f"{BASE}/livre/team/users", timeout=15).status_code == 200

    def test_team_drivers(self, admin):
        assert admin.get(f"{BASE}/livre/team/drivers", timeout=15).status_code == 200

    def test_navixy_sso_invalid(self):
        r = requests.post(f"{BASE}/auth/navixy-sso",
                          json={"session_key": "invalidsessionkey12345"}, timeout=15)
        assert r.status_code in (400, 401)

    def test_tenant_switcher_header(self, superadmin):
        tenants = superadmin.get(f"{BASE}/admin/tenants", timeout=15).json()
        assert len(tenants) >= 1
        r = superadmin.get(f"{BASE}/livre/team/users",
                           headers={"X-Tenant-Id": tenants[0]["id"]}, timeout=15)
        assert r.status_code == 200
