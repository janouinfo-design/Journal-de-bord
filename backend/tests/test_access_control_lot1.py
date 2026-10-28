"""Lot 1 — Modules par client + permissions par utilisateur (fondations backend).

Couvre : cohérence des catalogues (T32), parité legacy ↔ permissions (T24), résolution
effective (overrides, lecture seule, modules), modes legacy / shadow / enforce sur un
tenant de test isolé, validation X-Tenant-Id (T17/T18), compte désactivé (T23),
positions GPS retirées sans `positions.view` (D1).
"""
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

from app import access_control as ac  # noqa: E402
import app.routes  # noqa: E402,F401  (peuple ac.REGISTRY)


def _login(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {creds['email']} -> {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok, tenant=None):
    h = {"Authorization": f"Bearer {tok}"}
    if tenant:
        h["X-Tenant-Id"] = tenant
    return h


def _code(resp):
    d = resp.json().get("detail")
    return d.get("code") if isinstance(d, dict) else d


@pytest.fixture(scope="module")
def mongo():
    mc = pymongo.MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    yield mc[os.environ["DB_NAME"]]
    mc.close()


# ---------------------------------------------------------------------------
# T32 — cohérence des catalogues
# ---------------------------------------------------------------------------
def test_catalog_coherence():
    for code, spec in ac.PERMISSIONS.items():
        assert "." in code
        assert spec["module"] is None or spec["module"] in ac.MODULES, code
    for code, spec in ac.MODULES.items():
        for dep in spec["depends_on"]:
            assert dep in ac.MODULES, (code, dep)
    for role, perms in ac.ROLE_TEMPLATES.items():
        unknown = set(perms) - set(ac.PERMISSIONS)
        assert not unknown, (role, unknown)
    assert set(ac.ROLE_TEMPLATES) == {"admin", "manager", "office", "driver", "lecture_seule"}
    assert ac.SENSITIVE_PERMISSIONS <= set(ac.PERMISSIONS)
    assert "positions.view" in ac.PERMISSIONS and "positions.view" not in ac.ROLE_TEMPLATES["office"]
    assert "positions.view" in ac.ROLE_TEMPLATES["admin"] and "positions.view" in ac.ROLE_TEMPLATES["manager"]
    assert len(ac.REGISTRY) >= 60


# ---------------------------------------------------------------------------
# T24 — parité : pour chaque dépendance déclarée, rôle autorisé hier ⇔ permission par défaut
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["admin", "manager", "driver", "lecture_seule"])
def test_parity_legacy_vs_templates(role):
    mismatches = []
    for entry in ac.REGISTRY:
        legacy_ok = entry["legacy_roles"] is None or role in entry["legacy_roles"]
        eff = ac.effective_permissions({"role": role}, None)
        perm_ok = any(p in eff for p in entry["perms"])
        if legacy_ok != perm_ok:
            mismatches.append((entry["perms"], entry["legacy_roles"], legacy_ok, perm_ok))
    assert not mismatches, mismatches


# ---------------------------------------------------------------------------
# Résolution unitaire
# ---------------------------------------------------------------------------
def test_module_resolution_legacy_and_dependencies():
    assert ac.module_enabled(None, "fuel") and ac.module_enabled(None, "fuel_cards")
    assert not ac.module_enabled(None, "documents") and not ac.module_enabled(None, "ev_charging")
    t = {"modules_enabled": {"journal": True, "fuel": False, "fuel_cards": True, "fines": True}}
    assert not ac.module_enabled(t, "fuel_cards"), "fuel_cards dépend de fuel"
    assert ac.module_enabled(t, "fines") and not ac.module_enabled(t, "energy")
    assert ac.resolve_mode({"access_control_mode": "enforce"}) == "enforce"
    assert ac.resolve_mode({"access_control_mode": "bogus"}) in ac.MODES


def test_effective_permissions_overrides_and_read_only():
    eff = ac.effective_permissions({"role": "manager", "permissions_override": {"grant": ["fines.admin"]}}, None)
    assert {"fines.admin", "fines.edit", "fines.view"} <= eff
    eff = ac.effective_permissions({"role": "admin", "permissions_override": {"revoke": ["audit.view"]}}, None)
    assert "audit.view" not in eff and "users.view" in eff
    eff = ac.effective_permissions({"role": "lecture_seule", "permissions_override": {"grant": ["fines.edit"]}}, None)
    assert "fines.edit" not in eff and "fines.view" in eff
    # permission d'un module OFF retirée, même accordée
    t = {"modules_enabled": {"journal": True, "fines": False}}
    eff = ac.effective_permissions({"role": "admin"}, t)
    assert "fines.view" not in eff and "users.view" in eff and "journal.view" in eff
    assert ac.effective_permissions({"role": "superadmin"}, None) >= set(ac.ROLE_TEMPLATES["admin"])


def test_validate_override_rules():
    with pytest.raises(ValueError, match="unknown_permission"):
        ac.validate_override("manager", ["nope.x"], [], None)
    with pytest.raises(ValueError, match="module_disabled"):
        ac.validate_override("manager", ["fines.edit"], [], {"modules_enabled": {"journal": True}})
    with pytest.raises(ValueError, match="sensitive_not_allowed_for_role"):
        ac.validate_override("driver", ["positions.view"], [], None)
    with pytest.raises(ValueError, match="write_not_allowed_for_read_only"):
        ac.validate_override("lecture_seule", ["fines.edit"], [], None)
    ac.validate_override("office", ["positions.view"], [], None)  # surcharge explicite autorisée


def test_strip_positions():
    out = ac.strip_positions({"trips": [{"id": 1, "start_lat": 1.0, "start_address": "x",
                                         "nested": {"lng": 2.0, "ok": True}}]})
    assert out == {"trips": [{"id": 1, "start_address": "x", "nested": {"ok": True}}]}


# ---------------------------------------------------------------------------
# Mode legacy (tenant default) : comportement inchangé + /auth/me enrichi
# ---------------------------------------------------------------------------
def test_me_enriched_legacy_mode():
    for creds, role in ((ADMIN, "admin"), (MANAGER, "manager"), (DRIVER, "driver"), (READER, "lecture_seule")):
        r = requests.get(f"{BASE}/auth/me", headers=_h(_login(creds)), timeout=15)
        assert r.status_code == 200, (role, r.text)
        body = r.json()
        assert body["user"]["role"] == role
        assert body["tenant"]["id"] == "default"
        assert body["access_control_mode"] == "legacy"
        assert "fuel" in body["modules_enabled"] and "documents" not in body["modules_enabled"]
        assert sorted(ac.ROLE_TEMPLATES[role] & set(body["permissions_effective"])) == body["permissions_effective"] \
            or set(body["permissions_effective"]) <= ac.expand(set(ac.ROLE_TEMPLATES[role]))


def test_legacy_mode_keeps_role_behaviour():
    mgr = _h(_login(MANAGER))
    assert requests.get(f"{BASE}/livre/fines", headers=mgr, timeout=15).status_code == 200
    assert requests.get(f"{BASE}/livre/settings/smtp-status", headers=mgr, timeout=15).status_code == 403
    rdr = _h(_login(READER))
    assert requests.get(f"{BASE}/livre/dashboard", headers=rdr, timeout=15).status_code == 200
    assert requests.get(f"{BASE}/livre/team/drivers", headers=rdr, timeout=15).status_code == 403


# ---------------------------------------------------------------------------
# Superadmin : X-Tenant-Id validé (T17 / T18)
# ---------------------------------------------------------------------------
def test_superadmin_tenant_header_validation():
    sup = _login(SUPER)
    r = requests.get(f"{BASE}/livre/vehicles", headers=_h(sup, "does-not-exist"), timeout=15)
    assert r.status_code == 400 and _code(r) == "invalid_tenant"
    r = requests.get(f"{BASE}/auth/me", headers=_h(sup, "does-not-exist"), timeout=15)
    assert r.status_code == 200 and r.json()["tenant"] is None
    r = requests.get(f"{BASE}/livre/vehicles", headers=_h(sup), timeout=15)
    assert r.status_code == 200 and r.json() == []
    r = requests.get(f"{BASE}/livre/vehicles", headers=_h(sup, "default"), timeout=15)
    assert r.status_code == 200 and len(r.json()) > 0


# ---------------------------------------------------------------------------
# Tenant de test isolé : enforce / shadow / suspendu / compte désactivé
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ac_tenant(mongo):
    from app.auth import hash_password
    tid = f"ac-test-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    mongo.tenants.insert_one({"id": tid, "name": "AC Test", "status": "active", "created_at": now,
                              "access_control_mode": "enforce",
                              "modules_enabled": {"journal": True, "trip_classification": True,
                                                  "private_mode": True, "drivers": True, "energy": True,
                                                  "fuel": True, "fuel_cards": True, "fines": False,
                                                  "reports": True, "notifications": True}})
    users = {}
    for role in ("admin", "manager", "office", "lecture_seule"):
        email = f"{role}.{tid}@ac-lot1.example.com"
        pwd = "AcTest1234!"
        mongo.users.insert_one({"id": str(uuid.uuid4()), "email": email, "name": f"AC {role}", "role": role,
                                "tenant_id": tid, "password_hash": hash_password(pwd), "created_at": now})
        users[role] = {"email": email, "password": pwd}
    trip_id = str(uuid.uuid4())
    mongo.trips.insert_one({"id": trip_id, "tenant_id": tid, "vehicle_id": "v-ac", "vehicle_plate": "AC 1",
                            "driver_id": None, "start_time": now, "end_time": now, "distance_km": 1.0,
                            "classification": "professional", "auto_classified": True,
                            "start_lat": 46.2, "start_lng": 6.1, "end_lat": 46.3, "end_lng": 6.2,
                            "start_address": "A", "end_address": "B"})
    yield {"id": tid, "users": users, "trip_id": trip_id}
    mongo.tenants.delete_one({"id": tid})
    mongo.users.delete_many({"tenant_id": tid})
    mongo.trips.delete_many({"tenant_id": tid})
    mongo.audit_log.delete_many({"tenant_id": tid})
    mongo.settings.delete_many({"tenant_id": tid})
    mongo.schedules.delete_many({"tenant_id": tid})


def _set_mode(mongo, tid, mode):
    mongo.tenants.update_one({"id": tid}, {"$set": {"access_control_mode": mode}})


def test_enforce_module_disabled(mongo, ac_tenant):
    _set_mode(mongo, ac_tenant["id"], "enforce")
    adm = _h(_login(ac_tenant["users"]["admin"]))
    r = requests.get(f"{BASE}/livre/fines", headers=adm, timeout=15)
    assert r.status_code == 403 and _code(r) == "module_disabled" and r.json()["detail"]["module"] == "fines"
    assert requests.get(f"{BASE}/livre/fuel/cards", headers=adm, timeout=15).status_code == 200
    me = requests.get(f"{BASE}/auth/me", headers=adm, timeout=15).json()
    assert me["access_control_mode"] == "enforce"
    assert "fines" not in me["modules_enabled"] and "fines.view" not in me["permissions_effective"]
    # superadmin : pas de bypass du module (T3)
    r = requests.get(f"{BASE}/livre/fines", headers=_h(_login(SUPER), ac_tenant["id"]), timeout=15)
    assert r.status_code == 403 and _code(r) == "module_disabled"


def test_enforce_permission_denied_and_office_gps(mongo, ac_tenant):
    _set_mode(mongo, ac_tenant["id"], "enforce")
    mgr = _h(_login(ac_tenant["users"]["manager"]))
    r = requests.get(f"{BASE}/livre/settings/smtp-status", headers=mgr, timeout=15)
    assert r.status_code == 403 and _code(r) == "permission_denied"
    assert requests.get(f"{BASE}/livre/privacy/state", headers=mgr, timeout=15).status_code == 200
    off = _h(_login(ac_tenant["users"]["office"]))
    assert requests.get(f"{BASE}/livre/dashboard", headers=off, timeout=15).status_code == 200
    r = requests.get(f"{BASE}/livre/privacy/state", headers=off, timeout=15)
    assert r.status_code == 403 and _code(r) == "permission_denied"
    r = requests.get(f"{BASE}/livre/trips/{ac_tenant['trip_id']}/track", headers=off, timeout=15)
    assert r.status_code == 403 and r.json()["detail"]["permission"] == "positions.view"
    r = requests.get(f"{BASE}/livre/trips", headers=off, timeout=15)
    assert r.status_code == 200
    trips = r.json()["trips"]
    assert trips and all("start_lat" not in t and "end_lng" not in t for t in trips)
    assert trips[0]["start_address"] == "A"
    # admin : positions conservées
    adm = _h(_login(ac_tenant["users"]["admin"]))
    trips = requests.get(f"{BASE}/livre/trips", headers=adm, timeout=15).json()["trips"]
    assert trips and "start_lat" in trips[0]


def test_enforce_overrides(mongo, ac_tenant):
    _set_mode(mongo, ac_tenant["id"], "enforce")
    tid = ac_tenant["id"]
    mongo.users.update_one({"email": ac_tenant["users"]["manager"]["email"]},
                           {"$set": {"permissions_override": {"grant": ["settings.edit"], "revoke": []}}})
    mongo.users.update_one({"email": ac_tenant["users"]["admin"]["email"]},
                           {"$set": {"permissions_override": {"grant": [], "revoke": ["audit.view"]}}})
    try:
        mgr = _h(_login(ac_tenant["users"]["manager"]))
        assert requests.get(f"{BASE}/livre/settings/smtp-status", headers=mgr, timeout=15).status_code == 200
        adm = _h(_login(ac_tenant["users"]["admin"]))
        r = requests.get(f"{BASE}/livre/audit-log", headers=adm, timeout=15)
        assert r.status_code == 403 and _code(r) == "permission_denied"
        # lecture seule : grant d'écriture inopérant (T22)
        mongo.users.update_one({"email": ac_tenant["users"]["lecture_seule"]["email"]},
                               {"$set": {"permissions_override": {"grant": ["work_schedule.edit"], "revoke": []}}})
        rdr = _h(_login(ac_tenant["users"]["lecture_seule"]))
        me = requests.get(f"{BASE}/auth/me", headers=rdr, timeout=15).json()
        assert "work_schedule.edit" not in me["permissions_effective"]
        assert "work_schedule.view" in me["permissions_effective"]
    finally:
        mongo.users.update_many({"tenant_id": tid}, {"$unset": {"permissions_override": ""}})


def test_shadow_mode_logs_without_blocking(mongo, ac_tenant):
    _set_mode(mongo, ac_tenant["id"], "shadow")
    tid = ac_tenant["id"]
    mongo.users.update_one({"email": ac_tenant["users"]["manager"]["email"]},
                           {"$set": {"permissions_override": {"grant": [], "revoke": ["private_mode.view"]}}})
    try:
        mgr = _h(_login(ac_tenant["users"]["manager"]))
        # permission manquante → journalisée, jamais bloquée
        assert requests.get(f"{BASE}/livre/privacy/state", headers=mgr, timeout=15).status_code == 200
        # module fines OFF → journalisé, jamais bloqué
        assert requests.get(f"{BASE}/livre/fines", headers=mgr, timeout=15).status_code == 200
        # legacy_roles toujours appliqués en shadow : manager ∉ ("admin",) → 403 legacy (texte, pas de code structuré)
        r = requests.get(f"{BASE}/livre/settings/smtp-status", headers=mgr, timeout=15)
        assert r.status_code == 403 and _code(r) == "Accès refusé"
        # office (hors matrice legacy) : refusé par legacy_roles, autorisé là où tout utilisateur l'était
        off = _h(_login(ac_tenant["users"]["office"]))
        assert requests.get(f"{BASE}/livre/dashboard", headers=off, timeout=15).status_code == 200
        assert requests.get(f"{BASE}/livre/privacy/state", headers=off, timeout=15).status_code == 403
    finally:
        mongo.users.update_many({"tenant_id": tid}, {"$unset": {"permissions_override": ""}})
    rows = list(mongo.audit_log.find({"tenant_id": tid, "action": "access.shadow_deny"}, {"_id": 0}))
    kinds = {(r["details"]["kind"], r["details"]["key"]) for r in rows}
    assert ("permission", "private_mode.view") in kinds
    assert ("module", "fines") in kinds


def test_tenant_suspended_and_account_disabled(mongo, ac_tenant):
    _set_mode(mongo, ac_tenant["id"], "legacy")
    tid = ac_tenant["id"]
    adm_tok = _login(ac_tenant["users"]["admin"])
    mongo.tenants.update_one({"id": tid}, {"$set": {"status": "suspended"}})
    try:
        r = requests.get(f"{BASE}/livre/vehicles", headers=_h(adm_tok), timeout=15)
        assert r.status_code == 403 and _code(r) == "tenant_suspended"
        r = requests.get(f"{BASE}/livre/vehicles", headers=_h(_login(SUPER), tid), timeout=15)
        assert r.status_code == 403 and _code(r) == "tenant_suspended"
    finally:
        mongo.tenants.update_one({"id": tid}, {"$set": {"status": "active"}})
    # compte désactivé : token encore valide → 401 account_disabled ; refresh → 401 (T23)
    r = requests.post(f"{BASE}/auth/login", json=ac_tenant["users"]["manager"], timeout=15)
    tokens = r.json()
    mongo.users.update_one({"email": ac_tenant["users"]["manager"]["email"]}, {"$set": {"active": False}})
    try:
        r = requests.get(f"{BASE}/auth/me", headers=_h(tokens["access_token"]), timeout=15)
        assert r.status_code == 401 and _code(r) == "account_disabled"
        r = requests.post(f"{BASE}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}, timeout=15)
        assert r.status_code == 401
    finally:
        mongo.users.update_one({"email": ac_tenant["users"]["manager"]["email"]}, {"$set": {"active": True}})


def test_audit_log_errors_not_silenced_signature():
    import inspect
    from app import audit
    src = inspect.getsource(audit.log_audit)
    assert "logger.error" in src and "except Exception:\n        pass" not in src
