"""Lot 6 (préparation) — bilan de préparation au mode enforce : fonction pure + endpoint Super Admin."""
import os
from datetime import datetime, timedelta, timezone

import requests

from app import access_control as ac

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
SUPER = ("superadmin@logitrak.ch", os.environ["SUPERADMIN_PASSWORD"])
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
TENANT = {"id": "t1", "status": "active"}


def _deny(key, email, role="office", kind="permission"):
    return {"user_email": email, "details": {"kind": kind, "key": key, "role": role}}


def test_readiness_ready_when_clean():
    r = ac.enforce_readiness(TENANT, [{"email": "a@x.ch", "role": "admin"}], [], (NOW - timedelta(days=10)).isoformat(), NOW)
    assert r["ready"] is True
    assert {c["id"]: c["status"] for c in r["checks"]} == {
        "tenant_active": "ok", "observation": "ok", "shadow_denies": "ok", "roles_known": "ok", "overrides_valid": "ok"}
    assert r["observation"]["days"] == 10


def test_readiness_warnings_do_not_block():
    users = [{"email": "o@x.ch", "role": "office", "permissions_override": {"grant": ["fines.view"], "revoke": []}}]
    tenant = {**TENANT, "modules_enabled": {"fines": False}}
    r = ac.enforce_readiness(tenant, users, [_deny("positions.view", "o@x.ch"), _deny("positions.view", "o@x.ch"),
                                             _deny("fines", "o@x.ch", kind="module")], None, NOW)
    st = {c["id"]: c["status"] for c in r["checks"]}
    assert r["ready"] is True
    assert st["observation"] == "warn" and st["shadow_denies"] == "warn" and st["overrides_valid"] == "warn"
    assert r["observation"]["by_key"][0] == {"kind": "permission", "key": "positions.view", "count": 2, "users": 1, "roles": ["office"]}
    assert r["invalid_overrides"] == [{"email": "o@x.ch", "grant": "fines.view", "reason": "module_disabled"}]


def test_readiness_blocked_on_unknown_role_or_suspended():
    r = ac.enforce_readiness({**TENANT, "status": "suspended"}, [{"email": "z@x.ch", "role": "zombie"}], [], None, NOW)
    assert r["ready"] is False
    st = {c["id"]: c["status"] for c in r["checks"]}
    assert st["tenant_active"] == "fail" and st["roles_known"] == "fail"
    assert r["users"]["unknown_role"] == ["z@x.ch"]


def test_readiness_endpoint_superadmin_only():
    tok = requests.post(f"{BASE}/auth/login", json={"email": SUPER[0], "password": SUPER[1]}, timeout=15).json()["access_token"]
    r = requests.get(f"{BASE}/admin/tenants/default/enforce-readiness", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "default" and body["mode_effective"] in ("legacy", "shadow")
    assert {c["id"] for c in body["checks"]} == {"tenant_active", "observation", "shadow_denies", "roles_known", "overrides_valid"}
    assert requests.get(f"{BASE}/admin/tenants/nope/enforce-readiness", headers={"Authorization": f"Bearer {tok}"}, timeout=15).status_code == 404
    adm = requests.post(f"{BASE}/auth/login", json={"email": "admin@logitrak.ch", "password": "admin123"}, timeout=15).json()["access_token"]
    assert requests.get(f"{BASE}/admin/tenants/default/enforce-readiness", headers={"Authorization": f"Bearer {adm}"}, timeout=15).status_code == 403
