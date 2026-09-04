# Runbook — Précheck D3 FMC130 (tracker 781479) — READ-ONLY

> **À exécuter VOUS-MÊME sur le VPS de production** (l'environnement réel qui
> contient le tracker 781479 + l'accès Navixy). Ce fork n'a **ni** le tracker
> **ni** de credential Navixy → le précheck ne peut pas y être exécuté.
>
> ```
> STEP                 = FMC130_D3_PRECHECK (READ-ONLY)
> TRACKER_ID           = 781479   MODEL = FMC130
> PRIVATE_MODE_GLOBAL  = DISABLED
> REAL_DEVICE_COMMANDS = MOCK / SIMULATION
> ```
>
> READ-ONLY strict : **aucun** `privatemode`, **aucun** `setparam`, **aucune**
> modification de sensor Navixy, **aucune** écriture device, **aucune** activation
> production. Le script ne fait que LIRE.

## Objectif

```text
TRACKER_ID        = 781479
MODEL             = FMC130
TRACKER_ONLINE    =
GPS_NORMAL        =
AVL16_PRESENT     =
AVL16_RAW_VALUE   =
AVL16_VALUE_KM    =
AVL16_TIMESTAMP   =
AVL16_RECENT      =
AVL16_API_READABLE=
```

Et vérifier le **mapping Navixy** du sensor AVL16 :

```text
INPUT      = avl_io_16   (ou hw_mileage)
MULTIPLIER = 1
DIVIDER    = 1000
UNIT       = km
```

## Étapes

### 1. Entrer dans le conteneur backend (adapter le nom réel)

```bash
docker ps
docker exec -it <NOM_CONTENEUR_BACKEND> bash
cd /app/backend          # adapter si besoin
```

### 2. Précheck « before » (état + AVL16 + GPS + online) — READ-ONLY

```bash
docker exec -e AUDIT_NAVIXY_HASH="$KEY_COMPTE_781479" -e TID=781479 <conteneur> \
  python3 scripts/d3_fmc130_snapshot.py before
```

Relever depuis la sortie :
- `tracker_online`, `MASKING_VERDICT` (attendu NOT_MASKED en Business = GPS normal),
- `AVL16_KM`, `AVL16_timestamp`, `gps position ts`, `ignition/moving`.

### 3. Vérification du mapping AVL16 — READ-ONLY

```bash
docker exec -e AUDIT_NAVIXY_HASH="$KEY_COMPTE_781479" -e TID=781479 <conteneur> \
  python3 scripts/d3_fmc130_snapshot.py mapping
```

Relever : `INPUT_NAME`, `MULTIPLIER`, `DIVIDER`, `UNIT`, `MAPPING_MATCHES_EXPECTED`.

> `AUDIT_NAVIXY_HASH` = clé du **compte Navixy qui possède 781479**. Le script ne
> l'affiche jamais. **Ne collez pas la clé dans le chat.**

### 4. Me renvoyer UNIQUEMENT ce bloc rempli

```text
TRACKER_ID        = 781479
MODEL             = FMC130
TRACKER_ONLINE    = ...
GPS_NORMAL        = ...        (NOT_MASKED = GPS normal en Business)
AVL16_PRESENT     = ...
AVL16_RAW_VALUE   = ...        (valeur brute avl_io_16 si visible)
AVL16_VALUE_KM    = ...        (= AVL16_KM affiché)
AVL16_TIMESTAMP   = ...
AVL16_RECENT      = ...        (timestamp proche de maintenant ?)
AVL16_API_READABLE= ...
--- mapping ---
INPUT             = ...        (attendu avl_io_16 / hw_mileage)
MULTIPLIER        = ...        (attendu 1)
DIVIDER           = ...        (attendu 1000)
UNIT              = ...        (attendu km)
MAPPING_MATCHES_EXPECTED = YES/NO
```

## Verdict (je le calcule à réception)

```text
Si AVL16 présent + récent + API readable + mapping cohérent (mult=1, div=1000, unit=km):
   FMC130_D3_PRECHECK = PASS
Sinon:
   FMC130_D3_PRECHECK = BLOCKED
   BLOCKING_REASON = ...
```

> ⚠️ Ce précheck ne déclenche **pas** le test terrain Private Mode. Le D3 terrain
> (bascule Privé/Pro) reste une action GATÉE, sur GO explicite séparé.

## Garanties

```text
WRITE_OPERATIONS   = NONE
DEVICE_COMMANDS    = NONE (aucun privatemode / setparam)
SENSOR_CHANGES     = NONE
SECRETS_PRINTED    = NONE (AUDIT_NAVIXY_HASH jamais affiché)
PRODUCTION_ACTIVATION = NONE
```
