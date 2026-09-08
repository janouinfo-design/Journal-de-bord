"""Autorisation véhicules par chauffeur — SOURCE D'AUTORITÉ backend.

Modèle stocké sur le document `drivers` :
  vehicle_access_mode : "ALL" | "SELECTED" | "SINGLE"  (absent = "ALL" — comportement historique)
  allowed_vehicle_ids : liste d'ids véhicules (SELECTED/SINGLE)
  default_vehicle_id  : véhicule proposé par défaut (doit appartenir au périmètre autorisé)

Règles :
- ALL = tous les véhicules actifs DU TENANT du chauffeur (jamais un autre tenant —
  garanti par le proxy Mongo tenant-scoped).
- Un default hors périmètre est invalidé à la lecture (jamais de fallback arbitraire).
- Un véhicule inactif/supprimé/archivé ne donne jamais un droit actif.
"""
from __future__ import annotations

VEHICLE_ACCESS_MODES = ("ALL", "SELECTED", "SINGLE")

_VEHICLE_FIELDS = {"_id": 0, "id": 1, "plate": 1, "label": 1, "model": 1}


def active_vehicle_query() -> dict:
    return {"active": {"$ne": False}, "deleted": {"$ne": True}, "archived": {"$ne": True}}


async def get_vehicle_access(db, driver_id: str) -> dict | None:
    drv = await db.drivers.find_one(
        {"id": driver_id},
        {"_id": 0, "id": 1, "vehicle_access_mode": 1, "allowed_vehicle_ids": 1,
         "default_vehicle_id": 1})
    if not drv:
        return None
    mode = drv.get("vehicle_access_mode") or "ALL"
    if mode not in VEHICLE_ACCESS_MODES:
        mode = "ALL"
    return {"mode": mode,
            "allowed_vehicle_ids": drv.get("allowed_vehicle_ids") or [],
            "default_vehicle_id": drv.get("default_vehicle_id")}


async def get_authorized_vehicles_for_driver(db, driver_id: str):
    """Retourne (access, [véhicules actifs autorisés]) — db DOIT être tenant-scoped."""
    acc = await get_vehicle_access(db, driver_id)
    if acc is None:
        return None, []
    q = active_vehicle_query()
    if acc["mode"] == "ALL":
        vehicles = await db.vehicles.find(q, _VEHICLE_FIELDS).sort("plate", 1).to_list(1000)
    elif acc["allowed_vehicle_ids"]:
        vehicles = await db.vehicles.find(
            {**q, "id": {"$in": acc["allowed_vehicle_ids"]}},
            _VEHICLE_FIELDS).sort("plate", 1).to_list(1000)
    else:
        vehicles = []
    vids = {v["id"] for v in vehicles}
    default = acc["default_vehicle_id"] if acc["default_vehicle_id"] in vids else None
    return {**acc, "default_vehicle_id": default}, vehicles


async def get_authorized_vehicle_ids_for_driver(db, driver_id: str) -> list[str]:
    _, vehicles = await get_authorized_vehicles_for_driver(db, driver_id)
    return [v["id"] for v in vehicles]


async def assert_vehicle_authorized(db, driver_id: str, vehicle_id: str) -> None:
    ids = await get_authorized_vehicle_ids_for_driver(db, driver_id)
    if vehicle_id not in ids:
        raise PermissionError("Véhicule non autorisé pour ce chauffeur")
