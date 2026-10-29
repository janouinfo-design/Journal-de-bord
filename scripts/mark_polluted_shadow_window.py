"""Marque une fenêtre de refus shadow pollués — SANS supprimer ni modifier les événements d'audit.

Contexte (29/10/2026, tenant Logitrak `default`) : un test UI a coupé `fines`, `fuel`, `fuel_cards`
(`tenant.modules_update` 14:29:52 UTC) jusqu'au rétablissement (14:55:47 UTC). Pendant cette fenêtre,
le mode Observation a journalisé des refus `access.shadow_deny` qui n'existeraient pas avec les modules réels.

Méthode : la fenêtre est dérivée des audits `tenant.modules_update` (modules coupés → rétablis) et enregistrée
dans `tenants.observation_exclusions` (règle de LECTURE : `access_control.deny_exclusion`). Le bilan
`enforce-readiness`, le pré-vol et la page Audit Super Admin comptent ces refus à part. Un audit
`tenant.observation_exclusion_add` documente l'opération.

Usage : cd /app/backend && python ../scripts/mark_polluted_shadow_window.py [--tenant default] [--apply]
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.access_control import deny_exclusion  # noqa: E402

SOURCE = "scripts/mark_polluted_shadow_window.py"


def detect_windows(db, tenant_id: str) -> list[dict]:
    """Paires (modules coupés → mêmes modules rétablis) dans l'audit du client."""
    updates = list(db.audit_log.find({"tenant_id": tenant_id, "action": "tenant.modules_update"},
                                     {"_id": 0, "at": 1, "details": 1, "user_email": 1}).sort("at", 1))
    windows = []
    for i, u in enumerate(updates):
        disabled = set((u.get("details") or {}).get("disabled") or [])
        if not disabled:
            continue
        for v in updates[i + 1:]:
            enabled = set((v.get("details") or {}).get("enabled") or [])
            if disabled <= enabled:
                windows.append({"from": u["at"], "to": v["at"], "modules": sorted(disabled),
                                "disabled_by": u.get("user_email"), "restored_by": v.get("user_email")})
                break
    return windows


def main() -> int:
    tenant_id = sys.argv[sys.argv.index("--tenant") + 1] if "--tenant" in sys.argv else "default"
    apply = "--apply" in sys.argv
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    tenant = db.tenants.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "name": 1, "observation_exclusions": 1})
    if not tenant:
        print(f"tenant {tenant_id} introuvable")
        return 1
    existing = tenant.get("observation_exclusions") or []
    windows = detect_windows(db, tenant_id)
    if not windows:
        print("Aucune fenêtre « modules coupés puis rétablis » détectée.")
        return 0
    denies = list(db.audit_log.find({"tenant_id": tenant_id, "action": "access.shadow_deny"},
                                    {"_id": 0, "at": 1, "details": 1, "user_email": 1}))
    print(f"Client {tenant['name']} ({tenant_id}) — {len(denies)} refus shadow bruts en base (jamais modifiés)\n")
    added = 0
    for w in windows:
        dup = next((e for e in existing if e["from"] == w["from"] and e["to"] == w["to"]), None)
        ex = dup or {"id": str(uuid.uuid4()), "from": w["from"], "to": w["to"], "modules": w["modules"],
                     "reason": (f"Fenêtre de test : modules {', '.join(w['modules'])} coupés par erreur "
                                f"({w['disabled_by']}) puis rétablis ({w['restored_by']}). Refus non représentatifs."),
                     "source": SOURCE, "created_at": datetime.now(timezone.utc).isoformat(), "created_by": "script"}
        covered = [d for d in denies if deny_exclusion(d, [ex])]
        legit = [d for d in denies if not deny_exclusion(d, [ex])]
        print(f"Fenêtre {w['from'][:19]}Z → {w['to'][:19]}Z  modules={w['modules']}  {'(déjà enregistrée)' if dup else ''}")
        print(f"  refus couverts (exclus du calcul) : {len(covered)}")
        for k in sorted({(d['details'].get('kind'), d['details'].get('key')) for d in covered}):
            print(f"    - {k[0]} {k[1]} ×{sum(1 for d in covered if (d['details'].get('kind'), d['details'].get('key')) == k)}")
        print(f"  refus conservés dans le bilan : {len(legit)}")
        for k in sorted({(d['details'].get('kind'), d['details'].get('key'), d.get('user_email')) for d in legit}):
            print(f"    - {k[0]} {k[1]} ({k[2]}) ×{sum(1 for d in legit if (d['details'].get('kind'), d['details'].get('key'), d.get('user_email')) == k)}")
        if apply and not dup:
            db.tenants.update_one({"id": tenant_id}, {"$push": {"observation_exclusions": ex}})
            db.audit_log.insert_one({
                "id": str(uuid.uuid4()), "action": "tenant.observation_exclusion_add",
                "at": datetime.now(timezone.utc).isoformat(), "tenant_id": tenant_id,
                "user_id": None, "user_email": "script", "user_role": "superadmin",
                "details": {"exclusion_id": ex["id"], "from": ex["from"], "to": ex["to"], "modules": ex["modules"],
                            "reason": ex["reason"], "excluded_count": len(covered), "source": SOURCE,
                            "note": "Événements access.shadow_deny conservés intacts ; exclusion = règle de lecture."},
            })
            added += 1
    print(f"\n{'ENREGISTRÉ' if apply else 'DRY-RUN — relancer avec --apply'} : {added} fenêtre(s) ajoutée(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
