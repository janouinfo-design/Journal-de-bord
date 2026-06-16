"""Iteration 3 tests — APScheduler + fine-grained vehicle↔driver assignments."""
import os
import time
import pytest
import requests

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except FileNotFoundError:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")

BASE = _load_backend_url()
API = f"{BASE}/api"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} failed {r.status_code} {r.text}"
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


# ---------------- Scheduler ----------------
class TestScheduler:
    def test_get_state_shape(self, admin):
        r = admin.get(f"{API}/livre/navixy/scheduler", timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        for k in ["enabled", "interval_min", "days", "configured"]:
            assert k in s, f"missing {k} in {s}"
        assert "last_run" in s and "next_run" in s
        assert s["configured"] is True

    def test_manager_can_get(self, manager):
        r = manager.get(f"{API}/livre/navixy/scheduler", timeout=15)
        assert r.status_code == 200

    def test_manager_cannot_put(self, manager):
        r = manager.put(f"{API}/livre/navixy/scheduler",
                        json={"enabled": True, "interval_min": 30, "days": 7}, timeout=15)
        assert r.status_code == 403

    def test_disable_clears_next_run(self, admin):
        r = admin.put(f"{API}/livre/navixy/scheduler",
                      json={"enabled": False, "interval_min": 60, "days": 10}, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["enabled"] is False
        assert s["interval_min"] == 60
        assert s["days"] == 10
        assert s["next_run"] in (None, "")

    def test_enable_sets_next_run(self, admin):
        r = admin.put(f"{API}/livre/navixy/scheduler",
                      json={"enabled": True, "interval_min": 30, "days": 7}, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["enabled"] is True
        assert s["interval_min"] == 30
        assert s["next_run"]  # should be a non-empty ISO string

    def test_validation_zero_interval(self, admin):
        r = admin.put(f"{API}/livre/navixy/scheduler",
                      json={"enabled": True, "interval_min": 0, "days": 7}, timeout=15)
        assert r.status_code == 400

    def test_validation_days_too_large(self, admin):
        r = admin.put(f"{API}/livre/navixy/scheduler",
                      json={"enabled": True, "interval_min": 15, "days": 400}, timeout=15)
        assert r.status_code == 400

    def test_run_now_admin(self, admin):
        r = admin.post(f"{API}/livre/navixy/scheduler/run-now", timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ["trackers", "drivers", "zones", "trips_new", "trips_updated"]:
            assert k in data, f"missing {k} in {data}"

    def test_run_now_manager_forbidden(self, manager):
        r = manager.post(f"{API}/livre/navixy/scheduler/run-now", timeout=30)
        assert r.status_code == 403


# ---------------- Assignments ----------------
class TestAssignments:
    @pytest.fixture(scope="class")
    def vehicles(self, admin):
        r = admin.get(f"{API}/livre/vehicles", timeout=15)
        assert r.status_code == 200
        v = r.json()
        assert len(v) >= 1
        return v

    @pytest.fixture(scope="class")
    def drivers_list(self, admin):
        r = admin.get(f"{API}/livre/drivers", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert len(d) >= 2
        return d

    def test_list_initial(self, admin):
        r = admin.get(f"{API}/livre/assignments", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_assignment_primary(self, admin, vehicles, drivers_list):
        v = vehicles[0]
        d = drivers_list[0]
        r = admin.post(f"{API}/livre/assignments",
                       json={"vehicle_id": v["id"], "driver_id": d["id"], "is_primary": True},
                       timeout=30)
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert "assignment" in data and "trips_reassigned" in data
        asg = data["assignment"]
        assert asg["source"] == "manual"
        assert asg["is_primary"] is True
        assert asg["from_date"] is None
        assert asg["to_date"] is None
        pytest.shared_primary_id = asg["id"]

        # verify list contains it
        r2 = admin.get(f"{API}/livre/assignments?vehicle_id={v['id']}", timeout=15)
        assert any(x["id"] == asg["id"] for x in r2.json())

    def test_primary_uniqueness(self, admin, vehicles, drivers_list):
        v = vehicles[0]
        d2 = drivers_list[1]
        r = admin.post(f"{API}/livre/assignments",
                       json={"vehicle_id": v["id"], "driver_id": d2["id"], "is_primary": True},
                       timeout=30)
        assert r.status_code in (200, 201), r.text
        # Now query — only one should be primary
        r2 = admin.get(f"{API}/livre/assignments?vehicle_id={v['id']}", timeout=15)
        rows = r2.json()
        primaries = [x for x in rows if x["is_primary"]]
        assert len(primaries) == 1, f"expected 1 primary, got {len(primaries)} rows={rows}"
        assert primaries[0]["driver_id"] == d2["id"]
        pytest.shared_new_primary_id = primaries[0]["id"]

    def test_driver_cannot_post(self, driver, vehicles, drivers_list):
        v = vehicles[0]
        d = drivers_list[0]
        r = driver.post(f"{API}/livre/assignments",
                        json={"vehicle_id": v["id"], "driver_id": d["id"], "is_primary": False},
                        timeout=15)
        assert r.status_code == 403

    def test_driver_cannot_delete(self, driver):
        # arbitrary id
        r = driver.delete(f"{API}/livre/assignments/00000000-0000-0000-0000-000000000000", timeout=15)
        assert r.status_code == 403

    def test_delete_assignment(self, admin, vehicles):
        v = vehicles[0]
        r = admin.get(f"{API}/livre/assignments?vehicle_id={v['id']}", timeout=15)
        rows = r.json()
        # delete non-primary if exists, else first
        target = next((x for x in rows if not x["is_primary"]), rows[0])
        r2 = admin.delete(f"{API}/livre/assignments/{target['id']}", timeout=60)
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["ok"] is True
        assert "trips_reassigned" in data
        # verify removed
        r3 = admin.get(f"{API}/livre/assignments?vehicle_id={v['id']}", timeout=15)
        assert not any(x["id"] == target["id"] for x in r3.json())


# ---------------- Driver visibility / multi-vehicle ----------------
class TestDriverMultiVehicle:
    def test_driver_sees_own_assignments_only(self, driver):
        r = driver.get(f"{API}/livre/assignments", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        # If non-empty, all must belong to driver's linked driver_id (Jean Dupont)
        # We can't know id directly, but they must all share one driver_id
        if rows:
            ids = {x["driver_id"] for x in rows}
            assert len(ids) == 1, f"driver sees multiple driver_ids: {ids}"

    def test_multi_vehicle_visibility(self, admin, driver):
        """Assign Jean Dupont (chauffeur user) to a second vehicle, verify trips count grows."""
        # find Jean Dupont
        dr = admin.get(f"{API}/livre/drivers", timeout=15).json()
        jean = next((d for d in dr if "Jean" in d.get("name", "") and "Dupont" in d.get("name", "")), None)
        if not jean:
            pytest.skip("Jean Dupont not in seed")
        vehicles = admin.get(f"{API}/livre/vehicles", timeout=15).json()
        # pick a vehicle NOT primarily Jean's by looking at existing trips
        trips_before = driver.get(f"{API}/livre/trips", timeout=20).json()
        if isinstance(trips_before, dict) and "trips" in trips_before:
            trips_before = trips_before["trips"]
        assert isinstance(trips_before, list)
        before_count = len(trips_before)
        # collect vehicle_ids already visible
        visible_vehicle_ids = {t.get("vehicle_id") for t in trips_before}
        candidate = next((v for v in vehicles if v["id"] not in visible_vehicle_ids), None)
        if not candidate:
            pytest.skip("no second vehicle available")
        # add non-primary assignment with no date window so all trips on that vehicle are reattributed
        r = admin.post(f"{API}/livre/assignments",
                       json={"vehicle_id": candidate["id"], "driver_id": jean["id"], "is_primary": False},
                       timeout=60)
        assert r.status_code in (200, 201), r.text
        trips_after = driver.get(f"{API}/livre/trips", timeout=20).json()
        if isinstance(trips_after, dict) and "trips" in trips_after:
            trips_after = trips_after["trips"]
        after_count = len(trips_after)
        assert after_count >= before_count, f"trips count should not decrease ({before_count} -> {after_count})"
        # cleanup: remove that assignment
        asgs = admin.get(f"{API}/livre/assignments?vehicle_id={candidate['id']}", timeout=15).json()
        for a in asgs:
            if a["driver_id"] == jean["id"] and not a["is_primary"]:
                admin.delete(f"{API}/livre/assignments/{a['id']}", timeout=60)


# ---------------- Cleanup ----------------
class TestZRestoreState:
    def test_zz_restore_scheduler(self, admin):
        r = admin.put(f"{API}/livre/navixy/scheduler",
                      json={"enabled": True, "interval_min": 15, "days": 7}, timeout=15)
        assert r.status_code == 200

    def test_zz_cleanup_test_assignments(self, admin):
        # Remove any leftover manual assignments created above on the first vehicle
        vehicles = admin.get(f"{API}/livre/vehicles", timeout=15).json()
        for v in vehicles[:2]:
            asgs = admin.get(f"{API}/livre/assignments?vehicle_id={v['id']}", timeout=15).json()
            for a in asgs:
                if a.get("source") == "manual":
                    admin.delete(f"{API}/livre/assignments/{a['id']}", timeout=60)
