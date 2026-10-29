"""Lot 2 (modules & mode par client — Super Admin) + Lot 3 (permissions par utilisateur, rôle office,
migration require_roles → require_permission des routeurs fuel / fines / energy / ble / identification).
Tenant jetable `ac23-*` créé / supprimé par le test ; tenant `default` jamais modifié."""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

from app.auth import hash_password

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
SUPER = ("superadmin@logitrak.ch", os.environ["SUPERADMIN_PASSWORD"])
ADMIN = ("admin@logitrak.ch", "admin123")
MANAGER = ("manager@logitrak.ch", "manager123")
DRIVER = ("chauffeur@logitrak.ch", "chauffeur123")
RO = ("lecture@logitrak.ch", "lecture123")


def _login(creds):
    r = requests.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token, tid=None):
    h = {"Authorization": f"Bearer {token}"}
    if tid:
        h["X-Tenant-Id"] = tid
    return h


def _code(r):
    d = r.json().get("detail")
    return d.get("code") if isinstance(d, dict) else d


@pytest.fixture(scope="module")
def mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def tenant(mongo):
    tid = f"ac23-{uuid.uuid4().hex[:8]}"
    mongo.tenants.insert_one({"id": tid, "name": "AC Lot23", "status": "active",
                              "created_at": "2026-01-01T00:00:00+00:00"})
    users = {}
    for role in ("admin", "manager", "office", "lecture_seule", "driver"):
        email = f"{role}.{tid}@ac-lot23.example.com"
        uid = str(uuid.uuid4())
        mongo.users.insert_one({"id": uid, "email": email, "name": role.title(), "role": role, "tenant_id": tid,
                                "password_hash": hash_password("Passw0rd!"), "active": True,
                                "created_at": "2026-01-01T00:00:00+00:00"})
        users[role] = {"id": uid, "email": email, "creds": (email, "Passw0rd!")}
    yield {"id": tid, "users": users}
    for coll in ("users", "trips", "audit_log", "settings", "fines", "fuel_cards", "fuel_transactions"):
        mongo[coll].delete_many({"tenant_id": tid})
    mongo.users.delete_many({"email": {"$regex": f"@ac-lot23\\.example\\.com$"}})
    mongo.tenants.delete_one({"id": tid})


# ---------------------------------------------------------------------------
# Lot 2 — Super Admin : catalogue, modules par client, mode de contrôle
# ---------------------------------------------------------------------------
def test_modules_catalog_superadmin_only():
    r = requests.get(f"{BASE}/admin/modules/catalog", headers=_h(_login(SUPER)), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert len(body["modules"]) == 17 and body["modes"] == ["legacy", "shadow", "enforce"]
    assert {m["code"] for m in body["modules"] if m["category"] == "reserved"} >= {"documents", "ev_charging"}
    assert requests.get(f"{BASE}/admin/modules/catalog", headers=_h(_login(ADMIN)), timeout=15).status_code == 403


def test_tenant_modules_update_cascade_and_audit(mongo, tenant):
    tid = tenant["id"]
    sa = _h(_login(SUPER))
    # état initial : legacy defaults (10 modules), aucun champ stocké
    row = next(t for t in requests.get(f"{BASE}/admin/tenants", headers=sa, timeout=15).json() if t["id"] == tid)
    assert row["modules_enabled"] is None and len(row["modules_effective"]) == 10
    assert row["access_control_mode"] is None and row["access_control_mode_effective"] == "legacy"
    # couper fuel → fuel_cards forcé OFF (dépendance) ; activer un module réservé sans dépendance
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa,
                     json={"modules_enabled": {"fuel": False, "documents": True}}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modules_enabled"]["fuel"] is False and body["modules_enabled"]["fuel_cards"] is False
    assert body["modules_enabled"]["documents"] is True
    assert "fuel" not in body["modules_effective"] and "documents" in body["modules_effective"]
    assert "fines" in body["modules_effective"]
    # module inconnu refusé
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa,
                     json={"modules_enabled": {"nope": True}}, timeout=15)
    assert r.status_code == 400 and _code(r) == "unknown_module"
    # audit before/after
    row = mongo.audit_log.find_one({"tenant_id": tid, "action": "tenant.modules_update"}, sort=[("at", -1)])
    assert row and "fuel" in row["details"]["disabled"] and "documents" in row["details"]["enabled"]
    # /auth/me du client reflète les modules et retire les permissions du module OFF
    me = requests.get(f"{BASE}/auth/me", headers=_h(_login(tenant["users"]["admin"]["creds"])), timeout=15).json()
    assert "fuel" not in me["modules_enabled"] and "fuel.view" not in me["permissions_effective"]
    # tenant admin (non superadmin) ne peut pas toucher aux modules
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules",
                     headers=_h(_login(tenant["users"]["admin"]["creds"])),
                     json={"modules_enabled": {"fuel": True}}, timeout=15)
    assert r.status_code == 403
    # réactiver fuel pour la suite (fuel_cards reste OFF tant que non réactivé explicitement)
    r = requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa,
                     json={"modules_enabled": {"fuel": True, "fuel_cards": True}}, timeout=15)
    assert "fuel_cards" in r.json()["modules_effective"]


def test_tenant_mode_update_validation_and_audit(mongo, tenant):
    tid = tenant["id"]
    sa = _h(_login(SUPER))
    r = requests.patch(f"{BASE}/admin/tenants/{tid}", headers=sa, json={"access_control_mode": "bogus"}, timeout=15)
    assert r.status_code == 400
    r = requests.patch(f"{BASE}/admin/tenants/{tid}", headers=sa, json={"access_control_mode": "enforce"}, timeout=15)
    assert r.status_code == 200 and r.json()["access_control_mode_effective"] == "enforce"
    row = mongo.audit_log.find_one({"tenant_id": tid, "action": "tenant.update",
                                    "details.fields": "access_control_mode"}, sort=[("at", -1)])
    assert row["details"]["before"]["access_control_mode"] == "legacy"
    assert row["details"]["after"]["access_control_mode"] == "enforce"


# ---------------------------------------------------------------------------
# Lot 3 — rôle office, catalogue, surcharges par utilisateur
# ---------------------------------------------------------------------------
def test_office_role_creatable_and_catalog(tenant):
    adm = _h(_login(tenant["users"]["admin"]["creds"]))
    email = f"office2.{tenant['id']}@ac-lot23.example.com"
    r = requests.post(f"{BASE}/livre/team/users", headers=adm,
                      json={"email": email, "name": "Office 2", "password": "Passw0rd!", "role": "office"}, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE}/livre/team/permissions/catalog", headers=adm, timeout=15)
    assert r.status_code == 200
    cat = r.json()
    assert "office" in cat["roles"] and len(cat["permissions"]) == 53
    assert "positions.view" not in cat["role_templates"]["office"]
    assert next(p for p in cat["permissions"] if p["code"] == "positions.view")["sensitive"] is True
    # manager (legacy_roles admin) n'accède pas au catalogue
    assert requests.get(f"{BASE}/livre/team/permissions/catalog",
                        headers=_h(_login(tenant["users"]["manager"]["creds"])), timeout=15).status_code == 403


def test_user_permissions_override_rules(mongo, tenant):
    tid = tenant["id"]
    adm = _h(_login(tenant["users"]["admin"]["creds"]))
    office = tenant["users"]["office"]
    driver = tenant["users"]["driver"]
    ro = tenant["users"]["lecture_seule"]
    base = f"{BASE}/livre/team/users"
    # lecture
    r = requests.get(f"{base}/{office['id']}/permissions", headers=adm, timeout=15)
    assert r.status_code == 200 and r.json()["override"] == {"grant": [], "revoke": []}
    assert "positions.view" not in r.json()["effective"]
    # validations
    assert _code(requests.put(f"{base}/{office['id']}/permissions", headers=adm,
                              json={"grant": ["nope.x"]}, timeout=15)) == "unknown_permission"
    assert _code(requests.put(f"{base}/{driver['id']}/permissions", headers=adm,
                              json={"grant": ["positions.view"]}, timeout=15)) == "sensitive_not_allowed_for_role"
    assert _code(requests.put(f"{base}/{ro['id']}/permissions", headers=adm,
                              json={"grant": ["fines.edit"]}, timeout=15)) == "write_not_allowed_for_read_only"
    # pas d'auto-modification
    r = requests.put(f"{base}/{tenant['users']['admin']['id']}/permissions", headers=adm,
                     json={"revoke": ["audit.view"]}, timeout=15)
    assert r.status_code == 400
    # office + positions.view : autorisé par surcharge explicite, audité comme accès GPS
    r = requests.put(f"{base}/{office['id']}/permissions", headers=adm,
                     json={"grant": ["positions.view"], "revoke": ["fines.pay"], "reason": "contrôle facturation"}, timeout=15)
    assert r.status_code == 200, r.text
    assert "positions.view" in r.json()["effective"] and "fines.pay" not in r.json()["effective"]
    row = mongo.audit_log.find_one({"tenant_id": tid, "action": "user.permissions_update"}, sort=[("at", -1)])
    assert row["details"]["gps_access_granted"] is True and row["details"]["reason"] == "contrôle facturation"
    assert "positions.view" in row["details"]["granted"] and "fines.pay" in row["details"]["revoked"]
    # en enforce (tenant en enforce depuis le test précédent) : office voit désormais la trace GPS
    off = _h(_login(office["creds"]))
    me = requests.get(f"{BASE}/auth/me", headers=off, timeout=15).json()
    assert "positions.view" in me["permissions_effective"]
    # module OFF ⇒ surcharge refusée
    sa = _h(_login(SUPER))
    requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa, json={"modules_enabled": {"fines": False}}, timeout=15)
    assert _code(requests.put(f"{base}/{office['id']}/permissions", headers=adm,
                              json={"grant": ["fines.admin"]}, timeout=15)) == "module_disabled"
    requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa, json={"modules_enabled": {"fines": True}}, timeout=15)
    # changement de rôle ⇒ surcharge réinitialisée
    r = requests.patch(f"{base}/{office['id']}", headers=adm, json={"role": "manager"}, timeout=15)
    assert r.status_code == 200 and "permissions_override" not in r.json()
    requests.patch(f"{base}/{office['id']}", headers=adm, json={"role": "office"}, timeout=15)
    # réinitialisation explicite
    r = requests.put(f"{base}/{office['id']}/permissions", headers=adm, json={"grant": [], "revoke": []}, timeout=15)
    assert r.status_code == 200 and r.json()["override"] == {"grant": [], "revoke": []}


# ---------------------------------------------------------------------------
# Lot 3 — routeurs migrés : parité legacy (tenant default) et enforce (tenant jetable)
# ---------------------------------------------------------------------------
LEGACY_MATRIX = [
    # (method, path, {role: status})
    ("GET", "/livre/fines", {"admin": 200, "manager": 200, "lecture_seule": 200, "driver": 403}),
    ("GET", "/livre/fines/mine", {"admin": 200, "manager": 200, "lecture_seule": 200, "driver": 200}),
    ("GET", "/livre/fines/meta", {"driver": 200, "lecture_seule": 200}),
    ("POST", "/livre/fines", {"lecture_seule": 403, "driver": 403}),
    ("GET", "/livre/fuel/cards", {"admin": 200, "manager": 200, "lecture_seule": 200, "driver": 403}),
    ("GET", "/livre/fuel/my-transactions", {"driver": 200, "lecture_seule": 403}),  # 403 interne « Réservé aux chauffeurs »
    ("GET", "/livre/fuel/import-fields", {"admin": 200, "manager": 403}),
    ("GET", "/livre/fuel/settings", {"manager": 200, "driver": 403}),
    ("GET", "/livre/fuel/statements", {"lecture_seule": 200, "driver": 403}),
    ("GET", "/livre/energy/status", {"driver": 200, "lecture_seule": 200}),
    ("GET", "/livre/energy/overview", {"driver": 403, "lecture_seule": 200}),
    ("GET", "/livre/energy/tenant-mapping", {"manager": 200, "lecture_seule": 403}),
    ("GET", "/livre/ble/sessions", {"manager": 200, "driver": 403, "lecture_seule": 403}),
    ("GET", "/livre/ble/settings", {"manager": 200, "lecture_seule": 403}),
    ("GET", "/livre/ble/debug/recent-detections", {"admin": 200, "manager": 403}),
    ("GET", "/livre/driver/vehicles", {"driver": 200, "manager": 400, "lecture_seule": 400}),  # 400 interne « non lié à un chauffeur »
    ("GET", "/livre/reports/weekly-driver/config", {"manager": 200, "lecture_seule": 403, "driver": 403}),
]
CREDS = {"admin": ADMIN, "manager": MANAGER, "driver": DRIVER, "lecture_seule": RO}


@pytest.mark.parametrize("method,path,expected", LEGACY_MATRIX)
def test_legacy_matrix_unchanged_on_default_tenant(method, path, expected):
    for role, status in expected.items():
        r = requests.request(method, f"{BASE}{path}", headers=_h(_login(CREDS[role])), json={}, timeout=20)
        assert r.status_code == status, f"{role} {method} {path} → {r.status_code} (attendu {status}) {r.text[:120]}"


def test_enforce_on_migrated_routers(mongo, tenant):
    tid = tenant["id"]
    u = tenant["users"]
    mongo.tenants.update_one({"id": tid}, {"$set": {"access_control_mode": "enforce"}})
    off = _h(_login(u["office"]["creds"]))
    mgr = _h(_login(u["manager"]["creds"]))
    drv = _h(_login(u["driver"]["creds"]))
    # office (hors matrice legacy) : lecture carburant / amendes OK, identification refusée
    assert requests.get(f"{BASE}/livre/fuel/transactions", headers=off, timeout=15).status_code == 200
    assert requests.get(f"{BASE}/livre/fines", headers=off, timeout=15).status_code == 200
    r = requests.get(f"{BASE}/livre/ble/sessions", headers=off, timeout=15)
    assert r.status_code == 403 and _code(r) == "permission_denied"
    # office : imports carburant autorisés par le modèle (fuel.import), rapprochement refusé
    assert requests.get(f"{BASE}/livre/fuel/import-fields", headers=off, timeout=15).status_code == 200
    r = requests.post(f"{BASE}/livre/fuel/anomalies/scan", headers=off, timeout=15)
    assert r.status_code == 403 and r.json()["detail"]["permission"] == "fuel.reconcile"
    # manager : surcharge revoke fines.view ⇒ liste refusée, statements (admin legacy) refusé
    mongo.users.update_one({"id": u["manager"]["id"]}, {"$set": {"permissions_override": {"grant": [], "revoke": ["fines.view"]}}})
    r = requests.get(f"{BASE}/livre/fines", headers=mgr, timeout=15)
    assert r.status_code == 403 and _code(r) == "permission_denied"
    assert requests.post(f"{BASE}/livre/fuel/statements", headers=mgr, json={}, timeout=15).status_code == 403
    mongo.users.update_one({"id": u["manager"]["id"]}, {"$unset": {"permissions_override": ""}})
    # chauffeur : console (permission OK → 400 interne « non lié », jamais 403) et mes amendes OK, liste entreprise refusée
    assert requests.get(f"{BASE}/livre/driver/vehicles", headers=drv, timeout=15).status_code == 400
    assert requests.get(f"{BASE}/livre/fines/mine", headers=drv, timeout=15).status_code == 200
    assert _code(requests.get(f"{BASE}/livre/fines", headers=drv, timeout=15)) == "permission_denied"
    # module fuel_cards OFF seul ⇒ cartes refusées (module_disabled), transactions OK
    sa = _h(_login(SUPER))
    requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa, json={"modules_enabled": {"fuel_cards": False}}, timeout=15)
    r = requests.get(f"{BASE}/livre/fuel/cards", headers=_h(_login(u["admin"]["creds"])), timeout=15)
    assert r.status_code == 403 and _code(r) == "module_disabled" and r.json()["detail"]["module"] == "fuel_cards"
    assert requests.get(f"{BASE}/livre/fuel/transactions", headers=_h(_login(u["admin"]["creds"])), timeout=15).status_code == 200
    mongo.tenants.update_one({"id": tid}, {"$set": {"access_control_mode": "legacy"}})



def test_enforce_driver_private_mode_module(mongo, tenant):
    """Lot 5 : `/driver/private-mode` dépend du module `private_mode` (comme les réglages web),
    pas seulement de `drivers` — l'app chauffeur masque la carte, le backend tranche en enforce."""
    tid = tenant["id"]
    drv = _h(_login(tenant["users"]["driver"]["creds"]))
    sa = _h(_login(SUPER))
    mongo.tenants.update_one({"id": tid}, {"$set": {"access_control_mode": "enforce"}})
    try:
        requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa,
                     json={"modules_enabled": {"private_mode": False}}, timeout=15)
        for method in ("get", "post"):
            r = requests.request(method, f"{BASE}/livre/driver/private-mode", headers=drv,
                                 json={"mode": "PRIVATE"} if method == "post" else None, timeout=15)
            assert r.status_code == 403 and _code(r) == "module_disabled", (method, r.text)
            assert r.json()["detail"]["module"] == "private_mode" and r.json()["detail"].get("msg")
        requests.put(f"{BASE}/admin/tenants/{tid}/modules", headers=sa,
                     json={"modules_enabled": {"private_mode": True}}, timeout=15)
        r = requests.get(f"{BASE}/livre/driver/private-mode", headers=drv, timeout=15)
        assert r.status_code != 403, r.text  # chauffeur non lié ⇒ erreur métier (jamais un refus d'accès)
        # module `drivers` ON mais permission retirée ⇒ permission_denied lisible
        mongo.users.update_one({"id": tenant["users"]["driver"]["id"]},
                               {"$set": {"permissions_override": {"grant": [], "revoke": ["identification.self"]}}})
        r = requests.get(f"{BASE}/livre/driver/private-mode", headers=drv, timeout=15)
        assert r.status_code == 403 and _code(r) == "permission_denied", r.text
    finally:
        mongo.users.update_one({"id": tenant["users"]["driver"]["id"]}, {"$unset": {"permissions_override": ""}})
        mongo.tenants.update_one({"id": tid}, {"$set": {"access_control_mode": "legacy"}, "$unset": {"modules_enabled": ""}})
