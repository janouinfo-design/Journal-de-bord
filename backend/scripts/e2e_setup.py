"""E2E TEST SETUP (FORK ONLY) — active un véhicule pilote pour tester la bascule.
Snapshot l'état initial dans /tmp pour restauration. Aucune prod, aucun device réel."""
import asyncio
import json
import os
from datetime import datetime, timezone

from app.db import init_db, get_db

TRACKER = 5000
VEHICLE_ID = "f5935504-7676-4d81-a885-7c4ff5578be5"
DRIVER_ID = "1580345e-6b8e-45a2-88e7-513a008b6b12"
SNAP = "/tmp/e2e_setup_snapshot.json"


async def main():
    init_db()
    db = get_db()
    snap = {}

    v = await db.vehicles.find_one({"id": VEHICLE_ID}, {"_id": 0})
    snap["vehicle_model"] = v.get("model")
    snap["vehicle_pilot"] = v.get("private_mode_pilot")
    t = await db.tenants.find_one({"id": "default"}, {"_id": 0})
    snap["tenant_pilot"] = (t or {}).get("private_mode_pilot")
    snap["tenant_navixy_hash"] = (t or {}).get("navixy_hash")
    cap = await db.vehicle_private_capabilities.find_one({"tracker_id": TRACKER}, {"_id": 0})
    snap["capability_existed"] = cap is not None
    sess = await db.driver_sessions.find_one(
        {"driver_id": DRIVER_ID, "status": {"$in": ["open", "manual", "confirmed"]}}, {"_id": 0})
    snap["session_existed"] = sess is not None
    st = await db.private_mode_state.find_one({"vehicle_id": VEHICLE_ID}, {"_id": 0})
    snap["state_existed"] = st is not None
    json.dump(snap, open(SNAP, "w"), default=str)

    # 1) véhicule pilote + modèle supporté (test)
    await db.vehicles.update_one({"id": VEHICLE_ID}, {"$set": {
        "model": "telfmb003_fmc003", "private_mode_pilot": True}})
    # 2) tenant pilote + credential Navixy factice (test) pour passer la gate intégration
    await db.tenants.update_one({"id": "default"}, {"$set": {
        "private_mode_pilot": True, "navixy_hash": "TEST_E2E_TENANT_CRED"}}, upsert=True)
    # 3) capability field_validated (test) pour tracker 5000
    await db.vehicle_private_capabilities.update_one({"tracker_id": TRACKER}, {"$set": {
        "vehicle_id": VEHICLE_ID, "tracker_id": TRACKER, "device_model": "FMC003",
        "private_distance_source": "TELTONIKA_TOTAL_ODOMETER", "raw_avl_id": 16,
        "navixy_input": "avl_io_16", "scale_status": "SCALE_VERIFIED",
        "runtime_verified": True, "cumulative_verified": True,
        "private_increment_verified": True, "field_validated": True,
        "tenant_id": "default", "updated_at": datetime.now(timezone.utc).isoformat(),
        "_e2e_test": True}}, upsert=True)
    # 4) session chauffeur ouverte sur GE 123456
    await db.driver_sessions.update_one(
        {"driver_id": DRIVER_ID, "vehicle_id": VEHICLE_ID},
        {"$set": {"tenant_id": "default", "driver_id": DRIVER_ID, "vehicle_id": VEHICLE_ID,
                  "vehicle_plate": "GE 123456", "status": "confirmed", "active_driver": True,
                  "last_seen": datetime.now(timezone.utc).isoformat(),
                  "started_at": datetime.now(timezone.utc).isoformat(), "_e2e_test": True}},
        upsert=True)
    # 5) état initial BUSINESS
    await db.private_mode_state.update_one({"vehicle_id": VEHICLE_ID},
        {"$set": {"vehicle_id": VEHICLE_ID, "state": "BUSINESS",
                  "updated_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)

    print("E2E setup done. Snapshot:", json.dumps(snap, default=str))


if __name__ == "__main__":
    asyncio.run(main())
