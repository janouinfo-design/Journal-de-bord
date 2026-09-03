# DRIVER_PRIVATE_MODE_D3B_FMC003_3657864.md
## D3-B — FMC003 Private Mode Field Pilot — tracker 3657864 (Audi)
### PRÉPARATION GATED — RESULT = NOT_EXECUTED — aucune bascule sans GO explicite

## ============================================================================
## FINAL PRECHECK (2026-09-03) — mécanisme remote + verrouillage config
## ============================================================================

### Mécanisme de bascule remote (documenté — sources Teltonika wiki + Navixy dev docs)
```
D3B_TRIGGER_METHOD       = NAVIXY_REMOTE_PRIVATE_MODE
TELTONIKA_TRIGGER_TYPE   = EXTERNAL (obligatoire ; Weekly Schedule -> commande REJETÉE)
BTAPP_PRODUCT_PATH       = NO
Commande PRIVATE  : "privatemode ON"   (casse stricte : privatemode minuscule, ON majuscule)
Commande BUSINESS : "privatemode OFF"
Vérif d'état       : "privatemode ?"
Voie d'envoi       : Navixy tracker/raw_command/send (reliable=true) — déjà câblé côté LOGITRAK
                     via app.navixy_client.send_raw_command(tracker_id, command, reliable=True).
```
⚠️ **NE PAS confondre avec Deep Sleep** `setparam 11000:4` (utilisé par `privacy_enforcer.py`
historique) : ce n'est PAS le Private Mode chauffeur. Deep Sleep couperait le GSM (tracker
injoignable) → INTERDIT pour D3-B. La Phase 2 produit devra utiliser `privatemode`, pas 11000:4.

### Chaîne produit cible (validée conceptuellement)
```
Driver App -> LOGITRAK Backend -> Navixy raw_command/send("privatemode ON/OFF")
           -> Teltonika (Trigger=External) -> Private/Business Mode
```

### Bloc PRECHECK
```
TRACKER_ID = 3657864   MODEL = FMC003   (FW 04.02 ; Odometer Value 11807=140267 ≈ 140268 dashboard ✅)

DEVICE_PRIVATE_CONFIG_CONFIRMED = PARTIAL (config .cfg 3657864 analysée ; 1 param à corriger)
ODOMETER_SOURCE_GNSS            = YES        (11806=0)
GPS_DATA_MASKING_ZERO           = NO  ❌     (11813=0 = Normal ; REQUIS 11813=1 = Data Sent As Zero)
PRIVATE_ODOMETER_CALCULATION    = ENABLED    (11815=1 -> distance privée incluse dans AVL16) ✅
TRIGGER_TYPE                    = EXTERNAL   (11849=0) ✅
TOTAL_ODOMETER_IO               = ACTIVE     (avl_io_16 transmis, prouvé runtime) ✅
CODEC                           = Codec 8 (113=0) — suffisant pour AVL16 (ID<=255) ✅

REMOTE_PRIVATE_COMMAND_SUPPORTED  = YES  (Navixy raw_command/send "privatemode ON", Trigger=External OK)
REMOTE_BUSINESS_COMMAND_SUPPORTED = YES  ("privatemode OFF")
BTAPP_REQUIRED                    = NO
AVL16_RUNTIME                     = PASS

D3B_READY = NO
D3B_BLOCKING_REASON = GPS Data Masking = Normal (param 11813=0). En mode privé, les coordonnées
   ne seraient PAS masquées. SEULE correction manquante -> passer 11813 = 1 (Data Sent As Zero).
   Tous les autres paramètres sont conformes.

D3B_EXECUTION = NOT_STARTED
PRIVATE_MODE_PRODUCTION = DISABLED
NEXT_ACTION = corriger 11813:1 sur 3657864 (opérateur) -> re-vérifier -> WAIT_FOR_EXPLICIT_GO_D3B
ROLLBACK_READY = YES
```

### CHANGE_REQUIRED (à faire par l'opérateur — l'audit N'exécute PAS)
```
TRACKER          = 3657864 (FMC003, compte 121349)
ACTION           = régler GPS Data Masking -> "Data Sent As Zero"  (param 11813 : 0 -> 1)
                   via Teltonika Configurator (Save to device) OU FOTA/Navixy setparam 11813:1
RAISON           = sans masquage, le mode privé transmettrait les vraies coordonnées (viole
                   l'exigence "GPS privé masqué"). Les autres params (Trigger External, Odometer
                   Calculation Enable, GNSS) sont déjà corrects.
ÉTAT ACTUEL      = 11813=0 (Normal)
RÉSULTAT ATTENDU = 11813=1 ; en privé, coordonnées envoyées à 0,0, tracker online, AVL16 continue
RISQUE           = faible (paramètre de confidentialité ; réversible)
ROLLBACK         = remettre 11813=0 (Normal) si besoin
```
> NB : cette écriture de config est décidée/exécutée par l'opérateur. L'audit ne la lance pas.
> Après correction : ré-exporter le .cfg pour confirmer 11813=1, puis D3B_READY pourra passer à YES.



### Précheck runtime READ-ONLY (à exécuter par l'opérateur avec d3b_snapshot.py before)
Confirmer avant tout GO : TRACKER_ONLINE, AVL16_PRESENT/RECENT/VALUE_KM/TIMESTAMP,
GPS_CURRENTLY_NORMAL, IGNITION, MOVING, NAVIXY_PLATFORM_ODOMETER (REFERENCE_ONLY).



> ⛔ Cette mission est **PRÉPARATION UNIQUEMENT**. Aucune commande device, aucun `privatemode`,
> aucun `setparam`, aucun `raw_command`, aucune écriture Navixy. L'exécution réelle attend le
> **GO D3-B FMC003 3657864** explicite de l'opérateur.

---

## A. SCOPE
- **UN seul pilote** : `TRACKER_ID = 3657864`, `MODEL = FMC003`, véhicule Audi.
- Objectif unique : prouver que le **Teltonika Total Odometer (AVL 16)** continue d'augmenter
  quand **Private/Business Mode = ACTIVE** ET **GPS Data Masking = Data Sent As Zero**.
- **NE PAS** inclure FMC130 (D3 séparé). Un PASS FMC003 ne vaut pas PASS FMC130.
- Un PASS ne concerne QUE ce tracker + son firmware/config (pas « tous les FMC003 »).

## B. PREUVES EXISTANTES AVL 16 (runtime, déjà validé)
```
AVL16_API_MAPPING = VERIFIED   (sensor 'ODO TOTAL' id 5570680, input avl_io_16, mult=1, div=1000, km)
AVL16_CUMULATIVE  = VERIFIED   (+5.3 km observé en roulage réel)
AVL16_SCALE       = VERIFIED   (140264.62 km ≈ 140268 tableau de bord Audi ; écart = roulage 14:53->15:00)
runtime_verified=TRUE  cumulative_verified=TRUE  private_increment_verified=FALSE  field_validated=FALSE
```
Source privée = **AVL 16** (PRIMARY). AVL 389 = SECONDARY_OPTIONAL (comparaison seulement, ne
modifie pas le verdict).

## C. CONFIGURATION DEVICE REQUISE (à CONFIRMER avant D3-B, ne rien modifier)
```
Odometer : Calculation Source = GNSS
Private/Business : GPS Data Masking = Data Sent As Zero ; Odometer Calculation = Enable ;
                   Trigger Type = External
I/O : Total Odometer = Low / Monitoring
```
Si non confirmé sur 3657864 -> **STOP, D3B_READY = NO**. (Ne PAS confondre avec Deep Sleep 11000:4,
INTERDIT ici : le tracker doit rester joignable.)

## D. PRÉCHECKS (READ-ONLY) — tous requis, sinon D3B_PRECHECK = FAIL, STOP
```
tracker online = YES
AVL16 présent = YES        AVL16 récent = YES        AVL16 API readable = YES
scale verified = YES       cumulative verified = YES
mode actuel = BUSINESS (ou état explicitement déterminé)
GPS normal avant test = YES
```

## E. PROCÉDURE TERRAIN (exécution FUTURE, sur GO explicite uniquement)
```
1. SNAPSHOT BEFORE_PRIVATE            (script READ-ONLY)
2. Passage BUSINESS -> PRIVATE_REQUESTED -> PRIVATE   [ACTION GATED — mécanisme Teltonika/Navixy
   validé pour ce firmware/config ; NE PAS supposer ; JAMAIS Deep Sleep]
3. SNAPSHOT PRIVATE_START            -> confirmer PRIVATE + tracker ONLINE + GPS masqué (0,0)
4. ROULAGE réel ~2 à 5 km
5. SNAPSHOT PRIVATE_DRIVING (>=1)    -> AVL16 timestamp s'actualise + valeur augmente
6. SNAPSHOT PRIVATE_END              -> AVL16_END = Y
7. Retour PRIVATE -> BUSINESS_REQUESTED -> BUSINESS   [ACTION GATED]
8. SNAPSHOT BUSINESS_RESTORED        -> GPS normal restauré + AVL16 dispo
private_distance_km = AVL16_END_KM - AVL16_START_KM   (JAMAIS via GPS/trip.length/Navixy odo)
```

## F. DONNÉES À CAPTURER (par snapshot)
```
TIMESTAMP, TRACKER_ONLINE, CURRENT_MODE, GPS_LAT/LON (technique seulement, NON persisté en privé),
GPS_TIMESTAMP, GPS_MASKED (0,0 ?), AVL16_RAW, AVL16_KM, AVL16_TIMESTAMP,
NAVIXY_PLATFORM_ODOMETER (référence, EXCLU du calcul privé), IGNITION, MOVING
```

## G. CRITÈRES PASS/FAIL (D3-B PASS uniquement si TOUS)
```
1  modèle = FMC003 confirmé
2  tracker online avant test
3  AVL16 disponible avant test
4  GPS normal avant test
5  passage Private réellement confirmé (pas seulement HTTP 200 / commande acceptée)
6  coordonnées transmises réellement masquées (preuve = données reçues par Navixy)
7  tracker reste online en Private
8  AVL16 reste disponible en Private (timestamp s'actualise)
9  AVL16 augmente pendant roulage Private (Y > X)
10 distance privée calculable
11 retour Business confirmé
12 GPS normal restauré
13 aucune position privée exploitable exposée dans LOGITRAK
-> private_increment_verified = TRUE ; field_validated = TRUE (CE pilote uniquement)
```
Résolution compteur : si distance trop faible / arrondi / MAJ tardive ->
`PRIVATE_INCREMENT = INCONCLUSIVE` + recommander un roulage plus long (NE PAS déclarer FAIL).

## H. ROLLBACK
```
Nominal : Private -> BUSINESS_REQUESTED -> BUSINESS confirmé -> GPS normal.
Erreur  : si retour Business NON confirmé -> state = FAILED ou UNKNOWN (JAMAIS BUSINESS silencieux).
          Afficher un état technique honnête au chauffeur + procédure de récupération manuelle.
Jamais laisser croire "Professionnel" si le backend ne peut pas le confirmer.
```

## I. PRIVACY (trajet PRIVATE dans LOGITRAK)
```
NON conservé : latitude, longitude, adresse, polyline, route, replay, breadcrumb, GPS reconstruit.
Conservé     : driver_id, vehicle_id, private_start_time, private_end_time, odometer_start,
               odometer_end, private_distance_km, odometer_source, mode_status, validation metadata.
```

## J. PRODUCTION GATE
Même si D3-B PASS : `PRIVATE_MODE_PRODUCTION = DISABLED` jusqu'à décision explicite de rollout
séparée. Ne PAS basculer `private_mode_production_allowed = TRUE` automatiquement.

## K. RÉSULTAT
```
RESULT = NOT_EXECUTED
D3B_PROTOCOL = READY (sous réserve de confirmer la config device §C sur 3657864)
D3B_EXECUTION = NOT_STARTED
NEXT_ACTION = WAIT_FOR_EXPLICIT_GO_D3B
```

## State machine (rappel) & terminologie
`BUSINESS | PRIVATE_REQUESTED | PRIVATE | BUSINESS_REQUESTED | FAILED | UNKNOWN`.
UI : BUSINESS = Professionnel ; PRIVATE = Privé. Backend autoritaire, aucun état optimiste.

## Garde-fous
NO privatemode / setparam / raw_command / config write / sensor Navixy / bulk / prod / FMC130.
Toute action réelle => STOP + `EXPLICIT_GO_REQUIRED`.
