#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC READ-ONLY — Perimetre vehicules du chauffeur & vehicule pilote.

Objet : verifier POURQUOI le chauffeur n'a pas de session active possible sur
le vehicule pilote (tracker 781479), afin de savoir s'il peut faire "Je conduis"
(claim) et voir les boutons Prive/Professionnel actifs.

STRICTEMENT READ-ONLY : aucune ecriture, aucun secret, aucune commande device.

EXECUTION (dans le conteneur backend) :
    docker exec -e DIAG_DRIVER_EMAIL="orhan@logitrak.ch" -i journal_backend python - < perimeter_diag.py
"""
from __future__ import annotations

import os
import sys
import asyncio


def _b(v) -> str:
    return "OUI" if v else "non"


async def main() -> int:
    try:
        from app.db import init_db, get_db, get_raw_db  # type: ignore
    except Exception as e:
        print(f"ERREUR import app.db : {type(e).__name__}: {e}")
        return 2

    from app import ble_engine
    from app.tenant_context import set_current_tenant, reset_current_tenant
    from app.routes._helpers import resolve_driver_id_for_user
    from app.vehicle_access import (get_vehicle_access,
                                    get_authorized_vehicles_for_driver)

    try:
        init_db()
        raw_db = get_raw_db()
        if raw_db is None:
            raise RuntimeError("DB non initialisee")
    except Exception as e:
        print(f"ERREUR connexion DB : {type(e).__name__}: {e}")
        return 2

    print("=" * 78)
    print("LOGITRAK — DIAGNOSTIC PERIMETRE VEHICULES (READ-ONLY)")
    print("=" * 78)

    target_email = os.environ.get("DIAG_DRIVER_EMAIL", "").strip().lower()
    pilot_tracker = os.environ.get("PRIVATE_MODE_PILOT_TRACKERS", "").strip()

    if not target_email:
        print("Definissez DIAG_DRIVER_EMAIL. Ex: export DIAG_DRIVER_EMAIL='orhan@logitrak.ch'")
        return 1

    user = await raw_db.users.find_one(
        {"email": {"$regex": f"^{target_email}$", "$options": "i"}},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "tenant_id": 1})
    if not user:
        print(f"Aucun utilisateur pour email={target_email!r}")
        return 0

    tenant_id = user.get("tenant_id") or "default"
    print(f"\nCHAUFFEUR : {user.get('email')}  role={user.get('role')}  tenant={tenant_id}")

    # --- Vehicule(s) pilote(s) declare(s) par tracker allowlist ---
    print(f"\n[VEHICULE PILOTE] PRIVATE_MODE_PILOT_TRACKERS={pilot_tracker!r}")
    _tok = set_current_tenant(tenant_id)
    try:
        db = get_db()

        # Vehicule associe au tracker pilote (peut etre plusieurs si CSV)
        tracker_ids = [t.strip() for t in pilot_tracker.split(",") if t.strip()]
        for tid in tracker_ids:
            # navixy_tracker_id peut etre stocke en int ou str -> on teste les deux
            v = await db.vehicles.find_one(
                {"$or": [{"navixy_tracker_id": tid},
                         {"navixy_tracker_id": int(tid)} if tid.isdigit() else {"navixy_tracker_id": tid}]},
                {"_id": 0, "id": 1, "plate": 1, "model": 1, "navixy_tracker_id": 1,
                 "private_mode_pilot": 1, "active": 1, "archived": 1, "deleted": 1})
            if not v:
                print(f"  tracker {tid} -> AUCUN vehicule trouve avec ce navixy_tracker_id.")
                continue
            print(f"  tracker {tid} -> vehicle_id={v.get('id')} plate={v.get('plate')!r} "
                  f"model={v.get('model')!r} pilot={v.get('private_mode_pilot')!r} "
                  f"active={v.get('active')!r} archived={v.get('archived')!r} deleted={v.get('deleted')!r}")

        # --- driver_id + perimetre ---
        driver_id = await resolve_driver_id_for_user(db, user)
        print(f"\n[PERIMETRE] driver_id={driver_id}")
        if not driver_id:
            print("  >>> Utilisateur non lie a un chauffeur (db.drivers).")
            return 0

        acc = await get_vehicle_access(db, driver_id)
        print(f"  vehicle_access_mode : {acc.get('mode') if acc else '<AUCUN>'}")
        print(f"  allowed_vehicle_ids : {acc.get('allowed_vehicle_ids') if acc else '<AUCUN>'}")
        print(f"  default_vehicle_id  : {acc.get('default_vehicle_id') if acc else '<AUCUN>'}")

        access, vehicles = await get_authorized_vehicles_for_driver(db, driver_id)
        print(f"\n  Vehicules AUTORISES (actifs) : {len(vehicles)}")
        pilot_in_scope = False
        for v in vehicles:
            print(f"    - {v.get('plate')!r}  id={v.get('id')}  model={v.get('model')!r}")
        # Verifie si un des vehicules autorises est le vehicule pilote
        for v in vehicles:
            vv = await db.vehicles.find_one({"id": v["id"]}, {"_id": 0, "navixy_tracker_id": 1})
            if vv and str(vv.get("navixy_tracker_id")) in tracker_ids:
                pilot_in_scope = True
        print(f"\n  Vehicule PILOTE dans le perimetre du chauffeur : {_b(pilot_in_scope)}")

        # --- Session courante ---
        sess = await ble_engine.get_current_session(db, driver_id)
        print(f"\n[SESSION] active : {_b(bool(sess))}")
        if sess:
            print(f"  vehicle_id={sess.get('vehicle_id')} status={sess.get('status')} "
                  f"plate={(sess.get('vehicle') or {}).get('plate')!r}")

        # --- Verdict ---
        print("\n=== VERDICT ===")
        if not pilot_in_scope:
            print("  >>> Le vehicule PILOTE n'est PAS dans le perimetre du chauffeur.")
            print("      -> Le claim 'Je conduis' renverra 403 pour ce vehicule.")
            print("      Fix data : ajouter le vehicule pilote au perimetre du chauffeur")
            print("      (vehicle_access_mode=ALL, ou l'ajouter a allowed_vehicle_ids).")
        elif not sess:
            print("  >>> Le vehicule pilote est autorise MAIS aucune session active.")
            print("      -> Dans l'app, le chauffeur doit appuyer 'Je conduis' (claim) sur")
            print("         le vehicule pilote. Ensuite les boutons Prive/Pro seront actifs.")
        else:
            print("  >>> Session active presente. Les boutons devraient etre disponibles.")
    finally:
        reset_current_tenant(_tok)

    print("\n" + "=" * 78)
    print("FIN — collez toute la sortie dans le chat.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
