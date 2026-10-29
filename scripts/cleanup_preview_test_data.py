"""Nettoyage des artefacts de test en base PREVIEW (jamais en production).

Supprime : tenants « TEST* » (+ utilisateurs, audit, données métier), utilisateurs ivan.<hex>@example.com
et leurs chauffeurs de test « Ivan Petrov<hex> », invitations test.inv.*/pending.*@client.ch.
Ne touche jamais : tenant default, Client Test B, comptes partagés, paul.test / invite.test.

Usage : python scripts/cleanup_preview_test_data.py            (dry-run)
        python scripts/cleanup_preview_test_data.py --apply
"""
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.tenancy import BUSINESS_COLLECTIONS  # noqa: E402

PROTECTED_TENANTS = {"default", "0ce32dd4-4aee-4046-96fa-b5533dbee8db"}
IVAN_RE = re.compile(r"^ivan\.[0-9a-f]{8}@example\.com$")
IVAN_DRIVER_RE = re.compile(r"^(Ivan Petrov([0-9a-f]{8})?|TEST_(INV|PEND)_[0-9a-f]+.*)$")
INVITE_RE = re.compile(r"^(test\.inv|pending)\.[0-9a-f]{8}@client\.ch$")


def main(apply: bool):
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    tenants = [t for t in db.tenants.find({}, {"_id": 0, "id": 1, "name": 1})
               if t["id"] not in PROTECTED_TENANTS and re.match(r"(?i)^test", t.get("name", ""))]
    tids = [t["id"] for t in tenants]
    plan = {"tenants": len(tids), "users_in_test_tenants": db.users.count_documents({"tenant_id": {"$in": tids}})}
    for c in sorted(set(BUSINESS_COLLECTIONS) | {"audit_log", "settings", "invitations", "push_tokens"}):
        n = db[c].count_documents({"tenant_id": {"$in": tids}})
        if n:
            plan[f"{c} (test tenants)"] = n
    ivan_users = list(db.users.find({"email": {"$regex": IVAN_RE.pattern}}, {"_id": 0, "id": 1, "email": 1}))
    ivan_ids = [u["id"] for u in ivan_users]
    ivan_drivers = list(db.drivers.find({"tenant_id": "default",
                                         "$or": [{"user_id": {"$in": ivan_ids}}, {"name": {"$regex": IVAN_DRIVER_RE.pattern}}]},
                                        {"_id": 0, "id": 1}))
    did = [d["id"] for d in ivan_drivers]
    linked = sum(db[c].count_documents({"driver_id": {"$in": did}}) for c in ("trips", "assignments", "fines", "fuel_transactions")
                 if c in db.list_collection_names())
    plan.update({"ivan_users": len(ivan_ids), "ivan_drivers": len(did), "ivan_driver_linked_business_docs": linked,
                 "test_invitations": db.invitations.count_documents({"email": {"$regex": INVITE_RE.pattern}})})
    for k, v in plan.items():
        print(f"{k:40s} {v}")
    if linked:
        print("ABANDON : des chauffeurs Ivan* portent des données métier — vérifier manuellement.")
        return 1
    if not apply:
        print("\nDRY-RUN — relancer avec --apply pour supprimer.")
        return 0
    for c in set(BUSINESS_COLLECTIONS) | {"audit_log", "settings", "invitations", "push_tokens", "users"}:
        db[c].delete_many({"tenant_id": {"$in": tids}})
    db.tenants.delete_many({"id": {"$in": tids}})
    db.drivers.delete_many({"id": {"$in": did}})
    db.users.delete_many({"id": {"$in": ivan_ids}})
    db.login_attempts.delete_many({"email": {"$regex": IVAN_RE.pattern}})
    db.invitations.delete_many({"email": {"$regex": INVITE_RE.pattern}})
    print("\nSUPPRIMÉ. Reste :", {"tenants": db.tenants.count_documents({}), "users": db.users.count_documents({}),
                              "drivers default": db.drivers.count_documents({"tenant_id": "default"}),
                              "invitations": db.invitations.count_documents({})})
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
