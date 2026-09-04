# Driver Private Mode — Pilot Feature Flag (PREPARATION ONLY)

> **Statut : ARCHITECTURE VALIDÉE (sur le principe) — AUCUNE IMPLÉMENTATION.**
> Décision utilisateur : **option (a)**. La divergence de base est acceptée comme
> une différence d'environnement. **Aucun seed fictif** pour `3657864`, **aucun
> substitut `tenant_id="default"`**. Implémentation bloquée jusqu'à résolution du
> vrai tenant dans l'environnement contenant réellement le tracker.

```
PRIVATE_MODE_GLOBAL               = DISABLED
REAL_DEVICE_COMMANDS              = MOCK / SIMULATION
PILOT_TARGETING                   = tenant_id + tracker_id
FAIL_CLOSED                       = TRUE
PILOT_TENANT_ID                   = UNRESOLVED_IN_THIS_FORK
PILOT_FEATURE_FLAG_IMPLEMENTATION = BLOCKED
NEXT_ACTION                       = RESOLVE_REAL_PILOT_TENANT_IN_TARGET_ENVIRONMENT
```

**Règles verrouillées pour la résolution du tenant (environnement cible, READ-ONLY) :**
Déterminer `TRACKER_ID`, `VEHICLE_ID`, `TENANT_ID`, `TENANT_NAME`, `SOURCE_OF_TRUTH`,
`RESOLUTION`. Seul `RESOLUTION = VERIFIED` autorise à renseigner l'allowlist pilote.
Ne pas utiliser de placeholder de production, ne pas fallback sur `default`, ne pas
déduire le tenant depuis le seul compte Navixy si le mapping canonique backend est
obtenable.

---

## 0. Résultat des pré-requis (ce cycle)

| Contrôle | Résultat |
|---|---|
| P0 — Redaction trajets PRIVATE (`/trips`, `/trips/{id}/track`) | **PASS** — aucune fuite réelle |
| Privacy hardening (variantes de champs + redaction récursive) | **PASS** — `PRIVATE_REDACTION_HARDENING = PASS` |
| Non-régression BUSINESS | **PASS** — `BUSINESS_NON_REGRESSION = PASS` |
| Tests unitaires privacy | **20/20 PASS** |
| Résolution `tenant_id` réel du tracker `3657864` | **NOT_FOUND** (voir §5) |

---

## 1. Objectif

Activer le Mode Privé **uniquement** pour des couples `tenant_id + tracker_id`
explicitement autorisés, avec le reste du parc **bloqué par défaut** (fail-closed).
Aucune activation implicite par modèle de device.

---

## 2. Règle d'autorisation (backend autoritaire)

Un véhicule est éligible au Mode Privé **si et seulement si TOUTES** les
conditions ci-dessous sont vraies :

```text
PRIVATE_MODE_GLOBAL == ENABLED                (kill switch global, défaut = DISABLED)
AND tenant_id       ∈ PILOT_TENANTS           (allowlist tenant)
AND tracker_id      ∈ PILOT_TRACKERS          (allowlist tracker)
AND vehicle_private_mode_allowed(vehicle) == TRUE   (capability gate existante)
AND capability.field_validated == TRUE        (validation terrain obligatoire)
```

- **Fail-closed** : en cas de doute, d'erreur, de donnée manquante ou de conflit
  → `allowed = false`.
- **Aucun défaut permissif** : aucun tracker n'est autorisé par défaut.
- **Aucune généralisation par modèle** : le PASS du `3657864` (FMC003) ne
  s'étend PAS aux autres FMC003, ni au FMC130.

---

## 3. Périmètre initial du pilote

```text
PILOT_TENANTS   = [ <TENANT_ID du tracker 3657864 — à VÉRIFIER, cf. §5> ]
PILOT_TRACKERS  = [ "3657864" ]           # FMC003 uniquement
OTHER_TRACKERS  = BLOCKED
```

- Seul le tracker `3657864` (FMC003) peut devenir autorisable.
- Tous les autres trackers restent bloqués.

---

## 4. Backend = autorité ; Frontend = affichage seulement

- Un endpoint backend renvoie l'éligibilité, ex. :
  `GET /api/livre/driver/private-mode` → `{ "allowed": true|false, "reason": "..." }`.
- Le frontend (mobile + web) n'affiche les boutons **Privé/Professionnel** que si
  le backend renvoie `allowed = true`.
- **Le frontend ne décide JAMAIS** sur la base du modèle ou du tracker_id.
- Toute tentative d'action alors que `allowed = false` → refus backend + audit.

---

## 5. Résolution du tenant réel (READ-ONLY) — **BLOQUANT**

Audit READ-ONLY exécuté sur la base de cet environnement (fork) :

```text
TRACKER_ID      = 3657864
VEHICLE_ID      = None
TENANT_ID       = None
TENANT_NAME     = None
FIELD_VALIDATED = None  (collection vehicle_private_capabilities ABSENTE ici)
SOURCE_OF_TRUTH = vehicles.navixy_tracker_id -> vehicles.tenant_id
RESOLUTION      = NOT_FOUND
```

Contexte de l'environnement courant : 6 véhicules de démo (trackers `5000–5005`),
tous `tenant_id = "default"`. Le tracker pilote `3657864` **n'existe pas** dans
cette base (données pilote présentes dans l'environnement d'origine/production).

**Conséquence (règle fail-closed) :**

```text
PILOT_FEATURE_FLAG_IMPLEMENTATION = BLOCKED
```

L'implémentation du feature flag reste **bloquée** tant que, dans
l'environnement cible (production), l'audit READ-ONLY ne renvoie pas :

```text
RESOLUTION      = VERIFIED
TENANT_ID       = <valeur réelle>
FIELD_VALIDATED = TRUE
```

> Script d'audit fourni (READ-ONLY, aucune écriture) :
> `/app/backend/scripts/resolve_pilot_tenant_3657864.py`

---

## 6. Mécanismes requis (à implémenter APRÈS validation + GO)

| Mécanisme | Description |
|---|---|
| Kill switch global | `PRIVATE_MODE_GLOBAL` — défaut `DISABLED`. Coupe le pilote instantanément. |
| Allowlist tenant | `PILOT_TENANTS` — liste explicite. Vide = personne. |
| Allowlist tracker | `PILOT_TRACKERS` — liste explicite. Vide = personne. |
| Capability gate | Réutilise la gate existante `field_validated = TRUE`. |
| Fail-closed | Toute incertitude → `allowed = false`. |
| Audit log | Journaliser chaque accès ET chaque refus (tenant, tracker, user, motif). |
| Désactivation immédiate | Basculer `PRIVATE_MODE_GLOBAL = DISABLED` doit désactiver tout le pilote sans redéploiement. |
| Rollback | Retour à l'état pré-pilote sans perte de données métier. |

**Stockage recommandé** (à décider avec vous) : configuration de flags en base
(collection dédiée, ex. `feature_flags`) plutôt qu'en dur, pour permettre le kill
switch et les allowlists sans redéploiement. Aucun secret dans le flag.

---

## 7. Tests exigés avant activation (préparation)

1. `PRIVATE_MODE_GLOBAL = DISABLED` → refus systématique.
2. Tenant non allowlisté → refus.
3. Tracker non allowlisté → refus.
4. Capability non `field_validated` → refus.
5. Seul `3657864` peut devenir autorisable (aucun autre FMC003/FMC130).
6. Cross-tenant → refus (isolation multi-tenant).
7. Aucun fallback permissif (défaut = refus).
8. Frontend ne montre les boutons que si backend `allowed = true`.

---

## 8. Interdits stricts (jusqu'à GO explicite)

- ❌ Activer `PRIVATE_MODE_GLOBAL`.
- ❌ Envoyer `privatemode ON/OFF`, `setparam`, `raw_command/send`.
- ❌ Modifier un device / un capteur / une intégration Navixy.
- ❌ Activer la production globale.
- ❌ Autoriser un tracker par défaut ou par déduction de modèle.

---

## 9. Sortie de statut

```text
PILOT_FEATURE_FLAG          = PREPARED (design validé pending)
GLOBAL_PRIVATE_MODE         = DISABLED
PILOT_TENANT_ALLOWLIST      = READY (valeurs à résoudre en prod)
PILOT_TRACKER_ALLOWLIST     = READY (["3657864"])
TRACKER_3657864             = ELIGIBLE (sous réserve VERIFIED + field_validated)
OTHER_TRACKERS              = BLOCKED
REAL_DEVICE_COMMANDS        = DISABLED
IMPLEMENTATION              = BLOCKED (tenant NOT_FOUND dans ce fork)
NEXT_ACTION                 = WAIT_FOR_EXPLICIT_PILOT_GO
```
