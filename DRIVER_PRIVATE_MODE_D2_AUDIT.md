# DRIVER_PRIVATE_MODE_D2_AUDIT.md
## Phase D2 — Audit READ-ONLY Private/Business + Total Odometer (PARC MULTI-MODÈLES)

## ============================================================================
## DEEP-DUMP compte 234783 (2026-09-02) — 3467714 / 3467693 / 3467717 — READ-ONLY
## ============================================================================
> Via `scripts/d2_deep_dump_234783.py` : dump get_state + readings/list + get_counters
> + **sensor/list** ; recherche récursive 389/odometer/mileage/odo/distance.
> Compte 234783 = compte démo Teltonika/Navixy (51 FMC003 nommés par villes).

Découvertes :
1. **`avl_io_389` absent de TOUS les endpoints API** des 3 trackers → la capture UI `165000`
   ne se retrouve pas dans l'état live (origine à clarifier).
2. **`obd_mileage` (« OBD : Kilométrage OBD total », km)** = sensor **DÉFINI** dans Navixy
   (sensor/list) mais **SANS valeur** dans readings → **mappé mais VIDE** (AVL OEM mileage non transmis).
3. **`obd_custom_odometer`** présent mais **NON fiable** (Dakar 103.87 « V » @18:17 ; Gilan 119.23 @14/08 ;
   échelles incohérentes vs GPS odo → config custom bricolée, à ne pas valider).
4. **OBD ACTIF/récent** (VIN VW temps réel, rpm/speed/fuel frais) mais **aucun km véhicule fiable exposé**.

Statut : `avl_io_389 = SENSOR_DEFINED_BUT_EMPTY` ; `obd_custom_odometer = NON_FIABLE` ;
`OBD_bus = ACTIF` ; `km_vehicule_fiable = AUCUN`.

Voie D3-config (NON exécutée, écriture, sur GO) : activer `40000:1;40430:1` (+`113:1` OK) sur un
véhicule au PID OEM supporté (VW utilitaires) → vérifier que `obd_mileage` se peuple et incrémente.

Question ouverte : d'où venait la capture `avl_io_389 = 165000` (écran/tracker/date) ?



## ============================================================================
## ÉTAT GLOBAL DES DOSSIERS (2026-09-02) — audit API Navixy CLOS
## ============================================================================
```
FMC130 : API_AUDIT=CLOSED | CONFIGURATOR_CHECK=PENDING | D3=BLOCKED
         (can_mileage figé 2022 ; aucun Total Odometer exposé ; GPS Navixy exclu)
FMC003 : API_AUDIT=CLOSED | HARDWARE_ODOMETER_VIA_NAVIXY=NONE (0/14) | CONFIGURATOR_CHECK=PENDING
         (aucun mileage HW véhicule ; aucun Total Odometer exposé ; GPS Navixy exclu)
FMU130 : DEPRECATED — NO FURTHER ACTION
FMC640/FMC650 : NOT_PRESENT
```
**Étape décisive suivante = lecture Teltonika Configurator** (READ-ONLY), 3 pilotes A/B/C —
voir `DRIVER_PRIVATE_MODE_CONFIGURATOR_READ_SHEET.md`.

> **Nuance importante (ne pas conclure trop tôt) :** aucun véhicule du parc n'expose aujourd'hui à
> Navixy d'odomètre **hardware** indépendant du GPS. Cela **ne déclare PAS** le Private Mode
> globalement impossible. Deux issues après Configurator :
> - `READY_FOR_D3_CONFIG_PILOT` — Total Odometer activable **et** conservé quand la position transmise
>   est masquée (idéalement GNSS interne) → solution idéale (GPS masqué + km conservés) → D3 (GO explicite).
> - `NO_VALID_PRIVATE_ODOMETER_SOURCE` — pas de distance privée hardware fiable → **décision produit
>   LOGITRAK** (privacy applicative / km privé = UNAVAILABLE / autre source / bouton Privé désactivé).
>
> Le **pilote C** (FMC003 EV → Total Odometer **GNSS interne** indépendant du véhicule) est le test le
> plus déterminant : s'il est concluant, l'absence de PID OBD sur les EV (Zoe/Enyaq/EX30) **ne condamne
> pas** le mode privé. Bouton Privé **désactivé en prod** (`private_mode_allowed()=False`) tant qu'aucun
> pilote n'est FIELD-VALIDATED.

## ============================================================================

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


## ============================================================================
## RE-AUDIT OEM MILEAGE (AVL 389) (2026-09-02) — READ-ONLY, 25 trackers
## ============================================================================
> Via `scripts/d2_oem_mileage_reaudit.py` : recherche explicite de `avl_io_389`
> (OBD OEM Total Mileage, km) + tous `avl_io_*` odométriques, sur FMC003 + FMC130,
> tous tenants (Logitrak 10, Pradervand 15, Gaggetta 0 → **25 trackers**).

### Résultats
```
avl_io_389 PRESENT              = 0 / 25   (aucun tracker accessible n'expose l'OEM mileage)
FOCUS tracker 3467714           = INTROUVABLE dans les 3 tenants (Logitrak/Pradervand/Gaggetta)
Verdict FMC003 "0/14" precedent = CONFIRMÉ (le re-scan avl_io_* ne révèle aucun angle mort)
```

### Point capital : le tracker 3467714 n'est sur AUCUN de nos 3 comptes Navixy
La capture fournie montre `avl_io_389 = 165000` pour `3467714`, et son `.cfg` a **Codec 8
Extended activé** (param `113=1`) — donc il **peut** transmettre l'AVL 389 (>255). MAIS ce
tracker **n'existe pas** dans les tenants Logitrak / Pradervand / Gaggetta accessibles.
→ Il réside sur un **4ᵉ compte Navixy** (dealer / test / autre client) non configuré dans
le backend multi-tenant. C'est pourquoi le re-audit ne le voit pas.

### Interprétation (terminologie stricte)
- **OBD OEM Total Mileage (AVL 389)** = source **véhicule/OBD, indépendante du GNSS**. Réellement
  exposée **uniquement** sur `3467714` (hors périmètre) ; **0/25** sur le parc accessible.
- Seul autre candidat sur le parc = `can_mileage` du `781479` (figé 2022 → inexploitable).
- Absence d'AVL 389 sur les 25 : Codec 8 simple (781479 `113=0`), et/ou OBD OEM non activé,
  et/ou véhicule ne fournissant pas le PID OEM.

### Conséquences
1. Piste **OEM mileage prometteuse mais démontrée sur 1 seul device** (`3467714`, dernier FW/config,
   Codec 8 Extended) → **candidat pilote idéal**, sous réserve d'accès à son compte Navixy.
2. Parc accessible agrandi : **25 FMC003/FMC130** (nouveaux : 3076994, 3218550, 1067937/38/39,
   478998, 479006, 597288, 3466146, 3472998).
3. `TELTONIKA_TOTAL_ODOMETER (11806=0=GNSS interne)` reste la piste pour les véhicules **sans** OEM
   mileage — non exposé à Navixy aujourd'hui (activation I/O = écriture config).

### Questions ouvertes
- Sur **quel compte Navixy** se trouve `3467714` ? Ajouter un **4ᵉ tenant/credential** ?
- Fraîcheur réelle de `avl_io_389 = 165000` (timestamp) ?


## ============================================================================
## FMC003 OBD/CAN MILEAGE AUDIT (2026-09-02) — READ-ONLY, par véhicule
## ============================================================================
> Runtime réel via `scripts/d2_fmc003_mileage_audit.py` (multi-tenant, READ-ONLY).
> 3 tenants scannés : **Logitrak (4 FMC003)**, **Pradervand (10 FMC003)**, **Gaggetta (0)**.
> Secrets/GPS masqués. Aucune écriture. FMC130 non touché.

### Verdict dossier
```
FMC003_HARDWARE_ODOMETER_VIA_NAVIXY = NONE  (0 / 14 véhicules)
FMC003_ALL_VEHICLES_STATUS          = NO_HARDWARE_ODOMETER  (14 / 14)
```

**Aucun** des 14 FMC003 n'expose à Navixy : ni `can_mileage`/`obd_mileage`/`vehicle_distance`/
`total_distance`/`total_mileage`, ni un **Total Odometer Teltonika** (`TELTONIKA_TOTAL_ODOMETER_
EXPOSED = NO` partout). Seul l'odomètre **GPS-calculé Navixy** est vivant → **exclu** par règle.

### Détail (14 véhicules)
| Tracker | Véhicule | OBD/CAN inputs | Mileage HW | Total Odo | GPS odo Navixy (exclu) | Statut |
|---|---|---|---|---|---|---|
| 3079431 | KAIO Renault Zoe | YES | NONE | NO | 7210 @ 2025-07-25 | NO_HARDWARE_ODOMETER |
| 3131157 | 5-Alliance 01 | YES | NONE | NO | 242979 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 3218549 | 1-Enyaq 01 Bern | YES | NONE | NO | 348 @ 2024-12-09 | NO_HARDWARE_ODOMETER |
| 3218553 | KAIO Volvo EX30 08 | NO | NONE | NO | 0.0 @ 2024-11-20 | NO_HARDWARE_ODOMETER |
| 478988 | 9-GE 643 258 | NO | NONE | NO | 232778 @ 2026-09-01 | NO_HARDWARE_ODOMETER |
| 478990 | 8-GE 894 929 | NO | NONE | NO | 142017 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 478994 | 7-GE 780467 | NO | NONE | NO | 190687 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 479003 | 4-GE 808 478 | YES | NONE | NO | 152344 @ 2026-08-28 | NO_HARDWARE_ODOMETER |
| 479009 | 2-GE 752 796 | YES | NONE | NO | 81886 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 479012 | 1-GE 433 787 | NO | NONE | NO | 64273 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 596853 | 5-GE 411 639 | NO | NONE | NO | 76260 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 3461150 | 11-GE 854 325 | NO | NONE | NO | 19921 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 3466130 | 12-GE498 143 | NO | NONE | NO | 29309 @ 2026-09-02 | NO_HARDWARE_ODOMETER |
| 3612095 | 15-GE 347 347 | YES | NONE | NO | 2599 @ 2026-09-02 | NO_HARDWARE_ODOMETER |

### Observations
- **Règle confirmée** : la présence d'inputs OBD (rpm/speed/fuel) sur 6 véhicules (`YES`) **ne fournit
  aucun kilométrage** — aucun n'a de PID mileage. « OBD présent » ≠ « kilométrage disponible ».
- Plusieurs véhicules sont **électriques** (Zoe, Enyaq, Volvo EX30, Alliance) : le PID kilométrage OBD
  y est souvent absent/non standard → cohérent avec l'absence totale de mileage CAN/OBD.
- Cas GPS odo figés / faibles : `3218553` (0.0, 2024-11), `3218549` (348, 2024-12), `3079431`
  (2025-07) → peu/pas de roulage récent sous Navixy ; sans incidence sur le verdict.

### Nuance de méthode (honnêteté)
`OBD_CAN_PRESENT` reflète les inputs OBD/CAN présents dans `readings/list` à l'instant T. Un véhicule
`NO` pourrait avoir des données OBD **figées** non présentes dans les readings courants (comme le CAN
2022 du FMC130). Cela **ne change pas** le verdict : même figées, ces valeurs ne contiennent aucun
kilométrage et ne seraient pas « vivantes » → non admissibles.

### Conséquence & options (comme FMC130)
Pour ces 14 FMC003, **aucune source de distance privée admissible via Navixy** aujourd'hui. Bifurcation :
- **(A) Lecture Teltonika Configurator** (par véhicule, lecture seule) : un Total Odometer est-il
  activable et sur quelle source (GNSS/OBD) ? Pour les EV sans PID mileage, la voie OBD restera
  probablement vide → Total Odometer serait alors GNSS (même problématique privé que FMC130).
- **(C) Fallback privacy applicative** LOGITRAK : `private_distance = UNAVAILABLE` si aucune source
  non-GPS. Ne jamais masquer au niveau device pour ces modèles sans nouvelle analyse.

## ============================================================================
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
