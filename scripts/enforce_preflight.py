"""Pré-vol Lot 6 — invariants à vérifier AVANT tout passage en mode enforce (preview ou production).

Lecture seule. Usage : python scripts/enforce_preflight.py [--tenant <id>]
Code retour 1 si un contrôle bloquant échoue.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.access_control import TENANT_ROLES, enforce_readiness, resolve_mode  # noqa: E402


def main(only_tenant: str | None) -> int:
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()
    failures = 0
    print(f"ACCESS_CONTROL_MODE (serveur) = {os.environ.get('ACCESS_CONTROL_MODE', '<absent → legacy>')}\n")

    no_tenant = list(db.users.find({"role": {"$ne": "superadmin"}, "tenant_id": {"$in": [None, ""]}}, {"_id": 0, "email": 1}))
    print(f"[{'FAIL' if no_tenant else 'OK  '}] utilisateurs entreprise sans tenant_id : {len(no_tenant)}",
          [u["email"] for u in no_tenant][:5])
    failures += bool(no_tenant)
    bad_roles = list(db.users.find({"role": {"$nin": list(TENANT_ROLES) + ["superadmin"]}}, {"_id": 0, "email": 1, "role": 1}))
    print(f"[{'FAIL' if bad_roles else 'OK  '}] rôles inconnus : {len(bad_roles)}", bad_roles[:5])
    failures += bool(bad_roles)
    not_active = list(db.tenants.find({"status": {"$ne": "active"}}, {"_id": 0, "id": 1, "name": 1, "status": 1}))
    print(f"[{'WARN' if not_active else 'OK  '}] tenants non actifs : {len(not_active)}", not_active[:5])

    print("\nPar client :")
    q = {"id": only_tenant} if only_tenant else {}
    for t in db.tenants.find(q, {"_id": 0}):
        users = list(db.users.find({"tenant_id": t["id"]}, {"_id": 0, "email": 1, "role": 1, "active": 1, "permissions_override": 1}))
        denies = list(db.audit_log.find({"tenant_id": t["id"], "action": "access.shadow_deny", "at": {"$gte": since}},
                                        {"_id": 0, "details": 1, "user_email": 1}))
        last_shadow = db.audit_log.find_one({"tenant_id": t["id"], "action": "tenant.update",
                                             "details.after.access_control_mode": "shadow"}, {"_id": 0, "at": 1}, sort=[("at", -1)])
        shadow_since = last_shadow["at"] if last_shadow and resolve_mode(t) == "shadow" else None
        r = enforce_readiness(t, users, denies, shadow_since, now)
        flag = "READY" if r["ready"] else "BLOCKED"
        print(f"  {t['id'][:12]:12s} {t.get('name', '')[:24]:24s} mode={r['mode_effective']:7s} users={r['users']['total']:3d} "
              f"denies30j={r['observation']['shadow_denies']:3d} {flag}")
        for c in r["checks"]:
            if c["status"] != "ok":
                print(f"      - {c['status'].upper():4s} {c['label']} — {c['detail']}")
        for d in r["observation"]["by_key"][:5]:
            print(f"      · {d['kind']} {d['key']} ×{d['count']} ({', '.join(d['roles']) or '?'})")
        failures += not r["ready"]
    print(f"\n{'PRÉ-VOL OK' if not failures else f'PRÉ-VOL : {failures} blocage(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    tid = sys.argv[sys.argv.index("--tenant") + 1] if "--tenant" in sys.argv else None
    sys.exit(main(tid))
