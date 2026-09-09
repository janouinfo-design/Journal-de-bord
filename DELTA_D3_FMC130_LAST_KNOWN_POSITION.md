# D3 FMC130 781479 — FINALISATION LOGICIELLE + CAPABILITY (dev only, aucun déploiement, aucune commande device)

> D3 terrain PASS enregistré côté logiciel. Confirmation Mode Privé du FMC130 activée
> UNIQUEMENT via stratégie explicite `LAST_KNOWN_POSITION` (jamais généralisée).
> Aucun `setparam` 11807, aucun Deep Sleep, aucune écriture Mongo prod ici, WRITE=0 inchangé.

---

## D3 FIELD VALIDATION = RECORDED (preuves)
```
privatemode ON/OFF confirmés (Air Console)
AVL16 début PRIVATE : 56443.20 km · fin : 56444.22 km · delta prouvé : +1.02 km · final : 56444.54 km
source : TELTONIKA_TOTAL_ODOMETER · sensor Navixy : 5577108
masquage GPS : 32/36 samples même position (ratio 0.889) · PRIVATE_MASK_PASS=true
reprise BUSINESS : +799.6 m après OFF · business_position_resume_pass=true
D3_PASS=true · health 200 · PRIVATE_MODE_DEVICE_WRITE=0 · ODOMETER_CALIBRATION_DEVICE_WRITE=0
getparam pilote : 11850=1 11814=1 11813=2 11815=1 11816=0 11849=0
INTERDITS respectés : 11807 non utilisé · FMC003 3661714 non touché · AVL391 non requis
```

## FIX (code)
- `odometer_capability.py` : + champ `private_confirmation_strategy` + constantes
  `CONFIRM_STRATEGY_FROZEN_POSITION` / `CONFIRM_STRATEGY_LAST_KNOWN_POSITION`.
- `private_mode_engine.py` :
  - `_model_supports_telemetry_confirm` : autorise si `field_validated` ET
    (`FMC003` OU `strategy==LAST_KNOWN_POSITION`). **Jamais** tous les FMC130.
  - `telemetry_confirm` : branche par stratégie. FROZEN_POSITION (FMC003) inchangé.
    LAST_KNOWN_POSITION : PRIVATE si actif + AVL16 augmente + coords masquées (0,0 ou ≤200 m
    de l'ancre) ; BUSINESS si trame post-OFF + coords réelles + position sortie (>200 m) de l'ancre.
    Un `applied:true` Navixy n'est JAMAIS une preuve.
  - `request_mode` : capture une ancre GPS interne (`private_gps_anchor_lat/lng`) à l'entrée PRIVATE ;
    `resolve_pending_confirmation` la SUPPRIME après confirmation BUSINESS. Jamais exposée à l'UI.
  - `private_distance_km` = delta AVL16 uniquement. Confidentialité API inchangée.

## TESTS
```
FMC130 CONFIRMATION STRATEGY = PASS
PRIVATE MODE TESTS      : test_private_mode_confirmation.py = 24/24 PASS (dont 10 LKP)
REGRESSION FMC003       : PASS (FROZEN_POSITION inchangé)
REGRESSION globale      : 134/134 PASS
MULTI-TENANT            : PASS (gate fail-closed inchangée)
testing_agent           : PASS
```

## FICHIERS MODIFIÉS (deploy)
| Fichier | Type |
|---|---|
| `backend/app/odometer_capability.py` | MODIFIED (champ + constantes) |
| `backend/app/private_mode_engine.py` | MODIFIED (stratégie LKP + ancre) |
| `backend/tests/test_private_mode_confirmation.py` | TEST_ONLY |

Backend rebuild : OUI · Frontend : NON · DB migration : NON · device action : NON.

## PROD (inchangé pendant cette étape)
```
PRIVATE_MODE_DEVICE_WRITE=0
ODOMETER_CALIBRATION_DEVICE_WRITE=0
PRIVATE_MODE_PILOT_TRACKERS=781479
READY_FOR_FINAL_PRODUCTION_ENABLEMENT : à confirmer après déploiement de ce fix + création capability
```
> Avec `DEVICE_WRITE=0` : l'UISera « éligible » (allowed=true) mais `can_switch=false`
> (`PRIVATE_MODE_DEVICE_WRITE_DISABLED`). La bascule reste NON exécutable. On n'active PAS WRITE=1 ici.

---

## COMMANDE MONGO PROPOSÉE — capability D3 (NE PAS EXÉCUTER — attendre GO)

> Enregistre officiellement la validation D3 du tracker 781479 UNIQUEMENT (upsert par tracker_id).
> `field_validated=true` + `private_confirmation_strategy=LAST_KNOWN_POSITION` + preuve D3 structurée
> (sans coordonnées GPS privées). N'affecte aucun autre tracker.

```bash
docker exec journal_database mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval '
const D=db.getMongo().getDB("journal_logitrak");
const now=new Date().toISOString();
const r=D.vehicle_private_capabilities.updateOne(
  { tracker_id: 781479 },
  { $set: {
      tenant_id: "default",
      vehicle_id: "995ee4d5-1496-4180-b895-1238f994d36d",
      tracker_id: 781479,
      device_model: "FMC130",
      private_distance_source: "TELTONIKA_TOTAL_ODOMETER",
      raw_avl_id: 16,
      navixy_input: "avl_io_16",
      navixy_sensor_id: 5577108,
      raw_unit: "m",
      normalized_unit: "km",
      multiplier: 1.0,
      divider: 1000.0,
      scale_status: "VERIFIED",
      runtime_verified: true,
      cumulative_verified: true,
      private_increment_verified: true,
      field_validated: true,
      capability: "FIELD_VALIDATED",
      validation_status: "FIELD_VERIFIED",
      private_confirmation_strategy: "LAST_KNOWN_POSITION",
      d3_proof: {
        private_start_km: 56443.20,
        private_end_km: 56444.22,
        private_delta_km: 1.02,
        mask_samples: 36,
        dominant_position_samples: 32,
        dominant_position_ratio: 0.889,
        business_resume_distance_m: 799.6,
        d3_result: "PASS"
      },
      updated_at: now
  } },
  { upsert: true }
);
printjson(r);
printjson(D.vehicle_private_capabilities.findOne({ tracker_id: 781479 }));
'
```

Vérifs attendues après exécution (sur GO) :
- doc présent, `field_validated=true`, `private_confirmation_strategy="LAST_KNOWN_POSITION"`, `private_distance_source="TELTONIKA_TOTAL_ODOMETER"`, `navixy_sensor_id=5577108` ;
- `d3_proof` présent, sans coordonnées GPS ;
- GET `/driver/private-mode` (pilote 781479) → `allowed=true`, `can_switch=false`,
  `reason/can_switch_reason=PRIVATE_MODE_DEVICE_WRITE_DISABLED` (car WRITE=0) ;
- fiche Kilométrage → vraie valeur AVL16 (le mapping sensor est inclus ci-dessus) ;
- aucun `setparam`, aucune commande device.

> ⚠️ Cette commande N'ACTIVE PAS `PRIVATE_MODE_DEVICE_WRITE=1`. L'activation finale de la bascule
> réelle reste une étape distincte, sur GO explicite ultérieur.

---

## RAPPORT FINAL
```
D3 FIELD VALIDATION = RECORDED (code + capability proposée, non écrite)
FMC130 CONFIRMATION STRATEGY = PASS
PRIVATE MODE TESTS = 24/24 PASS
REGRESSION FMC003 = PASS
MULTI-TENANT = PASS
HEALTH = 200 (local fork)
TRACKER 781479 GATE = ALLOWED (une fois la capability field_validated créée) ; can_switch=false tant que WRITE=0
PRIVATE_MODE_DEVICE_WRITE = 0
ODOMETER_CALIBRATION_DEVICE_WRITE = 0
READY_FOR_FINAL_PRODUCTION_ENABLEMENT = YES (côté logiciel) — activation WRITE=1 sur GO final séparé
```
