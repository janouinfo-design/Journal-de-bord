# DRIVER_PRIVATE_MODE_D2_AUDIT.md
## Phase D2 — Audit READ-ONLY Private/Business + Total Odometer (PARC MULTI-MODÈLES)

> **Suite de** D1 FINAL (`db1b25d`). **READ-ONLY strict** : aucun `setparam`,
> `privatemode`, `raw_command/send`, `counter/value/set`, `counter/update`, aucune
> modification device/Navixy. Aucune donnée inventée.
> **Règle** : la capacité est par **MODÈLE + FIRMWARE + CONFIG**, jamais « Teltonika » global.
> `DOCUMENTED` ≠ `RUNTIME_VERIFIED` ≠ `FIELD_VERIFIED`.

---

## 1. CORRECTION DE TERMINOLOGIE D1
On distingue désormais 2 objets :
- **NAVIXY_PLATFORM_ODOMETER** = le compteur `type=odometer` de Navixy. Source constatée
  runtime (D1) : **`NAVIXY_GPS_CALCULATED`** (connue, pas « unverified »).
- **TELTONIKA_TOTAL_ODOMETER** = l'odomètre INTERNE du device (section Odometer, calc GNSS/LVCAN/OBD).
  → **NON lisible via l'API Navixy** ; statut `AVL16_MAPPING = NOT_VERIFIED`, `HARDWARE_ODOMETER = UNKNOWN`.

Ce qui reste **non vérifié** : `TELTONIKA_TOTAL_ODOMETER`, `AVL16_MAPPING`, `HARDWARE_ODOMETER_AVAILABILITY`.

---

## 2. PILOTE (FMU130) — RUNTIME (tracker 625282, Gaggetta, GE-898 507)

```
PRIVATE_BUSINESS_SUPPORTED:        UNKNOWN   (config device non lisible via API Navixy)
PRIVATE_BUSINESS_CONFIG_READABLE:  NO (via Navixy) — nécessite Teltonika Configurator (getparam)
GPS_DATA_MASKING:                  NOT_READABLE (via Navixy)
ODOMETER_CALCULATION:              NOT_READABLE (via Navixy)
TRIGGER_TYPE:                      NOT_READABLE (via Navixy)   [observation antérieure: "Weekly Schedule" — à relire Configurator]
CODEC:                             NOT_READABLE (via Navixy)

TELTONIKA_TOTAL_ODOMETER:          UNKNOWN (interne device, non exposé Navixy)
CALCULATION_SOURCE:                UNKNOWN (GNSS/LVCAN/OBD — à lire Configurator)
AVL16_DEVICE_SUPPORT:              NOT_VERIFIED
AVL16_ENABLED:                     UNKNOWN
AVL16_RECEIVED_BY_NAVIXY:          NO (aucun élément AVL16 constaté dans readings/counters)
AVL16_VALUE:                       null

NAVIXY_TOTAL_ODOMETER_SENSOR:      NO
NAVIXY_SENSOR_ID:                  null
NAVIXY_COUNTER_SOURCE:             GPS_CALCULATED
NAVIXY_COUNTER_SENSOR_ID:          null (compteur odometer non lié à un sensor HW)

CAN_ODOMETER:                      UNAVAILABLE (aucun can_mileage exposé)
OBD_ODOMETER:                      UNAVAILABLE (OBD présent: conso/rpm/vitesse/temp… mais AUCUN PID mileage)
TACHOGRAPH_ODOMETER:               UNAVAILABLE (FMU130 non tachy)
```
Preuves runtime D1/D2 : `sensor/list`, `readings/list`, `get_counters`, `counter/value/get`,
`counter/data/read` (croissance GPS-corrélée), `get_state` (source.model=telfmu130).

---

## 3. MATRICE MULTI-MODÈLES (états stricts) — parc RÉEL

Inventaire runtime (3 comptes Navixy) :
- `telfmb003_fmc003` = **FMC003** — 14 devices (Logitrak 4, Pradervand 10)
- `telfmu130_fmc130` = **FMC130** — 11 devices (Logitrak 6, Pradervand 5)  ⚠️ code trompeur (contient `fmu130` + suffixe `_fmc130`)
- `telfmu130` = **FMU130** — 3 devices (Gaggetta) — PILOTE
- `iosnavixytracker_xgps` / `navixymobile_xgps` = **smartphones** (2) — hors périmètre
- **FMC640 / FMC650 : ABSENTS** des comptes réels → `NOT_PRESENT`

| Modèle | Private/Business | GPS masking | Odomètre HW exposé | Source / AVL | Odo pendant privé | État |
|---|---|---|---|---|---|---|
| **FMC003** (14) | DOCUMENTED | DOCUMENTED | **NON** (RUNTIME) | Navixy=GPS-calc ; OBD sans mileage | UNKNOWN | NOT_TESTED |
| **FMC130** (11) | DOCUMENTED | DOCUMENTED | **OUI `can_mileage`** (RUNTIME) | VEHICLE_CAN | UNKNOWN (à prouver D3) | NOT_TESTED |
| **FMU130** (3) | UNKNOWN | UNKNOWN | **NON** (RUNTIME) | Navixy=GPS-calc | UNKNOWN | **PILOT** |
| **FMC640** | — | — | — | — | — | NOT_PRESENT |
| **FMC650** | — | — | — | — | — | NOT_PRESENT |

Preuves runtime D2 (`get_counters` + `sensor/list`, 1 device/modèle) :
- FMC003 (ex 3079431, Renault Zoe) : counters=odometer(GPS)+engine_hours ; sensors OBD ; **HARDWARE_MILEAGE=NONE**.
- FMC130 (ex 781479, LOGITRAK AUDI) : counters=odometer+engine_hours ; sensors incl. **`can_mileage`, `can_consumption`, `avl_io_463`, `ble_beacon_id`** ; **HARDWARE_MILEAGE=`can_mileage`** ✅.
- FMU130 (ex 625282, Fiat Doblo) : counters=odometer(GPS) ; sensors OBD ; **HARDWARE_MILEAGE=NONE**.

> ⚠️ Aucune cellule `FIELD_VERIFIED`. `can_mileage` (FMC130) est `RUNTIME_VERIFIED` (présent), pas
> encore prouvé « continue en Private Mode » (→ D3). Aucun AVL figé (pas d'AVL16 universel).

---

## 4. REGISTRE DE CAPACITÉS (implémenté, backend)
Fichier : `backend/app/odometer_capability.py` — `HardwareOdometerCapability` par modèle +
`resolve_model()` (gère le piège `telfmu130_fmc130 → FMC130`) + `private_mode_allowed()` (gate prod).
- **Aucun** modèle `verified=True` (règle absolue). Tests `test_odometer_capability.py` **7/7**.
- Gate prod : `private_mode_allowed()` = `False` pour TOUS les modèles → bouton Privé interdit
  en production tant qu'un modèle n'est pas FIELD-VALIDATED.
- FMC130 : `source_type=VEHICLE_CAN`, `navixy_input=can_mileage`, `evidence_level=RUNTIME_VERIFIED`.
- FMC003/FMU130 : `NAVIXY_GPS_CALCULATED`, `navixy_sensor_exposable=NOT_SUPPORTED`.
- FMC640/FMC650 : `status=NOT_PRESENT`.

---

## 5. OPTIONS (basées sur le runtime réel par modèle)

```
OPTION_A_TELTONIKA_TOTAL_ODOMETER: UNKNOWN (tous modèles)
  - Non lisible via API Navixy ; nécessite lecture Configurator + activation transmission AVL +
    exposition sensor + preuve terrain de continuité en Private Mode.

OPTION_B_CAN_OBD:
  - FMC130: **VIABLE (candidate)** — `can_mileage` réellement exposé (source HW indépendante du GPS).
            À prouver en D3 : la valeur can_mileage continue quand le GPS transmis est masqué.
  - FMC003: UNAVAILABLE (aucun mileage HW ; OBD sans PID kilométrage).
  - FMU130: UNAVAILABLE (aucun mileage HW).

OPTION_C_APPLICATION_PRIVACY: REPLI pour FMC003 & FMU130
  - Aucune source HW → masquage applicatif côté LOGITRAK + distance privée = DISTANCE UNAVAILABLE
    si aucune source non-GPS. Ne pas masquer au niveau device (0,0) pour ces modèles sans nouvelle analyse.
```

**Conclusion stratégique** : le rollout Private/Business devra être **par modèle** :
- **FMC130** → piste **Option B (CAN)** → candidat prioritaire pour D3.
- **FMC003 / FMU130** → pas de source HW exposée → Option A (Configurator/AVL) à explorer, sinon Option C.

---

## 6. DETTE SÉCURITÉ CREDENTIALS (§20)
```
LEGACY_PLAINTEXT_NAVIXY_CREDENTIALS_COUNT: 3  (Logitrak, Pradervand, Gaggetta — clés en clair)
```
Plan de re-chiffrement (mission séparée, NON exécutée en D2) :
1. Sauvegarde `navixy_hash` clair de chaque tenant (backup chiffré hors-ligne).
2. Pour chaque tenant : `enc = encrypt_secret(clair)` puis `update` atomique du seul champ `navixy_hash`.
3. Vérifier lecture (`get_integration_credential` → credential déchiffré == clair d'origine).
4. Rollback : restaurer la valeur claire depuis la sauvegarde si échec de lecture.
Idempotent (préfixe `enc::` déjà chiffré → skip). À exécuter dans une fenêtre de maintenance.

---

## 7. ACTIONS DE LECTURE ENCORE REQUISES (hors API Navixy)
Pour compléter la matrice sans rien écrire :
- **Teltonika Configurator** (lecture seule) sur 1 device de CHAQUE modèle réellement présent :
  `Odometer > Calculation Source` + `Odometer Value` ; `Private/Business` (`GPS Data Masking`,
  `Odometer calculation`, `Trigger Type`) ; **firmware version**.
- Confirmer, par modèle, quel **AVL** porte le Total Odometer (16 pour FMx1xx supposé ;
  199/216/192 pour FMX6xx supposé) — **preuve requise**, pas la doc.

---

## D2 STATUS
```
D2 STATUS: READY_FOR_PILOT_CONFIG  (pour FMC130 uniquement — via can_mileage)
           NEEDS_DEVICE_READ       (pour FMC003 & FMU130 — aucune source HW exposée)
```
Justification : la gate de sortie (§22) exige une stratégie crédible « GPS masqué + odomètre
indépendant qui continue ». Le runtime D2 a **identifié une telle source sur le FMC130** :
`can_mileage` (CAN véhicule), indépendant du GPS transmis → candidat solide pour D3.
Pour **FMC003** et **FMU130**, aucune source HW n'est exposée → il faut d'abord une lecture
Configurator (Total Odometer / AVL) ; sinon Option C (privacy applicative).

### GATE DE SORTIE (§22)
- **FMC130 : ATTEINTE** (source non-GPS `can_mileage` identifiée ; reste à prouver terrain
  qu'elle continue en Private Mode — objet de D3). Le compteur GPS-calculé Navixy reste **exclu**.
- **FMC003 / FMU130 : NON atteinte** (pas de source HW indépendante du GPS pour l'instant).

### NEXT SAFE STEP
```
NEXT SAFE STEP: D3 CAN/OBD ODOMETER PILOT   (cible FMC130 — 1 seul device)
```
Dans l'ordre, SANS écriture device tant que non décidé explicitement :
1. **FMC130** (Option B — prioritaire) : choisir 1 device FMC130, lire l'historique `can_mileage`
   (`counter/data/read` ou readings) pour confirmer unité + caractère cumulatif ; puis D3 terrain :
   Private ON → vérifier GPS transmis masqué **ET** `can_mileage` qui continue → Private OFF →
   `private_distance = can_mileage_end - can_mileage_start`.
2. **FMC003 / FMU130** : lecture **Teltonika Configurator** (Total Odometer / Calculation Source /
   Private-Business / firmware). Si un Total Odometer HW est activable et continue en privé →
   `D3 SINGLE-DEVICE CONFIGURATION PILOT`. Sinon → étudier `OPTION C` (privacy applicative).
3. **FMC640 / FMC650** : `NOT_PRESENT` dans le parc → hors périmètre tant qu'aucun device réel.

**Ne PAS** démarrer D3 ni aucune écriture device automatiquement. Le bouton Privé reste **désactivé
en production** pour TOUS les modèles (gate `private_mode_allowed()` = False) jusqu'à FIELD-VALIDATION
par modèle.
