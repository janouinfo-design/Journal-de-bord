"""Phase 3 regression — Fiche Admin Chauffeur + KPI Identification + Je m'arrête.

Suite backend uniquement. Le frontend est testé via Playwright séparément.
Tous les artefacts créés (drivers/users/sessions/tags/login_attempts) sont
nettoyés à la fin de la classe pour ne pas perturber la démo. En particulier
AUCUN ble_id ne doit rester posé sur un chauffeur de la démo à la fin
(le scheduler Navixy consommerait la clé Client).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

frontend_env = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL")
        or frontend_env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE:
    raise RuntimeError("REACT_APP_BACKEND_URL manquant")

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env.get("MONGO_URL") or os.environ["MONGO_URL"]
DB_NAME = backend_env.get("DB_NAME") or os.environ["DB_NAME"]

ADMIN = ("admin@logitrak.ch", "admin123")
DRIVER = ("chauffeur@logitrak.ch", "chauffeur123")   # Jean Dupont
PAUL = ("paul.test@client.ch", "paul1234")
ADMIN_B = ("admin-b@test.ch", "testb123")
JEAN_ID = "1580345e-6b8e-45a2-88e7-513a008b6b12"
PAUL_ID = "315c46f5-e1cd-4daf-9cb2-396735f8de5f"


def login(email, password):
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    return r


def _tok(email, password):
    r = login(email, password)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def admin_tok():
    return _tok(*ADMIN)


@pytest.fixture(scope="module")
def admin_b_tok():
    r = login(*ADMIN_B)
    if r.status_code != 200:
        pytest.skip(f"admin-b login indisponible: {r.status_code}")
    return r.json()["access_token"]


_LOOP = None


def _loop():
    """Boucle asyncio dédiée au module — les suites précédentes peuvent avoir
    fermé la boucle du MainThread (get_event_loop est déprécié/fragile)."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


def _run(coro):
    return _loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _ensure_loop():
    # Les coroutines Motor sont construites au call-site (avant _run) :
    # la policy asyncio doit avoir une boucle valide avant CHAQUE test,
    # même si un module/test précédent l'a remise à None (asyncio.run).
    _loop()
    yield


@pytest.fixture(scope="module")
def mongo():
    _loop()
    cli = AsyncIOMotorClient(MONGO_URL)
    return cli[DB_NAME]


@pytest.fixture(scope="module")
def created():
    """Registry of test artifacts to clean at teardown."""
    return {"driver_ids": [], "user_ids": [], "emails": [], "session_ids": [],
            "tags_touched_drivers": [], "temp_ble": []}


@pytest.fixture(scope="module", autouse=True)
def _cleanup(created, admin_tok):
    yield
    hdr = _h(admin_tok)
    # Retirer les ble_id posés sur les vrais chauffeurs (Jean/Paul) pendant les tests
    for did in set(created["tags_touched_drivers"]):
        try:
            requests.patch(f"{BASE}/api/livre/team/drivers/{did}",
                           headers=hdr, json={"ble_id": None}, timeout=10)
        except Exception:
            pass
    # Fermer les sessions test résiduelles
    import asyncio
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    async def _wipe():
        # sessions des drivers test
        for did in set(created["driver_ids"]):
            await db.driver_sessions.update_many(
                {"driver_id": did, "status": {"$nin": ["closed"]}},
                {"$set": {"status": "closed",
                          "ended_at": datetime.now(timezone.utc).isoformat(),
                          "active_driver": False, "end_reason": "test_cleanup"}})
            await db.drivers.delete_one({"id": did})
        for uid in set(created["user_ids"]):
            await db.users.delete_one({"id": uid})
        for em in set(created["emails"]):
            await db.login_attempts.delete_many({"identifier": em.lower()})
        # Sécurité : rien ne doit rester sur Jean/Paul
        await db.drivers.update_many(
            {"id": {"$in": [JEAN_ID, PAUL_ID]}, "ble_id": {"$ne": None}},
            {"$set": {"ble_id": None, "ble_id_norm": None}})
        # Fermer résidus sur Jean/Paul créés par les tests
        await db.driver_sessions.update_many(
            {"driver_id": {"$in": [JEAN_ID, PAUL_ID]},
             "status": {"$nin": ["closed"]},
             "$or": [{"end_reason": {"$exists": False}}, {"end_reason": None}]},
            {"$set": {"status": "closed",
                      "ended_at": datetime.now(timezone.utc).isoformat(),
                      "active_driver": False, "end_reason": "test_cleanup"}})
    _run(_wipe())


def _make_test_driver(admin_tok, with_account=True, ble_id=None):
    """Create a fresh test driver (and optional linked account)."""
    tid = uuid.uuid4().hex[:8]
    body = {"first_name": "Ivan", "last_name": f"Petrov{tid}",
            "internal_number": f"T-{tid}"}
    if ble_id:
        body["ble_id"] = ble_id
    r = requests.post(f"{BASE}/api/livre/team/drivers",
                      headers=_h(admin_tok), json=body, timeout=15)
    assert r.status_code == 200, r.text
    drv = r.json()
    email = f"ivan.{tid}@example.com"
    pwd = "testpwd12345"
    user_id = None
    if with_account:
        rg = requests.post(f"{BASE}/api/livre/team/drivers/{drv['id']}/grant-access",
                           headers=_h(admin_tok), json={"email": email, "password": pwd}, timeout=15)
        assert rg.status_code == 200, rg.text
        user_id = rg.json()["user_id"]
    return {"driver_id": drv["id"], "user_id": user_id, "email": email,
            "password": pwd, "name": f"Ivan Petrov{tid}"}


# ================================================================
# TEST A — Overview endpoint
# ================================================================
class TestA_Overview:
    def test_admin_overview_jean(self, admin_tok):
        r = requests.get(f"{BASE}/api/livre/team/drivers/{JEAN_ID}/overview",
                         headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Sections requises
        for k in ("driver", "account", "identification",
                  "current_session", "sessions", "events", "last_activity"):
            assert k in data, f"clé manquante: {k}"
        assert data["driver"]["id"] == JEAN_ID
        assert data["account"] is not None
        assert data["account"]["email"] == "chauffeur@logitrak.ch"
        # identification.app + identification.ble structurés
        ident = data["identification"]
        assert "app" in ident and "ble" in ident
        assert set(ident["app"].keys()) >= {"enabled", "last_login_at", "last_claim_at"}
        assert ident["app"]["enabled"] is True
        assert set(ident["ble"].keys()) >= {"tag", "last_detection_at", "field_validation_note"}
        # Note terrain BLE en attente
        assert ident["ble"]["field_validation_note"] == "Validation terrain BLE en attente"
        # sessions ≤ 20, events ≤ 15
        assert isinstance(data["sessions"], list) and len(data["sessions"]) <= 20
        assert isinstance(data["events"], list) and len(data["events"]) <= 15
        # sessions doivent toutes concerner Jean
        for s in data["sessions"]:
            assert s["driver_id"] == JEAN_ID
            assert "vehicle_plate" in s

    def test_manager_can_read_overview(self, admin_tok, created):
        # créer manager temporaire
        mem = f"mgr.{uuid.uuid4().hex[:6]}@example.com"
        rc = requests.post(f"{BASE}/api/auth/register",
                           headers=_h(admin_tok),
                           json={"email": mem, "password": "mgrpwd123",
                                 "name": "Mgr Test", "role": "manager"}, timeout=15)
        assert rc.status_code in (200, 201), rc.text
        mtok = _tok(mem, "mgrpwd123")
        try:
            r = requests.get(f"{BASE}/api/livre/team/drivers/{JEAN_ID}/overview",
                             headers=_h(mtok), timeout=15)
            assert r.status_code == 200, r.text
        finally:
            # cleanup manager
            uid = None
            lst = requests.get(f"{BASE}/api/livre/team/users",
                               headers=_h(admin_tok), timeout=10).json()
            for u in lst:
                if u["email"] == mem:
                    uid = u["id"]
                    break
            if uid:
                requests.delete(f"{BASE}/api/livre/team/users/{uid}",
                                headers=_h(admin_tok), timeout=10)

    def test_overview_404_unknown(self, admin_tok):
        r = requests.get(f"{BASE}/api/livre/team/drivers/nope-{uuid.uuid4()}/overview",
                         headers=_h(admin_tok), timeout=10)
        assert r.status_code == 404


# ================================================================
# TEST B — Désactivation driver + user
# ================================================================
class TestB_Disable:
    def test_disable_driver_blocks_login(self, admin_tok, created):
        drv = _make_test_driver(admin_tok)
        created["driver_ids"].append(drv["driver_id"])
        created["user_ids"].append(drv["user_id"])
        created["emails"].append(drv["email"])

        # login OK au départ
        assert login(drv["email"], drv["password"]).status_code == 200
        # disable driver
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{drv['driver_id']}",
                           headers=_h(admin_tok), json={"active": False}, timeout=10)
        assert r.status_code == 200
        # login refusé
        assert login(drv["email"], drv["password"]).status_code == 401
        # réactivation
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{drv['driver_id']}",
                           headers=_h(admin_tok), json={"active": True}, timeout=10)
        assert r.status_code == 200
        # login à nouveau OK (nettoyage brute force)
        # supprimer d'éventuels login_attempts posés par les tentatives ratées
        import asyncio
        cli = AsyncIOMotorClient(MONGO_URL)
        _run(
            cli[DB_NAME].login_attempts.delete_many({"identifier": drv["email"].lower()}))
        assert login(drv["email"], drv["password"]).status_code == 200

    def test_disable_user_blocks_login(self, admin_tok, created):
        drv = _make_test_driver(admin_tok)
        created["driver_ids"].append(drv["driver_id"])
        created["user_ids"].append(drv["user_id"])
        created["emails"].append(drv["email"])
        r = requests.patch(f"{BASE}/api/livre/team/users/{drv['user_id']}",
                           headers=_h(admin_tok), json={"active": False}, timeout=10)
        assert r.status_code == 200
        assert login(drv["email"], drv["password"]).status_code == 401
        # réactivation
        r = requests.patch(f"{BASE}/api/livre/team/users/{drv['user_id']}",
                           headers=_h(admin_tok), json={"active": True}, timeout=10)
        assert r.status_code == 200
        import asyncio
        cli = AsyncIOMotorClient(MONGO_URL)
        _run(
            cli[DB_NAME].login_attempts.delete_many({"identifier": drv["email"].lower()}))
        assert login(drv["email"], drv["password"]).status_code == 200


# ================================================================
# TEST C + D — BLE tag assign/remove + duplicate rejection
# ================================================================
class TestCD_BleTag:
    def test_assign_and_remove_tag(self, admin_tok, created):
        drv = _make_test_driver(admin_tok, with_account=False)
        created["driver_ids"].append(drv["driver_id"])
        tag = "AA:BB:CC:DD:EE:51"
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{drv['driver_id']}",
                           headers=_h(admin_tok), json={"ble_id": tag}, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ble_id_norm") == "AABBCCDDEE51"

        # remove
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{drv['driver_id']}",
                           headers=_h(admin_tok), json={"ble_id": None}, timeout=10)
        assert r.status_code == 200
        assert (r.json().get("ble_id") in (None, "")) and (r.json().get("ble_id_norm") in (None, ""))

    def test_duplicate_tag_rejected(self, admin_tok, created):
        drv1 = _make_test_driver(admin_tok, with_account=False)
        drv2 = _make_test_driver(admin_tok, with_account=False)
        created["driver_ids"].extend([drv1["driver_id"], drv2["driver_id"]])
        tag = "AA:BB:CC:DD:EE:52"
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{drv1['driver_id']}",
                           headers=_h(admin_tok), json={"ble_id": tag}, timeout=10)
        assert r.status_code == 200
        # même tag, casse & séparateur différents
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{drv2['driver_id']}",
                           headers=_h(admin_tok),
                           json={"ble_id": "aa-bb-cc-dd-ee-52"}, timeout=10)
        assert r.status_code == 409
        assert "déjà" in (r.json().get("detail") or "").lower()

        # cleanup
        requests.patch(f"{BASE}/api/livre/team/drivers/{drv1['driver_id']}",
                       headers=_h(admin_tok), json={"ble_id": None}, timeout=10)


# ================================================================
# TEST E, F, M, N, O — sessions + stop
# ================================================================
class TestSessions:
    @pytest.fixture(autouse=True)
    def _close_prior(self):
        # Fermer une éventuelle session Jean/Paul restée ouverte
        import asyncio
        cli = AsyncIOMotorClient(MONGO_URL)
        _run(
            cli[DB_NAME].driver_sessions.update_many(
                {"driver_id": {"$in": [JEAN_ID, PAUL_ID]},
                 "status": {"$nin": ["closed"]}},
                {"$set": {"status": "closed",
                          "ended_at": datetime.now(timezone.utc).isoformat(),
                          "active_driver": False, "end_reason": "test_cleanup"}}))
        yield

    def _pick_vehicle(self, admin_tok):
        r = requests.get(f"{BASE}/api/livre/vehicles", headers=_h(admin_tok), timeout=10)
        assert r.status_code == 200
        v = r.json()
        assert len(v) >= 2, "besoin d'au moins 2 véhicules démo"
        return v

    def test_E_claim_session_in_overview(self, admin_tok):
        vehicles = self._pick_vehicle(admin_tok)
        veh = vehicles[0]
        # Purge les détections BLE résiduelles de Jean (laissées par les suites
        # de simulation) : sinon la fusion APP+BLE — comportement produit correct —
        # rend la source différente de "APP".
        import pymongo
        mc = pymongo.MongoClient(MONGO_URL)
        mc[DB_NAME].ble_detections.delete_many({"driver_id": JEAN_ID})
        mc.close()
        jtok = _tok(*DRIVER)
        r = requests.post(f"{BASE}/api/livre/driver/claim",
                          headers=_h(jtok), json={"vehicle_id": veh["id"]}, timeout=15)
        assert r.status_code == 200, r.text
        # overview
        ov = requests.get(f"{BASE}/api/livre/team/drivers/{JEAN_ID}/overview",
                          headers=_h(admin_tok), timeout=10).json()
        cs = ov["current_session"]
        assert cs is not None
        assert cs["vehicle_id"] == veh["id"]
        assert cs.get("identification_source") == "APP"
        assert cs.get("status") == "confirmed"
        # liste enrichie
        lst = requests.get(f"{BASE}/api/livre/team/drivers",
                           headers=_h(admin_tok), timeout=10).json()
        jrow = next((d for d in lst if d["id"] == JEAN_ID), None)
        assert jrow and jrow["current_session"]
        assert jrow["current_session"].get("vehicle_plate") == veh["plate"]

    def test_F_history_only_this_driver(self, admin_tok):
        ov = requests.get(f"{BASE}/api/livre/team/drivers/{JEAN_ID}/overview",
                          headers=_h(admin_tok), timeout=10).json()
        for s in ov["sessions"]:
            assert s["driver_id"] == JEAN_ID

    def test_M_stop_active_session(self, admin_tok):
        jtok = _tok(*DRIVER)
        # s'assurer d'une session active
        vehicles = self._pick_vehicle(admin_tok)
        requests.post(f"{BASE}/api/livre/driver/claim",
                      headers=_h(jtok), json={"vehicle_id": vehicles[0]["id"]}, timeout=15)
        r = requests.post(f"{BASE}/api/livre/driver/stop", headers=_h(jtok), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("stopped") is True
        assert data["session"]["status"] == "closed"
        assert data["session"]["ended_at"]
        assert data["session"]["active_driver"] is False
        # my-vehicle : current=false
        mv = requests.get(f"{BASE}/api/livre/driver/my-vehicle",
                          headers=_h(jtok), timeout=10).json()
        assert mv["current"] is False
        # audit
        import asyncio
        cli = AsyncIOMotorClient(MONGO_URL)
        aud = _run(
            cli[DB_NAME].audit_log.find_one(
                {"action": "driver_session_closed", "driver_id": JEAN_ID,
                 "end_source": "APP"},
                sort=[("ts", -1)]))
        assert aud is not None
        assert aud.get("end_source") == "APP"
        assert aud.get("end_reason") == "app_stop"

    def test_N_stop_without_session_and_idempotent(self):
        jtok = _tok(*DRIVER)
        r1 = requests.post(f"{BASE}/api/livre/driver/stop", headers=_h(jtok), timeout=15)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("stopped") is False
        # 2e appel : idem, jamais 500
        r2 = requests.post(f"{BASE}/api/livre/driver/stop", headers=_h(jtok), timeout=15)
        assert r2.status_code == 200
        assert r2.json().get("stopped") is False

    def test_O_stop_doesnt_touch_other_driver(self, admin_tok):
        vehicles = self._pick_vehicle(admin_tok)
        ptok = _tok(*PAUL)
        # Paul démarre une session
        r = requests.post(f"{BASE}/api/livre/driver/claim",
                          headers=_h(ptok), json={"vehicle_id": vehicles[1]["id"]}, timeout=15)
        assert r.status_code == 200, r.text
        # Jean stop → n'affecte pas Paul
        jtok = _tok(*DRIVER)
        requests.post(f"{BASE}/api/livre/driver/stop", headers=_h(jtok), timeout=10)
        # session Paul toujours active
        ov = requests.get(f"{BASE}/api/livre/team/drivers/{PAUL_ID}/overview",
                          headers=_h(admin_tok), timeout=10).json()
        assert ov["current_session"] is not None
        assert ov["current_session"]["status"] in ("confirmed", "open", "automatic", "pending", "manual")
        # cleanup Paul
        requests.post(f"{BASE}/api/livre/driver/stop", headers=_h(ptok), timeout=10)

    def test_O_admin_stop_400(self, admin_tok):
        r = requests.post(f"{BASE}/api/livre/driver/stop", headers=_h(admin_tok), timeout=10)
        # admin non lié à un chauffeur
        assert r.status_code == 400


# ================================================================
# TEST G/H/I/J/L — Dashboard KPIs
# ================================================================
class TestKPIs:
    def test_dashboard_kpi_keys(self, admin_tok):
        r = requests.get(f"{BASE}/api/livre/ble/dashboard",
                         headers=_h(admin_tok), timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_sessions", "identified_app", "identified_ble",
                  "identified_app_ble", "manual_set", "pending_validation",
                  "conflicts", "success_rate", "trips"):
            assert k in d, f"KPI manquant: {k}"
        assert "unidentified" in d["trips"]

    def test_kpi_matches_mongo_counts(self, admin_tok, mongo):
        r = requests.get(f"{BASE}/api/livre/ble/dashboard",
                         headers=_h(admin_tok), timeout=10)
        d = r.json()
        import asyncio
        loop = _loop()
        n_app = loop.run_until_complete(
            mongo.driver_sessions.count_documents(
                {"tenant_id": "default", "identification_source": "APP"}))
        n_ble = loop.run_until_complete(
            mongo.driver_sessions.count_documents(
                {"tenant_id": "default", "identification_source": "BLE"}))
        n_manual = loop.run_until_complete(
            mongo.driver_sessions.count_documents(
                {"tenant_id": "default",
                 "$or": [{"identification_source": "MANUEL"}, {"status": "manual"}]}))
        assert d["identified_app"] == n_app
        assert d["identified_ble"] == n_ble
        assert d["manual_set"] == n_manual

    def test_J_sessions_filter_by_source(self, admin_tok):
        r = requests.get(f"{BASE}/api/livre/ble/sessions?source=APP",
                         headers=_h(admin_tok), timeout=10)
        assert r.status_code == 200
        for s in r.json():
            assert (s.get("identification_source") or "") == "APP"

    def test_J_sessions_filter_by_driver_and_vehicle(self, admin_tok):
        r = requests.get(f"{BASE}/api/livre/ble/sessions?driver_id={JEAN_ID}",
                         headers=_h(admin_tok), timeout=10)
        assert r.status_code == 200
        for s in r.json():
            assert s["driver_id"] == JEAN_ID

    def test_L_unidentified_from_trips(self, admin_tok, mongo):
        r = requests.get(f"{BASE}/api/livre/ble/dashboard",
                         headers=_h(admin_tok), timeout=10)
        d = r.json()
        import asyncio
        n = _run(
            mongo.trips.count_documents(
                {"tenant_id": "default",
                 "$or": [{"driver_id": None}, {"driver_id": {"$exists": False}}]}))
        assert d["trips"]["unidentified"] == n


# ================================================================
# TEST K — Conflit + résolution
# ================================================================
class TestK_Conflict:
    def test_conflict_created_and_resolved(self, admin_tok, mongo):
        # Fermer sessions actives Jean/Paul
        import asyncio
        loop = _loop()
        loop.run_until_complete(
            mongo.driver_sessions.update_many(
                {"driver_id": {"$in": [JEAN_ID, PAUL_ID]}, "status": {"$nin": ["closed"]}},
                {"$set": {"status": "closed",
                          "ended_at": datetime.now(timezone.utc).isoformat(),
                          "active_driver": False, "end_reason": "test_cleanup"}}))
        vehicles = requests.get(f"{BASE}/api/livre/vehicles",
                                headers=_h(admin_tok), timeout=10).json()
        veh = vehicles[0]
        # Jean claim
        jtok = _tok(*DRIVER)
        r1 = requests.post(f"{BASE}/api/livre/driver/claim",
                           headers=_h(jtok), json={"vehicle_id": veh["id"]}, timeout=15)
        assert r1.status_code == 200, r1.text
        # Paul claim même véhicule dans 10 min
        ptok = _tok(*PAUL)
        r2 = requests.post(f"{BASE}/api/livre/driver/claim",
                           headers=_h(ptok), json={"vehicle_id": veh["id"]}, timeout=15)
        assert r2.status_code == 200, r2.text
        # Trouver la session conflit de Paul
        sess_list = requests.get(
            f"{BASE}/api/livre/ble/sessions?status=conflict",
            headers=_h(admin_tok), timeout=10).json()
        conflict_sess = next((s for s in sess_list if s["driver_id"] == PAUL_ID
                              and s["vehicle_id"] == veh["id"]), None)
        assert conflict_sess is not None, f"pas de conflit trouvé: {sess_list}"
        # Résoudre : Jean gagne
        rr = requests.post(
            f"{BASE}/api/livre/ble/sessions/{conflict_sess['id']}/resolve",
            headers=_h(admin_tok),
            json={"winner_driver_id": JEAN_ID, "source": "page"}, timeout=15)
        assert rr.status_code == 200, rr.text
        # Audit trace
        aud = loop.run_until_complete(
            mongo.audit_log.find_one(
                {"action": {"$in": ["conflict_resolved", "resolve_conflict"]}},
                sort=[("ts", -1)]))
        assert aud is not None
        # Sanity : winner=Jean actif, loser=Paul closed
        winner = loop.run_until_complete(
            mongo.driver_sessions.find_one({"driver_id": JEAN_ID,
                                            "vehicle_id": veh["id"],
                                            "active_driver": True}))
        assert winner is not None
        # cleanup
        loop.run_until_complete(
            mongo.driver_sessions.update_many(
                {"driver_id": {"$in": [JEAN_ID, PAUL_ID]}, "status": {"$nin": ["closed"]}},
                {"$set": {"status": "closed",
                          "ended_at": datetime.now(timezone.utc).isoformat(),
                          "active_driver": False, "end_reason": "test_cleanup"}}))


# ================================================================
# TEST P — Isolation multi-tenant
# ================================================================
class TestP_MultiTenant:
    def test_tenant_b_cannot_see_default_drivers(self, admin_b_tok):
        r = requests.get(f"{BASE}/api/livre/team/drivers",
                         headers=_h(admin_b_tok), timeout=10)
        assert r.status_code == 200
        for d in r.json():
            assert d["id"] != JEAN_ID and d["id"] != PAUL_ID

    def test_tenant_b_overview_404(self, admin_b_tok):
        r = requests.get(f"{BASE}/api/livre/team/drivers/{JEAN_ID}/overview",
                         headers=_h(admin_b_tok), timeout=10)
        assert r.status_code == 404

    def test_tenant_b_patch_404(self, admin_b_tok):
        r = requests.patch(f"{BASE}/api/livre/team/drivers/{JEAN_ID}",
                           headers=_h(admin_b_tok), json={"phone": "0790000000"}, timeout=10)
        assert r.status_code == 404

    def test_tenant_b_reset_pw_404(self, admin_b_tok):
        r = requests.post(f"{BASE}/api/livre/team/drivers/{JEAN_ID}/reset-password",
                          headers=_h(admin_b_tok), timeout=10)
        assert r.status_code == 404


# ================================================================
# TEST Q — Reset password
# ================================================================
class TestQ_ResetPassword:
    def test_reset_password_flow(self, admin_tok, mongo, created):
        drv = _make_test_driver(admin_tok)
        created["driver_ids"].append(drv["driver_id"])
        created["user_ids"].append(drv["user_id"])
        created["emails"].append(drv["email"])
        r = requests.post(
            f"{BASE}/api/livre/team/drivers/{drv['driver_id']}/reset-password",
            headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "temp_password" in data
        assert data["must_change_password"] is True
        temp = data["temp_password"]

        # Le temp password NE DOIT PAS apparaître dans audit_log
        import asyncio
        rows = _run(
            mongo.audit_log.find({"action": "driver.password_reset"}).to_list(50))
        for r_ in rows:
            assert temp not in str(r_), "mot de passe temporaire fuité dans audit_log"

        # Login avec temp password
        login_r = login(drv["email"], temp)
        assert login_r.status_code == 200, login_r.text
        me = requests.get(f"{BASE}/api/auth/me",
                          headers=_h(login_r.json()["access_token"]), timeout=10).json()
        # must_change_password présent (peut être dans /auth/me ou /my-profile)
        prof = requests.get(f"{BASE}/api/livre/driver/my-profile",
                            headers=_h(login_r.json()["access_token"]), timeout=10)
        assert prof.status_code == 200
        assert prof.json().get("must_change_password") is True

    def test_manager_cannot_reset(self, admin_tok):
        # créer manager temporaire
        mem = f"mgr2.{uuid.uuid4().hex[:6]}@example.com"
        rc = requests.post(f"{BASE}/api/auth/register",
                           headers=_h(admin_tok),
                           json={"email": mem, "password": "mgrpwd123",
                                 "name": "Mgr2", "role": "manager"}, timeout=15)
        assert rc.status_code in (200, 201)
        mtok = _tok(mem, "mgrpwd123")
        try:
            r = requests.post(
                f"{BASE}/api/livre/team/drivers/{JEAN_ID}/reset-password",
                headers=_h(mtok), timeout=10)
            assert r.status_code == 403
        finally:
            lst = requests.get(f"{BASE}/api/livre/team/users",
                               headers=_h(admin_tok), timeout=10).json()
            for u in lst:
                if u["email"] == mem:
                    requests.delete(f"{BASE}/api/livre/team/users/{u['id']}",
                                    headers=_h(admin_tok), timeout=10)


# ================================================================
# TEST R — Création chauffeur avec first_name/last_name calculé
# ================================================================
class TestR_CreateDriver:
    def test_create_computes_name(self, admin_tok, created):
        body = {"first_name": "Ivan", "last_name": "Petrov",
                "internal_number": f"IP-{uuid.uuid4().hex[:6]}"}
        r = requests.post(f"{BASE}/api/livre/team/drivers",
                          headers=_h(admin_tok), json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "Ivan Petrov"
        assert d["first_name"] == "Ivan"
        assert d["last_name"] == "Petrov"
        created["driver_ids"].append(d["id"])

    def test_create_without_name_fails(self, admin_tok):
        r = requests.post(f"{BASE}/api/livre/team/drivers",
                          headers=_h(admin_tok), json={}, timeout=10)
        assert r.status_code == 400
