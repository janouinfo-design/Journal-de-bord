"""End-to-end backend tests for Logitrak Livre de Bord.

Covers: auth (login/me/logout), role enforcement, driver visibility,
dashboard, trips listing & classification, settings (modes A/B/C),
vehicle mode override, report exports (PDF/XLSX/CSV) and Swiss tax report.
"""
import io
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-classifier-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


# ---------- Fixtures ----------
def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.status_code} {r.text}"
    return s, r.json()


@pytest.fixture(scope="module")
def admin_session():
    s, _ = _login(ADMIN)
    yield s


@pytest.fixture(scope="module")
def manager_session():
    s, _ = _login(MANAGER)
    yield s


@pytest.fixture(scope="module")
def driver_session():
    s, _ = _login(DRIVER)
    yield s


# ---------- Auth ----------
class TestAuth:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=15)
        assert r.status_code == 200

    def test_login_admin(self):
        s, data = _login(ADMIN)
        assert data["user"]["role"] == "admin"
        assert "access_token" in s.cookies.get_dict()

    def test_login_manager(self):
        _, data = _login(MANAGER)
        assert data["user"]["role"] == "manager"

    def test_login_driver(self):
        _, data = _login(DRIVER)
        assert data["user"]["role"] == "driver"

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": "admin@logitrak.ch", "password": "bad"}, timeout=15)
        assert r.status_code == 401

    def test_me(self, admin_session):
        r = admin_session.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["email"] == ADMIN["email"]

    def test_logout(self):
        s, _ = _login(ADMIN)
        r = s.post(f"{API}/auth/logout", timeout=15)
        assert r.status_code == 200
        # after logout cookie cleared -> me should 401
        r2 = s.get(f"{API}/auth/me", timeout=15)
        assert r2.status_code == 401


# ---------- Role enforcement ----------
class TestRoles:
    def test_driver_cannot_update_settings(self, driver_session):
        r = driver_session.put(f"{API}/livre/settings",
                               json={"mode": "A", "rules": {}}, timeout=15)
        assert r.status_code == 403

    def test_driver_cannot_classify(self, driver_session, admin_session):
        # pick any trip via admin
        trips = admin_session.get(f"{API}/livre/trips?limit=1", timeout=15).json()["trips"]
        assert trips, "no trips seeded"
        r = driver_session.put(f"{API}/livre/trips/{trips[0]['id']}/classify",
                               json={"classification": "personal"}, timeout=15)
        assert r.status_code == 403

    def test_manager_can_update_settings(self, manager_session):
        r = manager_session.get(f"{API}/livre/settings", timeout=15)
        assert r.status_code == 200
        current = r.json()
        r2 = manager_session.put(f"{API}/livre/settings",
                                 json={"mode": current["mode"], "rules": current["rules"]}, timeout=30)
        assert r2.status_code == 200


# ---------- Driver visibility ----------
class TestDriverVisibility:
    def test_driver_only_sees_own_trips(self, driver_session):
        # Les données démo ont été remplacées par la synchro Navixy réelle :
        # Jean n'a plus forcément de trajet. On en seed un, puis on vérifie
        # l'isolation stricte côté serveur.
        import pymongo
        JEAN = "1580345e-6b8e-45a2-88e7-513a008b6b12"
        mc = pymongo.MongoClient(os.environ["MONGO_URL"])
        dbn = mc[os.environ["DB_NAME"]]
        veh = dbn.vehicles.find_one({"tenant_id": "default"}, {"id": 1, "plate": 1})
        seeded = {
            "id": "test-visibility-trip-jean", "tenant_id": "default",
            "driver_id": JEAN, "driver_name": "Jean Dupont",
            "vehicle_id": veh["id"], "vehicle_plate": veh.get("plate") or "",
            "start_time": "2026-08-18T07:00:00+00:00",
            "end_time": "2026-08-18T07:30:00+00:00",
            "classification": "professional", "auto_classified": True,
        }
        dbn.trips.update_one({"id": seeded["id"]}, {"$set": seeded}, upsert=True)
        try:
            r = driver_session.get(f"{API}/livre/trips?limit=500", timeout=30)
            assert r.status_code == 200
            trips = r.json()["trips"]
            assert trips, "driver should have trips"
            names = {t.get("driver_name") for t in trips}
            assert names == {"Jean Dupont"}, f"Driver saw other drivers: {names}"
        finally:
            dbn.trips.delete_one({"id": seeded["id"]})
            mc.close()


# ---------- Dashboard ----------
class TestDashboard:
    def test_dashboard_kpis(self, admin_session):
        r = admin_session.get(f"{API}/livre/dashboard", timeout=30)
        assert r.status_code == 200
        body = r.json()
        kpi = body["kpi"]
        for k in ("pro_km", "perso_km", "total_km", "pct_pro", "pct_perso",
                  "pro_fuel", "perso_fuel", "pro_time_min", "perso_time_min", "trips_count"):
            assert k in kpi
        assert isinstance(body["daily_series"], list)
        assert isinstance(body["table"], list)
        assert kpi["total_km"] > 0


# ---------- Trips filter ----------
class TestTrips:
    def test_filter_professional(self, admin_session):
        r = admin_session.get(f"{API}/livre/trips?classification=professional&limit=100", timeout=30)
        assert r.status_code == 200
        for t in r.json()["trips"]:
            assert t["classification"] == "professional"

    def test_filter_personal(self, admin_session):
        r = admin_session.get(f"{API}/livre/trips?classification=personal&limit=100", timeout=30)
        assert r.status_code == 200
        for t in r.json()["trips"]:
            assert t["classification"] == "personal"


# ---------- Manual classification + audit ----------
class TestClassify:
    def test_flip_pro_to_personal(self, admin_session):
        trips = admin_session.get(f"{API}/livre/trips?classification=professional&limit=1",
                                  timeout=15).json()["trips"]
        assert trips, "no pro trips"
        tid = trips[0]["id"]
        r = admin_session.put(f"{API}/livre/trips/{tid}/classify",
                              json={"classification": "personal"}, timeout=15)
        assert r.status_code == 200
        # verify persisted
        all_t = admin_session.get(f"{API}/livre/trips?limit=2000", timeout=30).json()["trips"]
        found = next((t for t in all_t if t["id"] == tid), None)
        assert found is not None
        assert found["classification"] == "personal"
        assert found.get("auto_classified") is False
        assert found.get("modified_by") == ADMIN["email"]
        # audit
        r2 = admin_session.get(f"{API}/livre/audit-log?limit=20", timeout=15)
        assert r2.status_code == 200
        assert any(a["trip_id"] == tid for a in r2.json())


# ---------- Settings modes ----------
class TestSettings:
    def test_modes_and_reapply(self, admin_session):
        # Modes actuels : 'mixte' | 'masked' (A/B legacy mappés, C supprimé)
        cur = admin_session.get(f"{API}/livre/settings", timeout=15).json()
        rules = cur["rules"]
        original = cur.get("mode") or "mixte"
        try:
            for legacy, expected in (("A", "mixte"), ("B", "masked"), ("mixte", "mixte"), ("masked", "masked")):
                r = admin_session.put(f"{API}/livre/settings",
                                      json={"mode": legacy, "rules": rules}, timeout=60)
                assert r.status_code == 200, r.text
                assert r.json()["mode"] == expected, f"{legacy} → {r.json()['mode']}"
            # Mode C supprimé → erreur explicite
            r = admin_session.put(f"{API}/livre/settings",
                                  json={"mode": "C", "rules": rules}, timeout=60)
            assert r.status_code >= 400, "mode C doit être refusé"
        finally:
            r = admin_session.put(f"{API}/livre/settings",
                                  json={"mode": original, "rules": rules}, timeout=60)
            assert r.status_code == 200, r.text

    def test_mode_b_masks_personal_for_manager(self, admin_session, manager_session):
        cur = admin_session.get(f"{API}/livre/settings", timeout=15).json()
        rules = cur["rules"]
        admin_session.put(f"{API}/livre/settings",
                          json={"mode": "B", "rules": rules}, timeout=60)
        try:
            # manager sees masked
            mr = manager_session.get(f"{API}/livre/trips?classification=personal&limit=50",
                                     timeout=30).json()["trips"]
            if mr:
                t = mr[0]
                assert t.get("masked") is True
                assert "start_address" not in t
                assert "fuel_l" not in t
            # admin sees full
            ar = admin_session.get(f"{API}/livre/trips?classification=personal&limit=50",
                                   timeout=30).json()["trips"]
            if ar:
                t = ar[0]
                assert "start_address" in t or t.get("masked") is None
                assert t.get("masked") is not True
        finally:
            admin_session.put(f"{API}/livre/settings",
                              json={"mode": "A", "rules": rules}, timeout=60)


# ---------- Vehicle mode override ----------
class TestVehicleMode:
    def test_always_pro_override(self, admin_session):
        veh = admin_session.get(f"{API}/livre/vehicles", timeout=15).json()
        assert veh
        vid = veh[0]["id"]
        r = admin_session.put(f"{API}/livre/vehicles/{vid}/mode",
                              json={"mode": "always_pro"}, timeout=60)
        assert r.status_code == 200
        trips = admin_session.get(f"{API}/livre/trips?vehicle_id={vid}&limit=2000",
                                  timeout=30).json()["trips"]
        auto = [t for t in trips if t.get("auto_classified", True)]
        if auto:
            non_pro = [t for t in auto if t["classification"] != "professional"]
            assert not non_pro, f"{len(non_pro)} auto trips not pro for always_pro vehicle"
        # reset
        admin_session.put(f"{API}/livre/vehicles/{vid}/mode",
                          json={"mode": "mixte"}, timeout=60)


# ---------- Reports ----------
class TestReports:
    def test_export_pdf(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export?classification=professional&fmt=pdf",
                              timeout=60)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_export_xlsx(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export?classification=professional&fmt=xlsx",
                              timeout=60)
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert r.content[:2] == b"PK"

    def test_export_csv(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/export?classification=personal&fmt=csv",
                              timeout=60)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert len(r.content) > 0

    def test_tax_swiss(self, admin_session):
        r = admin_session.get(f"{API}/livre/reports/tax-swiss?year=2026", timeout=60)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert "attachment" in r.headers.get("content-disposition", "")
        assert r.content[:4] == b"%PDF"
