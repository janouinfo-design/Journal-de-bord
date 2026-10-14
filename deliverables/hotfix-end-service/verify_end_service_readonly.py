#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GO 3 — VÉRIFICATION POST-DÉPLOIEMENT READ-ONLY (hotfix « Fin de service »).

100% LECTURE. Aucune mutation, aucun END réel, aucune commande device.
À exécuter DANS le conteneur backend :
    docker exec -i journal_backend python3 /tmp/verify_end_service.py

Contrôles :
  IVAN_S564            : _resolve_end_service_decision(Ivan) -> applicable=false, end_allowed=true
                         + affectation ACTIVE Ivan/S564 présente + véhicule S564 résolu
  ORHAN_PRIVATE_BLOCK  : decide_end_service(applicable=true, state=PRIVATE)   -> END refusé
  ORHAN_PENDING_BLOCK  : decide_end_service(applicable=true, state=PENDING)   -> END refusé
  ORHAN_UNKNOWN_BLOCK  : decide_end_service(applicable=true, state=UNKNOWN)   -> END refusé
  ORHAN_BUSINESS_ALLOW : decide_end_service(applicable=true, state=BUSINESS)  -> END autorisé
  DB_WRITE             : 0 (ce script n'écrit jamais)

Config attendue dans l'environnement du conteneur : MONGO_URL, DB_NAME.
Identité Ivan paramétrable via env (par défaut email ivan@logitrak.ch) :
    IVAN_EMAIL (def "ivan@logitrak.ch")
    S564_PLATE (def "S564")  -> plaque attendue du véhicule actif d'Ivan
"""
import os
import sys
import asyncio

IVAN_EMAIL = os.environ.get("IVAN_EMAIL", "ivan@logitrak.ch")
S564_PLATE = os.environ.get("S564_PLATE", "S564")

# Garde READ-ONLY : on neutralise toute tentative d'écriture Mongo au cas où.
_WRITE_METHODS = (
    "insert_one", "insert_many", "update_one", "update_many",
    "delete_one", "delete_many", "bulk_write", "replace_one",
    "find_one_and_update", "find_one_and_delete", "find_one_and_replace",
    "drop", "create_index",
)


def _install_readonly_guard(db):
    """Remplace les méthodes d'écriture par un raise (défense en profondeur)."""
    seen = set()

    def guard(name):
        async def _blocked(*a, **k):
            raise RuntimeError(f"WRITE BLOQUÉ (READ-ONLY): {name}")
        return _blocked

    # On ne peut pas monkeypatcher toutes les collections dynamiques facilement,
    # mais on protège les collections connues utilisées par la logique.
    for coll_name in ("vehicle_assignments", "vehicle_assignment_events", "trips",
                       "vehicles", "drivers", "users", "settings", "audit_log",
                       "private_mode_state"):
        try:
            coll = getattr(db, coll_name)
        except Exception:
            continue
        for m in _WRITE_METHODS:
            if hasattr(coll, m):
                try:
                    setattr(coll, m, guard(f"{coll_name}.{m}"))
                    seen.add(f"{coll_name}.{m}")
                except Exception:
                    pass
    return seen


async def _run():
    # Import de la logique backend réelle.
    sys.path.insert(0, "/app/backend")
    from app.db import init_db
    from app.end_service_policy import (
        decide_end_service, R_END_OK_NOT_APPLICABLE, R_END_OK_BUSINESS,
        R_END_BLOCKED_NOT_BUSINESS,
    )
    from app.routes.identification import _resolve_end_service_decision
    from app.routes._helpers import resolve_driver_id_for_user

    db = init_db()
    _install_readonly_guard(db)

    results = {}

    # ---------- Non-régression Orhan/Audi via la règle pure (états simulés) ----------
    d_priv = decide_end_service(private_mode_applicable=True, state="PRIVATE")
    results["ORHAN_PRIVATE_BLOCK"] = (d_priv["end_service_allowed"] is False)

    d_pend = decide_end_service(private_mode_applicable=True, state="PENDING_CONFIRMATION")
    results["ORHAN_PENDING_BLOCK"] = (d_pend["end_service_allowed"] is False)

    d_unk = decide_end_service(private_mode_applicable=True, state="UNKNOWN")
    results["ORHAN_UNKNOWN_BLOCK"] = (d_unk["end_service_allowed"] is False)

    d_bus = decide_end_service(private_mode_applicable=True, state="BUSINESS")
    results["ORHAN_BUSINESS_ALLOW"] = (d_bus["end_service_allowed"] is True
                                       and d_bus["reason"] == R_END_OK_BUSINESS)

    # ---------- Cas réel Ivan / S564 (lecture base + vraie décision backend) ----------
    ivan_detail = {"email": IVAN_EMAIL}
    ok_ivan = False
    try:
        # Résolution utilisateur Ivan (par email).
        user = await db.users.find_one({"email": IVAN_EMAIL}, {"_id": 0})
        if not user:
            ivan_detail["error"] = f"Utilisateur {IVAN_EMAIL} introuvable"
        else:
            tenant_id = user.get("tenant_id") or "default"
            driver_id = await resolve_driver_id_for_user(db, user)
            ivan_detail["tenant_id"] = tenant_id
            ivan_detail["driver_id"] = driver_id
            if not driver_id:
                ivan_detail["error"] = "driver_id non résolu pour Ivan"
            else:
                # Affectation ACTIVE d'Ivan (doit exister et pointer S564).
                asg = await db.vehicle_assignments.find_one(
                    {"tenant_id": tenant_id, "driver_id": driver_id, "status": "ACTIVE"},
                    {"_id": 0},
                )
                ivan_detail["active_assignment"] = bool(asg)
                veh = None
                if asg:
                    veh = await db.vehicles.find_one(
                        {"id": asg.get("vehicle_id"), "tenant_id": tenant_id},
                        {"_id": 0, "plate": 1, "model": 1, "id": 1},
                    )
                    ivan_detail["vehicle_id"] = asg.get("vehicle_id")
                    ivan_detail["vehicle_plate"] = (veh or {}).get("plate")
                    ivan_detail["vehicle_model"] = (veh or {}).get("model")

                # DÉCISION RÉELLE backend (lecture seule).
                decision = await _resolve_end_service_decision(db, tenant_id, driver_id)
                ivan_detail["decision"] = decision
                plate_ok = (not asg) or ((veh or {}).get("plate") == S564_PLATE)
                ok_ivan = (
                    bool(asg)
                    and plate_ok
                    and decision.get("private_mode_applicable") is False
                    and decision.get("end_service_allowed") is True
                    and decision.get("reason") == R_END_OK_NOT_APPLICABLE
                )
    except Exception as e:  # jamais planter : on rapporte
        ivan_detail["exception"] = f"{type(e).__name__}: {e}"

    results["IVAN_S564"] = ok_ivan

    # ---------- Sortie ----------
    print("=" * 60)
    print("VÉRIFICATION READ-ONLY — hotfix Fin de service")
    print("=" * 60)
    for k in ("IVAN_S564", "ORHAN_PRIVATE_BLOCK", "ORHAN_PENDING_BLOCK",
              "ORHAN_UNKNOWN_BLOCK", "ORHAN_BUSINESS_ALLOW"):
        print(f"{k} = {'PASS' if results.get(k) else 'FAIL'}")
    print("DB_WRITE = 0")
    print("-" * 60)
    print("Détail Ivan/S564 :")
    for kk, vv in ivan_detail.items():
        print(f"  {kk} = {vv}")
    print("=" * 60)
    all_pass = all(results.get(k) for k in results)
    print("VERDICT GLOBAL =", "PASS" if all_pass else "FAIL")
    print("Aucune écriture effectuée (READ-ONLY).")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
