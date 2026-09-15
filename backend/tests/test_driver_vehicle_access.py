"""ACCÈS VÉHICULES PAR CHAUFFEUR — ALL / SELECTED / SINGLE (T1–T20).

Source d'autorité backend : app/vehicle_access.py + PUT /team/drivers/{id}/vehicle-access.
Chauffeur de test : chauffeur@logitrak.ch (driver « Jean Dupont », tenant default).
Aucune session de conduite n'est créée (les claims testés sont tous REFUSÉS 403).
L'état d'origine du chauffeur (aucun champ = ALL implicite) est restauré en teardown.
"""
import os
import uuid

import pymongo
import pytest
import requests

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DRIVER_ID = "1580345e-6b8e-45a2-88e7-513a008b6b12"  # Jean Dupont (chauffeur@logitrak.ch)


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def driver_h():
    return _login("chauffeur@logitrak.ch", "chauffeur123")


@pytest.fixture(scope="module")
def manager_h():
    return _login("manager@logitrak.ch", "manager123")


@pytest.fixture(scope="module")
def admin_b_h():
    return _login("admin-b@test.ch", "testb123")


@pytest.fixture(scope="module")
def mongo():
    mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    yield mc[os.environ["DB_NAME"]]
    mc.close()


@pytest.fixture(scope="module")
def env(mongo):
    """Véhicules de test : A/B/C/D actifs (default), 1 inactif, 1 tenant B."""
    tag = uuid.uuid4().hex[:8]
    tenant_b = mongo.users.find_one({"email": "admin-b@test.ch"})["tenant_id"]
    vehicles = []
    for name in ("A", "B", "C", "D"):
        vehicles.append({"id": f"va-{name.lower()}-{tag}", "tenant_id": "default",
                         "plate": f"VA-{name}-{tag}", "label": f"Test Access {name}"})
    inactive = {"id": f"va-inactive-{tag}", "tenant_id": "default",
                "plate": f"VA-INACTIVE-{tag}", "label": "Test inactif", "active": False}
    cross = {"id": f"va-cross-{tag}", "tenant_id": tenant_b,
             "plate": f"VA-CROSS-{tag}", "label": "Test cross-tenant"}
    mongo.vehicles.insert_many([dict(v) for v in vehicles] + [dict(inactive), dict(cross)])
    baseline_assignment_ids = [a["id"] for a in
                               mongo.assignments.find({}, {"_id": 0, "id": 1})]
    yield {"A": vehicles[0]["id"], "B": vehicles[1]["id"], "C": vehicles[2]["id"],
           "D": vehicles[3]["id"], "inactive": inactive["id"], "cross": cross["id"],
           "tenant_b": tenant_b, "baseline_assignment_ids": baseline_assignment_ids}
    mongo.vehicles.delete_many({"id": {"$regex": f"^va-.*-{tag}$"}})
    mongo.drivers.update_one({"id": DRIVER_ID}, {"$unset": {
        "vehicle_access_mode": "", "allowed_vehicle_ids": "", "default_vehicle_id": ""}})


def _put_access(h, body, driver_id=DRIVER_ID):
    return requests.put(f"{API}/livre/team/drivers/{driver_id}/vehicle-access",
                        json=body, headers=h, timeout=20)


def _my_vehicles(h):
    r = requests.get(f"{API}/livre/driver/vehicles", headers=h, timeout=20)
    assert r.status_code == 200
    return r.json()


def _claim(h, vehicle_id):
    return requests.post(f"{API}/livre/driver/claim",
                         json={"vehicle_id": vehicle_id}, headers=h, timeout=20)


class TestDefaultBehaviourAndAll:
    def test_implicit_all_before_any_config(self, driver_h, env):
        """Migration douce : champ absent = ALL (comportement historique préservé)."""
        body = _my_vehicles(driver_h)
        assert body["access_mode"] == "ALL"
        ids = {v["id"] for v in body["vehicles"]}
        assert env["A"] in ids

    def test_t1_all_returns_all_active_tenant_vehicles(self, admin_h, driver_h, env):
        assert _put_access(admin_h, {"mode": "ALL", "vehicle_ids": []}).status_code == 200
        body = _my_vehicles(driver_h)
        ids = {v["id"] for v in body["vehicles"]}
        for k in ("A", "B", "C", "D"):
            assert env[k] in ids
        assert len(ids) >= 18

    def test_t2_all_never_cross_tenant(self, driver_h, env):
        ids = {v["id"] for v in _my_vehicles(driver_h)["vehicles"]}
        assert env["cross"] not in ids, "ALL = ALL_WITHIN_DRIVER_TENANT uniquement"

    def test_t12_inactive_vehicle_not_returned(self, driver_h, env):
        ids = {v["id"] for v in _my_vehicles(driver_h)["vehicles"]}
        assert env["inactive"] not in ids


class TestSelected:
    def test_t3_selected_exactly_four(self, admin_h, driver_h, env):
        four = [env["A"], env["B"], env["C"], env["D"]]
        r = _put_access(admin_h, {"mode": "SELECTED", "vehicle_ids": four,
                                  "default_vehicle_id": env["A"]})
        assert r.status_code == 200
        body = _my_vehicles(driver_h)
        assert body["access_mode"] == "SELECTED"
        assert {v["id"] for v in body["vehicles"]} == set(four)
        assert body["default_vehicle_id"] == env["A"]

    def test_t4_unselected_vehicle_claim_403(self, admin_h, driver_h, mongo, env):
        real = mongo.vehicles.find_one(
            {"tenant_id": "default", "id": {"$regex": "^(?!va-)"}}, {"id": 1})
        r = _claim(driver_h, real["id"])
        assert r.status_code == 403, "véhicule du même tenant hors sélection → 403"

    def test_t17_shrink_selection_immediately_enforced(self, admin_h, driver_h, env):
        r = _put_access(admin_h, {"mode": "SELECTED",
                                  "vehicle_ids": [env["A"], env["B"]]})
        assert r.status_code == 200
        ids = {v["id"] for v in _my_vehicles(driver_h)["vehicles"]}
        assert ids == {env["A"], env["B"]}
        assert _claim(driver_h, env["C"]).status_code == 403
        assert _claim(driver_h, env["D"]).status_code == 403

    def test_t19_default_removed_no_arbitrary_selection(self, admin_h, driver_h, env):
        _put_access(admin_h, {"mode": "SELECTED", "vehicle_ids": [env["A"], env["B"]],
                              "default_vehicle_id": env["A"]})
        r = _put_access(admin_h, {"mode": "SELECTED", "vehicle_ids": [env["B"]],
                                  "default_vehicle_id": None})
        assert r.status_code == 200
        body = _my_vehicles(driver_h)
        assert body["default_vehicle_id"] is None, "jamais de véhicule arbitraire"

    def test_selected_empty_rejected(self, admin_h):
        assert _put_access(admin_h, {"mode": "SELECTED", "vehicle_ids": []}).status_code == 400


class TestSingle:
    def test_t5_single_exactly_one(self, admin_h, driver_h, env):
        r = _put_access(admin_h, {"mode": "SINGLE", "vehicle_ids": [env["A"]]})
        assert r.status_code == 200
        body = _my_vehicles(driver_h)
        assert body["access_mode"] == "SINGLE"
        assert [v["id"] for v in body["vehicles"]] == [env["A"]]
        assert body["default_vehicle_id"] == env["A"]  # default = le véhicule unique

    def test_t6_single_other_same_tenant_403(self, driver_h, env):
        assert _claim(driver_h, env["B"]).status_code == 403

    def test_t18_all_to_single_only_single_remains(self, admin_h, driver_h, env):
        _put_access(admin_h, {"mode": "ALL", "vehicle_ids": []})
        _put_access(admin_h, {"mode": "SINGLE", "vehicle_ids": [env["B"]]})
        body = _my_vehicles(driver_h)
        assert [v["id"] for v in body["vehicles"]] == [env["B"]]
        assert _claim(driver_h, env["A"]).status_code == 403

    def test_single_two_vehicles_rejected(self, admin_h, env):
        r = _put_access(admin_h, {"mode": "SINGLE",
                                  "vehicle_ids": [env["A"], env["B"]]})
        assert r.status_code == 400


class TestDefaultVehicleRules:
    def test_t7_default_in_allowed_accepted(self, admin_h, env):
        r = _put_access(admin_h, {"mode": "SELECTED",
                                  "vehicle_ids": [env["A"], env["B"]],
                                  "default_vehicle_id": env["B"]})
        assert r.status_code == 200
        assert r.json()["default_vehicle_id"] == env["B"]

    def test_t8_default_outside_allowed_rejected(self, admin_h, env):
        r = _put_access(admin_h, {"mode": "SELECTED",
                                  "vehicle_ids": [env["A"], env["B"]],
                                  "default_vehicle_id": env["C"]})
        assert r.status_code == 400

    def test_t8b_all_default_cross_tenant_rejected(self, admin_h, env):
        r = _put_access(admin_h, {"mode": "ALL", "vehicle_ids": [],
                                  "default_vehicle_id": env["cross"]})
        assert r.status_code == 400


class TestCrossTenantAndRbac:
    def test_t9_admin_b_cannot_configure_default_tenant_driver(self, admin_b_h, env):
        r = _put_access(admin_b_h, {"mode": "ALL", "vehicle_ids": []})
        assert r.status_code == 404, "chauffeur invisible cross-tenant"

    def test_t10_selected_with_cross_tenant_vehicle_rejected(self, admin_h, env):
        r = _put_access(admin_h, {"mode": "SELECTED", "vehicle_ids": [env["cross"]]})
        assert r.status_code == 400

    def test_t13_driver_cannot_modify(self, driver_h, env):
        r = _put_access(driver_h, {"mode": "ALL", "vehicle_ids": []})
        assert r.status_code == 403

    def test_manager_cannot_modify(self, manager_h, env):
        r = _put_access(manager_h, {"mode": "ALL", "vehicle_ids": []})
        assert r.status_code == 403

    def test_t14_admin_can_modify_and_audited(self, admin_h, env):
        r = _put_access(admin_h, {"mode": "SELECTED", "vehicle_ids": [env["A"]],
                                  "default_vehicle_id": env["A"]})
        assert r.status_code == 200
        rows = requests.get(f"{API}/livre/audit-log", params={"limit": 30},
                            headers=admin_h, timeout=20).json()
        hits = [x for x in rows if x.get("action") == "driver.vehicle_access_updated"
                and (x.get("details") or {}).get("driver_id") == DRIVER_ID]
        assert hits, "audit driver.vehicle_access_updated manquant"
        d = hits[0]["details"]
        assert "previous_access_mode" in d and d["new_access_mode"] == "SELECTED"
        assert d["new_vehicle_ids"] == [env["A"]]


class TestNoVehicleAndInactive:
    def test_t11_only_inactive_vehicle_yields_empty_list(self, admin_h, driver_h,
                                                         mongo, env):
        _put_access(admin_h, {"mode": "SINGLE", "vehicle_ids": [env["D"]]})
        mongo.vehicles.update_one({"id": env["D"]}, {"$set": {"active": False}})
        try:
            body = _my_vehicles(driver_h)
            assert body["vehicles"] == [], "aucun fallback vers d'autres véhicules"
            assert body["default_vehicle_id"] is None, "default invalidé proprement"
            assert _claim(driver_h, env["D"]).status_code == 403
        finally:
            mongo.vehicles.update_one({"id": env["D"]}, {"$set": {"active": True}})


class TestExistingAssignmentsPreserved:
    def test_t15_t16_assignments_untouched(self, mongo, env):
        # Invariant du lot : les opérations vehicle-access ne créent/suppriment
        # JAMAIS d'assignment. Chaque affectation existante au démarrage du module
        # doit toujours exister (robuste aux données de test d'autres suites).
        ids = env["baseline_assignment_ids"]
        still = mongo.assignments.count_documents({"id": {"$in": ids}})
        assert still == len(ids), "aucune affectation existante ne doit être supprimée"
        # Les 4 affectations réelles Navixy d'origine restent intactes.
        navixy_count = mongo.assignments.count_documents(
            {"id": {"$in": ids}, "source": "navixy"})
        assert navixy_count >= 4, "les affectations Navixy réelles doivent être conservées"


class TestBusinessEndpointsScope:
    def test_t20_fleet_tags_scoped(self, admin_h, driver_h, env):
        """API métier (tags BLE) : jamais de tag d'un véhicule hors périmètre."""
        _put_access(admin_h, {"mode": "SINGLE", "vehicle_ids": [env["A"]]})
        r = requests.get(f"{API}/livre/driver/fleet-tags", headers=driver_h, timeout=20)
        assert r.status_code == 200
        plates = {t.get("vehicle_plate") for t in r.json() if t.get("vehicle_plate")}
        allowed_plate_prefix = "VA-A-"
        for p in plates:
            assert p.startswith(allowed_plate_prefix) or p is None, \
                f"tag d'un véhicule hors périmètre exposé : masqué"

    def test_restore_all_final(self, admin_h, driver_h, env):
        """Remet le chauffeur en ALL (état effectif historique) avant teardown."""
        assert _put_access(admin_h, {"mode": "ALL", "vehicle_ids": []}).status_code == 200
        assert _my_vehicles(driver_h)["access_mode"] == "ALL"
