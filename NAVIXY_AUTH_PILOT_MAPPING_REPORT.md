# NAVIXY_AUTH_PILOT_MAPPING_REPORT.md
## Phase D1.1 — Auth Navixy (API Key) + résolution tracker pilote réel

> **Suite de** : audit `168efad`, Phase D D1 `a34fdff`.
> **Exécution** : READ-ONLY strict. Aucun appel Navixy réel possible (credential absent).
> Aucune écriture, aucune commande device, aucun secret affiché/journalisé.

---

## ==================== PHASE D1.4 (dernière exécution) ====================

### Audit provisioning existant (§1)
```
TENANT_NAVIXY_READ_ENDPOINT:  YES   (GET /api/admin/tenants -> masqué, jamais le secret)
TENANT_NAVIXY_WRITE_ENDPOINT: YES   (POST + PATCH /api/admin/tenants[/{id}], superadmin)
TENANT_NAVIXY_TEST_ENDPOINT:  PARTIAL (validation via fetch_navixy_identity au set + POST /tenants/{id}/sync)
ADMIN_UI_AVAILABLE:           YES   (API superadmin)
```
→ Provisioning **réutilisé** (pas de nouvelle API créée).

### Correction appliquée (§5) — chiffrement au repos
- Écriture admin (`POST`/`PATCH /admin/tenants`) : le credential tenant est désormais stocké via
  `encrypt_secret()` (préfixe `enc::`) **si** `INTEGRATION_ENCRYPTION_KEY` est configurée ; sinon
  clair legacy (rétro-compat). Validation `tracker`/identity faite sur la valeur **en clair** avant chiffrement.
- Lecture directe `driver_beacons.py` : `decrypt_secret()` défensif (idempotent sur clair → zéro régression).
- `_tenant_out` : ajoute `navixy_credential_encrypted` (booléen) ; **ne renvoie jamais** la valeur (masquée).
- Réutilise `app/integrations.py` (aucun 2e mécanisme crypto). `navixy_hash` = champ legacy conservé (pas de renommage — §6).

### État runtime (§7, §10, §11)
```
TENANT_PILOT:                 TENANT_PILOT_SELECTION_REQUIRED
  Tenants disponibles (aucun credential Navixy configuré) :
   - "default" (Logitrak)                     navixy_configured=false
   - "TEST_Tenant_..._edited"                 navixy_configured=false
TENANT_NAVIXY_CONFIGURED:     NO
TENANT_CREDENTIAL_ENCRYPTION: DISABLED  (INTEGRATION_ENCRYPTION_KEY non configurée dans cet env)
CREDENTIAL_SCOPE:             NONE
GLOBAL_FALLBACK_USED:         NO
NAVIXY_CONNECTION_TEST:       NOT_CONFIGURED
NAVIXY_AUTH:                  BLOCKED (tracker/list non appelé)
REAL_TRACKERS_DISCOVERED:     0
PILOT_MAPPING:                UNRESOLVED
ODOMETER_STATUS:              UNAVAILABLE (jamais 0, jamais trip.length)
...                           NOT_VERIFIED
D1 STATUS:                    BLOCKED
```

### Où saisir la clé du tenant pilote (§8 — JAMAIS dans le chat)
Le credential ne doit pas être collé ici. Il se configure via l'**API superadmin sécurisée existante** :
```
PATCH /api/admin/tenants/{tenant_id}
Authorization: Bearer <token superadmin>
Body: {"navixy_hash": "<clé API Navixy du tenant>"}
```
→ Le backend **teste** la clé (fetch_navixy_identity), **rejette** une clé invalide ou un compte
Navixy déjà rattaché, **chiffre** (si `INTEGRATION_ENCRYPTION_KEY` présente) puis **stocke**. La réponse
ne contient jamais la clé (uniquement `navixy_hash_masked`, `has_navixy_hash`, `navixy_credential_encrypted`).
Recommandé : définir aussi `INTEGRATION_ENCRYPTION_KEY` (Fernet) côté serveur pour un stockage chiffré.

### Réponse à la question centrale de D1.4
« Peut-on configurer et utiliser la clé Navixy propre à un tenant, récupérer ses trackers réels et lire
un odomètre réel sans utiliser le credential d'un autre client ? »
→ **OUI côté architecture/code** (résolveur tenant-first, fail-closed, isolation prouvée par tests) ;
**runtime NON encore prouvé** car aucun tenant n'a de clé Navixy réelle configurée dans cet environnement.

**NEXT** : `READY FOR REAL DRIVE ODOMETER RECHECK` — dès qu'une clé tenant réelle est saisie via
`PATCH /api/admin/tenants/{id}` (superadmin), je relance D1 avec `CREDENTIAL_SCOPE=TENANT` et
`GLOBAL_FALLBACK_USED=NO`. **D2 non démarré.**

## ========================================================================


## RÉSULTAT GLOBAL
```
RUNTIME PILOT: BLOCKED_CREDENTIAL_NOT_INJECTED
```

### Phase D1.2 (reprise) — vérification runtime immédiate (§1)
```
NAVIXY_CREDENTIAL_TYPE = NONE   (dans le processus backend réellement exécuté)
```
→ **STOP** (règle §1). La variable `NAVIXY_API_KEY` annoncée comme « configurée » n'est
**pas visible** par le processus backend. Diagnostic (présence uniquement, valeur jamais lue) :

| Emplacement vérifié | NAVIXY_API_KEY |
|---|---|
| `/app/backend/.env` (chargé par `server.py` via load_dotenv) | **ABSENT** |
| Environnement du process backend en cours (PID uvicorn) | **ABSENT** |
| Ligne `environment=` de supervisor (program:backend) | **ABSENT** |
| Shell courant / autres process python·node | **ABSENT** |

**Cause probable** : le secret a été saisi dans un service/onglet différent de celui qui
exécute CE backend, ou le backend n'a pas été redémarré après injection, ou la variable
n'a pas été propagée au container/process de ce backend.

**Comment corriger (côté opérateur)** — au choix :
1. Ajouter `NAVIXY_API_KEY=<clé>` dans **`/app/backend/.env`** puis
   `sudo supervisorctl restart backend`. (le backend lit ce fichier au démarrage)
2. OU ajouter la variable à la ligne `environment=` du program `backend` dans la conf
   supervisor, puis `reread`/`update`/`restart backend`.
- Ne jamais committer la clé ni l'afficher. Vérifier ensuite : le runtime doit renvoyer
  `NAVIXY_CREDENTIAL_TYPE = API_KEY`.

Le message décrivait la procédure **quand** la clé est visible par le backend ; ici elle ne
l'est pas → on reste bloqué **avant** l'auth Navixy (aucun `tracker/list` appelé).

---

## CREDENTIAL
```
NAVIXY_CREDENTIAL_TYPE: NONE          (API_KEY / LEGACY_HASH / NONE)
NAVIXY_AUTH:            BLOCKED       (aucun appel possible sans credential)
```
- **Support ajouté (code)** : variable **`NAVIXY_API_KEY`** désormais **prioritaire** sur
  l'ancien `NAVIXY_HASH` (déprécié, conservé pour compat migration). Le credential est
  toujours transmis à Navixy dans le champ JSON `hash` (format accepté pour une API key
  comme pour un session hash) — **aucun payload d'appel modifié à l'aveugle**.
- **Sécurité** : le secret n'est **jamais** loggé, **jamais** renvoyé par l'API, **jamais**
  transmis au frontend. Un avertissement de dépréciation (sans valeur) est émis si l'ancien
  `NAVIXY_HASH` est utilisé. `admin.py` masque déjà le hash tenant.

### Audit des usages du credential (avant modification)
`NAVIXY_HASH` / `tenant.navixy_hash` est utilisé par : `navixy_client`, `scheduler`,
`driver_beacons`, `routes/ble`, `routes/admin` (masqué), `tenancy`, `odometer_audit`.
→ `NAVIXY_HASH` **non supprimé** (d'autres modules l'utilisent). Migration contrôlée.

---

## AUTH READ-ONLY (§5)
```
Endpoint testé:  aucun (tracker/list NON appelé — credential absent)
NAVIXY_AUTH:     BLOCKED
```
> Dès qu'un credential réel sera présent, l'appel READ-ONLY minimal sera `tracker/list`
> (déjà supporté par le client), sans jamais afficher headers/payload contenant le secret.

---

## TRACKERS RÉELS (§6–§7)
```
REAL_TRACKERS_DISCOVERED: 0   (tracker/list non exécutable)
```
- Les `navixy_tracker_id` 5000–5005 présents en base proviennent du **seed mock**
  (`app/mock_navixy.py`) → **rejetés** comme non réels. Non utilisés comme pilote.
- Modèle de traceur (FMC003/FMC130) : **non déterminable** sans `tracker/list` réel.
  Rappel (conservé) : `vehicle.model` (Mercedes Sprinter…) ≠ modèle de traceur.

---

## MAPPING VÉHICULE ↔ TRACKER (§8–§10)
```
PILOT_MAPPING: UNRESOLVED
```
- Source du mapping actuel : `vehicles.navixy_tracker_id` (seed mock), scoping tenant `default`.
- Aucun matching approximatif effectué (interdit §9 : ni label, ni plaque, ni modèle, ni index).
- Aucun candidat réel → **UNRESOLVED → STOP** (règle §9).

---

## PILOTE (§10)
```
PILOT_TRACKER:        NOT_RESOLVED
PILOT_DEVICE_MODEL:   NOT_VERIFIED
```
Aucun véhicule ne satisfait (tenant + canonical vehicle + tracker Navixy réel + modèle FMC003/FMC130 non ambigu).

---

## ODOMÈTRE (§12–§16) — NON EXÉCUTÉ (bloqué avant)
```
ODOMETER_COUNTER:  UNKNOWN
ODOMETER_VALUE:    NOT_VERIFIED
ODOMETER_SOURCE:   UNKNOWN
ODOMETER_INCREMENT: NOT_TESTED
```
Endpoint `GET /api/livre/driver/vehicle/odometer` reste honnête : renvoie
`{status:"UNAVAILABLE", odometer_km:null, reason:"navixy_not_configured"}` — **jamais 0**,
**aucune estimation GPS**. Sécurité inchangée (auth + tenant + anti-IDOR, le mobile ne fournit
jamais un `tracker_id`).

---

## TESTS AUTOMATIQUES (§19) — exécutés
```
Credential:
  - aucun credential -> NONE / UNAVAILABLE propre .......... PASS
  - legacy NAVIXY_HASH supporté pendant migration .......... PASS
  - NAVIXY_API_KEY prioritaire si les deux existent ........ PASS
  - aucun secret fuité dans type/configured ................ PASS   (tests/test_navixy_credential.py 4/4)
Odomètre:
  - auth requise (401) ..................................... PASS
  - null != 0 (UNAVAILABLE) ................................ PASS
  - session active sans Navixy -> UNAVAILABLE .............. PASS
  - anti-IDOR (403) ........................................ PASS   (tests/test_odometer_audit.py 4/4)
```

---

## STOP GATE (§21)
```
NAVIXY_AUTH       = BLOCKED       -> FAIL
PILOT_MAPPING     = UNRESOLVED    -> FAIL
ODOMETER_VALUE    = NOT_VERIFIED  -> FAIL
ODOMETER_INCREMENT= NOT_TESTED    -> FAIL
```

---

## RÉSULTAT FINAL D1.2 (§12)
```
NAVIXY_CREDENTIAL_TYPE:   NONE           (clé non injectée dans le process backend)
NAVIXY_AUTH:              BLOCKED        (tracker/list non appelé)
REAL_TRACKERS_DISCOVERED: 0

PILOT_MAPPING:            UNRESOLVED
PILOT_VEHICLE:            NOT_RESOLVED
PILOT_PLATE:              NOT_RESOLVED
PILOT_TRACKER:            NOT_RESOLVED
DEVICE_MODEL:             NOT_VERIFIED

ODOMETER_STATUS:          UNAVAILABLE    (jamais 0, jamais trip.length)
ODOMETER_VALUE:           null
ODOMETER_SOURCE:          UNKNOWN
ODOMETER_COUNTER_EXISTS:  UNKNOWN
HARDWARE_READING:         NOT_VERIFIED
AVL16_MAPPING:            NOT_VERIFIED

ODOMETER_BEFORE:          NOT_VERIFIED
ODOMETER_AFTER:           NOT_VERIFIED
DELTA_KM:                 NOT_VERIFIED
ODOMETER_INCREMENT:       NOT_TESTED
```

---

## D1 STATUS
```
BLOCKED
```

## NEXT SAFE STEP
Le code supporte déjà `NAVIXY_API_KEY` (rien à développer). Il faut **injecter la clé dans
le process backend** qui exécute cette API, puis me redonner la main :
1. Placer `NAVIXY_API_KEY=<clé>` dans **`/app/backend/.env`** (fichier lu par `server.py`).
2. `sudo supervisorctl restart backend`.
3. Vérifier : le runtime doit renvoyer `NAVIXY_CREDENTIAL_TYPE = API_KEY`.
Ne jamais committer/afficher la clé.

Dès que `NAVIXY_CREDENTIAL_TYPE = API_KEY` est confirmé dans CE backend, je reprends D1.2 :
`tracker/list` (auth) → trackers réels → mapping non ambigu (ou `PILOT_SELECTION_REQUIRED`)
→ odomètre `REAL` → `get_counters` → source/AVL16 → snapshot → incrément.

**Aucune** étape D2/D3/D4/D5 (Private Mode) ne sera lancée tant que D1 n'est pas `PASS`
ou `PASS_WITH_SOURCE_UNVERIFIED`.

---

## GARANTIES DE CETTE MISSION
- READ-ONLY strict : **aucun** `counter/value/set`, **aucun** `raw_command/send`, **aucun**
  `setparam`, **aucun** `privatemode`, **aucune** mise à jour de config, **aucune** action bulk.
- Aucune clé affichée / journalisée / commitée / envoyée au frontend.
- Aucune donnée inventée (pas de 0 km, pas de distance GPS comme odomètre).
