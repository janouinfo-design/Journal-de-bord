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

    from app.driver_beacons import _navixy_tracker_ids, _read_beacons

    async with httpx.AsyncClient(timeout=30.0) as http:
        valid = await _navixy_tracker_ids(http, api, tenant["navixy_hash"])
        usable = [t for t in trackers if t in valid]
        stale = [t for t in trackers if t not in valid]
        print(f"\n— Traceurs valides côté Navixy : {len(usable)}/{len(trackers)}")
        if stale:
            print(f"   ⚠ {len(stale)} traceur(s) mappé(s) localement mais INEXISTANT(S) côté Navixy")
            print(f"     (ignorés — relancez une synchro Navixy pour purger) : {stale[:10]}")
        if not usable:
            print("   ✗ Aucun traceur valide — impossible d'interroger l'API Beacon.")
            client.close()
            return

        print(f"\n=== beacon/data/read (fenêtre {minutes} min, repli par traceur si besoin) ===")
        records, err = await _read_beacons(
            http, api, tenant["navixy_hash"], usable,
            frm.strftime(TS), now.strftime(TS))
        if err:
            print(f"   ✗ Erreur Navixy : {err}")
            matches = []
        else:
            matches = _show_records(records, by_tag, by_tracker)

    print("\n=== VERDICT ===")
    if matches:
        print("✓ CHAUFFEUR RECONNU — chaîne complète prouvée :")
        print("  tag chauffeur → traceur Teltonika → Navixy → backend Logitrak")
        for m_ in matches[:20]:
            print(f"  • CHAUFFEUR RECONNU : {m_['driver']}")
            print(f"      tag BLE   : {m_['tag']} (canon {m_['canon']})")
            print(f"      véhicule  : {m_['vehicle']}  |  tracker : {m_['tracker']}")
            print(f"      détection : {m_['ts']} UTC  |  rssi {m_['rssi']}  |  source : BLE")
        print("\n  → Le poller (toutes les 2 min) ingérera ces détections et ouvrira/mettra")
        print("    à jour la session chauffeur (source BLE). Contrôlez ensuite la page")
        print("    Identification ou GET /api/livre/team/drivers/{id}/overview.")
    else:
        print("✗ Chaîne NON prouvée sur cette fenêtre : aucun enregistrement Navixy ne")
        print("  correspond à un tag chauffeur configuré. Vérifiez : 1) le tag émet (pile),")
        print("  2) le traceur Teltonika a « Beacon List/Detection » activé (ex. FMC130 :")
        print("  Bluetooth 4.0 → Beacon Detection = All / Configured), 3) la fenêtre de temps,")
        print("  4) drivers.ble_id correspond bien au MAC/UUID du tag.")

    client.close()


def _show_records(records: list, by_tag: dict, by_tracker: dict) -> list:
    print(f"   {len(records)} enregistrement(s) reçu(s)")
    matches = []
    for rec in records[:200]:
        norm = normalize_identifier(rec.get("hardware_id"))
        drv = by_tag.get(norm)
        veh = by_tracker.get(rec.get("tracker_id"))
        status = []
        if drv:
            status.append(f"CHAUFFEUR RECONNU → {drv['name']}")
            matches.append({
                "driver": drv["name"], "tag": drv.get("ble_id"), "canon": norm,
                "vehicle": (veh or {}).get("plate") or "traceur non mappé",
                "tracker": rec.get("tracker_id"),
                "ts": rec.get("get_time"), "rssi": rec.get("rssi"),
            })
        else:
            status.append("beacon inconnu (aucun chauffeur avec ce tag)")
        if veh:
            status.append(f"véhicule {veh.get('plate')}")
        else:
            status.append(f"traceur {rec.get('tracker_id')} NON mappé")
        print(f"   • tracker={rec.get('tracker_id')} hw={rec.get('hardware_id')} "
              f"(canon {norm}) rssi={rec.get('rssi')} t={rec.get('get_time')} | {' | '.join(status)}")
    if len(records) > 200:
        print(f"   … {len(records) - 200} lignes supplémentaires tronquées")
    return matches


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", default="default")
    p.add_argument("--minutes", type=int, default=60)
    a = p.parse_args()
    asyncio.run(main(a.tenant, a.minutes))
