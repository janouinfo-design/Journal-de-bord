# AVL16 DASHBOARD CALIBRATION — PHASE B — PACKAGE DELTA VPS

> Fonction : un administrateur relève le kilométrage RÉEL du tableau de bord et l'utilise
> comme baseline absolue du Total Odometer Teltonika (AVL16). Les Km Pro/Privé se calculent
> ensuite exclusivement sur les deltas AVL16, jamais sur le compteur générique Navixy.
>
> **PHASE B = code + tests, AUCUN device réel, AUCUN déploiement, AUCUN setparam réel.**
> Le vrai `setparam 11807` sur le FMC130 `781479` reste soumis à un GO terrain séparé.

---

## AUDIT TELTONIKA (preuve, non supposé)

```
- device            : FMC130 (Configurator + wiki Teltonika)
- parameter 11807   : "Odometer Value"  (SUPPORTED = YES)
- unit              : KILOMÈTRES (entier)   ← on envoie des km, PAS des mètres
- range             : 0 .. 4 294 967
- command syntax    : "setparam 11807:<km>"  (alt. documentée : "odoset:<km>")
- calc source (11806): GNSS sélectionné  → c'est la source de l'AVL16 (avl_io_16)
- EXPECTED_AVL16_EFFECT : setparam 11807=X  →  AVL16 devient ≈ X km puis incrémente
- persistence       : à confirmer au test terrain (D_calibration)
```

## AVL16 (prouvé READ-ONLY sur 781479, véhicule roulant)

```
- raw AVL ID        : 16
- Navixy input      : avl_io_16   · sensor id : 5577108
- multiplier/divider: 1 / 1000    (raw mètres → km)  ← prouvé : raw/normalized = 1000.000
- incremental valid : OUI (+36.118 km sur ~2h30, monotone)
- ⚠️ compteur odometer Navixy générique (≈139 599) ≠ AVL16 (≈56 378) → NE PAS l'utiliser
```

---

## FICHIERS MODIFIÉS / CRÉÉS

| Fichier | Type | Déploiement |
|---|---|---|
| `backend/app/odometer_calibration.py` | NEW | ✅ DEPLOY (backend) |
| `backend/app/routes/odometer_calibration.py` | NEW | ✅ DEPLOY (backend) |
| `backend/app/routes/__init__.py` | MODIFIED (wire router) | ✅ DEPLOY (backend) |
| `frontend/src/pages/VehicleOdometerPage.jsx` | NEW | ✅ DEPLOY (frontend) |
| `frontend/src/pages/vehicleOdometerLogic.js` | NEW (logique fail-closed pure) | ✅ DEPLOY (frontend) |
| `frontend/src/pages/__tests__/vehicleOdometerLogic.test.js` | TEST_ONLY | ⛔ ne pas déployer |
| `frontend/src/App.js` | MODIFIED (route admin) | ✅ DEPLOY (frontend) |
| `frontend/src/pages/AdministrationLayout.jsx` | MODIFIED (onglet) | ✅ DEPLOY (frontend) |
| `backend/tests/test_odometer_calibration.py` | TEST_ONLY | ⛔ ne pas déployer |

---

## ARCHITECTURE (garanties)

```
- absolute baseline       : AVL16 (Total Odometer Teltonika) via setparam 11807 (km)
- distance source         : TELTONIKA_AVL16 (raw_avl_id=16, avl_io_16, ÷1000)
- Navixy generic odometer : JAMAIS utilisé comme source Pro/Privé pour ce profil
- calibration event       : CALIBRATION_EVENT append-only (jamais écrasé)
- false-delta protection  : safe_avl16_delta_km() renvoie None si une calibration
                            traverse l'intervalle → le saut (ex +83 242 km) n'est
                            JAMAIS compté comme distance. Deltas reprennent après baseline.
- confirmation réelle     : "command accepted" ≠ succès. odometer_calibrated=true seulement
                            si relecture AVL16 ≈ valeur demandée (tolérance 1 km).
```

## GATE DEVICE (verrou DÉDIÉ + allowlist pilote FAIL-CLOSED)

```
ODOMETER_CALIBRATION_DEVICE_WRITE  = 0         (défaut obligatoire, fail-closed)
ODOMETER_CALIBRATION_PILOT_TENANTS = default   (allowlist DÉDIÉE — absente => AUCUNE écriture)
ODOMETER_CALIBRATION_PILOT_TRACKERS= 781479    (allowlist DÉDIÉE — absente => AUCUNE écriture)

- Totalement INDÉPENDANT de PRIVATE_MODE_DEVICE_WRITE / PRIVATE_MODE_PILOT_* (prouvé par test).
- Une commande RÉELLE ne part QUE si TOUT est vrai :
    APP_ENV autorisé + DEVICE_WRITE=1 + tenant allowlisté + tracker allowlisté
    + véhicule canonique résolu + tracker lié exactement + capability AVL16
    + RBAC admin/superadmin + tracker online + valeur valide.
- Liste absente => refus (JAMAIS "tous autorisés").
- Sinon : aucune commande, aucun setparam, aucune calibration confirmée, baseline inchangée.
- Seul tracker 781479 / tenant default / FMC130 peut franchir la gate. Tout autre => REFUS.
```

## UI (fiche véhicule — /livre/administration/kilometrage)

```
- accès       : Admin + Superadmin uniquement (ProtectedRoute + require_roles backend)
                Manager/Driver/lecture_seule -> 403 (backend autoritaire)
- affichage   : Km télématique (AVL16) + Source "Teltonika AVL16" + dernière mise à jour
- FAIL-CLOSED : bouton "Synchroniser" actif SEULEMENT si can_calibrate === true (booléen strict).
                Aucun fallback sur device_write_enabled. false/null/undefined/absent/erreur GET
                -> bouton désactivé, aucun POST, aucun spinner, message "indisponible".
                openConfirm() garde aussi fail-closed (pas de dialogue si gate refuse).
- saisie      : "Kilométrage du tableau de bord" — ENTIER strict (décimale refusée, jamais tronqué)
- confirmation: dialogue 2 temps (valeur actuelle vs saisie + écart) — pas d'écriture auto
- avertissement: écart important (>= 1000 km) affiché avant confirmation
- historique  : liste append-only des calibrations (date, avant/saisie/après, résultat, auteur)
- jargon      : aucun terme technique (setparam/Navixy/Teltonika) exposé à l'écran
```

## BACKEND (endpoints)

```
GET  /api/livre/vehicles/{vehicle_id}/odometer            (admin) — état + historique READ-ONLY
POST /api/livre/vehicles/{vehicle_id}/odometer/calibrate  (admin) — calibration (GATED)
- multi-tenant strict (tenant du contexte serveur, jamais du frontend)
- device command : GATED + mocké en dev ; AVL16 verification : relecture cohérente
```

---

## TESTS

```
- backend total (calibration) : 16  → PASS 16 / FAIL 0   (T1..T14 + 2 extra)
- régression private-mode+capability : 73 → PASS 73 / FAIL 0
- testing_agent backend : PASS (RBAC, fail-fast, anti-faux-delta, multi-tenant confirmés)
- frontend : build production OK + lint OK
  (E2E navigateur de la page admin NON exécutable dans le fork — voir note ci-dessous)
```

> Note fork : la page `/livre/administration/kilometrage` vit sous `AppLayout` (auth cookie +
> nombreuses dépendances data) ; dans le fork, le superviseur sert l'app **Expo** et l'auth
> réelle/CORS empêchent un test navigateur authentifié. Validation front = build + lint + revue.
> Le smoke test post-déploiement (ci-dessous) couvre ce point sur le VPS.

---

## ENV (à ajouter — défauts sûrs, fail-closed)

```
ODOMETER_CALIBRATION_DEVICE_WRITE=0        # verrou dédié, défaut OFF (aucune commande)
ODOMETER_CALIBRATION_PILOT_TENANTS=default # allowlist tenant dédiée (absente => aucune écriture)
ODOMETER_CALIBRATION_PILOT_TRACKERS=781479 # allowlist tracker dédiée (absente => aucune écriture)
```
Le premier déploiement prod reste **WRITE=0** (lecture + UI + RBAC + historique + capability + tests).
Ne PAS activer WRITE=1 avant le GO terrain. Les allowlists n'ouvrent RIEN tant que WRITE=0.

## TESTS (mise à jour durcissement + UI fail-closed)

```
- backend calibration : 27 → PASS 27 / FAIL 0   (T1..T14 + T15..T24 gate + env)
- régression globale   : 100 → PASS 100 / FAIL 0
- frontend (Jest)      : 10 → PASS 10 / FAIL 0   (vehicleOdometerLogic : can_calibrate strict, no fallback)
- testing_agent backend: PASS (gate fail-closed, isolation tenant/tracker, anti-faux-delta, RBAC)
- testing_agent frontend: PASS (règle UI fail-closed, aucun fallback device_write_enabled)
```

## GO DÉPLOIEMENT PROD — WRITE OFF (à exécuter par l'utilisateur sur le VPS)

> ⚠️ L'agent n'a PAS accès au VPS. Les commandes ci-dessous sont à lancer par vous.

Configuration production (ne PAS activer WRITE avant GO terrain) :
```
ODOMETER_CALIBRATION_DEVICE_WRITE=0
ODOMETER_CALIBRATION_PILOT_TENANTS=default
ODOMETER_CALIBRATION_PILOT_TRACKERS=781479
```
Rebuild (uniquement ces 2 services) :
```
docker compose build journal_backend  && docker compose up -d journal_backend
docker compose build journal_frontend && docker compose up -d journal_frontend
```

## SMOKE TEST PROD (checklist à cocher par vous)

```
- backend healthy / frontend healthy
- Page /livre/administration/kilometrage chargée (admin) ; non visible pour chauffeur
- Véhicule pilote (LOGITRAK AUDI / 781479) visible ; Km AVL16 réel affiché ; source TELTONIKA_AVL16
- Historique accessible ; aucune erreur console importante
- Gate WRITE=0 : GET renvoie can_calibrate=false -> bouton DÉSACTIVÉ, aucune commande device
- RBAC : admin OK · superadmin OK · manager 403 · driver 403
- Isolation : aucun autre tracker calibrable (can_calibrate=false partout sauf, plus tard, 781479 si WRITE=1)
- PREUVE DEVICE : setparam 11807 réel envoyé = NON · tracker 781479 modifié = NON · autres = NON
```

## COMMANDES VPS (DELTA)

```bash
docker compose build journal_backend  && docker compose up -d journal_backend
docker compose build journal_frontend && docker compose up -d journal_frontend
```

## SMOKE TEST POST-DÉPLOIEMENT

```
- Login admin -> onglet Administration -> "Kilométrage" visible (chauffeur : non visible / 403).
- Sélection FMC130 -> Km télématique (AVL16) affiché, source "Teltonika AVL16".
- Saisie décimale (139620.8) -> message "kilométrage ENTIER" (jamais tronqué).
- Saisie entière (ex 139620) -> avertissement d'écart -> dialogue de confirmation.
- Avec ODOMETER_CALIBRATION_DEVICE_WRITE=0 : "Confirmer" -> message "indisponible",
  aucune commande device, historique inchangé.
```

---

## STATUS

```
- calibration code        : READY
- CALIBRATION_EVENT        : READY
- anti-faux-delta          : READY
- RBAC (admin/superadmin)  : READY
- verrou device dédié      : READY (défaut OFF, découplé du Mode Privé)
- tests                    : PASS (16 calibration + 73 régression + testing_agent)
- device réel modifié      : NON
- production déployée      : NON
- ready field test FMC130  : OUI (protocole D_calibration à lancer sur GO terrain séparé)
```

## CRITÈRE DE FIN — respecté

Le kilométrage du tableau de bord peut devenir la baseline absolue AVL16 **sans créer de
faux kilomètres** (CALIBRATION_EVENT + `safe_avl16_delta_km`), puis tous les km Pro/Privé
se calculent uniquement à partir des deltas AVL16 réellement reçus. **Aucun device réel
touché ; aucun déploiement.** Le vrai `setparam 11807` reste soumis à un GO terrain séparé.
