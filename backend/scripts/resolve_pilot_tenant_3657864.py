"""READ-ONLY audit — résout le tenant réel du tracker pilote 3657864.

Aucune écriture, aucune migration, aucun appel device/Navixy.
Source de vérité canonique : tracker -> vehicle -> tenant (MongoDB backend).

Balaye TOUTES les bases accessibles sur l'instance Mongo courante (au cas où
les données pilote vivraient dans une autre base que la base applicative),
et essaie plusieurs conventions de champ pour le tracker id.
"""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

TRACKER_ID = "3657864"
TRACKER_VARIANTS = ("3657864", 3657864)
_SKIP_DBS = {"admin", "local", "config"}


async def _find_vehicle_in_db(db):
    """Cherche le véhicule associé au tracker dans une base donnée (READ-ONLY)."""
    cols = await db.list_collection_names()
    if "vehicles" not in cols:
        return None
    # 1) requête directe sur conventions connues
    for field in ("navixy_tracker_id", "tracker_id", "navixy_id"):
        for val in TRACKER_VARIANTS:
            v = await db.vehicles.find_one({field: val}, {"_id": 0})
            if v:
                return v
    # 2) scan tolérant (typage inconnu)
    async for v in db.vehicles.find({}, {"_id": 0}):
        for field in ("navixy_tracker_id", "tracker_id", "navixy_id"):
            if str(v.get(field)) == TRACKER_ID:
                return v
    return None


async def _resolve_in_db(client, db_name):
    db = client[db_name]
    vehicle = await _find_vehicle_in_db(db)
    if not vehicle:
        return None

    vehicle_id = vehicle.get("id")
    tenant_id = vehicle.get("tenant_id")

    tenant_name = None
    if tenant_id:
        t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1}) \
            if "tenants" in await db.list_collection_names() else None
        if t:
            tenant_name = t.get("name")

    field_validated = None
    if "vehicle_private_capabilities" in await db.list_collection_names():
        cap = await db.vehicle_private_capabilities.find_one(
            {"vehicle_id": vehicle_id}, {"_id": 0}) if vehicle_id else None
        if not cap:
            for val in TRACKER_VARIANTS:
                cap = await db.vehicle_private_capabilities.find_one(
                    {"tracker_id": val}, {"_id": 0})
                if cap:
                    break
        if cap:
            field_validated = cap.get("field_validated")

    return {
        "db_name": db_name,
        "vehicle_id": vehicle_id,
        "plate": vehicle.get("plate"),
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "field_validated": field_validated,
    }


async def main():
    # Le MONGO_URL est lu en local et n'est JAMAIS imprimé (aucune fuite de secret).
    mongo_url = os.environ["MONGO_URL"]
    client = AsyncIOMotorClient(mongo_url)

    print("=== READ-ONLY: RESOLVE_REAL_PILOT_TENANT — tracker", TRACKER_ID, "===")
    print("# READ-ONLY strict : aucune ecriture, aucune migration.")
    print("# N'imprime AUCUN secret (MONGO_URL / credentials / API keys / tokens / .env).")

    db_names = [d for d in await client.list_database_names() if d not in _SKIP_DBS]
    print(f"[scan] bases accessibles: {db_names}")

    hit = None
    for name in db_names:
        res = await _resolve_in_db(client, name)
        if res:
            hit = res
            break

    print()
    if hit and hit["tenant_id"]:
        resolution = "VERIFIED"
    elif hit and not hit["tenant_id"]:
        resolution = "AMBIGUOUS"
    else:
        resolution = "NOT_FOUND"

    print(f"TRACKER_ID      = {TRACKER_ID}")
    print(f"VEHICLE_ID      = {hit['vehicle_id'] if hit else None}")
    print(f"VEHICLE_PLATE   = {hit['plate'] if hit else None}")
    print(f"TENANT_ID       = {hit['tenant_id'] if hit else None}")
    print(f"TENANT_NAME     = {hit['tenant_name'] if hit else None}")
    print(f"FIELD_VALIDATED = {hit['field_validated'] if hit else None}")
    print(f"FOUND_IN_DB     = {hit['db_name'] if hit else None}")
    print("SOURCE_OF_TRUTH = vehicles.navixy_tracker_id -> vehicles.tenant_id "
          "(+ vehicle_private_capabilities.field_validated)")
    print(f"RESOLUTION      = {resolution}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
