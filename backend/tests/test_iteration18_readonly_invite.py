"""Iteration 18 — Rôle lecture seule, invitation chauffeur par email, historique aperçus."""
import os
import re
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-classifier-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    s = requests.Session()
    last = None
    for _ in range(3):
        try:
            r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
            assert r.status_code == 200, f"login {email} → {r.status_code} {r.text[:200]}"
            return s
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(2)
    raise last


@pytest.fixture(scope="module")
def admin():
    return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def readonly():
    return _login("lecture@logitrak.ch", "lecture123")


@pytest.fixture(scope="module")
def superadmin():
    return _login("superadmin@logitrak.ch", "superadmin123")


@pytest.fixture(scope="module")
def admin_b():
    return _login("admin-b@test.ch", "testb123")


# ============= Bloc A : rôle lecture seule =============
class TestReadOnlyRole:
    def test_readonly_login_ok_and_role_correct(self, readonly):
        r = readonly.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "lecture_seule"

    def test_readonly_can_get_dashboard(self, readonly):
        r = readonly.get(f"{API}/livre/dashboard", timeout=15)
        assert r.status_code == 200

    def test_readonly_can_get_trips(self, readonly):
        r = readonly.get(f"{API}/livre/trips", timeout=15)
        assert r.status_code == 200

    def test_readonly_can_get_fines(self, readonly):
        r = readonly.get(f"{API}/livre/fines", timeout=15)
        assert r.status_code == 200
        assert "rows" in r.json()

    def test_readonly_can_get_fines_stats_extended(self, readonly):
        r = readonly.get(f"{API}/livre/fines/stats/extended", timeout=15)
        assert r.status_code == 200

    def test_readonly_can_export_fines_csv(self, readonly):
        r = readonly.get(f"{API}/livre/fines/export?fmt=csv", timeout=20)
        assert r.status_code == 200

    def test_readonly_can_get_tax_swiss_report(self, readonly):
        r = readonly.get(f"{API}/livre/reports/tax-swiss?year=2026", timeout=20)
        assert r.status_code == 200

    def test_readonly_write_fine_blocked(self, readonly):
        r = readonly.post(f"{API}/livre/fines", json={"amount": 100}, timeout=10)
        assert r.status_code == 403
        assert "lecture seule" in r.text.lower()

    def test_readonly_classify_blocked(self, readonly):
        r = readonly.put(f"{API}/livre/trips/xxx/classify",
                         json={"classification": "professional"}, timeout=10)
        assert r.status_code == 403

    def test_readonly_settings_write_blocked(self, readonly):
        r = readonly.put(f"{API}/livre/settings", json={"privacy_mode": "mixed"}, timeout=10)
        assert r.status_code == 403

    def test_readonly_create_user_blocked(self, readonly):
        r = readonly.post(f"{API}/livre/team/users",
                          json={"email": "x@x.ch", "password": "12345678", "name": "x", "role": "driver"},
                          timeout=10)
        assert r.status_code == 403

    def test_readonly_delete_blocked(self, readonly):
        r = readonly.delete(f"{API}/livre/fines/does-not-exist", timeout=10)
        assert r.status_code == 403

    def test_readonly_ble_simulate_blocked(self, readonly):
        r = readonly.post(f"{API}/livre/ble/simulate", json={}, timeout=10)
        assert r.status_code == 403

    def test_readonly_logout_allowed(self):
        s = _login("lecture@logitrak.ch", "lecture123")
        r = s.post(f"{API}/auth/logout", timeout=10)
        assert r.status_code == 200

    def test_readonly_refresh_allowed(self):
        s = _login("lecture@logitrak.ch", "lecture123")
        # cookie contains refresh_token
        r = s.post(f"{API}/auth/refresh", json={}, timeout=10)
        assert r.status_code == 200

    def test_admin_can_create_lecture_seule_user_and_cleanup(self, admin):
        email = f"TEST_ro_{uuid.uuid4().hex[:8]}@x.ch"
        r = admin.post(f"{API}/livre/team/users",
                       json={"email": email, "password": "abcdef12", "name": "RO Test", "role": "lecture_seule"},
                       timeout=10)
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
        # cleanup
        r2 = admin.delete(f"{API}/livre/team/users/{uid}", timeout=10)
        assert r2.status_code == 200


# ============= Bloc B : flux d'invitation par email =============
class TestInvitationFlow:
    def _cleanup_user_by_email(self, admin, email):
        try:
            r = admin.get(f"{API}/livre/team/users", timeout=10)
            for u in r.json():
                if u.get("email") == email.lower():
                    admin.delete(f"{API}/livre/team/users/{u['id']}", timeout=10)
        except Exception:
            pass

    def _create_test_driver(self, admin, name):
        r = admin.post(f"{API}/livre/team/drivers",
                       json={"name": name, "active": True}, timeout=10)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_full_invitation_flow(self, admin):
        driver_name = f"TEST_INV_{uuid.uuid4().hex[:6]}"
        email = f"test.inv.{uuid.uuid4().hex[:8]}@client.ch"
        did = self._create_test_driver(admin, driver_name)

        # 1) POST invite
        r = admin.post(f"{API}/livre/team/drivers/{did}/invite",
                       json={"email": email}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email_sent"] is False
        assert body["expires_days"] == 7
        assert "invite_url" in body and "token=" in body["invite_url"]
        token = body["invite_url"].split("token=")[-1]

        # 2) GET invitation info (public, no auth)
        pub = requests.Session()
        r = pub.get(f"{API}/auth/invitation/{token}", timeout=10)
        assert r.status_code == 200, r.text
        info = r.json()
        assert info["email"] == email.lower()
        assert info.get("driver_name") == driver_name

        # 3) Accept with too-short password
        r = pub.post(f"{API}/auth/invitation/{token}/accept",
                     json={"password": "short"}, timeout=10)
        assert r.status_code == 400
        assert "8" in r.text

        # 4) Accept with valid password
        r = pub.post(f"{API}/auth/invitation/{token}/accept",
                     json={"password": "goodpass1"}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["role"] == "driver"
        assert data["user"]["email"] == email.lower()
        # cookies should now be set
        assert "access_token" in pub.cookies or data.get("access_token")

        # 5) Replay token → 404
        r = pub.post(f"{API}/auth/invitation/{token}/accept",
                     json={"password": "goodpass1"}, timeout=10)
        assert r.status_code == 404

        # 6) GET info reused token → 404
        r = pub.get(f"{API}/auth/invitation/{token}", timeout=10)
        assert r.status_code == 404

        # 7) Login with new account
        s = _login(email.lower(), "goodpass1")
        r = s.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "driver"

        # 8) Second invite on same driver (already has user_id) → 400
        r = admin.post(f"{API}/livre/team/drivers/{did}/invite",
                       json={"email": f"other.{uuid.uuid4().hex[:6]}@x.ch"}, timeout=10)
        assert r.status_code == 400

        # 9) Invite with already-used email → 400 (create new driver, use existing email)
        did2 = self._create_test_driver(admin, f"TEST_INV_{uuid.uuid4().hex[:6]}")
        r = admin.post(f"{API}/livre/team/drivers/{did2}/invite",
                       json={"email": email}, timeout=10)
        assert r.status_code == 400

        # cleanup
        self._cleanup_user_by_email(admin, email)
        admin.patch(f"{API}/livre/team/drivers/{did}", json={"active": False}, timeout=10)
        admin.patch(f"{API}/livre/team/drivers/{did2}", json={"active": False}, timeout=10)

    def test_invalid_token_returns_404(self):
        pub = requests.Session()
        r = pub.get(f"{API}/auth/invitation/INVALID_XXX", timeout=10)
        assert r.status_code == 404

    def test_pending_invitation_exposed_in_drivers_list(self, admin):
        """Spec: GET /team/drivers doit exposer pending_invitation pour les chauffeurs avec une invitation en attente."""
        driver_name = f"TEST_PEND_{uuid.uuid4().hex[:6]}"
        email = f"pending.{uuid.uuid4().hex[:8]}@client.ch"
        r = admin.post(f"{API}/livre/team/drivers", json={"name": driver_name, "active": True}, timeout=10)
        did = r.json()["id"]
        admin.post(f"{API}/livre/team/drivers/{did}/invite", json={"email": email}, timeout=10)

        r = admin.get(f"{API}/livre/team/drivers", timeout=10)
        assert r.status_code == 200
        rows = r.json()
        me = next((d for d in rows if d["id"] == did), None)
        assert me is not None, "created driver not found in list"
        # spec explicit: "Invitations listées dans GET /team/drivers via champ pending_invitation"
        has_pending = me.get("pending_invitation")
        # cleanup
        admin.patch(f"{API}/livre/team/drivers/{did}", json={"active": False}, timeout=10)
        assert has_pending is not None, (
            "pending_invitation absent de la réponse GET /team/drivers — spec attend "
            "que le champ soit peuplé pour les chauffeurs avec une invitation en attente. "
            f"Driver renvoyé: {me}"
        )
        assert has_pending.get("email") == email.lower()


# ============= Bloc C : historique des aperçus =============
class TestImpersonationSessionsHistory:
    def test_admin_sees_own_tenant_sessions(self, admin):
        r = admin.get(f"{API}/livre/team/impersonation-sessions", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # aucun token_hash exposé
        for row in rows:
            assert "token_hash" not in row
            assert "status" in row
            assert row["status"] in ("active", "ended", "expired", "denied", "pending")

    def test_manager_403(self):
        s = _login("manager@logitrak.ch", "manager123")
        r = s.get(f"{API}/livre/team/impersonation-sessions", timeout=10)
        assert r.status_code == 403

    def test_impersonate_with_reason_stored(self, admin):
        # find manager user id
        r = admin.get(f"{API}/livre/team/users", timeout=10)
        assert r.status_code == 200
        manager = next(u for u in r.json() if u["role"] == "manager")

        reason = f"TEST_REASON_{uuid.uuid4().hex[:6]}"
        r = admin.post(f"{API}/livre/team/users/{manager['id']}/impersonate",
                       json={"reason": reason}, timeout=10)
        assert r.status_code == 200, r.text

        # verify listed in sessions with reason
        r = admin.get(f"{API}/livre/team/impersonation-sessions", timeout=10)
        rows = r.json()
        found = next((x for x in rows if x.get("reason") == reason), None)
        assert found is not None, f"reason not persisted; sample={rows[:2]}"
        assert found["target_email"] == manager["email"]
        assert found["target_role"] == "manager"
        assert found["actor_email"] == "admin@logitrak.ch"

    def test_impersonate_accepts_empty_body(self, admin):
        r = admin.get(f"{API}/livre/team/users", timeout=10)
        manager = next(u for u in r.json() if u["role"] == "manager")
        # No body
        r = admin.post(f"{API}/livre/team/users/{manager['id']}/impersonate", timeout=10)
        assert r.status_code == 200, r.text

    def test_admin_b_isolated_from_default_tenant(self, admin_b):
        r = admin_b.get(f"{API}/livre/team/impersonation-sessions", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            # admin-b's tenant_id, not "default"
            assert row.get("actor_email") != "admin@logitrak.ch", \
                "admin-b sees default tenant sessions — tenant isolation broken"

    def test_superadmin_tenant_id_all(self, superadmin):
        r = superadmin.get(f"{API}/livre/team/impersonation-sessions?tenant_id=all", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)

    def test_superadmin_tenant_id_specific(self, superadmin):
        r = superadmin.get(f"{API}/livre/team/impersonation-sessions?tenant_id=default", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        # all rows must be tenant=default
        for row in rows:
            assert row.get("tenant_id") in (None, "default"), row
