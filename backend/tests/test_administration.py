"""Tests Administration client (team.py) — utilisateurs, chauffeurs, PWA access, isolation multi-tenant."""
import os
import uuid
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://trip-classifier-2.preview.emergentagent.com"
API = f"{BASE}/api"

ADMIN = ("admin@logitrak.ch", "admin123")
MANAGER = ("manager@logitrak.ch", "manager123")
SUPERADMIN = ("superadmin@logitrak.ch", os.environ["SUPERADMIN_PASSWORD"])
ADMIN_B = ("admin-b@test.ch", "testb123")
PAUL = ("paul.test@client.ch", "paul1234")
NAVIXY_HASH = "a25480874b7492bd01ff1d926061e491"


def login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return s, r.json()


# ============ ADMIN Logitrak — Users ============
class TestAdminUsers:
    def setup_method(self):
        self.s, self.me = login(*ADMIN)

    def test_list_users(self):
        r = self.s.get(f"{API}/livre/team/users")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        emails = {u["email"] for u in data}
        assert "admin@logitrak.ch" in emails
        assert "manager@logitrak.ch" in emails
        # linked_driver field must exist
        for u in data:
            assert "linked_driver" in u
            assert "password_hash" not in u
        # paul driver linked
        paul_u = next((u for u in data if u["email"] == "paul.test@client.ch"), None)
        if paul_u:
            assert paul_u["role"] == "driver"

    def test_create_update_delete_user(self):
        email = f"test_admin_{uuid.uuid4().hex[:8]}@example.com"
        # CREATE
        r = self.s.post(f"{API}/livre/team/users",
                        json={"email": email, "password": "pw123456", "name": "Temp Test", "role": "manager"})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
        assert r.json()["role"] == "manager"
        # Verify persistence via list
        listing = self.s.get(f"{API}/livre/team/users").json()
        assert any(u["email"] == email for u in listing)

        # PATCH role to driver
        r = self.s.patch(f"{API}/livre/team/users/{uid}", json={"role": "driver"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "driver"

        # DELETE
        r = self.s.delete(f"{API}/livre/team/users/{uid}")
        assert r.status_code == 200
        listing = self.s.get(f"{API}/livre/team/users").json()
        assert not any(u["email"] == email for u in listing)

    def test_cannot_delete_self(self):
        r = self.s.delete(f"{API}/livre/team/users/{self.me['user']['id']}")
        assert r.status_code == 400

    def test_cannot_demote_self(self):
        r = self.s.patch(f"{API}/livre/team/users/{self.me['user']['id']}", json={"role": "manager"})
        assert r.status_code == 400


# ============ Register endpoint : role superadmin refuse ============
class TestRegisterRoleValidation:
    def test_register_superadmin_forbidden(self):
        s, _ = login(*ADMIN)
        r = s.post(f"{API}/auth/register",
                   json={"email": f"try_{uuid.uuid4().hex[:6]}@x.ch",
                         "password": "abc12345", "name": "X", "role": "superadmin"})
        assert r.status_code == 400, r.text

    def test_register_invalid_role(self):
        s, _ = login(*ADMIN)
        r = s.post(f"{API}/auth/register",
                   json={"email": f"try_{uuid.uuid4().hex[:6]}@x.ch",
                         "password": "abc12345", "name": "X", "role": "hacker"})
        assert r.status_code == 400


# ============ MANAGER — restrictions ============
class TestManagerAccess:
    def setup_method(self):
        self.s, _ = login(*MANAGER)

    def test_users_forbidden(self):
        r = self.s.get(f"{API}/livre/team/users")
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_drivers_allowed(self):
        r = self.s.get(f"{API}/livre/team/drivers")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ============ Isolation multi-tenant ============
class TestTenantIsolation:
    def test_admin_b_isolated(self):
        s_a, _ = login(*ADMIN)
        s_b, _ = login(*ADMIN_B)
        users_a = s_a.get(f"{API}/livre/team/users").json()
        users_b = s_b.get(f"{API}/livre/team/users").json()
        assert isinstance(users_a, list) and isinstance(users_b, list)
        emails_a = {u["email"] for u in users_a}
        emails_b = {u["email"] for u in users_b}
        # No overlap on tenant-specific accounts
        assert "admin@logitrak.ch" in emails_a
        assert "admin@logitrak.ch" not in emails_b, f"tenant B sees Logitrak users! {emails_b}"
        assert "admin-b@test.ch" in emails_b
        assert "admin-b@test.ch" not in emails_a

    def test_admin_b_drivers_isolated(self):
        s_a, _ = login(*ADMIN)
        s_b, _ = login(*ADMIN_B)
        drv_a = s_a.get(f"{API}/livre/team/drivers").json()
        drv_b = s_b.get(f"{API}/livre/team/drivers").json()
        ids_a = {d["id"] for d in drv_a}
        ids_b = {d["id"] for d in drv_b}
        assert not (ids_a & ids_b), "tenant driver overlap"


# ============ DRIVERS — CRUD + grant-access + unlink ============
class TestDriversCRUD:
    def setup_method(self):
        self.s, _ = login(*ADMIN)

    def test_list_drivers_with_paul(self):
        r = self.s.get(f"{API}/livre/team/drivers")
        assert r.status_code == 200
        drivers = r.json()
        assert any(d["name"] == "Paul Test" for d in drivers), "Paul Test manuel absent"
        # Look for any Navixy driver (has navixy_employee_id)
        assert any(d.get("navixy_employee_id") for d in drivers), "Aucun chauffeur Navixy trouvé"
        # Paul has linked account
        paul = next(d for d in drivers if d["name"] == "Paul Test")
        assert paul.get("account"), "Paul devrait avoir un compte lié"
        assert paul["account"]["email"] == "paul.test@client.ch"

    def test_create_edit_toggle_driver(self):
        name = f"TEST Driver {uuid.uuid4().hex[:6]}"
        matricule = f"T-{uuid.uuid4().hex[:6]}"
        r = self.s.post(f"{API}/livre/team/drivers",
                        json={"name": name, "internal_number": matricule, "ibutton_id": "IBTEST01", "active": True})
        assert r.status_code == 200, r.text
        did = r.json()["id"]

        # Edit
        r = self.s.patch(f"{API}/livre/team/drivers/{did}", json={"phone": "+41000000"})
        assert r.status_code == 200
        assert r.json()["phone"] == "+41000000"

        # Toggle inactive
        r = self.s.patch(f"{API}/livre/team/drivers/{did}", json={"active": False})
        assert r.status_code == 200
        assert r.json()["active"] is False

    def test_grant_and_unlink_access(self):
        # Create driver
        name = f"TEST GrantDrv {uuid.uuid4().hex[:6]}"
        r = self.s.post(f"{API}/livre/team/drivers", json={"name": name})
        assert r.status_code == 200
        did = r.json()["id"]

        # Grant access
        email = f"test_grant_{uuid.uuid4().hex[:6]}@ex.ch"
        pw = "pwtest1234"
        r = self.s.post(f"{API}/livre/team/drivers/{did}/grant-access",
                        json={"email": email, "password": pw})
        assert r.status_code == 200, r.text
        uid = r.json()["user_id"]

        # New account can login
        s2, u2 = login(email, pw)
        assert u2["user"]["role"] == "driver"

        # Cannot grant again (already linked)
        r = self.s.post(f"{API}/livre/team/drivers/{did}/grant-access",
                        json={"email": "another@ex.ch", "password": "xx12345678"})
        assert r.status_code == 400

        # Unlink
        r = self.s.post(f"{API}/livre/team/drivers/{did}/unlink-user")
        assert r.status_code == 200

        # Cleanup created user
        self.s.delete(f"{API}/livre/team/users/{uid}")


# ============ SSO Navixy — logitrak@logitrak.ch => admin ============
class TestNavixySSO:
    def test_sso_promotes_master_to_admin(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/navixy-sso", json={"session_key": NAVIXY_HASH}, timeout=20)
        # Could be 200 (existing) or 403 if tenant issue; we expect 200 with admin role
        assert r.status_code == 200, f"SSO failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["user"]["email"] == "logitrak@logitrak.ch"
        assert data["user"]["role"] == "admin", f"expected admin, got {data['user']['role']}"


# ============ Régression: superadmin + fines list for admin ============
class TestRegression:
    def test_superadmin_tenants(self):
        s, _ = login(*SUPERADMIN)
        r = s.get(f"{API}/admin/tenants")
        assert r.status_code == 200

    def test_admin_fines_list(self):
        s, _ = login(*ADMIN)
        r = s.get(f"{API}/livre/fines")
        assert r.status_code == 200
        data = r.json()
        items = data.get("rows") or data.get("items") or (data if isinstance(data, list) else [])
        assert len(items) >= 5, f"attendu >= 5 amendes, obtenu {len(items)}"
