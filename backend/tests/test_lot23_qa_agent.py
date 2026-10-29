"""Lot 2 + Lot 3 QA (testing agent) — Super Admin modules & mode, team permissions overrides,
office role, legacy parity on tenant default (shadow), enforce on a throwaway tenant, shadow audit."""
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
SUPER = {"email": "superadmin@logitrak.ch", "password": os.environ["SUPERADMIN_PASSWORD"]}
ROLES = {"admin": ADMIN, "manager": MANAGER, "driver": DRIVER, "lecture_seule": READER}
T = 30
_TOK = {}
PWD = "QaLot23pass!"


def _login(creds):
    if creds["email"] in _TOK:
        return _TOK[creds["email"]]
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=T)
    assert r.status_code == 200, f"login {creds['email']} -> {r.status_code} {r.text}"
    _TOK[creds["email"]] = r.json()["access_token"]
    return _TOK[creds["email"]]


def _h(creds, tenant=None):
    h = {"Authorization": f"Bearer {_login(creds)}"}
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


@pytest.fixture(scope="module")
def qa(mongo):
    from app.auth import hash_password
    tid = f"qa23-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    mongo.tenants.insert_one({"id": tid, "name": "QA23 throwaway", "status": "active", "created_at": now})
    users = {}
    for role in ("admin", "manager", "office", "driver", "lecture_seule"):
        email = f"{role}.{tid}@qa23.example.com"
        uid = str(uuid.uuid4())
        mongo.users.insert_one({"id": uid, "email": email, "name": f"QA {role}", "role": role,
                                "tenant_id": tid, "password_hash": hash_password(PWD), "created_at": now})
        users[role] = {"email": email, "password": PWD, "id": uid}
    yield {"id": tid, "users": users}
    mongo.tenants.delete_many({"id": tid})
    for c in ("users", "audit_log", "settings", "schedules", "vehicles", "drivers", "trips"):
        mongo[c].delete_many({"tenant_id": tid})
    mongo.login_attempts.delete_many({"email": {"$regex": "qa23\\.example\\.com$"}})


def _c(u):
    return {"email": u["email"], "password": u["password"]}


# ---------------- LOT 2 — Super Admin ----------------
def test_modules_catalog():
    r = requests.get(f"{BASE}/admin/modules/catalog", headers=_h(SUPER), timeout=T)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["modules"]) == 17
    assert d["modes"] == ["legacy", "shadow", "enforce"]
    for m in d["modules"]:
        assert {"code", "label", "category", "depends_on", "legacy_default"} <= set(m)
    assert sum(1 for m in d["modules"] if m["legacy_default"]) == 10
    r = requests.get(f"{BASE}/admin/modules/catalog", headers=_h(ADMIN), timeout=T)
    assert r.status_code == 403


def test_tenants_list_fields(qa):
    r = requests.get(f"{BASE}/admin/tenants", headers=_h(SUPER), timeout=T)
    assert r.status_code == 200, r.text
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("tenants", rows.get("items"))
    by = {t["id"]: t for t in rows}
    d = by["default"]
    assert d["access_control_mode_effective"] == "shadow"
    # default : modules configurés explicitement = 10 modules legacy, aucun réservé
    assert len(d["modules_effective"]) == 10 and {"fuel", "fuel_cards", "fines"} <= set(d["modules_effective"])
    assert not {"documents", "ev_charging"} & set(d["modules_effective"])
    q = by[qa["id"]]
    assert q["modules_enabled"] is None and q["access_control_mode"] is None
    assert len(q["modules_effective"]) == 10
    assert q["access_control_mode_effective"] == "legacy"


def test_modules_update_cascade_and_audit(mongo, qa):
    tid = qa["id"]
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=_h(SUPER),
                     json={"modules_enabled": {"fuel": False}}, timeout=T)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["modules_enabled"]["fuel"] is False and d["modules_enabled"]["fuel_cards"] is False
    assert "fuel" not in d["modules_effective"] and "fuel_cards" not in d["modules_effective"]
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=_h(SUPER),
                     json={"modules_enabled": {"bogus_mod": True}}, timeout=T)
    assert r.status_code == 400 and _code(r) == "unknown_module", r.text
    a = mongo.audit_log.find_one({"tenant_id": tid, "action": "tenant.modules_update"}, sort=[("at", -1)])
    assert a and {"before", "after", "enabled", "disabled"} <= set(a["details"])
    assert "fuel" in a["details"]["disabled"] and "fuel_cards" in a["details"]["disabled"]
    me = requests.get(f"{BASE}/auth/me", headers=_h(_c(qa["users"]["admin"])), timeout=T).json()
    me_mods = me.get("modules_enabled")
    assert "fuel" not in (me_mods if isinstance(me_mods, list) else [k for k, v in me_mods.items() if v])
    assert "fuel.view" not in me["permissions_effective"]
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=_h(_c(qa["users"]["admin"])),
                     json={"modules_enabled": {"fuel": True}}, timeout=T)
    assert r.status_code == 403


def test_patch_mode(mongo, qa):
    tid = qa["id"]
    r = requests.patch(f"{BASE}/admin/tenants/{tid}", headers=_h(SUPER),
                       json={"access_control_mode": "bogus"}, timeout=T)
    assert r.status_code == 400, r.text
    r = requests.patch(f"{BASE}/admin/tenants/{tid}", headers=_h(SUPER),
                       json={"access_control_mode": "enforce"}, timeout=T)
    assert r.status_code == 200 and r.json()["access_control_mode_effective"] == "enforce", r.text
    a = mongo.audit_log.find_one({"tenant_id": tid, "action": "tenant.update"}, sort=[("at", -1)])
    assert a["details"]["before"]["access_control_mode"] == "legacy"
    assert a["details"]["after"]["access_control_mode"] == "enforce"
    r = requests.patch(f"{BASE}/admin/tenants/{tid}", headers=_h(SUPER),
                       json={"access_control_mode": "legacy"}, timeout=T)
    assert r.status_code == 200


# ---------------- LOT 3 — Team permissions (fuel still OFF here) ----------------
def test_team_create_office_and_catalog(mongo, qa):
    tid = qa["id"]
    ah = _h(_c(qa["users"]["admin"]))
    email = f"office2.{tid}@qa23.example.com"
    r = requests.post(f"{BASE}/livre/team/users", headers=ah,
                      json={"email": email, "password": PWD, "name": "Office 2", "role": "office"}, timeout=T)
    assert r.status_code == 200 and r.json()["role"] == "office", r.text
    r = requests.get(f"{BASE}/livre/team/permissions/catalog", headers=ah, timeout=T)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["modules"][0]["code"] == "journal"
    assert len(c["permissions"]) == 53
    for p in c["permissions"]:
        assert {"sensitive", "write", "available"} <= set(p)
    assert "positions.view" not in c["role_templates"]["office"]
    roles = [x if isinstance(x, str) else x.get("code") for x in c["roles"]]
    assert "office" in roles
    assert c["sensitive_blocked_roles"] == ["driver", "lecture_seule"]
    r = requests.get(f"{BASE}/livre/team/permissions/catalog", headers=_h(_c(qa["users"]["manager"])), timeout=T)
    assert r.status_code == 403


def test_team_override_validations(qa):
    u = qa["users"]
    ah = _h(_c(u["admin"]))
    url = lambda uid: f"{BASE}/livre/team/users/{uid}/permissions"  # noqa: E731
    r = requests.get(url(u["office"]["id"]), headers=ah, timeout=T)
    assert r.status_code == 200 and r.json()["role"] == "office"
    assert {"template", "override", "effective"} <= set(r.json())
    cases = [
        (u["office"]["id"], {"grant": ["nope.view"]}, "unknown_permission"),
        (u["driver"]["id"], {"grant": ["positions.view"]}, "sensitive_not_allowed_for_role"),
        (u["lecture_seule"]["id"], {"grant": ["fines.edit"]}, "write_not_allowed_for_read_only"),
        (u["office"]["id"], {"grant": ["fuel.reconcile"]}, "module_disabled"),
    ]
    for uid, body, code in cases:
        r = requests.put(url(uid), headers=ah, json=body, timeout=T)
        assert r.status_code == 400 and _code(r) == code, (body, r.status_code, r.text)
    r = requests.put(url(u["admin"]["id"]), headers=ah, json={"revoke": ["fines.view"]}, timeout=T)
    assert r.status_code == 400


def test_restore_modules(qa):
    r = requests.put(f"{BASE}/admin/tenants/{qa['id']}/modules", headers=_h(SUPER),
                     json={"modules_enabled": {"fuel": True, "fuel_cards": True}}, timeout=T)
    assert r.status_code == 200 and "fuel_cards" in r.json()["modules_effective"], r.text


def test_team_override_valid_and_reset(mongo, qa):
    u = qa["users"]
    ah = _h(_c(u["admin"]))
    oid = u["office"]["id"]
    url = f"{BASE}/livre/team/users/{oid}/permissions"
    r = requests.put(url, headers=ah, json={"grant": ["positions.view"], "revoke": ["fines.pay"],
                                            "reason": "QA GPS"}, timeout=T)
    assert r.status_code == 200, r.text
    assert "positions.view" in r.json()["effective"] and "fines.pay" not in r.json()["effective"]
    a = mongo.audit_log.find_one({"tenant_id": qa["id"], "action": "user.permissions_update"}, sort=[("at", -1)])
    d = a["details"]
    assert d["gps_access_granted"] is True and "positions.view" in d["granted"]
    assert "fines.pay" in d["revoked"] and d["reason"] == "QA GPS"
    # empty → reset
    r = requests.put(url, headers=ah, json={"grant": [], "revoke": []}, timeout=T)
    assert r.status_code == 200 and r.json()["override"] == {"grant": [], "revoke": []}
    assert "permissions_override" not in mongo.users.find_one({"id": oid})
    # role change resets override
    r = requests.put(url, headers=ah, json={"grant": ["positions.view"]}, timeout=T)
    assert r.status_code == 200
    r = requests.patch(f"{BASE}/livre/team/users/{oid}", headers=ah, json={"role": "manager"}, timeout=T)
    assert r.status_code == 200 and "permissions_override" not in r.json(), r.text
    a = mongo.audit_log.find_one({"tenant_id": qa["id"], "action": "user.update"}, sort=[("at", -1)])
    assert "permissions_override_reset" in a["details"]["fields"]
    r = requests.patch(f"{BASE}/livre/team/users/{oid}", headers=ah, json={"role": "office"}, timeout=T)
    assert r.status_code == 200


# ---------------- LOT 3 — legacy parity on tenant default (shadow) ----------------
# (path, method, {role: expected})
MATRIX = [
    ("/livre/fines", "GET", {"admin": 200, "manager": 200, "lecture_seule": 200, "driver": 403}),
    ("/livre/fines/mine", "GET", {"admin": 200, "manager": 200, "lecture_seule": 200, "driver": 200}),
    ("/livre/fines", "POST", {"lecture_seule": 403, "driver": 403}),
    ("/livre/fuel/cards", "GET", {"admin": 200, "manager": 200, "lecture_seule": 200, "driver": 403}),
    ("/livre/fuel/import-fields", "GET", {"admin": 200, "manager": 403}),
    ("/livre/fuel/statements", "GET", {"lecture_seule": 200, "driver": 403}),
    ("/livre/energy/status", "GET", {"driver": 200}),
    ("/livre/energy/overview", "GET", {"driver": 403, "lecture_seule": 200}),
    ("/livre/energy/tenant-mapping", "GET", {"manager": 200, "lecture_seule": 403}),
    ("/livre/ble/sessions", "GET", {"manager": 200, "driver": 403, "lecture_seule": 403}),
    ("/livre/ble/debug/recent-detections", "GET", {"admin": 200, "manager": 403}),
    ("/livre/driver/vehicles", "GET", {"driver": 200, "manager": 400, "lecture_seule": 400}),
    ("/livre/reports/weekly-driver/config", "GET", {"manager": 200, "lecture_seule": 403}),
]


def test_legacy_parity_default(mongo):
    v = mongo.vehicles.find_one({"tenant_id": "default"}, {"_id": 0, "id": 1})
    rows = MATRIX + [(f"/livre/vehicles/{v['id'] if v else 'unknown'}/odometer", "GET",
                      {"admin": 200 if v else 404, "manager": 403})]
    bad = []
    for path, method, exp in rows:
        for role, code in exp.items():
            r = requests.request(method, f"{BASE}{path}", headers=_h(ROLES[role]),
                                 json={} if method == "POST" else None, timeout=60)
            if r.status_code != code or r.status_code >= 500 or (code == 403 and _detail(r) not in ("Accès refusé", "Compte en lecture seule — action non autorisée")):
                bad.append((method, path, role, r.status_code, code, r.text[:120]))
    assert not bad, bad


def test_shadow_audit_default():
    r = requests.get(f"{BASE}/admin/audit", params={"action": "access.shadow_deny", "tenant_id": "default"},
                     headers=_h(SUPER), timeout=T)
    assert r.status_code == 200 and isinstance(r.json(), list)
    print(f"SHADOW_DENY_COUNT={len(r.json())}")


# ---------------- LOT 3 — enforce on throwaway tenant ----------------
def test_enforce_matrix(mongo, qa):
    tid = qa["id"]
    u = qa["users"]
    mongo.tenants.update_one({"id": tid}, {"$unset": {"modules_enabled": ""},
                                           "$set": {"access_control_mode": "enforce"}})
    requests.get(f"{BASE}/admin/tenants", headers=_h(SUPER), timeout=T)  # warm cache
    import time
    time.sleep(2)
    try:
        oh = _h(_c(u["office"]))
        for p in ("/livre/fuel/transactions", "/livre/fines", "/livre/fuel/import-fields"):
            r = requests.get(f"{BASE}{p}", headers=oh, timeout=T)
            assert r.status_code == 200, (p, r.status_code, r.text[:200])
        r = requests.get(f"{BASE}/livre/ble/sessions", headers=oh, timeout=T)
        assert r.status_code == 403 and _code(r) == "permission_denied", r.text
        r = requests.post(f"{BASE}/livre/fuel/anomalies/scan", headers=oh, json={}, timeout=T)
        assert r.status_code == 403 and _detail(r).get("permission") == "fuel.reconcile", r.text
        mongo.users.update_one({"id": u["manager"]["id"]},
                               {"$set": {"permissions_override": {"grant": [], "revoke": ["fines.view"]}}})
        r = requests.get(f"{BASE}/livre/fines", headers=_h(_c(u["manager"])), timeout=T)
        assert r.status_code == 403 and _code(r) == "permission_denied", r.text
        dh = _h(_c(u["driver"]))
        r = requests.get(f"{BASE}/livre/fines", headers=dh, timeout=T)
        assert r.status_code == 403 and _code(r) == "permission_denied", r.text
        r = requests.get(f"{BASE}/livre/fines/mine", headers=dh, timeout=T)
        assert r.status_code == 200, r.text
        r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=_h(SUPER),
                         json={"modules_enabled": {"fines": False}}, timeout=T)
        assert r.status_code == 200
        r = requests.get(f"{BASE}/livre/fines", headers=_h(SUPER, tenant=tid), timeout=T)
        assert r.status_code == 403 and _code(r) == "module_disabled", r.text
    finally:
        mongo.tenants.update_one({"id": tid}, {"$unset": {"modules_enabled": "", "access_control_mode": ""}})


def test_zz_default_untouched(mongo):
    t = mongo.tenants.find_one({"id": "default"})
    assert t.get("access_control_mode") == "shadow"
    from app.access_control import MODULES, enabled_modules
    assert enabled_modules(t) == [c for c, m in MODULES.items() if m["legacy_default"]], enabled_modules(t)
    assert t.get("status", "active") == "active"
