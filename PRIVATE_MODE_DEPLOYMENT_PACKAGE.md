# PRIVATE MODE — DEPLOYMENT PACKAGE (préparation — NE RIEN DÉPLOYER)

> Ce document est un **plan d'exécution prêt à l'emploi**. Aucune action n'a été
> réalisée : aucun push, aucun pull VPS, aucun rebuild, aucune migration, aucun
> changement `.env` prod, aucun flag activé, aucun device touché.
>
> État logiciel : sécurité pilote / Expo / Web / E2E croisé = **READY** ; tests **verts** ;
> environnement restauré **fail-closed** ; aucun device réel encore testé.

---

## 1. INVENTAIRE EXACT DES FICHIERS

### Backend (déployables)
| Fichier | Type |
|---|---|
| `backend/app/private_mode_gate.py` | **NEW** — gate centrale fail-closed (feature/kill/tenant/véhicule/hardware/intégration) |
| `backend/app/private_mode_engine.py` | **NEW** (absent du VPS) — state machine + redaction + simulate-confirm (gardé) |
| `backend/app/odometer_capability.py` | **NEW** (absent du VPS) — registre AVL16 FMC003/FMC130 |
| `backend/app/integrations.py` | **MODIFIED** — `classify_secret()`, `encryption_key_available()` |
| `backend/app/mock_navixy.py` | **MODIFIED** — `dev_private_fixture_enabled()` (gate fail-closed) + fixture DEV |
| `backend/app/routes/identification.py` | **MODIFIED** — endpoints driver private-mode (gate, HTTP codes) |
| `backend/app/routes/settings.py` | **MODIFIED** — endpoints admin `/private-mode/status` + `/kill-switch` |
| `backend/app/routes/reports.py` | **MODIFIED** — redaction des trajets privés dans les exports (P0) |
| `backend/app/reports.py` | **MODIFIED** — lectures d'adresses null-safe |
| `backend/app/tenant_context.py` | (déjà sur VPS) `refresh_tenant_cache` requis — vérifier version |
| `backend/server.py` | (inchangé) CORS lit `CORS_ORIGINS` |

### Backend — Scripts
| Fichier | Type |
|---|---|
| `backend/scripts/migrate_navixy_hash.py` | **NEW** — migration credential (dry-run/apply), admin only |
| `backend/scripts/d3_fmc130_snapshot.py` | **NEW** — précheck AVL16 READ-ONLY (diagnostic terrain) |
| `backend/scripts/resolve_pilot_tenant_3657864.py` | **NEW** — audit tenant READ-ONLY (diagnostic) |
| `backend/scripts/d3b_snapshot.py` | (existant) diagnostic FMC003 |
| `backend/scripts/e2e_setup.py` | **REMOVED** (DEV-only DB mutation + fake credential — retiré du repo avant push) |
| `backend/scripts/e2e_teardown.py` | **REMOVED** (DEV-only — retiré du repo avant push) |

### Expo (mobile chauffeur)
| Fichier | Type |
|---|---|
| `logitrak-driver-app/src/hooks/usePrivateMode.ts` | **MODIFIED** — machine à états, foreground refresh, mapping raisons/HTTP |
| `logitrak-driver-app/src/api/privateMode.ts` | **MODIFIED** — types + capture refus HTTP |
| `logitrak-driver-app/src/screens/DriverScreen.tsx` | **MODIFIED** — UX Privé/Pro, km conditionnel |

### Web (gestionnaire)
| Fichier | Type |
|---|---|
| `frontend/src/lib/privateMode.js` | **NEW** — `isPrivateTrip()` (miroir backend) |
| `frontend/src/components/livre/Badges.jsx` | **MODIFIED** — `PrivateMaskedBadge` |
| `frontend/src/pages/HistoryPage.jsx` | **MODIFIED** — badge « Position masquée », adresses masquées |
| `frontend/src/components/livre/TripsMap.jsx` | **MODIFIED** — exclusion privé + bandeau (défensif ; composant non monté) |
| `frontend/.env` | **DEV_ONLY / DO_NOT_DEPLOY** — créé pour le test local (pointe localhost:8001) |
| `frontend/yarn.lock` | (untracked) — régénéré `--ignore-engines` ; à inclure ou exclure selon politique CI |

### Tests (TEST_ONLY — non embarqués dans l'image prod)
| Fichier | Type |
|---|---|
| `backend/tests/test_private_mode_gate.py` | TEST_ONLY (14) |
| `backend/tests/test_private_mode_phase2.py` | TEST_ONLY (20) |
| `backend/tests/test_reports_private_redaction.py` | TEST_ONLY (6) |
| `backend/tests/test_migrate_navixy_hash.py` | TEST_ONLY (13) |
| `backend/tests/test_dev_private_fixture_guard.py` | TEST_ONLY (6) |
| `logitrak-driver-app/src/__tests__/usePrivateMode.test.tsx` | TEST_ONLY (13) |

### ⛔ NE DOIVENT JAMAIS ÊTRE ACTIFS/EXÉCUTÉS EN PROD
- `scripts/e2e_setup.py` / `scripts/e2e_teardown.py` (mutent la DB — DEV only).
- Logique `PRIVATE_MODE_SIMULATE_CONFIRM` (présente dans le code mais **fail-closed en prod**, voir §2).
- Fixture DEV `DEV-PRIVATE-FIXTURE-0001` (gate `APP_ENV` — inactive en prod).
- `frontend/.env` de test (URL localhost) — ne pas déployer ; le `.env` prod garde `REACT_APP_BACKEND_URL` officiel.
- Faux credential de test `TEST_E2E_*` — jamais commité (retiré ; `.env` restauré).

---

## 2. AUDIT DEV/TEST — `PRIVATE_MODE_SIMULATE_CONFIRM`

Fonction `simulate_confirm_enabled()` (`app/private_mode_engine.py`) :
```python
app_env = os.environ.get("APP_ENV", "production").strip().lower()
if app_env not in ("development", "dev", "preview", "local", "test"):
    return False                      # PRODUCTION -> toujours False (explicitement exclu)
return os.environ.get("PRIVATE_MODE_SIMULATE_CONFIRM", "0")... in ("1","true","yes","on")
```

| Contrôle | Résultat |
|---|---|
| défaut (var absente) | **False** ✅ |
| APP_ENV absent | traité `production` → **False** ✅ |
| Impossible à activer accidentellement | requiert **2 conditions** (APP_ENV dev + flag=1) ✅ |
| Valeur hardcodée `true` | **aucune** ✅ |
| Activation en prod | **impossible** : `APP_ENV=production` (défaut) exclut, même si le flag=1 ✅ |
| Route publique pour l'activer | **aucune** (uniquement variable serveur) ✅ |
| Explicitement interdit en prod | **OUI** — pas seulement par convention : le code refuse hors {dev,preview,local,test} ✅ |

**Comportement** : en production, la confirmation device NE PEUT PAS être simulée. Le seul
moyen de confirmer une bascule en prod = lecture réelle du device (à implémenter au moment du
rollout terrain) OU `PRIVATE_MODE_DEVICE_WRITE=1` + confirmation réelle. Tant que non implémenté,
le backend reste honnête : pas de confirmation → pas d'état PRIVATE affiché.

---

## 3. DIFF DE DÉPLOIEMENT (PROD ACTUELLE vs CODE À DÉPLOYER)

Constaté sur le VPS (`docker exec journal_backend ls /app/app`) :
```text
ABSENTS du VPS (à ajouter)      : private_mode_gate.py, private_mode_engine.py, odometer_capability.py
PRÉSENTS mais ANCIENS (Sep 1)   : integrations.py, mock_navixy.py, reports.py, tenant_context.py,
                                  routes/identification.py, routes/settings.py, routes/reports.py
=> versions VPS ne contiennent PAS : gate pilote, fix export privé, endpoints private-mode
   actualisés, kill switch, classify_secret, dev-fixture guard, redaction exports.
```
**Conclusion** : le VPS est en retard de plusieurs commits. Un `git pull` du dépôt (après
« Save to Github ») met TOUT à niveau de façon cohérente (fichiers NEW + MODIFIED ensemble).

> ⚠️ Le repo étant auto-commité à chaque étape, « Save to Github » poussera l'ensemble.

---

## 4. VARIABLES D'ENVIRONNEMENT

| NOM | OBLIG. | DÉFAUT | VALEUR PROD RECOMMANDÉE | SENSIBLE | SI ABSENTE |
|---|---|---|---|---|---|
| `PRIVATE_MODE_ENABLED` | Non | `false` | **`false`** (au déploiement) | Non | feature OFF (fail-closed) |
| `PRIVATE_MODE_PILOT_TENANTS` | Non | vide | vide puis `<tenant pilote>` | Non | aucun tenant autorisé |
| `PRIVATE_MODE_PILOT_TRACKERS` | Non | vide | vide puis `3657864` (pilote) | Non | aucun tracker autorisé |
| `PRIVATE_MODE_SIMULATE_CONFIRM` | Non | `0` | **NE PAS DÉFINIR** (inopérant en prod) | Non | simulation OFF |
| `PRIVATE_MODE_DEVICE_WRITE` | Non | `0` | `0` jusqu'au GO terrain | Non | commande device OFF (simulation) |
| `APP_ENV` | **Oui** | `production` | **`production`** | Non | traité production (bon défaut) |
| `ENABLE_DEV_PRIVATE_FIXTURE` | Non | `true` | **NE PAS DÉFINIR** (gate APP_ENV) | Non | fixture inactive en prod |
| `INTEGRATION_ENCRYPTION_KEY` | **Oui (prod)** | vide | **clé Fernet dédiée** | **OUI** | credential chiffré illisible (fail-closed) |
| `ALLOW_GLOBAL_NAVIXY_FALLBACK` | Non | `true` | **`false`** (prod : pas d'emprunt global) | Non | fallback autorisé (à éviter en prod) |
| `NAVIXY_API_KEY` / `NAVIXY_HASH` | Non | vide | vide (credential par tenant) | **OUI** | pas de fallback global |
| `CORS_ORIGINS` | Non | `*` | domaine(s) réel(s) app | Non | `*` (à restreindre en prod) |

### ÉTAT INITIAL PROD OBLIGATOIRE (au déploiement du code)
```text
PRIVATE_MODE_ENABLED=false
PRIVATE_MODE_DEVICE_WRITE=0
APP_ENV=production
INTEGRATION_ENCRYPTION_KEY=<clé Fernet définie>
ALLOW_GLOBAL_NAVIXY_FALLBACK=false   (recommandé)
# NE PAS définir : PRIVATE_MODE_SIMULATE_CONFIRM, ENABLE_DEV_PRIVATE_FIXTURE, allowlists (vides)
```
Le déploiement du **code n'active PAS** le Mode Privé (fail-closed).

---

## 5. NAVIXY_HASH — MIGRATION (2 temps)

### Étape A — DRY-RUN (READ-ONLY, aucune écriture)
```bash
docker exec -w /app journal_backend python3 -m scripts.migrate_navixy_hash --dry-run
```
Sortie attendue (exemple) :
```text
Tenants analyses / Deja chiffres valides / Legacy en clair / Champ vide-absent /
Chiffres invalides / A migrer / Migres=0 / Ecritures effectuees=0 / Erreurs=0 / STATUT=OK
```
**STOP si `Chiffres invalides (INVALID_ENCRYPTED) > 0`** → aucun `--apply`, intervention manuelle.
**STOP si `INTEGRATION_ENCRYPTION_KEY` absente** → statut `FAILED_NO_KEY`.

### Étape B — APPLY (écriture) — NE PAS EXÉCUTER MAINTENANT
À faire seulement après : (1) snapshot Mongo validé, (2) dry-run propre, (3) GO explicite.
```bash
docker exec -w /app journal_backend python3 -m scripts.migrate_navixy_hash --apply
```
Idempotent, conditionnel (SKIP CONFLICT si changement concurrent), ne double-chiffre jamais.

---

## 6. BACKUP AVANT DÉPLOIEMENT (checklist — aucun secret ici)
- [ ] Commit/tag Git actuel de la prod noté (`git rev-parse HEAD`) pour rollback code.
- [ ] Image Docker actuelle taggée/sauvegardée (`docker commit` ou tag registry) pour rollback image.
- [ ] `.env` prod sauvegardé de façon **sécurisée** (hors repo, hors chat).
- [ ] **Snapshot Mongo** (`mongodump` collection `tenants` au minimum, idéalement base complète).
- [ ] Config nginx/systemd/compose sauvegardée si modifiée.
- [ ] Vérifier qu'on peut redéployer exactement l'ancienne version (commit + image).

---

## 7. ORDRE DE DÉPLOIEMENT (préparé — ne rien lancer)
```text
PHASE 0 — PRECHECK   : tests verts (backend 59/59, Expo 48/48) ; matrice GO/NO-GO §17 revue.
PHASE 1 — BACKUP     : §6 complet (commit, image, .env, mongodump).
PHASE 2 — CODE       : Save to Github -> sur VPS: git pull (branche cible).
PHASE 3 — BUILD      : docker compose build journal_backend (image à jour).
PHASE 4 — DB DRY-RUN : migrate_navixy_hash --dry-run -> lire, STOP si invalides.
PHASE 5 — SERVICES   : docker compose up -d journal_backend (env fail-closed §4).
PHASE 6 — HEALTHCHECK: backend UP + endpoints répondent (voir §10).
PHASE 7 — FAIL-CLOSED: prouver PRIVATE_MODE_ENABLED=false bloque tout (voir §11).
PHASE 8 — PILOTE     : activer allowlists + PRIVATE_MODE_ENABLED=true (surface minimale, §12).
PHASE 9 — TERRAIN    : test device réel sur GO (protocole §14).
```

---

## 8. SAVE TO GITHUB (préparation — ne pas pousser)
> L'action git se fait via le bouton **« Save to Github »** de l'interface (je n'exécute aucune commande git).

- **Branche recommandée** : `feat/private-mode-pilot`
- **Message de commit proposé** :
  `feat(private-mode): gated driver private mode, central fail-closed authz gate, privacy redaction (trips+exports), navixy_hash migration, pilot safeguards + tests`
- **Inclure** : tout le code backend/expo/web listé §1 + tests + scripts diagnostic + docs.
- **Exclure absolument** :
  - `frontend/.env` (test local — doit rester non commité ; `.gitignore`).
  - tout `.env` (aucun secret commité).
  - `node_modules/`, logs, `__pycache__`.
  - éventuels faux credentials de test (déjà retirés).
- **À décider** : `frontend/yarn.lock` (inclure = build reproductible ; exclure si politique CI).

---

## 9. BUILD / REBUILD VPS (documenté — ne pas exécuter)
```text
Service backend      : conteneur `journal_backend` (compose)
Orchestration        : docker compose (fichier compose du projet) OU systemd selon setup
Pull                 : cd <repo_prod> && git fetch && git checkout feat/private-mode-pilot && git pull
Build                : docker compose build journal_backend
Restart              : docker compose up -d journal_backend
Health endpoint      : GET https://<domaine>/api/  (ou /api/auth/me avec token) -> 200
Logs à inspecter     : docker logs -f journal_backend  (startup complet, pas d'exception import)
```

---

## 10. SMOKE TEST APRÈS DÉPLOIEMENT (fail-closed) — attendus
- [ ] Backend UP (logs « Application startup complete », pas d'ImportError).
- [ ] Login admin + driver OK (`/api/auth/me` 200).
- [ ] `GET /api/livre/driver/private-mode` (driver) → `allowed=false`, `reason=PRIVATE_MODE_FEATURE_DISABLED`.
- [ ] Expo : toggle Privé/Pro **absent** (feature OFF).
- [ ] Web : dashboard/historique normaux ; trajets Business avec adresses.
- [ ] Trajets privés historiques → **toujours redacted** (`private_redacted=true`, adresses null).
- [ ] Exports Business normaux ; export d'un trajet privé → « Privé — position masquée » (aucune adresse).
- [ ] Aucun 500 sur `/private-mode` ; aucun secret dans les logs.

---

## 11. TEST FAIL-CLOSED EN PROD (preuve obligatoire avant tout pilote)
Avec `PRIVATE_MODE_ENABLED=false` :
- [ ] `POST /api/livre/driver/private-mode {"mode":"PRIVATE"}` → **HTTP 403** `PRIVATE_MODE_FEATURE_DISABLED`.
- [ ] Aucun appel Navixy device émis (device write OFF).
- [ ] Expo toggle absent.
- [ ] Reste de l'app 100 % fonctionnel.

---

## 12. ACTIVATION PILOTE (préparé — ne pas exécuter) — surface minimale
```text
1 tenant  : <TENANT_ID réel du tracker pilote>   (à résoudre READ-ONLY en prod)
1 véhicule: tracker 3657864 (FMC003 field_validated)  [FMC130 781479 = après test terrain]
1 chauffeur (option) : le chauffeur assigné
```
Ordre :
```text
1. feature global      : PRIVATE_MODE_ENABLED=true
2. tenant allowlist     : PRIVATE_MODE_PILOT_TENANTS=<tenant>   (ou tenant.private_mode_pilot=true)
3. véhicule allowlist   : PRIVATE_MODE_PILOT_TRACKERS=3657864   (ou vehicle.private_mode_pilot=true)
4. capability vérifiée  : field_validated=true (déjà pour 3657864)
5. intégration Navixy   : credential du tenant présent (chiffré) + ALLOW_GLOBAL_NAVIXY_FALLBACK=false
6. kill switch prêt      : testé ON/OFF (voir §13)
7. SEULEMENT ensuite     : test chauffeur réel (§14)
```

---

## 13. KILL SWITCH (coupe immédiate du pilote)
```text
Activer   : POST /api/livre/private-mode/kill-switch {"active": true}   (admin)
Vérifier  : GET  /api/livre/private-mode/status -> {"kill_switch_active": true}
Désactiver: POST /api/livre/private-mode/kill-switch {"active": false}  (admin)
```
Comportement :
- Nouvelles activations : **refusées** (`HTTP 403 PRIVATE_MODE_KILL_SWITCH_ACTIVE`).
- Véhicule DÉJÀ en PRIVATE : **NON forcé** vers Professionnel automatiquement (la confidentialité
  n'est jamais coupée sans procédure maîtrisée — on ne révèle pas une position en catastrophe).
  Retour Pro = décision opérateur explicite.
- Indépendant d'une nouvelle version Expo (appliqué côté backend).

---

## 14. PLAN TEST TERRAIN (protocole seulement — aucune commande)

### FMC130 pilote (781479)
Pré-requis (déjà obtenus) : AVL16 exposé (sensor Navixy créé), précheck PASS.
Reste à faire terrain (sur GO) :
```text
1. État initial PRO (device online).
2. Lire config : GPS Data Masking = Data Sent As Zero (11813=1) [correction #2 requise], Odometer=Enable, Trigger=External.
3. Activer Privé (privatemode ON) — GATED, GO explicite.
4. Rouler ~2-5 km.
5. Vérifier données reçues : position transmise MASQUÉE (0,0 ou gelée) ; aucune position exploitable.
6. Vérifier AVL16 incrémente (distance privée = AVL16_fin - AVL16_début).
7. Retour PRO (privatemode OFF) — position réelle revient.
CRITÈRES PASS : online + GPS masqué + AVL16 +delta>0 + retour Pro confirmé + aucune position privée exposée.
CRITÈRES FAIL : GPS non masqué OU AVL16 non incrémenté OU retour Pro non confirmé.
```

### FMC003 (3657864) — déjà `field_validated`
```text
Re-confirmation légère (précheck PASS déjà obtenu). Cycle Privé/Pro identique.
PASS = mêmes critères ; la validation terrain FMC003 est déjà acquise (D3-B).
```

---

## 15. ROLLBACK (deux niveaux)

### Rollback CODE (problème logiciel / import / 500 généralisé)
```text
git checkout <commit_précédent>  &&  docker compose build journal_backend  &&  up -d
(ou redéployer l'image Docker sauvegardée en §6)
```

### Rollback FONCTIONNEL (problème pilote, sans toucher au code) — IMMÉDIAT
```text
PRIVATE_MODE_ENABLED=false           (coupe l'accès feature)
POST /private-mode/kill-switch {"active": true}   (bloque toute nouvelle activation)
```
Quand utiliser quoi :
- Bug de code / crash / fuite → **rollback CODE**.
- Comportement pilote indésirable, doute device → **rollback FONCTIONNEL** (instantané, sans redéploiement).

### Rollback DB (migration navixy_hash)
```text
Restaurer le snapshot Mongo pris en §6 (mongorestore).
(La migration ne fait que chiffrer du legacy plaintext -> réversible par decrypt, mais snapshot = voie sûre.)
```

---

## 16. CONDITIONS DE STOP
Ne pas passer à l'étape suivante si :
- tests pré-déploiement non verts ;
- backup absent ;
- `INVALID_ENCRYPTED > 0` au dry-run ;
- `INTEGRATION_ENCRYPTION_KEY` manquante ;
- backend health KO ;
- 500 sur `/private-mode` ;
- fuite de secret détectée ;
- soupçon cross-tenant ;
- capability device non validée ;
- GPS masking incorrect (terrain) ;
- odomètre privé non incrémenté (terrain).

---

## 17. MATRICE GO / NO-GO
| Étape | Statut actuel |
|---|---|
| CODE DEPLOYABLE | **GO** (tests verts, fail-closed) |
| BACKUP VALIDÉ | NO-GO (à faire en prod avant) |
| CRYPTO DRY-RUN | NO-GO (à exécuter en prod) |
| BACKEND HEALTH | NO-GO (post-déploiement) |
| FAIL-CLOSED PROD | NO-GO (à prouver post-déploiement) |
| TENANT PILOTE | NO-GO (tenant réel à résoudre) |
| VÉHICULE PILOTE | GO (3657864 field_validated) / FMC130 après terrain |
| CAPABILITY HARDWARE | GO (FMC003) / FMC130 après config #2 + terrain |
| KILL SWITCH | **GO** (implémenté + testé) |
| TEST TERRAIN | NO-GO (GO explicite requis) |
| PRODUCTION GÉNÉRALE | NO-GO |

---

## 18. ACTIONS NÉCESSITANT VOTRE GO (séparés)
1. **Save to Github** (pousser la branche `feat/private-mode-pilot`).
2. **Déploiement backend fail-closed** (pull + build + up + env §4, `PRIVATE_MODE_ENABLED=false`).
3. **Migration navixy_hash** : dry-run puis (sur GO séparé) apply après snapshot.
4. **Activation pilote** (allowlists + feature ON, surface minimale).
5. **Test terrain device** (privatemode réel, FMC130/FMC003).

> Rien n'est exécuté. Le package est prêt ; j'attends vos GO séparés.
