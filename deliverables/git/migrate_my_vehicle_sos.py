#!/usr/bin/env python3
"""
Lot A-bis (PROD) — Migration IDEMPOTENTE de my-vehicle + sos vers resolve_active_vehicle.

Contexte : sur le VPS PROD (/opt/apps/journal-logitrak), les endpoints km-summary et
odometer utilisent DÉJÀ resolve_active_vehicle. Il reste 2 endpoints qui utilisent encore
get_current_session SEUL :
  - driver_my_vehicle  (~l.770)
  - driver_sos         (~l.809)

Ce script applique, de façon idempotente et ciblée (par contexte de fonction), le même
pattern que les autres endpoints : résolution via affectation persistante en priorité,
fallback session BLE. Insensible aux numéros de ligne.

USAGE (sur le VPS) :
  cd /opt/apps/journal-logitrak
  cp backend/app/routes/identification.py backend/app/routes/identification.py.bak
  python3 migrate_my_vehicle_sos.py            # dry-run (montre ce qui serait fait)
  python3 migrate_my_vehicle_sos.py --apply    # applique
  # rollback : mv backend/app/routes/identification.py.bak backend/app/routes/identification.py

Ne touche PAS : km-summary, odometer, private_mode_engine, AVL16, trajets.
"""
import sys
import re

PATH = "backend/app/routes/identification.py"

# --- Bloc SOS ---------------------------------------------------------------
SOS_OLD = (
    '    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0, "name": 1}) or {}\n'
    '    sess = await ble_engine.get_current_session(db, driver_id)\n'
    '    vehicle_id = sess.get("vehicle_id") if sess else None\n'
)
SOS_NEW = (
    '    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0, "name": 1}) or {}\n'
    '    # Véhicule actif = affectation persistante (fallback session BLE).\n'
    '    from app import vehicle_assignment as va\n'
    '    vehicle_id = await va.resolve_active_vehicle(db, driver_id, tenant_id)\n'
    '    if not vehicle_id:\n'
    '        sess = await ble_engine.get_current_session(db, driver_id)\n'
    '        vehicle_id = sess.get("vehicle_id") if sess else None\n'
)

# --- Bloc MY-VEHICLE --------------------------------------------------------
# On insère, juste après "current = bool(sess)", un court-circuit affectation si pas de session.
MYV_OLD = (
    '    sess = await ble_engine.get_current_session(db, driver_id)\n'
    '    current = bool(sess)\n'
    '    if not sess:\n'
    '        last = await db.driver_sessions.find_one(\n'
)
MYV_NEW = (
    '    sess = await ble_engine.get_current_session(db, driver_id)\n'
    '    current = bool(sess)\n'
    '    # Lot 1/2 : si pas de session BLE, utiliser l\'affectation PERSISTANTE.\n'
    '    if not sess:\n'
    '        from app import vehicle_assignment as va\n'
    '        _asg_vid = await va.resolve_active_vehicle(db, driver_id, tenant_id)\n'
    '        if _asg_vid:\n'
    '            _veh = await db.vehicles.find_one({"id": _asg_vid, "tenant_id": tenant_id}, {"_id": 0}) or {}\n'
    '            return {"vehicle": {"id": _veh.get("id"), "plate": _veh.get("plate"),\n'
    '                                "model": _veh.get("model")}, "current": True, "session": None}\n'
    '    if not sess:\n'
    '        last = await db.driver_sessions.find_one(\n'
)

# my-vehicle a besoin de tenant_id : on s'assure qu'il est défini dans la fonction.
MYV_TENANT_OLD = (
    '    db = get_db()\n'
    '    driver_id = await resolve_driver_id_for_user(db, user)\n'
    '    if not driver_id:\n'
    '        raise HTTPException(400, "Utilisateur non lié à un chauffeur")\n'
    '    sess = await ble_engine.get_current_session(db, driver_id)\n'
    '    current = bool(sess)\n'
)
MYV_TENANT_NEW = (
    '    db = get_db()\n'
    '    tenant_id = user.get("tenant_id") or "default"\n'
    '    driver_id = await resolve_driver_id_for_user(db, user)\n'
    '    if not driver_id:\n'
    '        raise HTTPException(400, "Utilisateur non lié à un chauffeur")\n'
    '    sess = await ble_engine.get_current_session(db, driver_id)\n'
    '    current = bool(sess)\n'
)


def main():
    apply = "--apply" in sys.argv
    with open(PATH, encoding="utf-8") as f:
        src = f.read()
    original = src
    changes = []

    # Idempotence : ne rien faire si déjà migré.
    already_sos = "Véhicule actif = affectation persistante (fallback session BLE)." in src
    already_myv = "si pas de session BLE, utiliser l'affectation PERSISTANTE" in src

    # 1) tenant_id dans my-vehicle (si absent)
    if MYV_TENANT_OLD in src and 'tenant_id = user.get("tenant_id")' not in src.split('def driver_my_vehicle')[1].split('def ')[0]:
        src = src.replace(MYV_TENANT_OLD, MYV_TENANT_NEW, 1)
        changes.append("my-vehicle: ajout tenant_id")

    # 2) my-vehicle court-circuit affectation
    if not already_myv and MYV_OLD in src:
        src = src.replace(MYV_OLD, MYV_NEW, 1)
        changes.append("my-vehicle: resolve_active_vehicle (fallback)")
    elif already_myv:
        changes.append("my-vehicle: DÉJÀ migré (skip)")

    # 3) sos
    if not already_sos and SOS_OLD in src:
        src = src.replace(SOS_OLD, SOS_NEW, 1)
        changes.append("sos: resolve_active_vehicle (fallback)")
    elif already_sos:
        changes.append("sos: DÉJÀ migré (skip)")

    print("=== Changements détectés ===")
    for c in changes:
        print("  -", c)
    if src == original:
        print("Aucune modification nécessaire (idempotent).")
        return

    if apply:
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"\n✅ APPLIQUÉ sur {PATH}")
    else:
        print("\n(dry-run) Relancer avec --apply pour écrire les changements.")


if __name__ == "__main__":
    main()
