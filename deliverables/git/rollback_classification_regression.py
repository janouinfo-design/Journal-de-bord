#!/usr/bin/env python3
"""
ROLLBACK régression classification (privacy_history_strict bugué) — V2 (rapport structuré).

RÈGLES (validées) :
- tenant RÉEL = trips.tenant_id (JAMAIS audit_log.tenant_id, backfillé à tort en 'default') ;
- vérification croisée vehicle.tenant_id ; divergence -> EXCLU + compté (TENANT_MISMATCH) ;
- EXCLURE exactement les 24 trip_id pilotes (PILOT_EXCLUDE_TRIP_IDS) ; PAS tout l'Audi ;
- auto_classified=False -> jamais touché ;
- valeur cible = old_classification du PREMIER événement du trip ;
- anti-race (classification actuelle inchangée depuis le DRY-RUN) ;
- aucun recalcul métier.

DRY-RUN par défaut. `--apply` requis pour écrire. Idempotent.

ENV :
  PILOT_EXCLUDE_TRIP_IDS = CSV des 24 trip_id pilotes (obligatoire pour traiter l'Audi).
  PILOT_VEHICLE_ID       = id véhicule pilote (défaut Audi) — garde-fou.
"""
import asyncio
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

STRAT = "privacy_history_strict"
PILOT_VEHICLE_ID = os.environ.get("PILOT_VEHICLE_ID", "995ee4d5-1496-4180-b895-1238f994d36d")
PILOT_EXCLUDE = {s.strip() for s in os.environ.get("PILOT_EXCLUDE_TRIP_IDS", "").split(",") if s.strip()}
WATCH_TRIP = "e5342053-4908-4afc-b02c-7a37c826d734"  # trajet témoin à restaurer


async def main():
    apply = "--apply" in sys.argv
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c[os.environ["DB_NAME"]]
    print(f"MODE: {'APPLY' if apply else 'DRY-RUN'} | pilotes exclus fournis: {len(PILOT_EXCLUDE)}")

    q = {"scope": "trip_classification", "strategy": STRAT}
    by_trip = defaultdict(list)
    events_bruts = 0
    async for e in db.audit_log.find(
        q, {"_id": 0, "trip_id": 1, "old_classification": 1, "ts": 1}).sort("ts", 1):
        events_bruts += 1
        tid = e.get("trip_id")
        if tid is not None:
            by_trip[tid].append(e)

    trip_uniques = len(by_trip)
    multi_events = sum(1 for v in by_trip.values() if len(v) > 1)

    pilot_excluded = manual_excluded = already_correct = 0
    missing_trips = tenant_mismatch = origin_non_concrete = 0
    by_tenant = Counter()
    restore_pro = restore_perso = 0
    todo = []
    watch_line = None

    for tid, evs in by_trip.items():
        origin = evs[0].get("old_classification")  # 1er = origine
        if tid in PILOT_EXCLUDE:
            pilot_excluded += 1
            continue
        trip = await db.trips.find_one(
            {"id": tid}, {"_id": 0, "tenant_id": 1, "vehicle_id": 1,
                          "classification": 1, "auto_classified": 1})
        if not trip:
            missing_trips += 1
            continue
        tenant_real = trip.get("tenant_id")
        if trip.get("vehicle_id") == PILOT_VEHICLE_ID and not PILOT_EXCLUDE:
            # Sécurité : Audi sans allowlist -> exclu.
            pilot_excluded += 1
            continue
        veh = await db.vehicles.find_one({"id": trip.get("vehicle_id")}, {"_id": 0, "tenant_id": 1})
        if veh and veh.get("tenant_id") != tenant_real:
            tenant_mismatch += 1
            continue
        if trip.get("auto_classified") is False:
            manual_excluded += 1
            continue
        if origin not in ("professional", "personal"):
            origin_non_concrete += 1
            continue
        cur = trip.get("classification")
        if cur == origin:
            already_correct += 1
            continue
        by_tenant[tenant_real] += 1
        if origin == "professional":
            restore_pro += 1
        else:
            restore_perso += 1
        todo.append((tid, tenant_real, cur, origin))
        if tid == WATCH_TRIP:
            watch_line = f"{tid} | tenant={tenant_real} | {cur} -> {origin}"

    # ---- RAPPORT STRUCTURÉ ----
    print("\n================= DRY-RUN ROLLBACK — RAPPORT =================")
    print(f"EVENTS_BRUTS        = {events_bruts}")
    print(f"TRIP_ID_UNIQUES     = {trip_uniques}")
    print(f"MULTI_EVENTS        = {multi_events}")
    print(f"PILOT_EXCLUDED      = {pilot_excluded}")
    print(f"MANUAL_EXCLUDED     = {manual_excluded}")
    print(f"ALREADY_CORRECT     = {already_correct}")
    print(f"ORIGIN_NON_CONCRETE = {origin_non_concrete}")
    print(f"MISSING_TRIPS       = {missing_trips}")
    print(f"TENANT_MISMATCH     = {tenant_mismatch}")
    print(f"RESTORE_PROFESSIONAL= {restore_pro}")
    print(f"RESTORE_PERSONAL    = {restore_perso}")
    print(f"APPLICABLE_TOTAL    = {len(todo)}")
    print(f"PAR_TENANT_REEL     = {dict(by_tenant)}")
    print(f"WATCH[{WATCH_TRIP[:8]}]  = {watch_line or 'NON présent dans les à-restaurer (vérifier !)'}")
    print("=============================================================")

    if not apply:
        print("\n(DRY-RUN) Aucune écriture. Fournir --apply APRÈS validation de ces chiffres.")
        return

    done = 0
    for tid, tenant_real, cur, origin in todo:
        fresh = await db.trips.find_one({"id": tid}, {"_id": 0, "classification": 1, "auto_classified": 1})
        if not fresh or fresh.get("auto_classified") is False:
            continue
        if fresh.get("classification") != cur:  # anti-race
            print(f"  ! {str(tid)[:8]} changé depuis DRY-RUN, ignoré"); continue
        await db.trips.update_one(
            {"id": tid, "tenant_id": tenant_real},
            {"$set": {"classification": origin, "auto_classified": True}})
        await db.audit_log.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification_rollback",
            "tenant_id": tenant_real,
            "trip_id": tid, "old_classification": cur, "new_classification": origin,
            "reason": "rollback_privacy_history_regression_v2",
        })
        done += 1
    print(f"\n✅ APPLY terminé : {done} trajet(s) restauré(s).")


if __name__ == "__main__":
    asyncio.run(main())
