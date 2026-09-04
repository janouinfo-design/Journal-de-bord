# Runbook — Précheck D3 FMC130 (tracker 781479) — READ-ONLY, resolver multi-tenant

> **À exécuter VOUS-MÊME sur le VPS réel** (celui qui contient 781479 + l'intégration
> Navixy du tenant). Ce fork n'a ni le tracker ni le credential → précheck non
> exécutable ici (résultat `BLOCKED / TENANT_UNRESOLVED`, ce qui est normal).
>
> ```
> STEP                 = FMC130_D3_PRECHECK (READ-ONLY)
> TRACKER_ID           = 781479   MODEL = FMC130
> PRIVATE_MODE_GLOBAL  = DISABLED
> REAL_DEVICE_COMMANDS = MOCK / SIMULATION
> ```

## Nouveauté : plus besoin d'`AUDIT_NAVIXY_HASH`

Le script résout désormais le credential via le **resolver multi-tenant** de
l'application (aucune clé manuelle, aucun secret affiché) :

```text
tracker 781479
  -> vehicle (vehicles.navixy_tracker_id)
  -> tenant_id (vehicles.tenant_id)
  -> get_integration_credential(tenant_id, "NAVIXY")   (fail-closed, jamais cross-tenant)
  -> client Navixy READ-ONLY
```

Si le tenant ne se résout pas → `BLOCKED / TENANT_UNRESOLVED`.
Si le tenant n'a pas de credential → `BLOCKED / NAVIXY_CREDENTIAL_MISSING`
(aucun emprunt du credential d'un autre tenant).

## Étapes

### 1. Entrer dans le conteneur backend (adapter le nom réel)

```bash
docker ps
docker exec -it <NOM_CONTENEUR_BACKEND> bash
cd /app/backend
```

### 2. Lancer le précheck READ-ONLY (bloc complet)

```bash
docker exec -e TID=781479 <NOM_CONTENEUR_BACKEND> \
  python3 scripts/d3_fmc130_snapshot.py precheck
```

> `precheck` produit le bloc complet (état + AVL16 + mapping). Les alias
> `before` et `mapping` produisent le même bloc. **Aucune clé à passer.**

### 3. Me renvoyer le bloc affiché

```text
TRACKER_ID = 781479
MODEL = ...
TENANT_ID = ...
CRED_SOURCE = ...            (TENANT attendu ; valeur jamais affichée)
TRACKER_ONLINE = ...
GPS_NORMAL = ...             (NOT_MASKED = GPS normal en Business)

AVL16_PRESENT = ...
AVL16_RAW_VALUE = ...
AVL16_TIMESTAMP = ...
AVL16_RECENT = ...

SENSOR_DEFINED = ...
SENSOR_ID = ...
SENSOR_INPUT = ...           (attendu avl_io_16 / hw_mileage)
SENSOR_MULTIPLIER = ...      (attendu 1)
SENSOR_DIVIDER = ...         (attendu 1000)
SENSOR_UNIT = ...            (attendu km)
SENSOR_VALUE_KM = ...

AVL16_API_READABLE = ...
AVL16_SCALE_VERIFIED = ...

FMC130_D3_PRECHECK = PASS / BLOCKED
BLOCKING_REASON = ...
```

## Verdict (calculé par le script, confirmé par moi à réception)

```text
PASS  si : tracker online + GPS normal + AVL16 présent + récent + API readable
           + mapping observé cohérent (input avl_io_16, mult=1, div=1000, unit=km)
BLOCKED sinon, avec BLOCKING_REASON parmi :
  TENANT_UNRESOLVED | NAVIXY_CREDENTIAL_MISSING | NAVIXY_AUTH_FAILED |
  TRACKER_OFFLINE | GPS_NOT_NORMAL | AVL16_ABSENT | AVL16_STALE |
  AVL16_NOT_READABLE | MAPPING_NOT_VERIFIED
```

> Le mapping est **observé et vérifié**, jamais forcé. `AVL16_SCALE_VERIFIED = True`
> uniquement si les valeurs réelles correspondent à l'attendu.

## Garanties

```text
CREDENTIAL_RESOLUTION = resolver multi-tenant (aucun AUDIT_NAVIXY_HASH manuel)
SECRETS_PRINTED       = NONE (seul CRED_SOURCE — un label — est affiché)
CROSS_TENANT_FALLBACK = NONE (fail-closed)
WRITE_OPERATIONS      = NONE
DEVICE_COMMANDS       = NONE (aucun privatemode / setparam)
SENSOR_CHANGES        = NONE
PRODUCTION_ACTIVATION = NONE
```

> Ce précheck ne déclenche PAS le test terrain Private Mode. Le D3 terrain reste
> GATÉ, sur GO explicite séparé.
