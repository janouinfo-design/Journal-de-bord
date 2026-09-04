# DRIVER_PRIVATE_MODE_D3B_FMC003_3657864.md
## D3-B — FMC003 Private Mode Field Pilot — tracker 3657864 (Audi)
### PRÉPARATION GATED — RESULT = NOT_EXECUTED — aucune bascule sans GO explicite

## ============================================================================
## NUANCE (2026-09-04) — diagnostic "masquage KO" était NON CONCLUANT
## ============================================================================
Erreur de méthode (due au faux positif gps_masked) : on a surtout envoyé `privatemode OFF`
sur un device DÉJÀ en Business -> aucun changement attendu (normal). On n'a JAMAIS fait le test
propre : `privatemode ON` PUIS vérification du masquage avec le script CORRIGÉ (lecture
`state.gps.location`). Donc « masquage ne fonctionne pas » = **NON PROUVÉ / à refaire**.

Doc Teltonika (confirmée) : avec `Trigger Type = External (11849=0)` — NOTRE config — la commande
`privatemode ON/OFF` DOIT fonctionner (c'est `Weekly Schedule` qui la bloquerait). Casse OK.
=> La config actuelle permet A PRIORI le pilotage par COMMANDE. Rien à changer avant d'avoir
refait le test ON proprement.

État de départ propre disponible : Business + GPS visible (location=46.54/6.59 réelle) ✅.

TEST PROPRE À FAIRE (sur GO, en roulant) :
1. snapshot (script corrigé) -> confirmer GPS_MASKED=False (Business).
2. privatemode ON.
3. attendre ~1-2 min -> snapshot -> GPS_MASKED devient-il True (location 0,0) ?
   - OUI -> masquage OK -> rouler -> AVL16 continue -> privatemode OFF -> GPS revient. PASS.
   - NON -> LÀ seulement, investiguer config/mécanisme (device attend peut-être un input malgré
     External, ou param complémentaire).


## ============================================================================
## DIAGNOSTIC MASQUAGE (2026-09-04) — le mode Privé NE S'ACTIVE PAS via privatemode
## ============================================================================
Preuve directe (get_state.state.gps.location, vraie position transmise) :
```
location = { lat: 46.5452033, lng: 6.58915 }   signal_level=100   (coords RÉELLES)
```
=> GPS **JAMAIS masqué** malgré plusieurs `privatemode ON/OFF` (tous `success:True` côté Navixy).
Correctif script : le masquage se lit sur `state.gps.location.{lat,lng}` (PAS gps.lat/lng, PAS
track/read qui renvoie 0 point). Vérifié : 46.54/6.59 -> GPS_MASKED=False ; 0,0 -> True.

CONCLUSION :
```
AVL16 (distance)          = OK, fiable, incrémente
Canal Navixy raw_command  = accepte privatemode ON/OFF (success:True)
MASQUAGE GPS via privatemode = NE FONCTIONNE PAS sur ce device/config (position reste réelle)
=> le mode Privé Teltonika ne bascule PAS via la commande GPRS privatemode ici.
```
HYPOTHÈSE PRINCIPALE : `Trigger Type = External` (11849=0) => le changement de mode est piloté par
une SOURCE EXTERNE (entrée physique / digital input), et NON par la commande `privatemode`.
La commande est acceptée par Navixy mais ignorée/inopérante par le device dans cette config.

PISTES À VÉRIFIER (aucune exécutée) :
1. Réponse RÉELLE du device à `privatemode ?` (canal commande asynchrone — peut renvoyer une erreur).
2. Sur Teltonika, quelle SOURCE le "Trigger External" attend-il exactement (DIN ? autre) ?
3. Alternative si on veut piloter par COMMANDE : est-il possible de configurer un trigger
   software/commande au lieu d'un input physique (changement de config device -> décision opérateur).

STATUT : D3-B masquage = FAIL/UNPROVEN ; field_validated=FALSE ; PRIVATE_MODE_PRODUCTION=DISABLED.


> 📌 REPRISE : test terrain reporté à **demain** (2026-09-04). Tout est prêt (`D3B_READY = YES`).
> Il ne reste qu'à exécuter la séquence terrain sur GO explicite. Voir « PLAN D'EXÉCUTION DEMAIN » ci-dessous.

## ============================================================================
## ⚠️ RÉTRACTATION (2026-09-04) — FAUX POSITIF gps_masked DANS d3b_snapshot.py
## ============================================================================
> BUG confirmé + corrigé : l'ancien `_gps_masked` lisait `state.gps.lat/lng` (INEXISTANTS dans
> `tracker/get_state` -> toujours None -> toujours "masqué"). L'opérateur confirme : le GPS n'a
> JAMAIS été masqué pendant le test. Fix : masquage jugé via `track/read` (vraies coords).
> Vérifié testing_agent : 4/4 PASS.

**Les conclusions "GPS masqué" du bloc D3-B EXÉCUTÉ ci-dessous sont INVALIDES et rétractées.**
Ce qui RESTE valide :
```
✅ AVL16 incrémente en roulant (+1.58 km 09:27->09:28) — source distance fonctionne
✅ Navixy raw_command/send accepte privatemode ON/OFF/? (success:True) — canal remote OK
```
Ce qui est NON prouvé (et croyait à tort prouvé) :
```
❌ PRIVATE_GPS_MASKING  = NON PROUVÉ (jamais masqué réellement)
❌ privatemode bascule réellement CE device = NON PROUVÉ (device probablement jamais entré en Privé)
   -> hypothèse : Trigger=External(11849=0) attend peut-être un déclencheur physique/entrée,
      OU le device n'exécute pas la commande privatemode dans cette config -> À INVESTIGUER.
```
Statut D3-B réel :
```
AVL16_PRIVATE_INCREMENT   = NON CONCLUANT (increment observé mais PAS en état masqué prouvé)
PRIVATE_GPS_MASKING       = FAIL/UNPROVEN
D3B_RESULT                = INVALIDÉ (à refaire avec le script corrigé + masquage réel prouvé)
field_validated           = FALSE   (inchangé)
PRIVATE_MODE_PRODUCTION   = DISABLED
```

## ============================================================================

> Sur GO explicite opérateur. Bascule via Navixy raw_command (`privatemode`), option (a) terminal.
> Compte 121349, tracker 3657864 (Audi). Mesures via d3b_snapshot.py (READ-ONLY).

Snapshots pendant roulage réel EN MODE PRIVÉ (GPS masqué) :
```
private_start : online=True  gps_masked=True(0,0)  AVL16=140310.36 km @ 09:27:03
private_end   : online=True  gps_masked=True(0,0)  AVL16=140311.94 km @ 09:28:33  (véhicule à 49 km/h)
PRIVATE_DISTANCE_KM = 140311.94 - 140310.36 = +1.58 km   (INCREMENT OK, Y>X)
```
**Triple preuve simultanée (exigence produit) :**
```
GPS_COORDINATES = MASKED               (lat/lng = None/0,0 même en roulant)
TRACKER = ONLINE                       (connection=active, données fraîches)
PRIVATE_DISTANCE = CONTINUES_TO_INCREMENT  (+1.58 km via AVL16, sans aucune coordonnée GPS)
```
Distance privée calculée EXCLUSIVEMENT via AVL16 (Total Odometer). GPS Navixy odo = REFERENCE,
non utilisé (140310.37, EXCLU).

Critères D3-B (§G) :
```
PRIVATE_GPS_MASKING       = PASS  (0,0 en roulant)
TRACKER_ONLINE_PRIVATE    = PASS
AVL16_AVAILABLE_PRIVATE   = PASS  (timestamps s'actualisent)
AVL16_PRIVATE_INCREMENT   = PASS  (+1.58 km)
PRIVATE_DISTANCE_COMPUTABLE = PASS
```
RESTE à confirmer pour clôturer le PASS complet :
```
BUSINESS_RESTORE          = PENDING  (privatemode OFF envoyé, GPS pas encore revenu -> à confirmer)
BUSINESS_GPS_NORMAL       = PENDING
```
> Tant que le retour Professionnel (GPS normal restauré) n'est pas CONFIRMÉ par relecture,
> field_validated reste FALSE (protocole §17 rollback : ne jamais déclarer BUSINESS sans preuve).

Mécanisme remote confirmé : Navixy `tracker/raw_command/send` accepte `privatemode ON/OFF/?`
(success:True). ⚠️ ACK Navixy ≠ application device (la bascule s'applique via la file reliable).

## ============================================================================



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

### Bloc PRECHECK  — ✅ MIS À JOUR (2026-09-03 13:40) : config corrigée, D3B_READY = YES
```
TRACKER_ID = 3657864   MODEL = FMC003   (FW 04.02 ; Odometer 11807=140267 ≈ 140268 dashboard ✅)

DEVICE_PRIVATE_CONFIG_CONFIRMED = YES  (.cfg 3657864 re-exporté ; tous params conformes)
ODOMETER_SOURCE_GNSS            = YES        (11806=0)
GPS_DATA_MASKING_ZERO           = YES ✅     (11813=1 = Data Sent As Zero)  [CORRIGÉ 0->1]
PRIVATE_ODOMETER_CALCULATION    = ENABLED    (11815=1 -> distance privée incluse dans AVL16) ✅
TRIGGER_TYPE                    = EXTERNAL   (11849=0) ✅
TOTAL_ODOMETER_IO               = ACTIVE     (avl_io_16 transmis, prouvé runtime) ✅
CODEC                           = Codec 8 (113=0) — suffisant pour AVL16 ✅

REMOTE_PRIVATE_COMMAND_SUPPORTED  = YES   (Navixy raw_command/send "privatemode ON")
REMOTE_BUSINESS_COMMAND_SUPPORTED = YES   ("privatemode OFF")
BTAPP_REQUIRED                    = NO
AVL16_RUNTIME                     = PASS

D3B_READY = YES
D3B_BLOCKING_REASON = (aucun) — config conforme ; attente GO explicite opérateur
D3B_EXECUTION = NOT_STARTED
PRIVATE_MODE_PRODUCTION = DISABLED
NEXT_ACTION = WAIT_FOR_EXPLICIT_GO_D3B  (GO D3-B FMC003 3657864)
ROLLBACK_READY = YES  (privatemode OFF via raw_command/send ; si retour Business non confirmé -> FAILED/UNKNOWN)
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
