# FMC130 AVL16 CAPABILITY — SOURCE NORMALIZATION — MINI-DELTA (dev only, aucun déploiement)

> Correctif : UNE seule source métier canonique `TELTONIKA_TOTAL_ODOMETER`.
> Suppression de la persistance de `TELTONIKA_AVL16` (devenu un simple LABEL UI).
> Aucun déploiement, aucune écriture Mongo prod, aucun `setparam`, WRITE=0 inchangé.

---

## CURRENT ISSUE
- duplicate source constants : `TELTONIKA_AVL16` (calibration) vs `TELTONIKA_TOTAL_ODOMETER` (capability/gate/FMC003).
- TELTONIKA_AVL16 persisted before : OUI (`_update_capability_baseline` écrivait `private_distance_source="TELTONIKA_AVL16"`), ce qui aurait rendu la capability FMC130 INCOMPATIBLE avec la gate private-mode.
- canonical source expected : **`TELTONIKA_TOTAL_ODOMETER`** (exigée par `vehicle_private_mode_allowed`).

## FIX
- canonical source : `TELTONIKA_TOTAL_ODOMETER` (réutilise `SOURCE_TELTONIKA_TOTAL_ODOMETER` importé d'`odometer_capability`).
- `SOURCE_TELTONIKA_AVL16` : conservé en **alias rétro-compat** = valeur canonique (plus jamais la chaîne `"TELTONIKA_AVL16"`).
- `AVL16_SOURCE_LABEL = "Teltonika AVL16"` : label d'affichage UI/API uniquement (jamais persisté comme source).
- calibration writer fixed : `_update_capability_baseline` persiste `TELTONIKA_TOTAL_ODOMETER`.
- live reader compatible : `read_live_avl16_km` renvoie `source=TELTONIKA_TOTAL_ODOMETER`.
- route : expose `source` (canonique) + `source_label` ("Teltonika AVL16"). Frontend affiche déjà le label.
- FMC003 compatibility : inchangé (pilote 3657864 reste `TELTONIKA_TOTAL_ODOMETER`, `field_validated=True`).
- FMC130 compatibility : la calibration écrit désormais la source canonique → cohérent avec la gate.
- résidu `"TELTONIKA_AVL16"` en dur dans app/ : AUCUN (grep vide).

## FICHIERS MODIFIÉS
| Fichier | Type |
|---|---|
| `backend/app/odometer_calibration.py` | MODIFIED (source canonique + label) |
| `backend/app/routes/odometer_calibration.py` | MODIFIED (source canonique + source_label) |
| `backend/tests/test_odometer_calibration.py` | TEST (T7 renommé + T1..T12 normalisation source) |

Backend rebuild : OUI · Frontend rebuild : NON nécessaire (le label était déjà en dur) · DB migration : NON · device action : NON.

## CAPABILITY (mapping cible FMC130 — à créer PLUS TARD, sur GO)
```
tenant_id               = default
vehicle_id              = 995ee4d5-1496-4180-b895-1238f994d36d
tracker_id              = 781479
device_model            = FMC130
private_distance_source = TELTONIKA_TOTAL_ODOMETER
raw_avl_id              = 16
navixy_input            = avl_io_16
navixy_sensor_id        = 5577108
raw_unit                = m
normalized_unit         = km
multiplier              = 1.0
divider                 = 1000.0
```

## MULTI-TENANT (audit, PAS de changement ici)
- current lookup tenant-scoped : **NON** — les 6 accès `vehicle_private_capabilities`
  (`odometer_calibration.py` x3, `private_mode_engine.py` x2, route x1) filtrent par `tracker_id` seul.
- risk : faible aujourd'hui (pilote mono-tenant `default`, un tracker Navixy = un compte).
  Théorique en généralisation multi-tenant si un même `tracker_id` existait sous 2 tenants.
- recommendation : filtrer par `tenant_id + tracker_id` (option : contrôle `vehicle_id`).
  → **Chantier SÉPARÉ** (risque de régression) — NE PAS mélanger avec ce correctif source.

## TESTS
- module (odometer_calibration) : 45 → PASS 45 / FAIL 0 (T1..T24 + live T1..T10 + source T1..T12 + fraîcheur)
- regression globale : 118 → PASS 118 / FAIL 0
- frontend (Jest) : 10 → PASS 10 (inchangé)
- FAIL : 0
- testing_agent : à lancer

## PROD (état — inchangé)
```
Mongo capability created : NON
setparam 11807           : NON
WRITE                    : 0
field_validated          : FALSE
private_mode_pilot       : FALSE
odometer_calibrated      : FALSE
```

---

## COMMANDE MONGO PROPOSÉE (NE PAS EXÉCUTER — attendre GO)

> À lancer **plus tard**, après déploiement du mini-fix, pour créer le mapping capteur
> et faire disparaître le N/A. Idempotente (`$set` mapping seul, `upsert:true`).
> **N'inclut JAMAIS** `field_validated` / `private_mode_pilot` / `odometer_calibrated`.

```bash
docker exec journal_database mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval '
const D=db.getMongo().getDB("journal_logitrak");
const now=new Date().toISOString();
const r=D.vehicle_private_capabilities.updateOne(
  { tracker_id: 781479 },                                  // filtre = clé de lookup actuelle du code
  { $set: {
      tenant_id: "default",
      vehicle_id: "995ee4d5-1496-4180-b895-1238f994d36d",
      tracker_id: 781479,
      device_model: "FMC130",
      private_distance_source: "TELTONIKA_TOTAL_ODOMETER", // source canonique (jamais TELTONIKA_AVL16)
      raw_avl_id: 16,
      navixy_input: "avl_io_16",
      navixy_sensor_id: 5577108,
      raw_unit: "m",
      normalized_unit: "km",
      multiplier: 1.0,
      divider: 1000.0,
      updated_at: now
  } },
  { upsert: true }
);
printjson(r);
printjson(D.vehicle_private_capabilities.findOne({ tracker_id: 781479 }));
'
```

Vérifs attendues après exécution (sur GO) :
- doc présent, `private_distance_source=TELTONIKA_TOTAL_ODOMETER`, `navixy_sensor_id=5577108` ;
- `field_validated` / `private_mode_pilot` / `odometer_calibrated` ABSENTS (non positionnés) ;
- fiche 781479 → Km télématique = vraie valeur AVL16 (≈ 56 3xx km) au lieu de N/A ;
- bouton "Synchroniser" TOUJOURS grisé (WRITE=0).

---

## ORDRE CONSERVÉ
1. normalisation source ✅ (ce delta) → 2. tests ✅ → 3. mini-déploiement (GO) →
4. mapping Mongo 781479/5577108 (GO) → 5. AVL16 live visible → 6. D_calibration 11807 (GO terrain) →
7. validation terrain → 8. Km Pro/Privé sur AVL16.
