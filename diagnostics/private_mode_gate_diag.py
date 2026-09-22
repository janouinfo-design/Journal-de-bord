#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC *READ-ONLY* — Pourquoi les boutons Privé/Professionnel
sont grisés dans l'app mobile ?
============================================================================

CE QUE FAIT CE SCRIPT
---------------------
Il REPRODUIT EXACTEMENT la décision du backend pour l'endpoint
`GET /api/livre/driver/private-mode`, chauffeur par chauffeur, et affiche
NIVEAU PAR NIVEAU lequel des 7 verrous de la gate fail-closed bloque
`allowed`. Rappel côté mobile :

    canToggle = hasVehicle && status.allowed && !busy

=> Si `allowed=false`, les DEUX boutons (Privé et Professionnel) sont grisés.

Le script décompose la décision en :
  1. PRIVATE_MODE_ENABLED (feature globale)              -> feature_enabled()
  2. kill switch backend (db.feature_flags/private_mode) -> kill_switch_active()
  3. Résolution driver_id (db.drivers)                   -> resolve_driver_id_for_user()
  4. Session active + vehicle_id (ble_engine)            -> get_current_session()
  5. Tenant autorisé (tenant.private_mode_pilot / env)   -> tenant_allowed()
  6. Véhicule pilote (vehicle.private_mode_pilot / env)  -> vehicle_is_pilot()
  7. Tracker présent (vehicle.navixy_tracker_id)
  8. Hardware field_validated (capability)               -> vehicle_private_mode_allowed()
  9. Intégration Navixy présente pour le tenant          -> get_integration_credential()

Puis affiche la décision finale `allowed / reason` ET `can_switch`
(= allowed AND PRIVATE_MODE_DEVICE_WRITE) pour info.

STRICTEMENT READ-ONLY
---------------------
  - Aucune écriture DB, aucune commande device, aucun appel Navixy réseau.
  - Les secrets (hash/clé) ne sont JAMAIS affichés (seulement présent/absent).
  - N'écrit rien sur disque : sortie sur stdout uniquement.

EXÉCUTION SUR LE VPS (dans le conteneur backend qui possède MONGO_URL + env) :

    docker exec -i journal_backend python - < private_mode_gate_diag.py

  ou, si le fichier est copié dans le conteneur :

    docker exec -it journal_backend python /chemin/private_mode_gate_diag.py

CIBLAGE DU CHAUFFEUR
--------------------
Par défaut le script scanne TOUS les chauffeurs (role=driver) du tenant.
Pour cibler un seul chauffeur, exportez avant l'exécution :

    export DIAG_DRIVER_EMAIL="orhan@logitrak.ch"

Collez l'intégralité de la sortie dans le chat pour analyse.
"""
from __future__ import annotations

import os
import sys
import asyncio


def _mask(v) -> str:
    if v is None:
        return "<absent>"
    s = str(v)
    if not s:
        return "<vide>"
    return f"<présent, {len(s)} car.>"


def _b(v) -> str:
    return "OUI" if v else "non"


async def main() -> int:
    # Imports internes au conteneur backend (mêmes modules que la route réelle).
    try:
        from app.db import init_db, get_db, get_raw_db  # type: ignore
    except Exception as e:  # pragma: no cover
        print(f"ERREUR import app.db : {type(e).__name__}: {e}")
        print("Exécutez ce script DANS le conteneur backend (journal_backend).")
        return 2

    from app import private_mode_gate as gate
    from app import private_mode_engine as pm
    from app import ble_engine
    from app.odometer_capability import (resolve_model,
                                         vehicle_private_mode_allowed)
    from app.integrations import get_integration_credential
    from app.tenant_context import set_current_tenant, reset_current_tenant

    # --- Connexion Mongo (identique au démarrage backend) ---
    try:
        init_db()
        raw_db = get_raw_db()
        if raw_db is None:
            raise RuntimeError("DB non initialisée (MONGO_URL/DB_NAME manquants ?)")
    except Exception as e:
        print(f"ERREUR connexion DB : {type(e).__name__}: {e}")
        return 2

    print("=" * 78)
    print("LOGITRAK — DIAGNOSTIC GATE MODE PRIVÉ (READ-ONLY)")
    print("=" * 78)

    # ---- Niveaux GLOBAUX (indépendants du chauffeur) ----
    feat = gate.feature_enabled()
    kill = await gate.kill_switch_active(raw_db)
    dev_write = pm.device_write_enabled()
    env_tenants = os.environ.get("PRIVATE_MODE_PILOT_TENANTS", "")
    env_trackers = os.environ.get("PRIVATE_MODE_PILOT_TRACKERS", "")

    print("\n[ENV / FLAGS GLOBAUX]")
    print(f"  PRIVATE_MODE_ENABLED (feature)        : {_b(feat)}  (env={os.environ.get('PRIVATE_MODE_ENABLED')!r})")
    print(f"  kill_switch actif (DB feature_flags)  : {_b(kill)}")
    print(f"  PRIVATE_MODE_DEVICE_WRITE             : {_b(dev_write)}  (env={os.environ.get('PRIVATE_MODE_DEVICE_WRITE')!r})")
    print(f"  PRIVATE_MODE_PILOT_TENANTS (env)      : {env_tenants!r}")
    print(f"  PRIVATE_MODE_PILOT_TRACKERS (env)     : {env_trackers!r}")

    if not feat:
        print("\n>>> BLOCAGE GLOBAL : PRIVATE_MODE_ENABLED est FAUX -> allowed=false pour TOUS.")
    if kill:
        print("\n>>> BLOCAGE GLOBAL : kill switch ACTIF -> allowed=false pour TOUS.")

    # ---- Sélection des chauffeurs à auditer ----
    target_email = os.environ.get("DIAG_DRIVER_EMAIL", "").strip().lower()
    q = {"role": "driver"} if not target_email else {}
    users = await raw_db.users.find(q, {"_id": 0, "id": 1, "email": 1,
                                        "role": 1, "tenant_id": 1}).to_list(2000)
    if target_email:
        users = [u for u in users if str(u.get("email", "")).lower() == target_email]

    if not users:
        print(f"\nAucun utilisateur trouvé (filtre email={target_email!r}).")
        return 0

    for u in users:
        email = u.get("email")
        role = u.get("role")
        tenant_id = u.get("tenant_id") or "default"
        print("\n" + "-" * 78)
        print(f"CHAUFFEUR : {email}  (role={role}, tenant_id={tenant_id})")
        print("-" * 78)

        # Contexte tenant (comme la route) -> db scopé multi-tenant identique.
        _tok = set_current_tenant(tenant_id)
        try:
            db = get_db()

            # 3. Résolution driver_id (même helper que la route)
            from app.routes._helpers import resolve_driver_id_for_user
            driver_id = await resolve_driver_id_for_user(db, u)
            print(f"  [3] driver_id résolu                 : {driver_id or '<AUCUN>'}")
            if not driver_id:
                print("      >>> BLOCAGE : utilisateur NON lié à un chauffeur (db.drivers).")
                print("          Fix data : créer/lier db.drivers avec email ou user_id.")
                continue

            # 4. Session active + vehicle_id
            sess = await ble_engine.get_current_session(db, driver_id)
            vehicle_id = (sess or {}).get("vehicle_id")
            print(f"  [4] session active                   : {'oui' if sess else 'NON'}")
            print(f"      vehicle_id de session            : {vehicle_id or '<AUCUN>'}")
            if not sess or not vehicle_id:
                print("      >>> BLOCAGE : pas de véhicule actif en session -> reason=NO_VEHICLE.")
                print("          Le chauffeur doit s'identifier sur un véhicule (BLE/manuel).")
                continue

            vehicle = await db.vehicles.find_one(
                {"id": vehicle_id, "tenant_id": tenant_id}, {"_id": 0}) or {}
            tracker_id = vehicle.get("navixy_tracker_id")
            model_raw = vehicle.get("model")
            model = resolve_model(model_raw)
            print(f"      véhicule                         : plate={vehicle.get('plate')!r} model={model_raw!r} -> {model!r}")
            print(f"      navixy_tracker_id                : {tracker_id!r}")
            print(f"      vehicle.private_mode_pilot       : {vehicle.get('private_mode_pilot')!r}")

            # 5. Tenant
            tenant_doc = await raw_db.tenants.find_one({"id": tenant_id}, {"_id": 0})
            t_ok = gate.tenant_allowed(tenant_doc, tenant_id)
            print(f"  [5] tenant.private_mode_pilot        : {(tenant_doc or {}).get('private_mode_pilot')!r}")
            print(f"      tenant autorisé                  : {_b(t_ok)}")

            # 6. Véhicule pilote
            v_ok = gate.vehicle_is_pilot(vehicle)
            print(f"  [6] véhicule pilote                  : {_b(v_ok)}")

            # 8. Capability field_validated
            vc = await pm.resolve_vehicle_capability(db, tracker_id, model)
            fv = bool(vc and getattr(vc, "field_validated", False))
            hw_ok = vehicle_private_mode_allowed(model, vc)
            print(f"  [8] capability présente              : {'oui' if vc else 'NON'}")
            print(f"      field_validated                  : {_b(fv)}")
            print(f"      vehicle_private_mode_allowed      : {_b(hw_ok)}")

            # 9. Intégration Navixy (présence seulement, pas de secret)
            cred = get_integration_credential(tenant_id, "NAVIXY")
            cred_present = bool(cred and cred.get("credential"))
            print(f"  [9] intégration Navixy (tenant)      : {_mask(cred.get('credential') if cred else None)}")

            # ---- DÉCISION FINALE (fonction réelle de la route) ----
            decision = await gate.can_use_private_mode(
                db, tenant_id=tenant_id, tenant_doc=tenant_doc,
                vehicle_doc=vehicle, capability=vc)
            allowed = decision["allowed"]
            reason = decision["reason"]
            can_switch = bool(allowed and dev_write)
            print("\n  === DÉCISION BACKEND ===")
            print(f"    allowed     : {_b(allowed)}")
            print(f"    reason      : {reason!r}")
            print(f"    level       : {decision.get('level')!r}")
            print(f"    can_switch  : {_b(can_switch)}  (allowed AND device_write)")
            if allowed:
                print("    >>> Les boutons DEVRAIENT être actifs (canToggle=true) côté app.")
                if not can_switch:
                    print("        NB : can_switch=false (device_write=0) mais N'AFFECTE PAS le grisé "
                          "des boutons (l'app grise sur `allowed`).")
            else:
                print(f"    >>> Boutons GRISÉS car allowed=false (blocage niveau: {decision.get('level')}).")
        finally:
            reset_current_tenant(_tok)

    print("\n" + "=" * 78)
    print("FIN DU DIAGNOSTIC — collez toute cette sortie dans le chat.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
