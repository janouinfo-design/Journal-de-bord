# DRIVER_PRIVATE_MODE_D3_FMC130_AVL16.md
## D3 FMC130 — Private Mode Field Test (stratégie V2 AVL16) — PRÉPARATION UNIQUEMENT

> **Statut : PROTOCOLE PRÊT — NON EXÉCUTÉ.** Préparation uniquement. Aucune
> commande device, aucun `privatemode ON/OFF`, aucun `setparam`, aucun
> `raw_command`, aucune modification Navixy, aucun rollout production.
>
> ```
> PRIVATE_MODE_GLOBAL   = DISABLED
> REAL_DEVICE_COMMANDS  = MOCK / SIMULATION
> D3_FMC130_EXECUTION   = NOT_STARTED
> NEXT_ACTION           = WAIT_FOR_EXPLICIT_GO_D3_FMC130 (dans l'environnement réel)
> ```

---

## RÉSULTATS DE PRÉCHECK (terrain réel — VPS journal_backend, 2026-09-04)

Précheck exécuté via `scripts/d3_fmc130_snapshot.py precheck` (READ-ONLY, resolver
multi-tenant, aucun credential affiché, aucune commande device).

```text
FMC003_3657864_D3           = PASS / FIELD_VALIDATED (déjà validé ; re-confirmé)
FMC130_781479_D3_PRECHECK   = BLOCKED_OFFLINE
FMC130_781479_D3_EXECUTION  = NOT_STARTED
```

### FMC003 `3657864` — PRÉCHECK = PASS (re-confirmation)
```text
MODEL = telfmb003_fmc003            TENANT_ID = default     CRED_SOURCE = TENANT
TRACKER_ONLINE = True               GPS_NORMAL = True (coords réelles récentes)
AVL16_PRESENT = True                AVL16_RAW_VALUE = 140289.52 km
AVL16_TIMESTAMP = 2026-09-04 16:52:33   AVL16_RECENT = True   AVL16_API_READABLE = True
SENSOR_DEFINED = True   SENSOR_ID = 5570680   SENSOR_INPUT = avl_io_16
SENSOR_MULTIPLIER = 1.0   SENSOR_DIVIDER = 1000.0   SENSOR_UNIT = kilometre
AVL16_SCALE_VERIFIED = True         FMC130_D3_PRECHECK = PASS
```
→ Mapping V2 confirmé terrain : `avl_io_16 · mult=1 · div=1000 · unit=km`.

### FMC130 `781479` — PRÉCHECK = BLOCKED (device offline)
```text
MODEL = telfmu130_fmc130            TENANT_ID = default     CRED_SOURCE = TENANT
TRACKER_ONLINE = False (connection_status="offline", ignition=false, movement=stopped)
AVL16_PRESENT = False   SENSOR_DEFINED = False   AVL16_SCALE_VERIFIED = False
FMC130_D3_PRECHECK = BLOCKED
BLOCKING_REASON = TRACKER_OFFLINE (→ AVL16 non lisible en direct)
```
Note : device sain (batterie 100%, GSM Swisscom, dernière position 46.545/6.589),
simplement en veille moteur coupé. Le blocage = état terrain, pas un défaut.

### Ordre des prochaines actions (décidé avec l'opérateur)
```text
1. (fait) Consigner ces résultats — READ-ONLY.
2. Relancer le précheck FMC130 781479 UNIQUEMENT quand le tracker sera ONLINE
   (véhicule démarré, ~2 min de remontée GSM) :
       docker exec -e TID=781479 -e PYTHONPATH=/app -w /app \
         journal_backend python3 scripts/d3_fmc130_snapshot.py precheck
   Si SENSOR_DEFINED=False alors que device online -> créer le sensor AVL16 côté
   Navixy (action séparée, sur GO explicite).
3. Test terrain réel (privatemode ON) : SEULEMENT après un précheck FMC130 PASS
   ET un nouveau GO explicite. Aucun device write d'ici là.
```

```text
PRIVATE_MODE_GLOBAL  = DISABLED
REAL_DEVICE_COMMANDS = MOCK/SIMULATION
```

---


## 0. Pourquoi ce document (remplace la version CAN périmée)

L'ancien protocole `DRIVER_PRIVATE_MODE_D3_PROTOCOL.md` reposait sur le sensor
`can_mileage` du FMC130 (tracker 781479), constaté **mort depuis 2022** → il
concluait `BLOCKED`. Il **précède la migration V2** qui a fait **réussir le
FMC003** (tracker 3657864) via **AVL ID 16** (Teltonika Total Odometer, GNSS
interne), et non via le CAN.

Ce document applique au FMC130 **exactement la stratégie qui a marché sur FMC003** :
distance privée mesurée par **AVL16**, indépendante des coordonnées GPS.

```text
Total Odometer Teltonika (GNSS interne)
   → AVL ID 16
      → Navixy (hw_mileage / avl_io_16)
         → LOGITRAK (private_distance = AVL16_end - AVL16_start)
```

> ⚠️ Un PASS FMC003 **ne vaut pas** PASS FMC130. La validation est par
> **MODÈLE + FIRMWARE + CONFIG + TRACKER**. FMC130 doit être prouvé séparément.

---

## 1. Environnement d'exécution — BLOQUANT dans ce fork

Le FMC130 pilote **n'existe pas** dans la base de ce fork (6 véhicules démo,
trackers 5000–5005). L'exécution terrain requiert l'**environnement réel** :
device FMC130 physique + compte Navixy réel + véhicule conduit.

```text
D3_FMC130_EXECUTABLE_IN_THIS_FORK = NO
```

Le script snapshot READ-ONLY est fourni et prêt : `scripts/d3_fmc130_snapshot.py`
(réutilise la logique AVL16 éprouvée de `d3b_snapshot.py`, généralisée par `TID`).

---

## 2. Configuration device requise (à CONFIRMER sur le FMC130 réel — lecture)

Mêmes paramètres que la config FMC003 validée (tracker 3657864, FW 04.02) :

```text
Odometer : Calculation Source = GNSS                        (11806 = 0)
Private/Business : GPS Data Masking = Data Sent As Zero      (11813 = 1)
                   Odometer Calculation = Enable             (11815 = 1)
                   Trigger Type = External                   (11849 = 0)
                   Scenario Settings = Low (ou High), PAS Disable   ← activation scénario
I/O : Total Odometer (AVL 16) = Low / Monitoring (transmis)
```

> Les param IDs Teltonika **doivent être reconfirmés pour le firmware réel du
> FMC130** avant toute écriture. Ne jamais écrire un ID non confirmé.
> Ne PAS confondre avec Deep Sleep `setparam 11000:4` (INTERDIT : couperait le GSM).

Si un seul de ces points n'est pas confirmé → **STOP**, `D3_FMC130_READY = NO`.

---

## 3. Préchecks READ-ONLY (tous requis, sinon STOP)

Exécuter `d3_fmc130_snapshot.py before` et confirmer :

```text
tracker online              = YES
AVL16 présent (avl_io_16)   = YES        AVL16 récent = YES        AVL16 lisible API = YES
scale AVL16 cohérente (m/1000 -> km ≈ tableau de bord)   = YES (à vérifier)
mode actuel                 = BUSINESS (ou état explicitement déterminé)
GPS normal avant test       = YES
```

---

## 4. Procédure terrain (exécution FUTURE, sur GO explicite uniquement)

```text
1. SNAPSHOT before                    (READ-ONLY)
2. Bascule BUSINESS -> PRIVATE        [ACTION GATÉE opérateur : privatemode ON via Navixy
                                        raw_command/send ; JAMAIS Deep Sleep ; sur GO explicite]
3. SNAPSHOT private_start             -> PRIVATE confirmé + tracker ONLINE + GPS masqué
4. ROULAGE réel ~2 à 5 km
5. SNAPSHOT private_driving (>=1)     -> AVL16 timestamp s'actualise + valeur augmente
6. SNAPSHOT private_end               -> AVL16_END = Y
7. Retour PRIVATE -> BUSINESS         [ACTION GATÉE : privatemode OFF ; sur GO explicite]
8. SNAPSHOT business_restored         -> GPS normal restauré + AVL16 dispo
9. SNAPSHOT summary                   -> PRIVATE_DISTANCE = AVL16_END - AVL16_START
```

Distance privée calculée **EXCLUSIVEMENT via AVL16**. GPS Navixy odo = référence,
**JAMAIS** utilisé. Jamais `trip.length` / distance GPS.

---

## 5. Critères PASS/FAIL — D3 FMC130 PASS uniquement si TOUS

```text
1  modèle = FMC130 confirmé (résolu via resolve_model)
2  tracker online avant test
3  AVL16 disponible avant test
4  GPS normal avant test
5  passage Privé réellement confirmé (pas seulement HTTP 200 Navixy)
6  coordonnées transmises réellement masquées (0,0 OU position gelée en roulant)
7  tracker reste online en Privé
8  AVL16 reste disponible en Privé (timestamp s'actualise)
9  AVL16 augmente pendant roulage Privé (Y > X)
10 distance privée calculable (= AVL16_end - AVL16_start)
11 retour Business confirmé
12 GPS normal restauré après OFF
13 aucune position privée exploitable exposée dans LOGITRAK
```

Résolution compteur : si delta trop faible / arrondi / MAJ tardive →
`PRIVATE_INCREMENT = INCONCLUSIVE` + rouler plus longtemps (NE PAS déclarer FAIL).

Si **tout** PASS :

```text
FMC130_PRIVATE_MODE_CAPABILITY = FIELD_VALIDATED   (CE tracker uniquement)
```

Alors seulement, dans `odometer_capability.py`, le FMC130 pourra passer
`verified=True, status=VALIDATED` pour ce tracker. **Jusque-là, bouton Privé de
production DÉSACTIVÉ pour tous les modèles.**

---

## 6. Rollback

```text
Nominal : Privé -> BUSINESS_REQUESTED -> BUSINESS confirmé -> GPS normal.
Erreur  : retour Business NON confirmé -> state = FAILED / UNKNOWN (jamais BUSINESS silencieux).
          Afficher un état technique honnête + procédure de récupération manuelle.
Config  : si Trigger Type / Scenario ont été modifiés, conserver la config .cfg
          originale et la procédure exacte de restauration.
```

---

## 7. Privacy (trajet PRIVATE dans LOGITRAK)

```text
NON conservé : latitude, longitude, adresse, polyline, route, replay, breadcrumb, GPS reconstruit.
Conservé     : driver_id, vehicle_id, private_start_time, private_end_time,
               odometer_start_km, odometer_end_km, private_distance_km,
               odometer_source, mode_status, validation metadata.
```

(La redaction backend centrale — `private_mode_engine.redact_private_trip` — est
déjà en place et durcie : lat/lng/adresses masqués, distance conservée, jamais 0,0.)

---

## 8. Registre — état FMC130 actuel

`odometer_capability.py` (V2) :

```text
FMC130 : PRIMARY = TELTONIKA_TOTAL_ODOMETER (AVL 16, GNSS interne)
         SECONDARY = can_mileage si présent (souvent périmé)
         verified = False   status = NOT_TESTED   field_validated = False
         GPS Navixy JAMAIS admissible ; FIELD_VALIDATED requis avant prod
```

Aucune modification du registre tant que D3 FMC130 n'est pas PASS en réel.

---

## 9. Garde-fous absolus

- 1 seul tracker FMC130 à la fois. Jamais de bulk. Jamais toucher FMC003/FMU130/FMC640/FMC650.
- Jamais `trip.length` / distance GPS comme mesure privée. Jamais `counter/value/set`.
- Écritures device (bascule Privé/Pro, config) seulement sur **autorisation explicite**, gate par gate.
- FMC130 validé ≠ « Teltonika validé » : validation MODÈLE + FIRMWARE + CONFIG + TRACKER.
- Toute action réelle ⇒ STOP + `EXPLICIT_GO_REQUIRED`.

---

## 10. Résultat

```text
RESULT              = NOT_EXECUTED
D3_FMC130_PROTOCOL  = READY (stratégie AVL16 ; config §2 à confirmer sur le device réel)
D3_FMC130_EXECUTION = NOT_STARTED
SNAPSHOT_SCRIPT     = scripts/d3_fmc130_snapshot.py (READ-ONLY, prêt)
NEXT_ACTION         = WAIT_FOR_EXPLICIT_GO_D3_FMC130 (environnement réel)
```
