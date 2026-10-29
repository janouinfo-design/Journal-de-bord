"""Lot 5 + Lot 6 QA (testing agent) — /auth/me payload for driver app, shadow non-blocking on default,
enforce scenario on a throwaway tenant (module_disabled / permission_denied / account_disabled),
enforce-readiness guard-rails endpoint."""
import os
import uuid
from datetime import datetime, timezone

import pymongo
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
SUPER = {"email": "superadmin@logitrak.ch", "password": os.environ["SUPERADMIN_PASSWORD"]}
LEGACY10 = {"journal", "trip_classification", "private_mode", "drivers", "energy", "fuel",
            "fuel_cards", "fines", "reports", "notifications"}
T = 30
PWD = "QaLot56pass!"
_TOK = {}


def _login_full(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=T)
    assert r.status_code == 200, f"login {creds['email']} -> {r.status_code} {r.text}"
    return r.json()


def _h(creds, tenant=None):
    if creds["email"] not in _TOK:
        _TOK[creds["email"]] = _login_full(creds)["access_token"]
    h = {"Authorization": f"Bearer {_TOK[creds['email']]}"}
    if tenant:
        h["X-Tenant-Id"] = tenant
    return h


def _detail(r):
    try:
        return r.json().get("detail")
    except Exception:
        return None


def _is_ac_403(r):
    d = _detail(r)
    return r.status_code == 403 and isinstance(d, dict) and d.get("code") in ("module_disabled", "permission_denied")


@pytest.fixture(scope="module")
def mongo():
    mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    yield mc[os.environ["DB_NAME"]]
    mc.close()


@pytest.fixture(scope="module")
def qa(mongo):
    from app.auth import hash_password
    tid = f"qa-lot5-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    mongo.tenants.insert_one({"id": tid, "name": "QA Lot5 throwaway", "status": "active",
                              "access_control_mode": "enforce", "created_at": now})
    uid = str(uuid.uuid4())
    email = f"driver.{tid}@qa-lot5.example.com"
    mongo.users.insert_one({"id": uid, "email": email, "name": "QA Lot5 driver", "role": "driver",
                            "tenant_id": tid, "active": True, "password_hash": hash_password(PWD),
                            "created_at": now})
    try:
        yield {"id": tid, "uid": uid, "creds": {"email": email, "password": PWD}}
    finally:
        mongo.tenants.delete_many({"id": tid})
        for c in ("users", "audit_log", "settings", "schedules", "vehicles", "drivers", "trips"):
            mongo[c].delete_many({"tenant_id": tid})
        mongo.login_attempts.delete_many({"email": {"$regex": "qa-lot5\\.example\\.com$"}})


# ---------------- LOT 5 — /auth/me (driver on default, shadow) ----------------
def test_me_driver_default():
    r = requests.get(f"{BASE}/auth/me", headers=_h(DRIVER), timeout=T)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["user"]["email"] == DRIVER["email"]
    assert d["tenant"]["id"] == "default" and d["tenant"]["status"] == "active"
    assert d["access_control_mode"] == "shadow"
    assert isinstance(d["modules_enabled"], list) and set(d["modules_enabled"]) == LEGACY10
    assert len(d["modules_enabled"]) == 10
    pe = d["permissions_effective"]
    assert pe == sorted(pe)
    assert {"journal.view_self", "trips.classify_self", "identification.self"} <= set(pe)
    assert "positions.view" not in pe and "journal.view" not in pe


# ---------------- LOT 5 — shadow never blocks the driver app endpoints ----------------
DRIVER_ENDPOINTS = ["/livre/driver/current-session", "/livre/driver/my-vehicle", "/livre/driver/my-profile",
                    "/livre/driver/vehicles", "/livre/driver/private-mode", "/livre/driver/km-summary?period=today", "/livre/driver/km-summary?period=month",
                    "/livre/trips?limit=5", "/livre/notifications/preferences"]


def test_shadow_driver_endpoints_not_blocked():
    bad = []
    for p in DRIVER_ENDPOINTS:
        r = requests.get(f"{BASE}{p}", headers=_h(DRIVER), timeout=60)
        print(p, r.status_code)
        if _is_ac_403(r) or r.status_code >= 500 or r.status_code not in (200, 400, 404):
            bad.append((p, r.status_code, r.text[:150]))
    assert not bad, bad


# ---------------- LOT 5 — enforce on throwaway tenant ----------------
def _sa_modules(tid, flags):
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=_h(SUPER),
                     json={"modules_enabled": flags}, timeout=T)
    assert r.status_code == 200, r.text
    return r.json()


def test_enforce_scenario(mongo, qa):
    tid, uid = qa["id"], qa["uid"]
    full = _login_full(qa["creds"])
    dh = {"Authorization": f"Bearer {full['access_token']}"}
    me = requests.get(f"{BASE}/auth/me", headers=dh, timeout=T).json()
    assert me["access_control_mode"] == "enforce" and me["tenant"]["id"] == tid

    # (a) private_mode OFF
    _sa_modules(tid, {"private_mode": False})
    for m, body in (("GET", None), ("POST", {"mode": "PRIVATE"})):
        r = requests.request(m, f"{BASE}/livre/driver/private-mode", headers=dh, json=body, timeout=T)
        d = _detail(r)
        assert r.status_code == 403 and d["code"] == "module_disabled" and d["module"] == "private_mode", (m, r.text)
        assert d.get("msg")
    # (b) private_mode back ON
    _sa_modules(tid, {"private_mode": True})
    r = requests.get(f"{BASE}/livre/driver/private-mode", headers=dh, timeout=T)
    assert r.status_code != 403 and r.status_code < 500, r.text
    print("b) private-mode after re-enable:", r.status_code, r.text[:120])

    # (c) revoke identification.self
    mongo.users.update_one({"id": uid}, {"$set": {"permissions_override": {"grant": [], "revoke": ["identification.self"]}}})
    for p in ("/livre/driver/vehicles", "/livre/driver/private-mode"):
        r = requests.get(f"{BASE}{p}", headers=dh, timeout=T)
        d = _detail(r)
        assert r.status_code == 403 and d["code"] == "permission_denied" and d.get("permission"), (p, r.text)
    # (d) revoke trips.classify_self
    mongo.users.update_one({"id": uid}, {"$set": {"permissions_override": {"grant": [], "revoke": ["trips.classify_self"]}}})
    r = requests.put(f"{BASE}/livre/trips/{uuid.uuid4()}/classify", headers=dh,
                     json={"classification": "professional"}, timeout=T)
    assert r.status_code == 403 and _detail(r)["code"] == "permission_denied", r.text
    # (e) revoke journal.view_self
    mongo.users.update_one({"id": uid}, {"$set": {"permissions_override": {"grant": [], "revoke": ["journal.view_self"]}}})
    r = requests.get(f"{BASE}/livre/trips", headers=dh, timeout=T)
    assert r.status_code == 403 and _detail(r)["code"] == "permission_denied", r.text
    mongo.users.update_one({"id": uid}, {"$unset": {"permissions_override": ""}})
    r = requests.get(f"{BASE}/livre/trips", headers=dh, timeout=T)
    assert r.status_code == 200, r.text

    # (f) journal OFF (cascade)
    out = _sa_modules(tid, {"journal": False})
    assert "private_mode" not in out["modules_effective"] and "trip_classification" not in out["modules_effective"]
    r = requests.get(f"{BASE}/livre/trips", headers=dh, timeout=T)
    d = _detail(r)
    journal_off = r.text
    me = requests.get(f"{BASE}/auth/me", headers=dh, timeout=T).json()
    assert "journal" not in me["modules_enabled"] and "journal.view_self" not in me["permissions_effective"]
    _sa_modules(tid, {"journal": True, "trip_classification": True, "private_mode": True})

    # (g) account disabled
    mongo.users.update_one({"id": uid}, {"$set": {"active": False}})
    r = requests.get(f"{BASE}/auth/me", headers=dh, timeout=T)
    assert r.status_code == 401 and _detail(r)["code"] == "account_disabled", r.text
    r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": full["refresh_token"]}, timeout=T)
    assert r.status_code == 401, r.text
    print("g) refresh:", r.status_code, r.text[:120])
    # (f) assertion deferred so (g) still runs — GET /trips lacks module="journal" in require_permission
    assert d["code"] == "module_disabled" and d.get("module") == "journal", journal_off


# ---------------- LOT 6 — enforce-readiness ----------------
def test_enforce_readiness_default():
    r = requests.get(f"{BASE}/admin/tenants/default/enforce-readiness", headers=_h(SUPER), timeout=T)
    assert r.status_code == 200, r.text
    d = r.json()
    print("readiness:", {c["id"]: c["status"] for c in d["checks"]}, d["observation"]["shadow_denies"], d["ready"])
    assert d["tenant_id"] == "default" and d["mode_effective"] == "shadow"
    assert set(d["modules_effective"]) == LEGACY10
    assert {"since", "days", "required_days", "eligible_at", "shadow_denies", "excluded", "exclusions", "by_key"} <= set(d["observation"])
    assert isinstance(d["observation"]["by_key"], list)
    # fenêtre de test du 29/10 (fuel/fines/fuel_cards coupés par un test) exclue du calcul, événements conservés
    assert d["observation"]["excluded"] >= 35 and d["observation"]["exclusions"][0]["modules"] == ["fines", "fuel", "fuel_cards"]
    assert all(k["key"] not in ("fuel", "fines", "fuel_cards") and not k["key"].startswith(("fuel.", "fines."))
               for k in d["observation"]["by_key"])
    assert {"total", "inactive", "by_role", "unknown_role", "with_override"} <= set(d["users"])
    ids = [c["id"] for c in d["checks"]]
    assert sorted(ids) == sorted(["tenant_active", "observation", "shadow_denies", "roles_known", "overrides_valid"])
    assert all(c["status"] in ("ok", "warn", "fail") for c in d["checks"])
    # garde-fou 7 jours : ready ⇔ aucun fail ; tant que l'observation est < 7 j, le passage reste refusé
    assert d["ready"] == (not d["blocked_reasons"]) == all(c["status"] != "fail" for c in d["checks"])
    assert d["observation"]["required_days"] == 7 and d["observation"]["eligible_at"]
    if d["observation"]["days"] < 7:
        assert d["ready"] is False and any("éligible le" in r for r in d["blocked_reasons"])


def test_enforce_readiness_404_and_403():
    r = requests.get(f"{BASE}/admin/tenants/nope-{uuid.uuid4().hex[:6]}/enforce-readiness", headers=_h(SUPER), timeout=T)
    assert r.status_code == 404, r.text
    r = requests.get(f"{BASE}/admin/tenants/default/enforce-readiness", headers=_h(ADMIN), timeout=T)
    assert r.status_code == 403, r.text


def test_zz_default_untouched(mongo):
    t = mongo.tenants.find_one({"id": "default"})
    assert t.get("access_control_mode") == "shadow"
    from app.access_control import enabled_modules
    assert set(enabled_modules(t)) == LEGACY10
    assert t.get("status", "active") == "active"
