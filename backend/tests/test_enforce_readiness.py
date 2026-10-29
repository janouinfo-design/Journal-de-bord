"""Lot 6 (préparation) — bilan de préparation au mode enforce : fonction pure, exclusions de lecture,
garde-fou « N jours d'Observation » côté serveur (PATCH enforce refusé) + endpoint Super Admin."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

from app import access_control as ac

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
SUPER = ("superadmin@logitrak.ch", os.environ["SUPERADMIN_PASSWORD"])
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
TENANT = {"id": "t1", "status": "active"}
OBSERVED = (NOW - timedelta(days=10)).isoformat()


def _deny(key, email, role="office", kind="permission", at=None):
    return {"user_email": email, "at": at or NOW.isoformat(), "details": {"kind": kind, "key": key, "role": role}}


def _st(r):
    return {c["id"]: c["status"] for c in r["checks"]}


def test_readiness_ready_when_clean():
    r = ac.enforce_readiness(TENANT, [{"email": "a@x.ch", "role": "admin"}], [], OBSERVED, NOW)
    assert r["ready"] is True and r["blocked_reasons"] == []
    assert _st(r) == {"tenant_active": "ok", "observation": "ok", "shadow_denies": "ok", "roles_known": "ok", "overrides_valid": "ok"}
    assert r["observation"]["days"] == 10 and r["observation"]["required_days"] == ac.OBSERVATION_MIN_DAYS == 7


def test_readiness_warnings_do_not_block():
    users = [{"email": "o@x.ch", "role": "office", "permissions_override": {"grant": ["fines.view"], "revoke": []}}]
    tenant = {**TENANT, "modules_enabled": {"fines": False}}
    r = ac.enforce_readiness(tenant, users, [_deny("positions.view", "o@x.ch"), _deny("positions.view", "o@x.ch"),
                                             _deny("fines", "o@x.ch", kind="module")], OBSERVED, NOW)
    assert r["ready"] is True
    st = _st(r)
    assert st["observation"] == "ok" and st["shadow_denies"] == "warn" and st["overrides_valid"] == "warn"
    assert r["observation"]["by_key"][0] == {"kind": "permission", "key": "positions.view", "count": 2, "users": 1, "roles": ["office"]}
    assert r["invalid_overrides"] == [{"email": "o@x.ch", "grant": "fines.view", "reason": "module_disabled"}]


def test_observation_guard_blocks_until_min_days():
    # jamais observé ⇒ fail, pas de date d'éligibilité
    r = ac.enforce_readiness(TENANT, [], [], None, NOW)
    assert r["ready"] is False and _st(r)["observation"] == "fail"
    assert r["observation"]["eligible_at"] is None and "jamais passé en mode Observation" in r["blocked_reasons"][0]
    # 3 jours sur 7 ⇒ fail avec date d'éligibilité = début + 7 j
    since = NOW - timedelta(days=3)
    r = ac.enforce_readiness(TENANT, [], [], since.isoformat(), NOW)
    assert r["ready"] is False and _st(r)["observation"] == "fail"
    assert r["observation"]["eligible_at"] == (since + timedelta(days=7)).isoformat()
    assert "3 jour(s) en Observation sur 7 requis" in r["blocked_reasons"][0] and "éligible le 02/11/2026" in r["blocked_reasons"][0]
    # exactement 7 jours ⇒ ok ; seuil configurable
    assert ac.enforce_readiness(TENANT, [], [], (NOW - timedelta(days=7)).isoformat(), NOW)["ready"] is True
    assert ac.enforce_readiness(TENANT, [], [], since.isoformat(), NOW, min_days=3)["ready"] is True
    assert ac.enforce_readiness(TENANT, [], [], since.isoformat(), NOW, min_days=4)["ready"] is False


def test_exclusion_window_is_read_only_rule():
    win = {"id": "w1", "from": (NOW - timedelta(hours=2)).isoformat(), "to": (NOW - timedelta(hours=1)).isoformat(),
           "modules": ["fuel", "fuel_cards", "fines"], "reason": "fenêtre de test", "source": "test"}
    tenant = {**TENANT, "observation_exclusions": [win]}
    inside = (NOW - timedelta(minutes=90)).isoformat()
    denies = [
        _deny("fuel", "a@x.ch", kind="module", at=inside),            # exclu (module coupé dans la fenêtre)
        _deny("fines.view", "a@x.ch", at=inside),                      # exclu (permission d'un module coupé)
        _deny("identification.self", "ro@x.ch", role="lecture_seule", at=inside),  # conservé (module non concerné)
        _deny("fuel.view", "b@x.ch", at=(NOW - timedelta(minutes=10)).isoformat()),  # conservé (hors fenêtre)
    ]
    assert ac.deny_exclusion(denies[0], [win]) is win and ac.deny_exclusion(denies[2], [win]) is None
    assert ac.deny_exclusion(denies[3], [win]) is None and ac.deny_exclusion({"details": {}}, [win]) is None
    r = ac.enforce_readiness(tenant, [], denies, OBSERVED, NOW)
    assert r["observation"]["shadow_denies"] == 2 and r["observation"]["excluded"] == 2
    assert {d["key"] for d in r["observation"]["by_key"]} == {"identification.self", "fuel.view"}
    assert r["observation"]["exclusions"][0]["excluded_count"] == 2 and r["observation"]["exclusions"][0]["reason"] == "fenêtre de test"
    assert "2 exclu(s)" in next(c for c in r["checks"] if c["id"] == "shadow_denies")["detail"]
    # fenêtre sans liste de modules ⇒ tout ce qui est dedans est exclu
    r2 = ac.enforce_readiness({**TENANT, "observation_exclusions": [{**win, "modules": []}]}, [], denies, OBSERVED, NOW)
    assert r2["observation"]["excluded"] == 3


def test_readiness_blocked_on_unknown_role_or_suspended():
    r = ac.enforce_readiness({**TENANT, "status": "suspended"}, [{"email": "z@x.ch", "role": "zombie"}], [], OBSERVED, NOW)
    assert r["ready"] is False
    st = _st(r)
    assert st["tenant_active"] == "fail" and st["roles_known"] == "fail"
    assert r["users"]["unknown_role"] == ["z@x.ch"] and len(r["blocked_reasons"]) == 2


# ---------------------------------------------------------------------------
# Endpoint + garde-fou serveur sur un tenant jetable (jamais `default`)
# ---------------------------------------------------------------------------
def _tok(creds):
    return requests.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]}, timeout=15).json()["access_token"]


@pytest.fixture(scope="module")
def mongo():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture()
def throwaway(mongo):
    tid = f"ac6-{uuid.uuid4().hex[:8]}"
    mongo.tenants.insert_one({"id": tid, "name": "AC Lot6", "status": "active", "created_at": NOW.isoformat()})
    yield tid
    mongo.audit_log.delete_many({"tenant_id": tid})
    mongo.tenants.delete_one({"id": tid})


def test_readiness_endpoint_superadmin_only():
    tok = _tok(SUPER)
    r = requests.get(f"{BASE}/admin/tenants/default/enforce-readiness", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "default" and body["mode_effective"] in ("legacy", "shadow")
    assert {c["id"] for c in body["checks"]} == {"tenant_active", "observation", "shadow_denies", "roles_known", "overrides_valid"}
    assert body["observation"]["required_days"] == ac.OBSERVATION_MIN_DAYS
    assert body["ready"] == (not body["blocked_reasons"])
    assert requests.get(f"{BASE}/admin/tenants/nope/enforce-readiness", headers={"Authorization": f"Bearer {tok}"}, timeout=15).status_code == 404
    adm = _tok(("admin@logitrak.ch", "admin123"))
    assert requests.get(f"{BASE}/admin/tenants/default/enforce-readiness", headers={"Authorization": f"Bearer {adm}"}, timeout=15).status_code == 403


def test_patch_enforce_refused_without_observation(mongo, throwaway):
    sa = {"Authorization": f"Bearer {_tok(SUPER)}"}
    # jamais observé ⇒ 409 enforce_not_ready, mode inchangé, audit tenant.enforce_refused
    r = requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "enforce"}, timeout=15)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["code"] == "enforce_not_ready" and "jamais passé en mode Observation" in d["msg"] and d["eligible_at"] is None
    assert mongo.tenants.find_one({"id": throwaway}).get("access_control_mode") is None
    assert mongo.audit_log.find_one({"tenant_id": throwaway, "action": "tenant.enforce_refused"})
    # observation de 2 jours seulement ⇒ 409 avec date d'éligibilité
    r = requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "shadow"}, timeout=15)
    assert r.status_code == 200 and r.json()["access_control_mode"] == "shadow"
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    mongo.audit_log.update_one({"tenant_id": throwaway, "action": "tenant.update", "details.after.access_control_mode": "shadow"},
                               {"$set": {"at": two_days_ago}})
    r = requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "enforce"}, timeout=15)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert "2 jour(s) en Observation sur 7 requis" in d["msg"]
    assert d["eligible_at"] == (datetime.fromisoformat(two_days_ago) + timedelta(days=7)).isoformat()
    assert mongo.tenants.find_one({"id": throwaway})["access_control_mode"] == "shadow"
    # legacy ⇐ shadow reste libre (le garde-fou ne concerne que l'entrée en enforce)
    assert requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "legacy"}, timeout=15).status_code == 200


def test_patch_enforce_allowed_after_observation(mongo, throwaway):
    sa = {"Authorization": f"Bearer {_tok(SUPER)}"}
    assert requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "shadow"}, timeout=15).status_code == 200
    mongo.audit_log.update_one({"tenant_id": throwaway, "action": "tenant.update", "details.after.access_control_mode": "shadow"},
                               {"$set": {"at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}})
    rd = requests.get(f"{BASE}/admin/tenants/{throwaway}/enforce-readiness", headers=sa, timeout=15).json()
    assert rd["ready"] is True and rd["observation"]["days"] == 8
    r = requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "enforce"}, timeout=15)
    assert r.status_code == 200 and r.json()["access_control_mode_effective"] == "enforce", r.text
    # retour immédiat en legacy : aucun tenant ne reste en enforce
    assert requests.patch(f"{BASE}/admin/tenants/{throwaway}", headers=sa, json={"access_control_mode": "legacy"}, timeout=15).status_code == 200
    assert mongo.tenants.count_documents({"access_control_mode": "enforce"}) == 0
