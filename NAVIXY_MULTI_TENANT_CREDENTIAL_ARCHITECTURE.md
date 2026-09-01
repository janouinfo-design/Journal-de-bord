# NAVIXY_MULTI_TENANT_CREDENTIAL_ARCHITECTURE.md
## Architecture de credential Navixy multi-tenant (chaque client = son compte)

> **Contrainte métier** : chaque client LOGITRAK peut avoir son propre compte / sa propre
> clé API Navixy. Un `NAVIXY_API_KEY` global n'est acceptable **que** comme fallback
> DEV/PILOT, jamais comme architecture de production.
> **Cette mission** : durcir la résolution du credential (fail-closed, par tenant, fallback
> gouverné, chiffrement optionnel) SANS migration destructive et SANS démarrer D2.

---

## CURRENT (état audité, avant/après ce durcissement)

**Déjà présent (réutilisé, PAS recréé)** :
- Le **doc `tenants`** stocke déjà la config Navixy PAR TENANT :
  `navixy_hash`, `navixy_api_url`, `navixy_login`, `navixy_master_user_id`, `status`.
- `app/tenant_context.py` : `ContextVar` `_current_tenant` (tenant du contexte d'auth serveur)
  + cache mémoire `_tenant_cache` par `tenant_id`.
- `app/navixy_client.py` : `_hash()` résolvait déjà **tenant-first** puis env.
- `app/routes/admin.py` : configuration/masquage (`_mask_hash`, `navixy_hash_masked`,
  `has_navixy_hash`) + test d'identité au set. **Le secret n'est jamais renvoyé**.
- Consommateurs par tenant : `scheduler`, `driver_beacons`, `routes/ble`, `tenancy`.

**Ce qui manquait** : une résolution centralisée fail-closed, un flag de fallback global,
et un chiffrement optionnel des credentials.

**Ajouté par cette mission** (rétro-compatible, non destructif) :
- `app/integrations.py` — résolveur central :
  `get_integration_credential(tenant_id=None, provider="NAVIXY")`,
  `integration_status(...)`, `encrypt_secret()`, `decrypt_secret()`.
- `navixy_client._hash()/is_configured()/credential_type()` **délèguent** désormais à ce
  résolveur (comportement identique en dev, mais durci et centralisé).

---

## TARGET (architecture cible)

```
authenticated user
      ↓  (tenant_id issu du contexte d'auth serveur — jamais du mobile)
tenant integration registry  (aujourd'hui : champs navixy_* du doc tenant)
      ↓
credential Navixy DU tenant  (déchiffré si chiffré)
      ↓
NavixyClient résolu par tenant
      ↓
trackers de CE tenant uniquement
```
Jamais : `all tenants → one global key` (sauf DEV/PILOT explicitement autorisé).

---

## TENANT CREDENTIAL STORAGE
- **Aujourd'hui** : champ `tenants.navixy_hash` (+ `navixy_api_url`). Réutilisé.
- **Évolution proposée (non migrée maintenant)** : collection générique multi-provider
  `tenant_integrations` :
  ```
  { tenant_id, provider (NAVIXY|MAPON|FLESPI), enabled,
    credentials_encrypted, configuration, connection_status,
    last_tested_at, created_at, updated_at }
  ```
  → Permet plusieurs fournisseurs télématiques. **Migration différée** (voir §MIGRATION),
  pour ne pas casser scheduler/driver_beacons/ble qui lisent `tenant.navixy_hash`.

---

## ENCRYPTION
- **Master key serveur** : `INTEGRATION_ENCRYPTION_KEY` (secret serveur uniquement, jamais commit).
  - Algorithme : **Fernet** (AES-128-CBC + HMAC), via `cryptography` (déjà en requirements).
- `encrypt_secret(x)` → préfixe `enc::` ; `decrypt_secret()` tolère les valeurs **legacy en clair**
  (sans préfixe) → **rétro-compatibilité** : aucune donnée existante n'est cassée.
- **Fail-closed chiffrement** : valeur `enc::…` mais clé absente → credential considéré
  indisponible (jamais de fuite, jamais de valeur brute).
- Si `INTEGRATION_ENCRYPTION_KEY` absente → stockage clair conservé (dev), documenté comme
  à durcir en production.
- **Jamais** : logger / renvoyer au frontend / inclure dans une erreur / dans un rapport / dans Git.

---

## FALLBACK POLICY
Priorité de résolution (`get_integration_credential`) :
1. **Credential du tenant** (`tenants.navixy_hash`, déchiffré) — **source normale prod**.
2. `NAVIXY_API_KEY` (env) — **FALLBACK DEV/PILOT UNIQUEMENT**.
3. `NAVIXY_HASH` (env) — **LEGACY FALLBACK**.
4. `NONE`.

Gouvernance : le fallback GLOBAL (2 & 3) n'est autorisé **que** si
`ALLOW_GLOBAL_NAVIXY_FALLBACK=true`.
```
GLOBAL NAVIXY_API_KEY: TEMPORARY PILOT FALLBACK — NOT PRODUCTION MULTI-TENANT ARCHITECTURE
DEV/PILOT : ALLOW_GLOBAL_NAVIXY_FALLBACK = true   (par défaut)
PRODUCTION: ALLOW_GLOBAL_NAVIXY_FALLBACK = false
```

---

## MULTI-TENANT ISOLATION (fail-closed)
- Le `tenant_id` provient **toujours** du contexte d'auth serveur ; **jamais** d'un paramètre
  mobile. Le mobile ne choisit jamais un `tracker_id` ni un tenant.
- **Fail-closed** : un tenant en contexte SANS credential → **NONE** ; on n'emprunte **jamais**
  celui d'un autre tenant. Si `ALLOW_GLOBAL_NAVIXY_FALLBACK=false`, aucun fallback env non plus.
- Endpoint odomètre : `driver → tenant → vehicle → tracker → credential DU tenant → counter`
  (auth + tenant + anti-IDOR déjà en place et testés).
- **Tests** (`tests/test_navixy_multitenant.py`, 6/6 PASS) :
  - tenant A ≠ tenant B (chacun son credential) ;
  - tenant sans credential + fallback off → NONE (pas de cross-tenant, pas d'env) ;
  - fallback global autorisé seulement si flag true ;
  - round-trip chiffrement + valeur legacy en clair tolérée ;
  - credential tenant chiffré correctement déchiffré ;
  - `integration_status` ne fuit jamais la valeur du secret.

---

## SUPERADMIN — INTÉGRATIONS (préparé, non exposé maintenant)
API future (déjà partiellement présente dans `routes/admin.py`) :
- configure / replace API key (reçu HTTPS → **test READ-ONLY `tracker/list`** → si valide,
  chiffrer → stocker → ne jamais renvoyer la valeur) ;
- `GET` statut renvoyant uniquement :
  `{ "provider":"NAVIXY", "configured":true, "enabled":true, "connection_status":"CONNECTED", "last_tested_at":"…" }` ;
- disable integration ; connection status.
Test connexion → `CONNECTED / INVALID_CREDENTIAL / API_ERROR / NOT_CONFIGURED`.

---

## MIGRATION PLAN (non destructif, différé)
1. **Maintenant (fait)** : résolveur central + fail-closed + flag fallback + chiffrement
   optionnel, **sans** toucher aux données ni aux modules consommateurs.
2. **Étape prod (plus tard)** : `INTEGRATION_ENCRYPTION_KEY` en prod + rechiffrer les
   `navixy_hash` existants (`encrypt_secret`) via un script contrôlé (idempotent, réversible).
3. **Étape multi-provider (optionnelle)** : introduire `tenant_integrations`, migrer les champs
   `navixy_*` du doc tenant, puis adapter progressivement scheduler/driver_beacons/ble à lire
   via `get_integration_credential`. Aucune bascule big-bang.
4. **Bascule prod** : `ALLOW_GLOBAL_NAVIXY_FALLBACK=false`, chaque tenant ayant sa clé.

⚠️ Aucune migration destructive lancée. Aucun credential réel modifié. D2 Private Mode non démarré.

---

## FICHIERS
- **Créé** : `app/integrations.py` (résolveur central + chiffrement).
- **Modifié** : `app/navixy_client.py` (`_hash`/`is_configured`/`credential_type` délèguent au résolveur).
- **Tests** : `tests/test_navixy_multitenant.py` (6), `tests/test_navixy_credential.py` (4) — 10/10 PASS.
- **Non modifié** : scheduler, driver_beacons, ble, admin, tenancy (rétro-compat conservée).

---

## PRIORITÉ IMMÉDIATE RESTANTE
Le **D1 runtime pilot** reste la priorité, dès qu'un credential pilote est **réellement visible
par le process backend** (`NAVIXY_CREDENTIAL_TYPE = API_KEY` ou `TENANT_HASH`). Cette mission ne
débloque pas le runtime par elle-même : elle rend l'architecture correcte et sûre pour le
multi-tenant, tout en conservant le fallback pilote.
