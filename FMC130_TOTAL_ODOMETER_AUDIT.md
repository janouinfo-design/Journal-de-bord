# FMC130_TOTAL_ODOMETER_AUDIT.md
## Dernière validation READ-ONLY avant D3 — FMC130 tracker 781479 (LOGITRAK AUDI)

> **Suite de** `678576e`. **READ-ONLY strict** : aucun `setparam`, `privatemode`,
> `raw_command/send`, `getparam`, `counter/update`, `counter/value/set`, aucune écriture.
> **D3 NE COMMENCE PAS ici.** Objectif unique : le FMC130 peut-il fournir son **Total
> Odometer INTERNE** à LOGITRAK, indépendamment du compteur GPS-calculé Navixy ?

---

## 3 DONNÉES STRICTEMENT SÉPARÉES
- **A — NAVIXY PLATFORM ODOMETER** : compteur Navixy, source = **GPS_CALCULATED** (fait acquis).
  Utile pour les trajets PRO, **jamais** admissible comme distance privée, **jamais** fallback silencieux.
- **B — TELTONIKA TOTAL ODOMETER** : compteur INTERNE du device (recherché ici).
- **C — can_mileage** : km CAN déjà observé (donnée périmée 2022) → **SECONDARY_VALIDATION_SOURCE** uniquement.

---

## RÉSULTAT (à compléter avec la sortie runtime `fmc130_odo.py`)
```
PILOT_TRACKER:                            781479
DEVICE_MODEL:                             FMC130 (telfmu130_fmc130)
FIRMWARE:                                 <runtime ou CONFIGURATOR_READ_REQUIRED>

NAVIXY_GPS_ODOMETER:                      <value> km @ <ts>
NAVIXY_GPS_ODOMETER_SOURCE:               GPS_CALCULATED  (acquis)

CAN_MILEAGE:                              80078.5 (observé) — PÉRIMÉ 2022-03-26
CAN_MILEAGE_UNIT:                         km
CAN_MILEAGE_CLASSIFICATION:               SECONDARY_VALIDATION_SOURCE (donnée morte, non primaire)

TELTONIKA_TOTAL_ODOMETER:                 <REAL value | NOT_CURRENTLY_EXPOSED>
TELTONIKA_ODOMETER_CALCULATION_SOURCE:    <GNSS | OBD | UNKNOWN | NOT_READABLE(Configurator)>
TELTONIKA_TOTAL_ODOMETER_IO_ENABLED:      <YES | NO | UNKNOWN>
TELTONIKA_TOTAL_ODOMETER_VALUE:           <REAL | null>
TELTONIKA_TOTAL_ODOMETER_AVL_ID:          <verified id | UNKNOWN>   (ne PAS forcer AVL16)
TELTONIKA_TOTAL_ODOMETER_NAVIXY_INPUT:    <input_name | none>
TELTONIKA_TOTAL_ODOMETER_SENSOR_ID:       <id | null>

TELTONIKA_ODO_BEFORE:                     <X | NOT_TESTED>
TELTONIKA_ODO_AFTER:                      <Y | NOT_TESTED>
TELTONIKA_ODO_DELTA:                      <Y-X | NOT_TESTED>
TELTONIKA_ODOMETER_INCREMENT:             <PASS | PENDING_REAL_DRIVE | NOT_TESTED>

CONFIGURATOR_READ_REQUIRED:               <YES | NO>
PRIVATE_BUSINESS_ENABLED:                 <valeur | NOT_READABLE (Configurator)>
GPS_DATA_MASKING:                         <valeur | NOT_READABLE>
ODOMETER_CALCULATION:                     <valeur | NOT_READABLE>
TRIGGER_TYPE:                             <valeur | NOT_READABLE>

FMC130_TOTAL_ODOMETER_STATUS:             <VALIDATED | NOT_CURRENTLY_EXPOSED | CONFIG_CHANGE_REQUIRED | PENDING_REAL_DRIVE | INCONCLUSIVE>
NEXT_SAFE_STEP:                           <READY_FOR_D3 | READY_FOR_D3_CONFIG_PILOT | DECISION_REQUISE (CAN secours vs poursuivre) >
```

---

## SI TOTAL ODOMETER NON TROUVÉ DANS NAVIXY (à ne PAS confondre avec "non supporté")
Conclure `NOT_CURRENTLY_EXPOSED` (pas `NOT_SUPPORTED`). Puis :
```
DEVICE_SUPPORT_DOCUMENTED: YES  (doc Teltonika FMC130 : section Odometer + Total Odometer AVL)
CONFIG_CHANGE_REQUIRED:    probable YES — à confirmer Configurator
```
Config à RELEVER (lecture seule Configurator, aucune écriture) :
- `Trip/Odometer > Odometer` : **Calculation Source** (GNSS/OBD) + **Odometer Value**
- **I/O** : *Total Odometer* enabled ? priority / operand / event generation
- **Private/Business** : `GPS Data Masking`, `Odometer calculation`, `Trigger Type`
- **Firmware version**
> Ce qui serait nécessaire pour exposer le Total Odometer à Navixy : activer l'I/O *Total
> Odometer* (priorité High/Low + event) dans le profil du device → il remontera en AVL →
> exposable en sensor Navixy. **NE PAS l'appliquer dans cette mission.**

---

## DISTINCTIONS CRITIQUES (ne pas conclure à tort)
- `GPS Data Masking = Zero` ≠ `GNSS receiver OFF`. La continuité du Total Odometer quand le
  GPS transmis est masqué sera **prouvée seulement en D3** (pas ici).
- `OBD available` ≠ `odometer available` (FMC003 comme FMC130).

## D3 : NON DÉMARRÉ
Aucune écriture device. Bouton Privé prod reste désactivé (gate par modèle/véhicule).
