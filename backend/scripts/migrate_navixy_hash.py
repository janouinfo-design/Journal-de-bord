"""Migration sûre de tenants.navixy_hash vers le chiffrement courant (Fernet enc::).

⚠️ PRÉPARATION / OUTIL ADMIN — jamais lancé au boot ni implicitement.
Dry-run par défaut. `--apply` requis pour écrire (à NE PAS exécuter en prod sans validation).

Garanties :
- READ-ONLY par défaut (dry-run) ; aucune écriture sans --apply.
- Ne migre QUE les valeurs LEGACY_PLAINTEXT reconnues.
- N'écrase JAMAIS une valeur ENCRYPTED_VALID (pas de double chiffrement).
- N'essaie JAMAIS de "réparer" un INVALID_ENCRYPTED (intervention manuelle requise).
- Fail-closed : clé de chiffrement absente/invalide -> arrêt, aucune écriture.
- Protection concurrentielle : update conditionné à la valeur relue (SKIP CONFLICT sinon).
- Aucun secret (plaintext / ciphertext / token / clé) n'est jamais imprimé ni loggé.
- Aucun backup en clair n'est créé (rollback = snapshot Mongo, documenté, non exécuté ici).

USAGE :
    python -m scripts.migrate_navixy_hash --dry-run        # défaut, aucun write
    python -m scripts.migrate_navixy_hash --apply          # écrit (NE PAS en prod sans GO)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _BACKEND_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.integrations import (  # noqa: E402
    classify_secret, encrypt_secret, encryption_key_available,
    FMT_ABSENT, FMT_EMPTY, FMT_LEGACY_PLAINTEXT, FMT_ENCRYPTED_VALID, FMT_INVALID_ENCRYPTED,
)


def _new_counters() -> dict:
    return {
        "analyzed": 0,
        FMT_ENCRYPTED_VALID: 0,
        FMT_LEGACY_PLAINTEXT: 0,
        FMT_ABSENT: 0,
        FMT_EMPTY: 0,
        FMT_INVALID_ENCRYPTED: 0,
        "to_migrate": 0,
        "migrated": 0,
        "skipped_conflict": 0,
        "writes": 0,
        "errors": 0,
    }


async def migrate_navixy_hash(db, *, apply: bool = False) -> dict:
    """Cœur de migration (testable). Retour = compteurs NON sensibles + statut.

    - apply=False (défaut) : dry-run strict, aucune écriture.
    - apply=True  : chiffre les LEGACY_PLAINTEXT, avec relecture conditionnelle (anti-concurrence).
    Fail-closed : si la clé n'est pas disponible -> aucune écriture, statut FAILED_NO_KEY.
    """
    c = _new_counters()

    # FAIL-CLOSED : sans clé de chiffrement valide, on ne fait AUCUNE écriture.
    if apply and not encryption_key_available():
        return {"status": "FAILED_NO_KEY", "apply": apply, "counters": c,
                "message": "INTEGRATION_ENCRYPTION_KEY absente/invalide — aucune écriture."}

    cursor = db.tenants.find({}, {"_id": 0, "id": 1, "navixy_hash": 1})
    tenants = await cursor.to_list(100000) if hasattr(cursor, "to_list") else cursor

    for t in tenants:
        c["analyzed"] += 1
        tenant_id = t.get("id")  # identifiant NON sensible
        stored = t.get("navixy_hash")
        fmt = classify_secret(stored)
        c[fmt] = c.get(fmt, 0) + 1

        if fmt != FMT_LEGACY_PLAINTEXT:
            # ENCRYPTED_VALID -> SKIP (pas de double chiffrement)
            # INVALID_ENCRYPTED -> SKIP (intervention manuelle ; jamais réparé auto)
            # ABSENT/EMPTY -> rien à migrer
            continue

        c["to_migrate"] += 1
        if not apply:
            continue  # dry-run : aucune écriture

        # --- APPLY : chiffrer, avec protection concurrentielle ---
        try:
            new_value = encrypt_secret(stored)  # "enc::..."
            # Update CONDITIONNEL : la valeur en base doit être EXACTEMENT celle auditée.
            res = await db.tenants.update_one(
                {"id": tenant_id, "navixy_hash": stored},
                {"$set": {"navixy_hash": new_value}},
            )
            matched = getattr(res, "matched_count", None)
            if matched == 0:
                c["skipped_conflict"] += 1  # la valeur a changé entre lecture et écriture
            else:
                c["migrated"] += 1
                c["writes"] += 1
        except Exception:
            c["errors"] += 1  # jamais de secret dans l'exception loggée

    status = "OK" if c["errors"] == 0 else "COMPLETED_WITH_ERRORS"
    return {"status": status, "apply": apply, "counters": c}


def _print_report(result: dict) -> None:
    c = result["counters"]
    print("=" * 56, flush=True)
    print("NAVIXY_HASH MIGRATION — %s" % ("APPLY" if result["apply"] else "DRY-RUN"), flush=True)
    print("=" * 56, flush=True)
    if result["status"] == "FAILED_NO_KEY":
        print("STATUT = FAILED_NO_KEY (fail-closed) —", result.get("message"), flush=True)
        return
    print("Tenants analyses       : %d" % c["analyzed"], flush=True)
    print("Deja chiffres valides  : %d" % c[FMT_ENCRYPTED_VALID], flush=True)
    print("Legacy en clair        : %d" % c[FMT_LEGACY_PLAINTEXT], flush=True)
    print("Champ vide/absent      : %d" % (c[FMT_EMPTY] + c[FMT_ABSENT]), flush=True)
    print("Chiffres invalides     : %d  (INVALID_ENCRYPTED -> intervention manuelle)"
          % c[FMT_INVALID_ENCRYPTED], flush=True)
    print("A migrer               : %d" % c["to_migrate"], flush=True)
    print("Migres                 : %d" % c["migrated"], flush=True)
    print("Skip conflit           : %d" % c["skipped_conflict"], flush=True)
    print("Ecritures effectuees   : %d" % c["writes"], flush=True)
    print("Erreurs                : %d" % c["errors"], flush=True)
    print("STATUT = %s" % result["status"], flush=True)
    print("(Aucun secret affiche. Identifiants tenant uniquement.)", flush=True)


async def _main_async(apply: bool) -> None:
    from app.db import init_db, get_db
    init_db()
    db = get_db()
    result = await migrate_navixy_hash(db, apply=apply)
    _print_report(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migration navixy_hash (dry-run par defaut).")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="Analyse seule (defaut).")
    g.add_argument("--apply", action="store_true", help="Ecrit les migrations (NE PAS en prod sans GO).")
    args = parser.parse_args()
    apply = bool(args.apply)  # dry-run par defaut si --apply absent
    if apply:
        print("!! MODE APPLY : des ecritures vont etre effectuees sur la base courante.", flush=True)
    asyncio.run(_main_async(apply))


if __name__ == "__main__":
    main()
