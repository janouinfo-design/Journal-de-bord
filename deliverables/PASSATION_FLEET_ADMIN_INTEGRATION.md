# PASSATION — Intégration FLEET ADMIN (`documents`) ↔ Journal-de-bord

> Document de passation officiel du dépôt **Journal-de-bord** vers la future session
> Emergent sur **`janouinfo-design/documents`** (FLEET ADMIN).
> Objectif : afficher, dans la fiche véhicule FLEET ADMIN, les documents ajoutés
> depuis l'app chauffeur (Journal), en **lecture seule (V1)**.
>
> ⚠️ Côté Journal : **RIEN à modifier** tant que l'audit `documents` n'a pas
> déterminé l'architecture d'auth ET la clé de jointure véhicule.

---

## 0. Statut Journal-de-bord (clôturé)

| Livrable | Statut |
|---|---|
| Mode Privé 0009 (confirmation télémétrie + anti-stale) | ✅ PROD + validé terrain + `main` |
| Lot 1 Vehicle Assignments (backend, affectation persistante) | ✅ PROD + `main` |
| Lot 2 Mobile (affectation + END-safety + fix spinner) | ✅ PROD + validé terrain (APK pilote) + `main` |
| Fédération Documents chauffeur → gestionnaire (contrat V1) | ✅ PROD + `main` |
| Audit READ-ONLY du contrat d'intégration | ✅ Clôturé |

**Aucun CORS à modifier, aucune auth à changer, aucun nouvel endpoint** tant que
l'audit `documents` n'a pas tranché l'architecture et la clé de jointure.

---

## A. Contrat V1 (FIGÉ — PROD `https://journal.logitrak.ch`)

Endpoints (réservés rôles **admin** ou **manager**) :

```
GET /api/livre/admin/vehicle-documents
GET /api/livre/admin/vehicle-documents/{id}/download
```

Filtres optionnels sur la liste : `?vehicle_id=<id>` · `?status=a_traiter|valide|expire`

### Exemple de réponse (`GET /admin/vehicle-documents`)

```json
{
  "count": 3,
  "vehicles": [
    {
      "vehicle_id": "995ee4d5-...",
      "vehicle_plate": "LOGITRAK AUDI",
      "vehicle_model": "telfmu130_fmc130",
      "vehicle_label": null,
      "documents": [
        {
          "id": "8b531677-...",
          "type": "autre",
          "filename": "4016.jpg",
          "content_type": "image/jpeg",
          "size_bytes": null,
          "status": "a_traiter",
          "document_date": null,
          "expiry_date": null,
          "created_at": "2026-09-23T08:54:30Z",
          "created_by": "orhan@logitrak.ch",
          "added_by_label": "Orhan",
          "source": "MOBILE_DRIVER",
          "download_url": "/api/livre/admin/vehicle-documents/8b531677-.../download"
        }
      ]
    }
  ]
}
```

`GET /admin/vehicle-documents/{id}/download` → fichier binaire (`Content-Disposition: attachment`).

### Champs d'identité véhicule exposés par le contrat V1
- `vehicle_id` : **UUID interne Journal** (`db.vehicles.id`)
- `vehicle_plate` : immatriculation
- `vehicle_model` : modèle
- ❌ **VIN non exposé** dans V1 (à ajouter plus tard SI retenu comme clé de jointure)
- ❌ **`navixy_tracker_id` non exposé** dans V1

---

## B. Authentification Journal (prouvé par le code)

| Élément | Valeur |
|---|---|
| Algorithme JWT | **HS256** (symétrique) |
| Secret | `JWT_SECRET` (Journal) |
| Claims | `sub` (user_id), `email`, `role`, `exp`, `type="access"` |
| Issuer (`iss`) | **AUCUN** |
| Audience (`aud`) | **AUCUN** |
| Lecture du token | Header `Authorization: Bearer <token>` (prioritaire) OU cookie `access_token` (httpOnly, secure, samesite=none) |
| Validation | `jwt.decode(token, JWT_SECRET, algorithms=["HS256"])` + `type=="access"` + `sub` existe dans `db.users` du backend cible + tenant = `user.tenant_id` |
| Rôle requis | `admin` ou `manager` |

**Conséquence critique** : un JWT FLEET ADMIN n'est accepté par Journal QUE si
(1) signé avec le MÊME `JWT_SECRET`, (2) `sub` = user existant dans `db.users` Journal,
(3) `role ∈ {admin, manager}`, `type=access`, non expiré.
→ **Compatibilité FLEET ADMIN ↔ Journal À PROUVER** dans le dépôt `documents`.
Interdits React : `JWT_SECRET`, credentials de service, token admin permanent, secret inter-service.

---

## C. CORS Journal (valeurs runtime PROUVÉES — INCHANGÉES)

| Environnement | `APP_URL` | `CORS_ORIGINS` |
|---|---|---|
| **PROD** (`journal_backend`) | `https://journal.logitrak.ch` | `https://journal.logitrak.ch` |
| **Preview** (`journal_preview_backend`) | `http://127.0.0.1:3102` | `http://127.0.0.1:3102` |

- Middleware : `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`,
  `allow_origins = CORS_ORIGINS.split(",")`.
- Le domaine FLEET ADMIN n'est PAS autorisé pour un appel navigateur direct.
- ⚠️ **Ne PAS modifier CORS maintenant.** Si l'architecture retenue est
  `backend FLEET ADMIN → backend Journal` (server-to-server), le navigateur
  n'appelle pas Journal → CORS potentiellement non requis pour ce flux.
- `allow_credentials=True` impose une **liste explicite** d'origines (jamais `*`).

### JWT_SECRET (empreintes prouvées)
- PROD `JWT_SECRET_SHA256` == Preview `JWT_SECRET_SHA256` (valeur identique).
- Conclusion autorisée : « PROD et Preview utilisent la même valeur de `JWT_SECRET` ».
- Ne PAS en déduire la compatibilité FLEET ADMIN (à prouver séparément).

---

## D. Clé de jointure véhicule — ORDRE DE PRÉFÉRENCE (RÈGLE CORRIGÉE)

> ⚠️ **`navixy_tracker_id` identifie le TRACEUR, PAS le VÉHICULE.**
> Un boîtier FMC130 remplacé / déplacé / réaffecté change le `navixy_tracker_id`
> alors que le véhicule reste le même. Ne PAS l'utiliser comme clé véhicule sans
> preuve que l'historique d'affectation traceur↔véhicule est maintenu.

**Ordre de préférence (du plus fiable au moins fiable) :**
1. **UUID véhicule commun** aux deux applications (s'il existe).
2. **VIN** — s'il est présent, **normalisé et unique** (identifiant intrinsèque, stable à vie).
3. **Identifiant métier véhicule partagé** (référence flotte commune).
4. **`navixy_tracker_id`** — **uniquement si** FLEET ADMIN prouve qu'il maintient
   correctement l'**historique d'affectation traceur↔véhicule**.
5. **Plaque** — rapprochement **secondaire/manuel uniquement** (jamais clé automatique).

**À vérifier explicitement dans `documents`** :
- Auditer **VIN** ET **`navixy_tracker_id`** côté FLEET ADMIN.
- Déterminer si le traceur est modélisé comme :
  - **attribut FIXE du véhicule** (→ tracker_id fragile comme clé), OU
  - **affectation ÉVOLUTIVE** (→ historique maintenu, tracker_id utilisable avec précaution).

> Note Journal : Journal ne garantit pas ici l'historique d'affectation traceur↔véhicule.
> Le **VIN** (si présent des deux côtés) reste la clé la plus robuste.

---

## E. Architecture d'intégration à privilégier (à décider dans `documents`)

```
React FLEET ADMIN  →  Backend FLEET ADMIN  →  Backend Journal
```

Ordre d'analyse :
1. **Backend FLEET ADMIN → Backend Journal** (server-to-server) — privilégié.
2. **Compte de service Journal borné** (scopes limités), server-to-server.
3. **SSO / auth commun** à terme.
4. Partage direct du `JWT_SECRET` — **dernier recours**, seulement si justifié après analyse sécurité.

**Éviter par défaut** : `React → Journal` en direct (couplage + secret exposé + CORS).

---

## F. Ajout futur éventuel au contrat V1 Journal (APRÈS audit `documents`)

Si la clé de jointure retenue nécessite un champ non exposé par V1
(ex. **VIN**, ou `navixy_tracker_id` avec précautions) :
→ revenir dans le dépôt **Journal** pour l'**ajouter au contrat V1** (petit ajout backend + redéploiement).
**Rien maintenant** — décision spéculative interdite avant preuve de la clé.

---

## G. Hors scope (reporté)
- Inspections (photos d'anomalies) — étape 2, après validation des documents.
- Migration / synchronisation / write-back / suppression / modification depuis FLEET ADMIN.
- V1 FLEET ADMIN = **lecture seule** (afficher, prévisualiser si possible, télécharger).

---

## H. Prompt d'audit à coller dans la session `documents`

> On travaille uniquement dans `janouinfo-design/documents` (FLEET ADMIN).
> **AUDIT READ-ONLY UNIQUEMENT** : ne rien coder, ne rien déployer, ne modifier
> aucune variable d'env / base / endpoint. Aucun secret affiché. Aucune hypothèse
> présentée comme un fait ; tout point non vérifié = **NON VÉRIFIÉ**.
>
> Contexte : le backend Journal expose déjà en PROD le contrat V1 (voir sections A/B/C).
>
> Livrer un rapport structuré :
> **A. Architecture** (frontend/backend/DB/env/déploiement/domaines Preview+PROD, chemins exacts).
> **B. Fiche véhicule** (route, page, composants, onglet Documents, appels API).
> **C. Documents** (modèle existant, stockage, endpoints, UI).
> **D. Identité véhicule** — tableau { Champ FLEET ADMIN · valeur/exemple · existe dans Journal ? · peut servir de jointure ? · preuve }. **Auditer VIN ET navixy_tracker_id.** Déterminer si le traceur est un **attribut fixe** du véhicule ou une **affectation évolutive**. Appliquer l'ordre de jointure : UUID commun → VIN → id métier → tracker_id (si historique maintenu) → plaque (manuel). **Ne pas inventer de mapping.**
> **E. Auth** (login, JWT/session/cookie, algo, empreinte non sensible du secret, claims, iss/aud, base users, rôles, tenant, middleware, client API).
> **F. Compatibilité avec Journal** : COMPATIBLE / NON COMPATIBLE / NON VÉRIFIÉ (preuves). Ne pas modifier les secrets pour rendre compatible.
> **G. Architecture recommandée** (comparer React→Journal vs Backend→Journal vs compte de service vs SSO ; avantages/risques ; server-to-server privilégié ; jamais de secret dans React).
> **H. Fichiers à modifier lors de l'implémentation** (liste précise) + **Risques/blocages** (NON VÉRIFIÉ).
>
> À la fin : `git status`, branche, HEAD, confirmation **0 fichier modifié**.

---

## I. Point décisif à retenir

Le résultat de l'audit `documents` (surtout **VIN** + modélisation du traceur +
mécanisme d'auth) déterminera :
1. La **clé de jointure** fiable (idéalement VIN ou UUID commun, PAS tracker_id seul).
2. L'**architecture d'auth** (server-to-server privilégié).
3. Si un **ajout au contrat V1 Journal** (ex. exposer le VIN) est nécessaire → seule
   action éventuelle à faire revenir côté Journal.

**Journal-de-bord est officiellement clôturé jusqu'à cette décision.**
