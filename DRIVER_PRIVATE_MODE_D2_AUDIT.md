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

## 3. MATRICE MULTI-MODÈLES (états stricts)

| Modèle | Private/Business | GPS masking | Total Odometer | AVL/Source | Odo pendant privé | État |
|---|---|---|---|---|---|---|
| **FMC003** | DOCUMENTED | DOCUMENTED | UNKNOWN | UNKNOWN (doc: GNSS/OBD) | UNKNOWN | NOT_TESTED |
| **FMC130** | DOCUMENTED | DOCUMENTED | UNKNOWN | UNKNOWN | UNKNOWN | NOT_TESTED |
| **FMU130** | UNKNOWN | UNKNOWN | UNKNOWN (interne) | Navixy=GPS_CALCULATED (RUNTIME) | UNKNOWN | **PILOT** |
| **FMC640** | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN (FMX6xx ≠ AVL16) | UNKNOWN | NOT_TESTED |
| **FMC650** | UNKNOWN | UNKNOWN | UNKNOWN | doc: AVL199 Trip / AVL216 Total / AVL192 Tacho (NON prouvé) | UNKNOWN | NOT_TESTED |

Légende preuve : `DOCUMENTED` (doc Teltonika, non prouvé), `RUNTIME_VERIFIED` (constaté via
Navixy API), `FIELD_VERIFIED` (prouvé sur device réel en Private Mode), `NOT_SUPPORTED`, `UNKNOWN`.

> ⚠️ **Aucune** cellule n'est `FIELD_VERIFIED`. Les AVL 199/216/192 (FMX6xx) sont **DOCUMENTED** au mieux.
> Ne JAMAIS imposer `AVL16` à FMC640/FMC650 (famille différente).

---

## 4. REGISTRE DE CAPACITÉS (implémenté, backend)
Fichier : `backend/app/odometer_capability.py` — `HardwareOdometerCapability` par modèle +
`resolve_model(navixy_code)` + `private_mode_allowed(model)` (gate prod).
- **Aucun** modèle `verified=True` (règle absolue respectée) ; tests `test_odometer_capability.py` **7/7**.
- Gate prod : `private_mode_allowed()` renvoie `False` pour TOUS les modèles → bouton Privé
  interdit en production tant qu'un modèle n'est pas FIELD-VALIDATED.
- Le backend résout la capacité **par modèle**, jamais `if teltonika: use_avl_16()`.

---

## 5. OPTIONS (basées sur le runtime FMU130 + doc pour les autres)

```
OPTION_A_TELTONIKA_TOTAL_ODOMETER: UNKNOWN
  - Non lisible via API Navixy. Nécessite: (a) lecture Configurator (Calculation Source + Odometer
    Value), (b) activation transmission Total Odometer (AVL) côté device, (c) exposition en
    sensor Navixy, (d) preuve terrain qu'il continue quand GPS transmis = 0,0.
OPTION_B_CAN_OBD: UNAVAILABLE (sur FMU130 pilote — aucun PID mileage). À réauditer par modèle.
OPTION_C_APPLICATION_PRIVACY: CANDIDAT DE REPLI
  - Ne pas masquer au niveau device (0,0) ; masquer la localisation UNIQUEMENT côté LOGITRAK
    (backend/app), et calculer la distance privée à partir d'une source non-GPS si disponible,
    sinon marquer DISTANCE UNAVAILABLE. Ne PAS choisir C tant que A/B ne sont pas éliminées par modèle.
```

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
D2 STATUS: NEEDS_DEVICE_READ
```
Raison : l'API Navixy ne permet pas de lire la config Private/Business ni le Total Odometer
interne. Sur le FMU130 pilote, **aucune** source odomètre hardware n'est exposée (seul un
compteur **GPS-calculé**). Pour statuer `READY_FOR_PILOT_CONFIG`, il faut une **lecture
Configurator** (par modèle) prouvant qu'un Total Odometer hardware existe/est activable et
continue quand le GPS transmis est masqué.

### GATE DE SORTIE (§22)
Non atteinte : on n'a PAS encore identifié de stratégie crédible « GPS masqué + odomètre
indépendant qui continue » sur le parc. (Le compteur GPS-calculé Navixy est **exclu** comme
source privée.)

### NEXT SAFE STEP
```
NEXT SAFE STEP: REASSESS PRIVACY ARCHITECTURE
```
Concrètement, dans l'ordre, SANS écriture device tant que non décidé :
1. Lecture Configurator FMU130 pilote → Total Odometer (Calc Source) + Private/Business config + firmware.
2. Si Total Odometer hardware activable & continue en privé → bascule vers `D3 SINGLE-DEVICE CONFIGURATION PILOT` (FMU130).
3. Répéter l'audit lecture par modèle (FMC003, FMC130, FMC640, FMC650) — chacun validé indépendamment.
4. Si aucun modèle n'offre d'odomètre indépendant du GPS → étudier `OPTION C` (privacy applicative).

**Ne PAS** démarrer D3 ni aucune écriture device automatiquement.
