# Runbook — Résolution du tenant pilote (tracker 3657864) — READ-ONLY

> **À exécuter VOUS-MÊME sur le VPS de production.** Aucun credential ne doit
> transiter par le chat. Le script est strictement READ-ONLY et n'imprime aucun
> secret (MONGO_URL / mot de passe / API keys / tokens / `.env`).

## Objectif

Résoudre, dans l'environnement réel contenant le tracker `3657864`, le mapping
canonique `tracker → vehicle → tenant` :

```text
TRACKER_ID      = 3657864
VEHICLE_ID      =
TENANT_ID       =
TENANT_NAME     =
SOURCE_OF_TRUTH =
RESOLUTION      = VERIFIED / AMBIGUOUS / NOT_FOUND
```

## Pré-requis

- Être sur le VPS de production, dans le conteneur backend qui possède déjà les
  variables d'environnement (`MONGO_URL`, `DB_NAME`) via son `.env`.
- Le script `scripts/resolve_pilot_tenant_3657864.py` doit être présent dans ce
  conteneur (il fait partie du dépôt).

## Étapes

### 1. Identifier le conteneur backend (adapter les noms réels)

```bash
docker ps
# repérer le conteneur backend LOGITRAK (colonne NAMES), ex. logitrak-backend
```

### 2. Entrer dans le conteneur

```bash
docker exec -it <NOM_DU_CONTENEUR_BACKEND> bash
```

### 3. Se placer dans le répertoire backend

```bash
cd /app/backend          # adapter si le WORKDIR de prod diffère
```

### 4. Lancer l'audit READ-ONLY

```bash
set -a && source .env && set +a && python scripts/resolve_pilot_tenant_3657864.py
```

> `source .env` charge `MONGO_URL`/`DB_NAME` **dans le shell** ; le script les lit
> mais ne les affiche jamais. La sortie ne contient que le bloc de résolution.

### 5. Copier UNIQUEMENT le bloc suivant et me le renvoyer

```text
TRACKER_ID      = 3657864
VEHICLE_ID      = ...
TENANT_ID       = ...
TENANT_NAME     = ...
FIELD_VALIDATED = ...
FOUND_IN_DB     = ...
SOURCE_OF_TRUTH = ...
RESOLUTION      = ...
```

## Après le résultat

- Si `RESOLUTION = VERIFIED` → je consignerai `TENANT_ID` + `TRACKER_ID` dans le
  document pilote, **sans implémenter** le Feature Flag (GO séparé requis).
- Si `RESOLUTION = AMBIGUOUS` ou `NOT_FOUND` → reste bloqué, investigation
  supplémentaire nécessaire.

## Garanties

```text
WRITE_OPERATIONS   = NONE   (aucune écriture, aucune migration)
SECRETS_PRINTED    = NONE   (MONGO_URL / credentials / API keys / tokens jamais affichés)
DEVICE_COMMANDS    = NONE
NAVIXY_CALLS       = NONE
FEATURE_FLAG_IMPL  = NOT DONE (GO séparé requis)
```
