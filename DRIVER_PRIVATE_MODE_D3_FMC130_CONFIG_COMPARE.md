# FMC130 781479 — Config Compare vs FMC003 3657864 (READ-ONLY, Configurator)

> **Relevé manuel opérateur** (Teltonika Configurator / Air Console). AUCUNE
> commande device envoyée par LOGITRAK : pas de `getparam`, pas de `raw_command`,
> pas de `setparam`, pas de `privatemode`.
>
> Objectif : comprendre pourquoi **AVL16 n'est pas actuellement transmis** par le
> FMC130 `781479` (statut `NOT_CURRENTLY_EXPOSED`), alors qu'il l'est sur le FMC003.

## Contexte (déjà établi, terrain)
```text
FMC003 3657864 : AVL16 PRESENT + mapping avl_io_16/mult=1/div=1000/km  -> PRECHECK PASS
FMC130 781479  : AVL16 NOT_CURRENTLY_EXPOSED ; can_mileage MORT (fige 2022-03-26) -> INEXPLOITABLE
=> Cible = exposer AVL16 sur le FMC130 (Voie A). can_mileage ecarte.
```

## Grille de comparaison (à remplir depuis le Configurator)

| Paramètre | ID | FMC003 3657864 (réf. validée) | FMC130 781479 (à relever) | OK ? |
|---|---|---|---|---|
| Odometer Calculation Source | 11806 | `0` = GNSS | ____ |  |
| GPS Data Masking | 11813 | `1` = Data Sent As Zero | ____ |  |
| Odometer Calculation (Private) | 11815 | `1` = Enable | ____ |  |
| Trigger Type | 11849 | `0` = External | ____ |  |
| Private/Business Scenario | 11850 | `1` = Low Priority | ____ |  |
| **Total Odometer I/O** (AVL 16) | — | **Low / Monitoring (transmis)** | ____ | ⬅️ **à regarder en 1er** |
| Total Odometer valeur | (11807) | (propre au véhicule) | ____ = existe ? valeur cohérente ? |  |
| AVL ID affiché | — | 16 | ____ |  |

> ⚠️ NE PAS comparer la valeur absolue de `11807` entre FMC130 et FMC003 : chaque
> véhicule a son propre kilométrage. On vérifie seulement que `11807` **existe** et
> contient une **valeur cohérente** (odomètre interne actif). Ce qui compte pour
> l'exposition Navixy, c'est le réglage **Total Odometer I/O** (transmission AVL16).

## Hypothèse prioritaire
```text
Si "Total Odometer I/O" est DÉSACTIVÉ / non surveillé sur le 781479 :
  -> l'odomètre interne peut exister (getparam 11807 aurait une valeur)
  -> MAIS l'élément AVL 16 n'est PAS transmis dans la trame
  -> donc avl_io_16 ABSENT côté Navixy (exactement ce qu'on observe).
Correction (à PROPOSER, jamais appliquer sans GO) :
  activer "Total Odometer" en I/O (Priority = Low, Operand = Monitoring)
  + vérifier 11806/11815 = GNSS/Enable
  + puis créer le sensor Navixy (input avl_io_16, mult=1, div=1000, unit=km).
```

## Ce qu'on décidera APRÈS le relevé
```text
- Si seul "Total Odometer I/O" manque  -> 1 seule modif config (Configurator/FOTA) + sensor Navixy.
- Si 11806/11815/11849/11850 diffèrent -> aligner sur la réf FMC003.
- Toute écriture = décision opérateur, sur GO EXPLICITE. LOGITRAK n'écrit rien.
```

## RÉSULTAT DU RELEVÉ (captures Configurator FMC130 781479, 2026-09-04)

Comparatif final :
```text
PARAMÈTRE                  FMC003 VALIDÉ        FMC130 781479        ÉTAT
11806 Source               GNSS                 GNSS                 = OK
11813 GPS masking          Data Sent As Zero    Normal               ⚠️ À CORRIGER
11815 Private odometer      Enable               Enable               = OK
11849 Trigger              External             External             = OK
11850 Scenario             Low                  Low                  = OK
Total Odometer I/O         Low / Monitoring     Priority = None      ❌ CAUSE AVL16 ABSENT
```

CAUSE RACINE (confirmée par capture onglet I/O) :
```text
Total Odometer -> Priority = None  => l'element AVL 16 n'est PAS transmis dans la trame.
L'odometre interne calcule bien (valeur visible), le sensor Navixy AVL16 existe,
mais le device n'emet jamais avl_io_16 -> absent chez Navixy. = NOT_CURRENTLY_EXPOSED expliqué.
```

CORRECTIONS REQUISES (device — à exécuter par l'opérateur, sur GO EXPLICITE ; LOGITRAK n'écrit rien) :
```text
#1 (débloque AVL16)  I/O -> Total Odometer : Priority = Low, Operand = Monitoring
                     -> AVL 16 commence à être transmis à Navixy.
#2 (mode Privé)      Private/Business -> GPS Data Masking = Data Sent As Zero (11813 : 0 -> 1)
                     -> sinon les vraies coordonnées seraient transmises en Privé (fuite).
ROLLBACK : re-mettre Total Odometer Priority=None et 11813=0 (Normal) si besoin.
APRÈS #1/#2 : re-lancer d3_fmc130_snapshot.py precheck -> viser FMC130_D3_PRECHECK = PASS.
```

```text
PRIVATE_MODE_GLOBAL  = DISABLED
REAL_DEVICE_COMMANDS = MOCK/SIMULATION
D3_FMC130_EXECUTION  = NOT_STARTED
NEXT_ACTION          = OPÉRATEUR applique #1 (+#2) sur GO -> re-precheck AVL16
```

## VERDICT FINAL (2026-09-04) — device OK, il manque le SENSOR NAVIXY

Preuves croisées :
```text
Air Console (device)  : avl_io_16 = 56268543  -> le DEVICE émet bien l'AVL 16 ✅
                        (=> Total Odometer I/O correctement activé côté device)
API Navixy sensor/list: AUCUN sensor avl_io_16 (18 sensors : obd_*, can_*, ble_*, mais pas AVL16)
API Navixy readings   : avl_io_16 ABSENT des 30 inputs remontés
```

CAUSE RACINE FINALE :
```text
Le SENSOR Navixy "Total Odometer" (input avl_io_16) n'a JAMAIS été créé pour le 781479.
Navixy ne remonte pas un IO brut tant qu'aucun sensor ne le référence.
(Sur le FMC003, ce sensor existe : "ODO TOTAL" id 5570680 -> d'où l'exposition.)
```

ACTION REQUISE (écriture Navixy — sur GO EXPLICITE ; LOGITRAK ne crée rien sans autorisation) :
```text
Créer dans Navixy, pour le tracker 781479, un sensor identique au FMC003 :
  Type       = Odometer / Mileage (metering)
  Input      = AVL IO 16  (avl_io_16)
  Multiplier = 1
  Divider    = 1000
  Unit       = km
  Nom        = "ODO TOTAL" (ou équivalent)
Valeur brute 56268543 -> normalisée ~56268.5 km.
Puis re-lancer d3_fmc130_snapshot.py precheck (véhicule en ligne) -> viser PASS.
```

Note config #2 (GPS Data Masking = Data Sent As Zero) : reste requise pour le TEST TERRAIN
Privé (masquage), mais PAS pour ce précheck AVL16.

## ✅ RÉSOLU (2026-09-07) — FMC130 781479 PRÉCHECK = PASS

Après création du sensor Navixy AVL16, précheck relancé (véhicule en ligne) :
```text
TRACKER_ONLINE = True     GPS_NORMAL = True (coords réelles récentes)
AVL16_PRESENT = True      AVL16_RAW_VALUE = 56273.74 km   AVL16_TIMESTAMP = 2026-09-07 10:33:26 (récent)
SENSOR_DEFINED = True     SENSOR_ID = 5577108   SENSOR_INPUT = avl_io_16
SENSOR_MULTIPLIER = 1.0   SENSOR_DIVIDER = 1000.0   SENSOR_UNIT = kilometre
AVL16_SCALE_VERIFIED = True
FMC130_D3_PRECHECK = PASS
```
Incrément cohérent vs Air Console (56268543 -> 56273.74 km = ~+5 km de roulage) -> AVL16 s'incrémente.

Mapping V2 confirmé terrain, IDENTIQUE au FMC003 : avl_io_16 / mult=1 / div=1000 / km.

```text
FMC130_781479_D3_PRECHECK = PASS
FMC130_781479_D3_EXECUTION = NOT_STARTED (test terrain Privé = étape séparée, sur GO)
RESTE avant test terrain : config #2 (GPS Data Masking = Data Sent As Zero, 11813=1) + GO explicite.
PRIVATE_MODE_GLOBAL = DISABLED
```



```text
PRIVATE_MODE_GLOBAL  = DISABLED
REAL_DEVICE_COMMANDS = MOCK/SIMULATION
D3_FMC130_EXECUTION  = NOT_STARTED
NEXT_ACTION          = RELEVÉ CONFIG MANUEL (opérateur) -> comparaison -> décision GO config
```
