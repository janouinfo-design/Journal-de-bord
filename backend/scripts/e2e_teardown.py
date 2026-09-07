"""E2E TEST TEARDOWN (FORK ONLY) — restaure l'état initial d'après le snapshot.
Aucune prod. Remet les flags/données comme avant le test croisé."""
import asyncio
import json
import os

from app.db import init_db, get_db

TRACKER = 5000
VEHICLE_ID = "f5935504-7676-4d81-a885-7c4ff5578be5"
DRIVER_ID = "1580345e-6b8e-45a2-88e7-513a008b6b12"
SNAP = "/tmp/e2e_setup_snapshot.json"


async def main():
    init_db()
    db = get_db()
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}

    # 1) véhicule : restaurer modèle + pilot
    await db.vehicles.update_one({"id": VEHICLE_ID}, {"$set": {
        "model": snap.get("vehicle_model") or "Mercedes Sprinter"},
        "$unset": ({} if snap.get("vehicle_pilot") else {"private_mode_pilot": ""})})
    if not snap.get("vehicle_pilot"):
        await db.vehicles.update_one({"id": VEHICLE_ID}, {"$unset": {"private_mode_pilot": ""}})

    # 2) tenant : restaurer pilot + navixy_hash
    unset = {}
    if not snap.get("tenant_pilot"):
        unset["private_mode_pilot"] = ""
    if not snap.get("tenant_navixy_hash"):
        unset["navixy_hash"] = ""
    if unset:
        await db.tenants.update_one({"id": "default"}, {"$unset": unset})
    if snap.get("tenant_navixy_hash"):
        await db.tenants.update_one({"id": "default"}, {"$set": {"navixy_hash": snap["tenant_navixy_hash"]}})

    # 3) capability : supprimer si elle n'existait pas
    if not snap.get("capability_existed"):
        await db.vehicle_private_capabilities.delete_one({"tracker_id": TRACKER, "_e2e_test": True})
        await db.vehicle_private_capabilities.delete_one({"tracker_id": TRACKER})

    # 4) session : supprimer la session de test
    await db.driver_sessions.delete_many({"_e2e_test": True})

    # 5) private_mode_state : supprimer si n'existait pas
    if not snap.get("state_existed"):
        await db.private_mode_state.delete_one({"vehicle_id": VEHICLE_ID})

    # Vérif
    v = await db.vehicles.find_one({"id": VEHICLE_ID}, {"_id": 0, "model": 1, "private_mode_pilot": 1})
    t = await db.tenants.find_one({"id": "default"}, {"_id": 0, "private_mode_pilot": 1, "navixy_hash": 1})
    cap = await db.vehicle_private_capabilities.find_one({"tracker_id": TRACKER}, {"_id": 0})
    print("RESTORED vehicle:", v)
    print("RESTORED tenant:", t)
    print("capability present:", cap is not None)


if __name__ == "__main__":
    asyncio.run(main())
