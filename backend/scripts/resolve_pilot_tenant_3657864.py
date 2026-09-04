"""READ-ONLY audit — résout le tenant réel du tracker pilote 3657864.

Aucune écriture, aucune migration, aucun appel device/Navixy.
Source de vérité : mapping tracker -> véhicule -> tenant dans MongoDB.
"""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

TRACKER_ID = "3657864"
TRACKER_ID_INT = 3657864


async def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print("=== READ-ONLY: résolution tenant du tracker", TRACKER_ID, "===")

    # 1) Véhicule associé au tracker (essaye string et int)
    vehicle = None
    for q in ({"navixy_tracker_id": TRACKER_ID}, {"navixy_tracker_id": TRACKER_ID_INT}):
        vehicle = await db.vehicles.find_one(q, {"_id": 0})
        if vehicle:
            break

    if not vehicle:
        # scan tolérant (au cas où le champ serait typé différemment)
        async for v in db.vehicles.find({}, {"_id": 0}):
            if str(v.get("navixy_tracker_id")) == TRACKER_ID:
                vehicle = v
                break

    vehicle_id = vehicle.get("id") if vehicle else None
    tenant_id = vehicle.get("tenant_id") if vehicle else None
    field_validated = None

    # capability doc (field_validated)
    cap = None
    if vehicle_id:
        cap = await db.vehicle_private_capabilities.find_one(
            {"vehicle_id": vehicle_id}, {"_id": 0})
    if not cap:
        for q in ({"tracker_id": TRACKER_ID}, {"tracker_id": TRACKER_ID_INT}):
            cap = await db.vehicle_private_capabilities.find_one(q, {"_id": 0})
            if cap:
                break
    if cap:
        field_validated = cap.get("field_validated")

    # tenant doc
    tenant_name = None
    if tenant_id:
        t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1})
        if t:
            tenant_name = t.get("name")

    # Résolution
    if vehicle and tenant_id:
        resolution = "VERIFIED"
    elif vehicle and not tenant_id:
        resolution = "AMBIGUOUS"
    else:
        resolution = "NOT_FOUND"

    print()
    print(f"TRACKER_ID = {TRACKER_ID}")
    print(f"VEHICLE_ID = {vehicle_id}")
    print(f"VEHICLE_PLATE = {vehicle.get('plate') if vehicle else None}")
    print(f"TENANT_ID = {tenant_id}")
    print(f"TENANT_NAME = {tenant_name}")
    print(f"FIELD_VALIDATED = {field_validated}")
    print(f"SOURCE_OF_TRUTH = vehicles.navixy_tracker_id -> vehicles.tenant_id (+ vehicle_private_capabilities)")
    print(f"RESOLUTION = {resolution}")

    # Contexte utile
    total_vehicles = await db.vehicles.count_documents({})
    distinct_tenants = await db.vehicles.distinct("tenant_id")
    print()
    print(f"[ctx] total_vehicles={total_vehicles} distinct_vehicle_tenants={distinct_tenants}")
    tenants_count = await db.tenants.count_documents({}) if "tenants" in await db.list_collection_names() else 0
    print(f"[ctx] tenants_collection_count={tenants_count}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
