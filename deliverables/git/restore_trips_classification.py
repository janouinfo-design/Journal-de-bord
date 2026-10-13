#!/usr/bin/env python3
"""
RESTAURATION (séparée du patch) — reclasse les trajets du véhicule pilote selon
l'historique mode CONFIRMÉ (même logique que privacy_history_strict).

⚠️ SÉPARÉ du patch rules.py pour audit/rollback indépendants.
⚠️ DRY-RUN par défaut. `--apply` requis pour écrire. Idempotent.

PRÉREQUIS : le patch `privacy_history_strict` doit être DÉPLOYÉ et le tenant
configuré, SINON le scheduler legacy re-reclasserait immédiatement après.

USAGE (dans le conteneur backend PROD) :
  docker exec -i journal_backend python3 /path/restore_trips_classification.py            # DRY-RUN
  docker exec -i journal_backend python3 /path/restore_trips_classification.py --apply    # écrit

Règles :
- cible : trajets AUTO (auto_classified != False) du véhicule pilote VID ;
- proposition = classify_by_mode_history (CONFIRMÉ <=2h -> pro/perso ; sinon None) ;
- JAMAIS écraser une classification manuelle (auto_classified == False) -> signalé, ignoré ;
- idempotent : un trajet déjà conforme n'est pas réécrit ;
- journalise chaque changement (trip_id, ancienne, nouvelle, raison, preuve) ;
- rapport avant/après + comptage par catégorie.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from app.rules import classify_by_mode_history, _confirmed_mode_events, PRIVACY_FRESH_MAX_S

VID = os.environ.get("RESTORE_VEHICLE_ID", "995ee4d5-1496-4180-b895-1238f994d36d")
TID = os.environ.get("RESTORE_TENANT_ID", "default")


async def main():
    apply = "--apply" in sys.argv
    c = AsyncIOMotorClient(os.environ["MONGO_URL"]); db = c[os.environ["DB_NAME"]]
    events = await _confirmed_mode_events(db, VID)
    print(f"Véhicule {VID} | événements mode confirmés: {len(events)} | fresh_max={PRIVACY_FRESH_MAX_S}s")
    print(f"MODE: {'APPLY (écriture)' if apply else 'DRY-RUN (lecture seule)'}\n")

    cats = {"personal->None": 0, "professional->None": 0, "None->professional": 0,
            "None->personal": 0, "personal->professional": 0, "professional->personal": 0,
            "inchangé": 0, "manuel_ignoré": 0, "autre": 0}
    changes = []
    skipped_manual = []

    # Cible : trajets du véhicule pilote (auto uniquement). On NE filtre PAS par date
    # (on balaie tous les trajets du véhicule) ; la logique décide trajet par trajet.
    async for t in db.trips.find({"tenant_id": TID, "vehicle_id": VID}, {"_id": 0}):
        tid_trip = t.get("id")
        current = t.get("classification")
        if t.get("auto_classified") is False:
            skipped_manual.append(tid_trip)
            cats["manuel_ignoré"] += 1
            continue
        proposed = classify_by_mode_history(t, events)
        if proposed == current:
            cats["inchangé"] += 1
            continue
        key = f"{current}->{proposed}"
        cats[key] = cats.get(key, 0) + 1
        changes.append((tid_trip, t.get("start_time"), t.get("end_time"),
                        t.get("distance_km"), current, proposed))

    # Rapport
    print("=== CHANGEMENTS PROPOSÉS ===")
    print("trip_id | start | end | km | actuelle -> proposee")
    for cid, s, e, km, cur, prop in changes:
        print(f"  {str(cid)[:8]} | {s} | {e} | {km} | {cur} -> {prop}")
    print("\n=== COMPTAGE PAR CATÉGORIE ===")
    for k, v in cats.items():
        if v:
            print(f"  {k}: {v}")
    print(f"  total à modifier: {len(changes)} | manuels ignorés: {len(skipped_manual)}")

    if not apply:
        print("\n(DRY-RUN) Relancer avec --apply APRÈS déploiement du patch privacy_history_strict.")
        return

    # --- APPLY (idempotent) ---
    done = 0
    for cid, s, e, km, cur, prop in changes:
        # Re-vérif anti-course : le trajet n'a pas changé depuis le DRY-RUN.
        fresh = await db.trips.find_one({"id": cid}, {"_id": 0, "classification": 1, "auto_classified": 1})
        if not fresh:
            print(f"  ! {str(cid)[:8]} introuvable, ignoré"); continue
        if fresh.get("auto_classified") is False:
            print(f"  ! {str(cid)[:8]} devenu MANUEL, ignoré (non écrasé)"); continue
        if fresh.get("classification") != cur:
            print(f"  ! {str(cid)[:8]} a changé depuis le DRY-RUN ({fresh.get('classification')}), ignoré")
            continue
        await db.trips.update_one(
            {"id": cid}, {"$set": {"classification": prop, "auto_classified": True}})
        await db.audit_log.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "scope": "trip_classification_restore",
            "trip_id": cid, "vehicle_id": VID,
            "old_classification": cur, "new_classification": prop,
            "reason": "restore_privacy_history_strict",
        })
        done += 1
    print(f"\n✅ APPLY terminé : {done} trajet(s) mis à jour.")

    # Contrôle READ-ONLY final
    from collections import Counter
    cnt = Counter()
    async for t in db.trips.find({"tenant_id": TID, "vehicle_id": VID}, {"_id": 0, "classification": 1}):
        cnt[t.get("classification")] += 1
    print("État final classification (véhicule pilote):", dict(cnt))


if __name__ == "__main__":
    asyncio.run(main())
