"""Lot 1 QA (testing agent) — access control: legacy parity, /auth/me enriched, superadmin
X-Tenant-Id, disabled account (via API), tenant isolation, enforce/shadow/suspended on a
throwaway tenant, office role not creatable, cleanup verification."""
import os
import uuid
from datetime import datetime, timezone

import pymongo
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
READER = {"email": "lecture@logitrak.ch", "password": "lecture123"}
ADMIN_B = {"email": "admin-b@test.ch", "password": "testb123"}
SUPER = {"email": "superadmin@logitrak.ch", "password": os.environ["SUPERADMIN_PASSWORD"]}
T = 30
_TOK = {}


def _login(creds, cache=True):
    if cache and creds["email"] in _TOK:
        return _TOK[creds["email"]]
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=T)
    assert r.status_code == 200, f"login {creds['email']} -> {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    if cache:
        _TOK[creds["email"]] = tok
    return tok


def _h(tok, tenant=None):
    h = {"Authorization": f"Bearer {tok}"}
    if tenant:
        h["X-Tenant-Id"] = tenant
    return h


def _detail(r):
    try:
        return r.json().get("detail")
    except Exception:
        return None


def _code(r):
    d = _detail(r)
    return d.get("code") if isinstance(d, dict) else d


@pytest.fixture(scope="module")
def mongo():
    mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    yield mc[os.environ["DB_NAME"]]
    mc.close()


ROLES = {"admin": ADMIN, "manager": MANAGER, "driver": DRIVER, "lecture_seule": READER}

# ---------------- Legacy parity (tenant default) ----------------
OPEN_GETS = ["/livre/dashboard", "/livre/trips", "/livre/vehicles", "/livre/drivers", "/livre/geofences",
             "/livre/assignments", "/livre/schedule", "/livre/notifications/catalog",
             "/livre/notifications/preferences", "/livre/notifications/inbox",
             "/livre/reports/export?classification=professional&fmt=csv", "/livre/reports/tax-swiss?year=2026"]
RESTRICTED = {
    "/livre/settings/smtp-status": ("admin",),
    "/livre/audit-log": ("admin",),
    "/livre/team/users": ("admin",),
    "/livre/navixy/scheduler": ("admin", "manager"),
    "/livre/privacy/state": ("admin", "manager"),
    "/livre/team/drivers": ("admin", "manager"),
    "/livre/schedule/drivers-with-override": ("admin", "manager"),
}


@pytest.mark.parametrize("role", list(ROLES))
def test_legacy_open_endpoints(role):
    h = _h(_login(ROLES[role]))
    bad = []
    for p in OPEN_GETS:
        r = requests.get(f"{BASE}{p}", headers=h, timeout=60)
        if r.status_code != 200:
            bad.append((p, r.status_code, r.text[:150]))
    assert not bad, bad


@pytest.mark.parametrize("role", list(ROLES))
def test_legacy_restricted_endpoints(role):
    h = _h(_login(ROLES[role]))
    bad = []
    for p, allowed in RESTRICTED.items():
        r = requests.get(f"{BASE}{p}", headers=h, timeout=T)
        exp = 200 if role in allowed else 403
        if r.status_code != exp or (exp == 403 and _detail(r) != "Accès refusé"):
            bad.append((p, r.status_code, exp, r.text[:150]))
    assert not bad, bad


def _pick_trip(mongo, driver_only=False):
    q = {"tenant_id": "default"}
    if driver_only:
        r = requests.get(f"{BASE}/livre/trips", headers=_h(_login(DRIVER)), timeout=T).json()
        own = r["trips"] if isinstance(r, dict) else r
        if not own:
            t = mongo.trips.find_one({"tenant_id": "default"}, {"_id": 0, "id": 1})
            r = requests.put(f"{BASE}/livre/trips/{t['id']}/classify", headers=_h(_login(DRIVER)),
                             json={"classification": "professional"}, timeout=T)
            assert r.status_code == 403 and "propres trajets" in str(_detail(r)), r.text
            pytest.skip("chauffeur has no own trips; role gate verified via ownership 403")
        q["id"] = own[0]["id"]
    t = mongo.trips.find_one(q, {"_id": 0, "id": 1, "classification": 1, "auto_classified": 1,
                                 "modified_by": 1, "modified_at": 1})
    assert t
    return t


def _restore_trip(mongo, t):
    s = {k: t[k] for k in ("classification", "auto_classified", "modified_by", "modified_at") if k in t}
    u = {k: "" for k in ("modified_by", "modified_at") if k not in t}
    upd = {"$set": s}
    if u:
        upd["$unset"] = u
    mongo.trips.update_one({"id": t["id"], "tenant_id": "default"}, upd)
    mongo.audit_log.delete_many({"trip_id": t["id"], "user_email": {"$in": [c["email"] for c in ROLES.values()]},
                                 "at": {"$gte": datetime.now(timezone.utc).date().isoformat()}})


@pytest.mark.parametrize("role", list(ROLES))
def test_legacy_classify(mongo, role):
    t = _pick_trip(mongo, driver_only=(role == "driver"))
    try:
        r = requests.put(f"{BASE}/livre/trips/{t['id']}/classify", headers=_h(_login(ROLES[role])),
                         json={"classification": t.get("classification") or "professional"}, timeout=T)
        if role == "lecture_seule":
            assert r.status_code == 403 and "lecture seule" in str(_detail(r)).lower(), r.text
        else:
            assert r.status_code == 200 and r.json().get("ok") is True, r.text
    finally:
        _restore_trip(mongo, t)


def test_legacy_track_admin(mongo):
    t = _pick_trip(mongo)
    r = requests.get(f"{BASE}/livre/trips/{t['id']}/track", headers=_h(_login(ADMIN)), timeout=60)
    assert r.status_code in (200, 403), r.text
    if r.status_code == 403:
        assert _code(r) not in ("permission_denied", "module_disabled")


# ---------------- /auth/me enriched ----------------
WRITE_MARKERS = (".edit", ".admin", ".classify", ".import", ".reconcile", ".statements", ".pay",
                 ".permissions", ".impersonate")


@pytest.mark.parametrize("role", list(ROLES))
def test_me_enriched(role):
    r = requests.get(f"{BASE}/auth/me", headers=_h(_login(ROLES[role])), timeout=T)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["user"]["role"] == role and "password_hash" not in b["user"]
    assert b["tenant"]["id"] == "default" and b["tenant"]["status"] == "active"
    assert b["access_control_mode"] in ("legacy", "shadow")  # default : jamais enforce sans GO
    for m in ("journal", "fuel", "fines", "energy", "reports", "notifications", "drivers"):
        assert m in b["modules_enabled"], m
    assert "documents" not in b["modules_enabled"] and "ev_charging" not in b["modules_enabled"]
    perms = b["permissions_effective"]
    assert perms == sorted(perms)
    if role == "admin":
        assert len(perms) == 53
    if role == "driver":
        assert "journal.view_self" in perms and "journal.view" not in perms
    if role == "lecture_seule":
        bad = [p for p in perms if any(p.endswith(w) or w + "_" in p for w in WRITE_MARKERS)
               or p.startswith("users.") or p == "settings.edit"]
        assert not bad, bad
    assert ("positions.view" in perms) == (role != "driver")


# ---------------- Superadmin X-Tenant-Id ----------------
def test_superadmin_header():
    s = _login(SUPER)
    r = requests.get(f"{BASE}/livre/vehicles", headers=_h(s, "does-not-exist"), timeout=T)
    assert r.status_code == 400 and _code(r) == "invalid_tenant", r.text
    r = requests.get(f"{BASE}/auth/me", headers=_h(s, "does-not-exist"), timeout=T)
    assert r.status_code == 200 and r.json()["tenant"] is None
    r = requests.get(f"{BASE}/livre/vehicles", headers=_h(s), timeout=T)
    assert r.status_code == 200 and r.json() == []
    r = requests.get(f"{BASE}/livre/vehicles", headers=_h(s, "default"), timeout=T)
    assert r.status_code == 200 and len(r.json()) > 0
    r = requests.get(f"{BASE}/admin/tenants", headers=_h(s, "does-not-exist"), timeout=T)
    assert r.status_code == 200, r.text


# ---------------- Office role not creatable + disabled account via API ----------------
def test_office_role_refused():
    r = requests.post(f"{BASE}/livre/team/users", headers=_h(_login(ADMIN)),
                      json={"email": f"lot1-office-{uuid.uuid4().hex[:6]}@example.com", "password": "Xx123456!",
                            "name": "QA office", "role": "office"}, timeout=T)
    assert r.status_code == 400 and "Rôle invalide" in str(_detail(r)), r.text


def test_disabled_account_flow(mongo):
    adm = _h(_login(ADMIN))
    email = f"lot1-disabled-{uuid.uuid4().hex[:8]}@example.com"
    pwd = "QaLot1pass!"
    r = requests.post(f"{BASE}/livre/team/users", headers=adm,
                      json={"email": email, "password": pwd, "name": "QA Disabled", "role": "manager"}, timeout=T)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    try:
        lr = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=T)
        assert lr.status_code == 200, lr.text
        toks = lr.json()
        assert requests.get(f"{BASE}/auth/me", headers=_h(toks["access_token"]), timeout=T).status_code == 200
        r = requests.patch(f"{BASE}/livre/team/users/{uid}", headers=adm, json={"active": False}, timeout=T)
        assert r.status_code == 200 and r.json()["active"] is False, r.text
        r = requests.get(f"{BASE}/auth/me", headers=_h(toks["access_token"]), timeout=T)
        assert r.status_code == 401 and _code(r) == "account_disabled", r.text
        r = requests.get(f"{BASE}/livre/vehicles", headers=_h(toks["access_token"]), timeout=T)
        assert r.status_code == 401 and _code(r) == "account_disabled", r.text
        r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": toks.get("refresh_token")}, timeout=T)
        assert r.status_code == 401, r.text
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=T)
        assert r.status_code in (401, 403), r.text
        r = requests.patch(f"{BASE}/livre/team/users/{uid}", headers=adm, json={"active": True}, timeout=T)
        assert r.status_code == 200 and r.json()["active"] is True
        # legacy DELETE still works
        r = requests.delete(f"{BASE}/livre/team/users/{uid}", headers=adm, timeout=T)
        assert r.status_code == 200 and r.json()["deleted"] is True, r.text
        assert mongo.users.find_one({"id": uid}) is None
    finally:
        mongo.users.delete_one({"id": uid})
        mongo.login_attempts.delete_many({"email": email})


# ---------------- Tenant isolation (tenant B) ----------------
def test_tenant_b_isolation(mongo):
    hb = _h(_login(ADMIN_B))
    me = requests.get(f"{BASE}/auth/me", headers=hb, timeout=T).json()
    tb = me["tenant"]["id"]
    assert tb != "default"
    default_plates = {v.get("plate") for v in mongo.vehicles.find({"tenant_id": "default"}, {"plate": 1})} - {None}
    vs = requests.get(f"{BASE}/livre/vehicles", headers=hb, timeout=T)
    assert vs.status_code == 200
    assert not ({v.get("plate") for v in vs.json()} & default_plates)
    tr = requests.get(f"{BASE}/livre/trips", headers=hb, timeout=T)
    assert tr.status_code == 200
    body = tr.json()
    trips = body["trips"] if isinstance(body, dict) else body
    default_trip_ids = {t["id"] for t in mongo.trips.find({"tenant_id": "default"}, {"id": 1}).limit(5000)}
    assert not ({t["id"] for t in trips} & default_trip_ids)
    us = requests.get(f"{BASE}/livre/team/users", headers=hb, timeout=T)
    assert us.status_code == 200 and all(u["tenant_id"] == tb for u in us.json())
    t = _pick_trip(mongo)
    r = requests.get(f"{BASE}/livre/trips/{t['id']}/track", headers=hb, timeout=T)
    assert r.status_code == 404, r.text


# ---------------- Throwaway tenant: enforce / shadow / suspended ----------------
@pytest.fixture(scope="module")
def qa_tenant(mongo):
    from app.auth import hash_password
    tid = f"lot1-qa-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    mongo.tenants.insert_one({"id": tid, "name": "Lot1 QA", "status": "active", "created_at": now,
                              "access_control_mode": "enforce",
                              "modules_enabled": {"journal": True, "trip_classification": True,
                                                  "private_mode": True, "drivers": True, "energy": True,
                                                  "fuel": True, "fuel_cards": True, "fines": False,
                                                  "reports": True, "notifications": True}})
    users = {}
    pwd = "QaLot1pass!"
    for role in ("admin", "manager", "office", "lecture_seule"):
        email = f"{role}.{tid}@lot1-qa.example.com"
        mongo.users.insert_one({"id": str(uuid.uuid4()), "email": email, "name": f"QA {role}", "role": role,
                                "tenant_id": tid, "password_hash": hash_password(pwd), "created_at": now})
        users[role] = {"email": email, "password": pwd}
    trip_id = str(uuid.uuid4())
    mongo.trips.insert_one({"id": trip_id, "tenant_id": tid, "vehicle_id": "v-qa", "vehicle_plate": "QA 1",
                            "driver_id": None, "start_time": now, "end_time": now, "distance_km": 2.0,
                            "classification": "professional", "auto_classified": True,
                            "start_lat": 46.2, "start_lng": 6.1, "end_lat": 46.3, "end_lng": 6.2,
                            "start_address": "A", "end_address": "B"})
    yield {"id": tid, "users": users, "trip_id": trip_id}
    for c in ("tenants",):
        mongo[c].delete_many({"id": tid})
    for c in ("users", "trips", "audit_log", "settings", "schedules", "vehicles", "drivers"):
        mongo[c].delete_many({"tenant_id": tid})
    mongo.login_attempts.delete_many({"email": {"$regex": "lot1-qa\\.example\\.com$"}})


def _mode(mongo, tid, mode):
    mongo.tenants.update_one({"id": tid}, {"$set": {"access_control_mode": mode}})


def test_enforce_mode(mongo, qa_tenant):
    tid = qa_tenant["id"]
    _mode(mongo, tid, "enforce")
    u = qa_tenant["users"]
    adm = _h(_login(u["admin"]))
    r = requests.get(f"{BASE}/livre/fines", headers=adm, timeout=T)
    d = _detail(r)
    assert r.status_code == 403 and d["code"] == "module_disabled" and d["module"] == "fines" and d.get("msg")
    assert requests.get(f"{BASE}/livre/fuel/cards", headers=adm, timeout=T).status_code == 200
    r = requests.get(f"{BASE}/livre/fines", headers=_h(_login(SUPER), tid), timeout=T)
    assert r.status_code == 403 and _code(r) == "module_disabled"
    me = requests.get(f"{BASE}/auth/me", headers=adm, timeout=T).json()
    assert me["access_control_mode"] == "enforce" and me["tenant"]["id"] == tid
    assert "fines" not in me["modules_enabled"] and "fines.view" not in me["permissions_effective"]
    mgr = _h(_login(u["manager"]))
    r = requests.get(f"{BASE}/livre/settings/smtp-status", headers=mgr, timeout=T)
    assert r.status_code == 403 and _code(r) == "permission_denied" and _detail(r)["permission"] == "settings.edit"
    assert requests.get(f"{BASE}/livre/privacy/state", headers=mgr, timeout=T).status_code == 200
    off = _h(_login(u["office"]))
    assert requests.get(f"{BASE}/livre/dashboard", headers=off, timeout=T).status_code == 200
    r = requests.get(f"{BASE}/livre/privacy/state", headers=off, timeout=T)
    assert r.status_code == 403 and _code(r) == "permission_denied"
    r = requests.get(f"{BASE}/livre/trips", headers=off, timeout=T)
    assert r.status_code == 200
    trips = r.json()["trips"]
    assert trips and all(not ({"start_lat", "start_lng", "end_lat", "end_lng"} & set(t)) for t in trips)
    trips_a = requests.get(f"{BASE}/livre/trips", headers=adm, timeout=T).json()["trips"]
    assert trips_a and {"start_lat", "start_lng", "end_lat", "end_lng"} <= set(trips_a[0])
    r = requests.get(f"{BASE}/livre/trips/{qa_tenant['trip_id']}/track", headers=off, timeout=T)
    assert r.status_code == 403 and _detail(r)["permission"] == "positions.view", r.text


def test_enforce_overrides(mongo, qa_tenant):
    tid = qa_tenant["id"]
    u = qa_tenant["users"]
    _mode(mongo, tid, "enforce")
    try:
        mongo.users.update_one({"email": u["manager"]["email"]},
                               {"$set": {"permissions_override": {"grant": ["settings.edit"], "revoke": []}}})
        mongo.users.update_one({"email": u["admin"]["email"]},
                               {"$set": {"permissions_override": {"grant": [], "revoke": ["audit.view"]}}})
        mongo.users.update_one({"email": u["lecture_seule"]["email"]},
                               {"$set": {"permissions_override": {"grant": ["work_schedule.edit"], "revoke": []}}})
        r = requests.get(f"{BASE}/livre/settings/smtp-status", headers=_h(_login(u["manager"])), timeout=T)
        assert r.status_code == 200, r.text
        r = requests.get(f"{BASE}/livre/audit-log", headers=_h(_login(u["admin"])), timeout=T)
        assert r.status_code == 403 and _code(r) == "permission_denied"
        me = requests.get(f"{BASE}/auth/me", headers=_h(_login(u["lecture_seule"])), timeout=T).json()
        assert "work_schedule.edit" not in me["permissions_effective"]
    finally:
        mongo.users.update_many({"tenant_id": tid}, {"$unset": {"permissions_override": ""}})


def test_shadow_mode(mongo, qa_tenant):
    tid = qa_tenant["id"]
    u = qa_tenant["users"]
    _mode(mongo, tid, "shadow")
    try:
        mongo.users.update_one({"email": u["manager"]["email"]},
                               {"$set": {"permissions_override": {"grant": [], "revoke": ["private_mode.view"]}}})
        mgr = _h(_login(u["manager"]))
        r = requests.get(f"{BASE}/livre/privacy/state", headers=mgr, timeout=T)
        assert r.status_code == 200, r.text
        r = requests.get(f"{BASE}/livre/fines", headers=_h(_login(u["admin"])), timeout=T)
        assert r.status_code == 200, r.text
        r = requests.get(f"{BASE}/livre/settings/smtp-status", headers=mgr, timeout=T)
        assert r.status_code == 403 and _detail(r) == "Accès refusé"
    finally:
        mongo.users.update_many({"tenant_id": tid}, {"$unset": {"permissions_override": ""}})
    rows = list(mongo.audit_log.find({"tenant_id": tid, "action": "access.shadow_deny"}, {"_id": 0}))
    kinds = {(x["details"]["kind"], x["details"]["key"]) for x in rows}
    assert ("permission", "private_mode.view") in kinds, kinds
    assert ("module", "fines") in kinds, kinds


def test_suspended_tenant(mongo, qa_tenant):
    tid = qa_tenant["id"]
    tok = _login(qa_tenant["users"]["admin"])
    mongo.tenants.update_one({"id": tid}, {"$set": {"status": "suspended"}})
    try:
        r = requests.get(f"{BASE}/livre/vehicles", headers=_h(tok), timeout=T)
        assert r.status_code == 403 and _code(r) == "tenant_suspended" and "suspendu" in _detail(r)["msg"]
        r = requests.get(f"{BASE}/livre/vehicles", headers=_h(_login(SUPER), tid), timeout=T)
        assert r.status_code == 403 and _code(r) == "tenant_suspended"
    finally:
        mongo.tenants.update_one({"id": tid}, {"$set": {"status": "active"}})
    r = requests.patch(f"{BASE}/admin/tenants/default", headers=_h(_login(SUPER)),
                       json={"status": "suspended"}, timeout=T)
    assert r.status_code == 400, r.text


# ---------------- Final: shared state untouched ----------------
def test_zz_default_tenant_untouched(mongo):
    t = mongo.tenants.find_one({"id": "default"}, {"_id": 0})
    assert t["status"] == "active"
    assert "modules_enabled" not in t and "access_control_mode" not in t
    for c in (ADMIN, MANAGER, DRIVER, READER, SUPER, ADMIN_B):
        _login(c, cache=False)
