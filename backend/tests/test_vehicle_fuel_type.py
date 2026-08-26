"""MOTORISATIONS RÉELLES — vehicles.fuel_type (T1–T18, T UI via testing agent).

Règles : motorisation UNIQUEMENT depuis une source factuelle prouvée
(ici : garage Navixy réel, champ structuré fuel_type, lié par tracker_id).
JAMAIS déduite du label/plaque/modèle commercial. Sans preuve → UNKNOWN (null).
Historique trips jamais recalculé. Energy jamais modifié.
"""
import os
import uuid

import pymongo
import pytest
import requests

from app import navixy_sync as ns

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"

AUDI_ID = "f9d6984f-f902-4a75-a703-32a51ea0b80d"       # LOGITRAK AUDI (tracker 781479)
ALLIANCE_ID = "669cd347-a78a-4da2-97ab-5b2b9e1a5c65"   # 5-Alliance 01 (tracker 3131157)
# Véhicules aux noms commerciaux évocateurs — SANS preuve structurée → doivent rester UNKNOWN
NAME_TRAP_IDS = {
    "878f3577-4411-4ea1-ab1a-44de18735cef": "KAIO Renault Zoe",
    "85de6367-8da5-43ff-acb2-ad8dcdbe711d": "Skoda Enyaq BE 579 928",
    "a8f5bce5-437e-46ab-87af-03e8f4aea0fb": "KAIO Volvo EX30 08",
    "0219ef8f-8523-44d2-a726-0445818132c2": "1-Enyaq 01 Bern",
    "b3151ad3-40b9-4b7b-b948-ded5e35f3cb3": "GE 123456 (Mercedes Sprinter)",
}
PILOT_TRIP = "8be7b16f-ff74-4262-a1ff-1735f085c3d4"


def _login(email, password):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login("admin@logitrak.ch", "admin123")


@pytest.fixture(scope="module")
def lecture_h():
    return _login("lecture@logitrak.ch", "lecture123")


@pytest.fixture(scope="module")
def admin_b_h():
    return _login("admin-b@test.ch", "testb123")


@pytest.fixture(scope="module")
def mongo():
    mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    yield mc[os.environ["DB_NAME"]]
    mc.close()


# ---------------------------------------------------------------------------
# T1 — source prouvée → fuel_type écrit (état réel post-lot)
# ---------------------------------------------------------------------------
class TestProvenSources:
    def test_t1_audi_essence_written(self, mongo):
        v = mongo.vehicles.find_one({"id": AUDI_ID}, {"_id": 0, "fuel_type": 1})
        assert v["fuel_type"] == "essence"  # garage Navixy fuel_type=petrol prouvé

    def test_t1_alliance_essence_written(self, mongo):
        v = mongo.vehicles.find_one({"id": ALLIANCE_ID}, {"_id": 0, "fuel_type": 1})
        assert v["fuel_type"] == "essence"

    def test_t14_audit_before_after(self, admin_h):
        # No-op update traçant : garantit une entrée d'audit fraîche même si
        # d'autres suites ont rempli le journal entre-temps.
        r0 = requests.put(f"{API}/livre/vehicles/{AUDI_ID}/fuel-type",
                          json={"fuel_type": "essence",
                                "source": "navixy_garage:test_t14 no-op"},
                          headers=admin_h, timeout=15)
        assert r0.status_code == 200
        r = requests.get(f"{API}/livre/audit-log", params={"limit": 50},
                         headers=admin_h, timeout=20)
        assert r.status_code == 200
        rows = r.json()
        hits = [x for x in rows if x.get("action") == "vehicle.fuel_type_updated"
                and (x.get("details") or {}).get("vehicle_id") == AUDI_ID]
        assert hits, "audit vehicle.fuel_type_updated manquant pour l'Audi"
        d = hits[0]["details"]
        assert d["before"] == "essence" and d["after"] == "essence"
        assert "navixy_garage" in (d.get("source") or "")


# ---------------------------------------------------------------------------
# T2–T6 — sans preuve → UNKNOWN ; jamais de déduction label/plaque/modèle
# ---------------------------------------------------------------------------
class TestNoGuessing:
    def test_t2_no_source_stays_unknown(self, mongo):
        n = mongo.vehicles.count_documents(
            {"tenant_id": "default", "fuel_type": {"$nin": [None, ""]}})
        assert n == 2, "seuls les 2 véhicules PROUVÉS doivent être renseignés"

    def test_t3_ambiguous_value_rejected(self, admin_h):
        # 'gas' (vu dans Navixy) est ambigu (GPL/gasoline) → hors vocabulaire → 400
        r = requests.put(f"{API}/livre/vehicles/{AUDI_ID}/fuel-type",
                         json={"fuel_type": "gas"}, headers=admin_h, timeout=15)
        assert r.status_code == 400

    def test_t4_t5_t6_no_deduction_from_names(self, mongo):
        # Zoe/Enyaq/EX30/Sprinter : évidents humainement, INTERDITS sans preuve.
        for vid, label in NAME_TRAP_IDS.items():
            v = mongo.vehicles.find_one({"id": vid}, {"_id": 0, "fuel_type": 1})
            assert v is not None, f"{label} introuvable"
            assert v.get("fuel_type") in (None, ""), \
                f"{label} : motorisation déduite du nom — INTERDIT"


# ---------------------------------------------------------------------------
# T7–T11 — garde-fou legacy conforme aux motorisations prouvées
# ---------------------------------------------------------------------------
class TestGuardrailBehaviour:
    def test_t7_bev_blocks_legacy(self):
        assert ns.legacy_fuel_estimation_allowed({"fuel_type": "electric"}) is False

    def test_t8_hev_no_legacy(self):
        assert ns.legacy_fuel_estimation_allowed({"fuel_type": "hybrid"}) is False

    def test_t9_phev_no_legacy(self):
        assert ns.legacy_fuel_estimation_allowed({"fuel_type": "phev"}) is False

    def test_t10_ice_legacy_allowed(self, mongo):
        audi = mongo.vehicles.find_one({"id": AUDI_ID}, {"_id": 0})
        assert ns.powertrain_from_fuel_type(audi["fuel_type"]) == "ICE"
        assert ns.legacy_fuel_estimation_allowed(audi) is True

    def test_t11_unknown_behaviour_preserved(self, mongo):
        v = mongo.vehicles.find_one({"id": list(NAME_TRAP_IDS)[0]}, {"_id": 0})
        assert ns.powertrain_from_fuel_type(v.get("fuel_type")) == "UNKNOWN"
        assert ns.legacy_fuel_estimation_allowed(v) is True  # dette résiduelle documentée


# ---------------------------------------------------------------------------
# T12/T13/T18 — RBAC + isolation tenant
# ---------------------------------------------------------------------------
class TestRbacAndTenant:
    def test_t12_lecture_403(self, lecture_h):
        r = requests.put(f"{API}/livre/vehicles/{AUDI_ID}/fuel-type",
                         json={"fuel_type": "diesel"}, headers=lecture_h, timeout=15)
        assert r.status_code == 403

    def test_t13_admin_allowed_and_reversible(self, admin_h, mongo):
        r = requests.put(f"{API}/livre/vehicles/{AUDI_ID}/fuel-type",
                         json={"fuel_type": None, "source": "test_t13"},
                         headers=admin_h, timeout=15)
        assert r.status_code == 200
        assert mongo.vehicles.find_one({"id": AUDI_ID})["fuel_type"] is None
        r2 = requests.put(f"{API}/livre/vehicles/{AUDI_ID}/fuel-type",
                          json={"fuel_type": "essence",
                                "source": "navixy_garage:restauration test_t13"},
                          headers=admin_h, timeout=15)
        assert r2.status_code == 200
        assert mongo.vehicles.find_one({"id": AUDI_ID})["fuel_type"] == "essence"

    def test_t18_tenant_isolation(self, admin_b_h):
        # Admin du tenant B : le véhicule du tenant default est invisible → 404
        r = requests.put(f"{API}/livre/vehicles/{AUDI_ID}/fuel-type",
                         json={"fuel_type": "diesel"}, headers=admin_b_h, timeout=15)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# T15/T16/T17 — historique intact, Energy non modifié, TripEnergyBlock OK
# ---------------------------------------------------------------------------
class TestNoSideEffects:
    def test_t15_history_untouched(self, mongo):
        pilot = mongo.trips.find_one({"id": PILOT_TRIP}, {"_id": 0, "fuel_l": 1})
        assert pilot and pilot.get("fuel_l") == 0.66  # jamais recalculé
        n = mongo.trips.count_documents({"fuel_l": {"$exists": True}})
        assert n >= 5000

    def test_t16_energy_not_modified(self, admin_h):
        r = requests.get(f"{API}/livre/energy/status", headers=admin_h, timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["mode"] == "real" and b["energy_tenant_configured"] is True

    def test_t17_trip_energy_block_independent(self, admin_h):
        # L'enveloppe Energy du trajet pilote AUDI reste pilotée par Energy,
        # pas par le nouveau fuel_type Journal (Energy powertrain = source Energy).
        r = requests.post(f"{API}/livre/energy/trips",
                          json={"trip_ids": [PILOT_TRIP]}, headers=admin_h, timeout=60)
        assert r.status_code == 200
        env = r.json()["results"][0]
        assert env["trip_id"] == PILOT_TRIP
        assert env["powertrain"] in ("UNKNOWN", "ICE", "HEV", "PHEV", "BEV", None)
        if env["availability"] == "UNAVAILABLE":
            fuel = env.get("fuel") or {}
            for m in fuel.values():
                if isinstance(m, dict):
                    assert m.get("value") is None  # jamais le legacy injecté
