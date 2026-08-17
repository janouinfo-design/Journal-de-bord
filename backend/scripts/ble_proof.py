"""Preuve terrain BLE chauffeur : tag porté → traceur Teltonika → Navixy → backend.

Usage (sur le serveur, avec le backend/.env chargé) :
    cd /app/backend && python scripts/ble_proof.py --minutes 60 [--tenant default]

Le script :
1. liste les chauffeurs du tenant avec un tag BLE configuré (drivers.ble_id) ;
2. liste les véhicules mappés à un traceur Navixy ;
3. interroge POST /beacon/data/last_values puis /beacon/data/read ;
4. affiche CHAQUE enregistrement brut reçu (hardware_id, tracker, rssi, heure)
   avec son statut de correspondance : CHAUFFEUR RECONNU / beacon inconnu /
   traceur non mappé — AUCUNE donnée n'est inventée ;
5. conclut par un verdict clair.

La clé Navixy n'est jamais affichée.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from app.ble_engine import normalize_identifier  # noqa: E402

TS = "%Y-%m-%d %H:%M:%S"


async def main(tenant_id: str, minutes: int):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant or not tenant.get("navixy_hash"):
        print(f"✗ Tenant '{tenant_id}' introuvable ou sans clé Navixy — abandon.")
        return
    api = (tenant.get("navixy_api_url") or "https://api.navixy.com/v2").rstrip("/")
    print(f"Tenant : {tenant.get('name', tenant_id)} | API : {api} | clé : ***masquée***\n")

    drivers = await db.drivers.find(
        {"tenant_id": tenant_id, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "ble_id": 1, "ble_id_norm": 1}).to_list(2000)
    by_tag = {}
    print("— Chauffeurs avec tag BLE configuré :")
    for d in drivers:
        norm = d.get("ble_id_norm") or normalize_identifier(d.get("ble_id"))
        if norm:
            by_tag[norm] = d
            print(f"   • {d['name']}  tag={d.get('ble_id')}  (canon {norm})")
    if not by_tag:
        print("   (aucun — configurez drivers.ble_id via Administration → Chauffeurs)")

    vehicles = await db.vehicles.find(
        {"tenant_id": tenant_id, "navixy_tracker_id": {"$ne": None}},
        {"_id": 0, "id": 1, "plate": 1, "model": 1, "navixy_tracker_id": 1}).to_list(2000)
    by_tracker = {v["navixy_tracker_id"]: v for v in vehicles if v.get("navixy_tracker_id")}
    print(f"\n— Véhicules mappés à un traceur Navixy : {len(by_tracker)}")
    if not by_tracker:
        print("   ✗ Aucun véhicule avec navixy_tracker_id — lancez une synchro Navixy d'abord.")
        return

    now = datetime.now(timezone.utc)
    frm = now - timedelta(minutes=minutes)
    trackers = list(by_tracker.keys())

    async with httpx.AsyncClient(timeout=30.0) as http:
        print("\n=== 1) beacon/data/last_values ===")
        r = await http.post(f"{api}/beacon/data/last_values",
                            json={"hash": tenant["navixy_hash"], "trackers": trackers})
        _show(r, by_tag, by_tracker)

        print(f"\n=== 2) beacon/data/read (fenêtre {minutes} min) ===")
        r = await http.post(f"{api}/beacon/data/read", json={
            "hash": tenant["navixy_hash"], "trackers": trackers,
            "from": frm.strftime(TS), "to": now.strftime(TS)})
        matched = _show(r, by_tag, by_tracker)

    print("\n=== VERDICT ===")
    if matched:
        print("✓ CHAÎNE PROUVÉE : au moins un tag chauffeur configuré a été détecté par un")
        print("  traceur mappé et remonté par Navixy. L'ingestion backend peut être activée")
        print("  (POST /api/livre/ble/beacons/poll-now en tant qu'admin).")
    else:
        print("✗ Chaîne NON prouvée sur cette fenêtre : aucun enregistrement Navixy ne")
        print("  correspond à un tag chauffeur configuré. Vérifiez : 1) le tag émet (pile),")
        print("  2) le traceur Teltonika a « Beacon List/Detection » activé (ex. FMC130 :")
        print("  Bluetooth 4.0 → Beacon Detection = All / Configured), 3) la fenêtre de temps,")
        print("  4) drivers.ble_id correspond bien au MAC/ID du tag.")

    client.close()


def _show(r: httpx.Response, by_tag: dict, by_tracker: dict) -> int:
    if r.status_code != 200:
        print(f"   ✗ HTTP {r.status_code} : {r.text[:300]}")
        return 0
    data = r.json()
    if not data.get("success"):
        print(f"   ✗ Réponse Navixy : {data.get('status')}")
        return 0
    records = data.get("list") or []
    print(f"   {len(records)} enregistrement(s) reçu(s)")
    matched = 0
    for rec in records[:200]:
        norm = normalize_identifier(rec.get("hardware_id"))
        drv = by_tag.get(norm)
        veh = by_tracker.get(rec.get("tracker_id"))
        status = []
        if drv:
            status.append(f"CHAUFFEUR RECONNU → {drv['name']}")
            matched += 1
        else:
            status.append("beacon inconnu (aucun chauffeur avec ce tag)")
        if veh:
            status.append(f"véhicule {veh.get('plate')}")
        else:
            status.append(f"traceur {rec.get('tracker_id')} NON mappé")
        print(f"   • hw={rec.get('hardware_id')} (canon {norm}) rssi={rec.get('rssi')} "
              f"t={rec.get('get_time')} | {' | '.join(status)}")
    if len(records) > 200:
        print(f"   … {len(records) - 200} lignes supplémentaires tronquées")
    return matched


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="default")
    p.add_argument("--minutes", type=int, default=60)
    a = p.parse_args()
    asyncio.run(main(a.tenant, a.minutes))
