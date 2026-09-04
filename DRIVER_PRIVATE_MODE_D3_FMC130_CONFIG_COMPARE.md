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
| Total Odometer valeur | (11807) | ~140xxx km | ____ |  |
| AVL ID affiché | — | 16 | ____ |  |

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

```text
PRIVATE_MODE_GLOBAL  = DISABLED
REAL_DEVICE_COMMANDS = MOCK/SIMULATION
D3_FMC130_EXECUTION  = NOT_STARTED
NEXT_ACTION          = RELEVÉ CONFIG MANUEL (opérateur) -> comparaison -> décision GO config
```
