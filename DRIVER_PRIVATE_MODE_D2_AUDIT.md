# DRIVER_PRIVATE_MODE_D2_AUDIT.md
## Phase D2 — Audit READ-ONLY Private/Business + Total Odometer (PARC MULTI-MODÈLES)

## ============================================================================
## D2 CLÔTURE — FMC130 TOTAL ODOMETER AUDIT (2026-09-02) — VERDICT DÉFINITIF
## ============================================================================
> **READ-ONLY strict.** Runtime réel collecté sur le VPS (conteneur `journal_backend`)
> via `scripts/d2_total_odometer_audit.py` : endpoints `tracker/get_state`,
> `tracker/readings/list`, `tracker/get_counters`, `track/list`. Secrets/IMEI/SIM/GPS masqués.
> Ce bloc **remplace l'hypothèse antérieure** (« `can_mileage` = candidat viable ») : la preuve
> runtime la contredit (voir ci-dessous). L'historique D1/D2 plus bas est conservé pour traçabilité.

**Device pilote :** tracker `781479` « LOGITRAK AUDI », `source.model = telfmu130_fmc130` (→ FMC130),
VIN OBD `WAUZZZ8V0JA152970` (Audi).

### Verdict D2 (défini, à figer au commit)
```
FMC130_TOTAL_ODOMETER               = NOT_CURRENTLY_EXPOSED
D3                                  = NEEDS_CONFIG
RECENT_DRIVING                      = YES  (6 trajets / 24h, 45.39 km, dernier mvt 2026-09-02 12:38:14)
TELTONIKA_TOTAL_ODOMETER_INCREMENT  = PENDING_REAL_DRIVE
TELTONIKA_TOTAL_ODOMETER_AVL_ID     = UNVERIFIED   (aucune preuve modèle/firmware/runtime pour ce device)
CAN_OBD_STATUS                      = CAN_OBD_NOT_CURRENTLY_REPORTING
```

### Preuve runtime (valeurs réelles, non inventées)
| Champ | Valeur | Unité | Dernier update | Interprétation |
|---|---|---|---|---|
| `can_mileage` (readings/inputs) | 80 078.5 | km | **2022-03-26 10:23:34** | Non renouvelé depuis 2022 → **source secondaire uniquement**, non fiable en l'état |
| `can_consumption` | 28.0 | L | 2022-03-26 | idem (CAN non renouvelé) |
| `obd_*` (rpm, speed, fuel, VIN…) | — | — | 2024-04 → 2024-06 | valeurs OBD non renouvelées depuis 2024 |
| `odometer` (get_counters, REF Navixy) | 139 316.67 | km | 2026-09-02 14:57 | **GPS-calculé Navixy → NON admissible** pour distance privée |
| `engine_hours` | 1 253.03 | h | 2026-09-02 15:09 | vivant, mais pas une distance |
| `board_voltage` | 13.22 | V | 2026-09-02 14:57 | device lui-même vivant |

### Formulations corrigées (importantes)
1. **NE PAS conclure « le bus CAN/OBD est mort ».** La preuve établit seulement
   `CAN_OBD_NOT_CURRENTLY_REPORTING` : les dernières valeurs CAN/OBD sont anciennes (2022 / 2024),
   mais D2 **ne prouve pas la cause physique** (câble, configuration device, mapping Navixy,
   changement de véhicule/ECU, etc.). Cause = **INDÉTERMINÉE depuis D2**.
2. **NE PAS figer l'AVL ID 16** comme vérité pour ce FMC130 : `TELTONIKA_TOTAL_ODOMETER_AVL_ID =
   UNVERIFIED` tant qu'aucune preuve spécifique **modèle + firmware + runtime/config** ne l'établit.

### Interprétation
- Aucun champ `total_odometer` / `hw_mileage` / odomètre total hardware n'est exposé à Navixy
  (ni `readings/list`, ni `get_state.state[.additional]`, ni `get_counters`).
- C'est un **`NOT_CURRENTLY_EXPOSED`**, **pas** `NOT_SUPPORTED` : le firmware FMC130 supporte en
  principe un « Total Odometer », mais il n'est pas exposé/mappé aujourd'hui pour ce device.
- Le device lui-même fonctionne (GPS/GSM/`board_voltage`/`ble_beacon_id` récents) ; seul le flux
  CAN/OBD n'est pas renouvelé.

### Pourquoi D3 = NEEDS_CONFIG (2 verrous avant tout test privatemode)
1. Faire **exposer un Total Odometer hardware** vers Navixy (activation/mapping) — sinon D3 n'a
   aucune source à mesurer.
2. Déterminer la **source de calcul de l'odomètre** (GNSS vs OBD/CAN). CAN/OBD ne remontant pas
   actuellement, la seule source restante serait GNSS → question centrale de D3 :
   *le Total Odometer GNSS continue-t-il d'incrémenter en interne quand la position transmise est
   masquée ?* (plausible mais **non prouvé**).

### Prochaine mission (READ-ONLY, décidée) — fermer la config FMC130 avant FMC003
Lecture de configuration/état **sans aucune écriture**. Verdict attendu unique parmi :
`READY_FOR_D3` | `READY_FOR_D3_CONFIG_PILOT` | `CONFIGURATOR_READ_REQUIRED` | `FMC130_NO_VALID_ODOMETER_SOURCE`.
FMC003 **non entamé** tant que FMC130 n'est pas clos.

### CLÔTURE CONFIG FMC130 — CONFIG-READ (2026-09-02) — VERDICT DÉFINITIF
> Runtime réel via `scripts/d2_fmc130_config_read.py` (READ-ONLY). Endpoints Navixy tentés
> et réponses **réelles** (falsifiable, non présumé).

```
VERDICT_FMC130                     = CONFIGURATOR_READ_REQUIRED
DEVICE_CONFIG_READABLE_VIA_NAVIXY  = NO
CONFIGURATOR_READ_REQUIRED         = YES
```

**Disponibilité réelle des endpoints READ-ONLY (tracker 781479) :**
| Endpoint | Résultat | Contenu réel |
|---|---|---|
| `tracker/get_state` | OK | état/GPS/inputs (config plateforme, pas device) |
| `tracker/get_diagnostics` | OK | inputs OBD (`obd_rpm`, `obd_speed`, `obd_coolant_t`…) + `obd_vin=WAUZZZ8V0JA152970`, `update_time` **2024-06-20** → **figé** ; **aucun PID kilométrage** |
| `tracker/settings/read` | OK | **uniquement** `label` + `group_id` (réglage **plateforme**) |
| `tracker/settings/tracking/read` | OK | mode tracking plateforme (angle/distance/interval, `stop_detection=ignition`) — **pas** la config Odometer/Private device |
| `tracker/command/list` | INDISPONIBLE | `code 112 Wrong method: 'list'` (info-seule ; ne donne pas la config de toute façon) |

**Paramètres Teltonika (tous NON lisibles via API Navixy) :** `odometer_calculation_source`,
`total_odometer_io_enabled`, `total_odometer_avl_id`, `private_business_supported`,
`gps_data_masking`, `odometer_calc_in_private_mode`, `trigger_type` → `NON_LISIBLE_VIA_NAVIXY`.

**Correction d'interprétation (honnêteté) :** `get_diagnostics` renvoie bien des valeurs OBD
(sous la clé `inputs`, non `list` — le compteur du script affichait « 0 » à tort), **mais** elles
sont **figées au 2024-06-20** et **ne contiennent aucun kilométrage**. Cela **confirme**
`CAN_OBD_NOT_CURRENTLY_REPORTING` (données présentes mais non renouvelées ; cause physique
toujours **indéterminée** depuis D2).

**Conséquence :** la config device Teltonika (source de calcul odomètre, Total Odometer I/O + son
AVL réel, Private/Business, GPS masking, comportement odomètre en privé, Trigger Type) **n'est pas
accessible via l'API User Navixy**. La seule voie « raw getparam » passerait par
`raw_command/send` = **écriture de commande → interdite en D2**. → **Lecture Teltonika Configurator
requise** (relevé manuel, sans modification).

**Bifurcation post-Configurator :**
- Total Odometer activable **et** source indépendante du GPS transmis en mode privé → `D3 pilote FMC130`.
- Sinon → `FMC130_NO_VALID_ODOMETER_SOURCE`.

## ============================================================================


> **Suite de** D1 FINAL (`db1b25d`). **READ-ONLY strict** : aucun `setparam`,
> `privatemode`, `raw_command/send`, `counter/value/set`, `counter/update`, aucune
> modification device/Navixy. Aucune donnée inventée.
> **Règle** : la capacité est par **MODÈLE + FIRMWARE + CONFIG**, jamais « Teltonika » global.
> `DOCUMENTED` ≠ `RUNTIME_VERIFIED` ≠ `FIELD_VERIFIED`.


## ============ CORRECTION DE STRATÉGIE PAR MODÈLE (décision métier) ============
> La stratégie de kilométrage privé **diffère selon le modèle** (ne pas généraliser).
> Le compteur **GPS-calculé Navixy n'est JAMAIS** une source de distance privée.

| Modèle | Installation | STRATÉGIE cible | Disponibilité | Statut |
|---|---|---|---|---|
| **FMC003** | OBD | `VEHICLE_OBD_CAN_MILEAGE` (fallback `TELTONIKA_TOTAL_ODOMETER`) | **VEHICLE_DEPENDENT** (par véhicule) | À valider (par véhicule) |
| **FMC130** | Fixe | `TELTONIKA_TOTAL_ODOMETER` (odomètre INTERNE) | DEVICE/CONFIG_DEPENDENT | À valider |
| **FMU130** | Ancien | — | N/A | **DEPRECATED** (retiré ~2027, aucun dev) |
| **FMC640** | Poids lourd | `HARDWARE_CAN_FMS_TACHO` (Total Odo) | VEHICLE/CONFIG_DEPENDENT | À valider (absent du parc) |
| **FMC650** | Poids lourd | `HARDWARE_CAN_FMS_TACHO` (Total Odo) | VEHICLE/CONFIG_DEPENDENT | À valider (absent du parc) |

Reclassements clés (les preuves D1/D2 sont conservées, réinterprétées) :
- **FMC130** : cible = **Total Odometer INTERNE Teltonika**, PAS `can_mileage` (observé mais donnée
  périmée 2022 → source secondaire/comparaison uniquement), PAS le GPS Navixy. Prochaine mission :
  **FMC130 TOTAL ODOMETER AUDIT** (READ-ONLY) : ce Total Odometer interne est-il transmis à Navixy
  et continue-t-il en Private Mode ?
- **FMC003** : cible = **OBD/CAN mileage**, mais **validation VÉHICULE PAR VÉHICULE**. L'absence de
  `can_mileage` sur un véhicule pilote ne prouve pas l'incapacité du modèle (dépend véhicule/ECU/PID/
  firmware/config). Statut par véhicule : `CAN_MILEAGE_VALIDATED | TELTONIKA_ODOMETER_VALIDATED |
  HARDWARE_SOURCE_VALIDATED | NO_HARDWARE_ODOMETER | NOT_TESTED`. Mission séparée : **FMC003 OBD/CAN
  MILEAGE AUDIT**.
- **FMU130** : **DEPRECATED** → `PRIVATE_MODE_ROLLOUT=NO`, `FURTHER_VALIDATION=NOT_REQUIRED`. Historique
  d'audit conservé, aucun nouveau développement, ne bloque plus le projet.
- **FMC640/FMC650** : restent dans le scope (poids lourds) ; sources CAN/FMS/Tacho/Total Odo à
  déterminer runtime ; jamais d'AVL universelle. Actuellement **absents** des comptes Navixy.

Gate production (par tracker) : `MODEL (+ VEHICLE pour FMC003) + SOURCE VALIDÉE + FIELD_VALIDATED`.
Implémenté : `odometer_capability.py` (champs `strategy`/`availability`, `STATUS_DEPRECATED`,
`VehicleOdometerCapability`, `private_mode_allowed(model, vehicle_capability)`,
`vehicle_private_mode_allowed(...)`). Bouton Privé **désactivé** pour tous tant que non FIELD-VALIDATED.

Ordre des prochaines missions (aucune n'est lancée automatiquement) :
1. **FMC130 TOTAL ODOMETER AUDIT** (READ-ONLY) → puis D3 FMC130 single device.
2. **FMC003 OBD/CAN MILEAGE AUDIT** (par véhicule).
3. FMC640 / FMC650 : quand des devices réels existeront.
4. FMU130 : **NO FURTHER ACTION**.

## =============================================================================

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
