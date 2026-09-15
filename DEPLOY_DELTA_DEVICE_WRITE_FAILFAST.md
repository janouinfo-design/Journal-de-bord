# DEVICE_WRITE=0 — FAIL-FAST FIX + KM SUMMARY STABILITY — PACKAGE DELTA VPS

> Objectif du correctif :
> 1. `PRIVATE_MODE_DEVICE_WRITE=0` → refus **immédiat** de toute bascule, **aucun**
>    état `PRIVATE_REQUESTED` / `BUSINESS_REQUESTED` / `PENDING_CONFIRMATION`, **aucune**
>    commande device, état confirmé précédent **conservé** (BUSINESS reste BUSINESS,
>    PRIVATE reste PRIVATE, UNKNOWN reste UNKNOWN).
> 2. Les cartes **Km Pro / Km Privé** ne disparaissent **jamais** pendant une transition,
>    une erreur ou un refetch. `N/A` si donnée réellement absente ; jamais de `0` inventé.
>
> **Aucun device réel touché. Aucune variable `.env` prod à modifier.**

---

## FICHIERS RÉELLEMENT MODIFIÉS

| Fichier | Type | Déploiement |
|---|---|---|
| `backend/app/private_mode_gate.py` | MODIFIED | ✅ DEPLOY (backend) |
| `backend/app/private_mode_engine.py` | MODIFIED | ✅ DEPLOY (backend) |
| `backend/app/routes/identification.py` | MODIFIED | ✅ DEPLOY (backend) |
| `frontend/src/pages/DriverConsolePage.jsx` | MODIFIED | ✅ DEPLOY (frontend) |
| `backend/tests/test_private_mode_phase2.py` | TEST_ONLY | ⛔ NE PAS déployer en prod (tests) |
| `backend/tests/test_private_mode_confirmation.py` | TEST_ONLY | ⛔ NE PAS déployer en prod (tests) |

> NB : l'app **Expo** (`/app/logitrak-driver-app`) n'est **PAS** touchée par ce correctif.

---

## DÉTAIL DES CHANGEMENTS

### Backend

**`private_mode_gate.py`**
- Ajout des raisons normalisées :
  - `R_DEVICE_WRITE_DISABLED = "PRIVATE_MODE_DEVICE_WRITE_DISABLED"` → HTTP `503`
  - `R_TRANSITION_IN_PROGRESS = "PRIVATE_MODE_TRANSITION_IN_PROGRESS"` → HTTP `409`
- Distinction claire **éligibilité** (`allowed`) vs **capacité d'action** (`can_switch`).

**`private_mode_engine.py` → `request_mode()`**
- Ordre de contrôle : gate centrale → idempotence → anti-concurrence → **FAIL-FAST écriture device**.
- Si `device_write_enabled()` est `False` : retour immédiat
  `{ok:false, allowed:true, can_switch:false, reason:"PRIVATE_MODE_DEVICE_WRITE_DISABLED", http:503, state:<inchangé>}`
  **AVANT** toute persistance d'état transitoire et **avant** tout `send_command`.
- L'idempotence (déjà dans l'état cible) reste un no-op `ok:true` (aucune commande), même write OFF.

**`routes/identification.py`**
- `GET /driver/private-mode` : expose désormais `can_switch` + `can_switch_reason`.
  - `can_switch = allowed AND device_write AND pas de transition en cours`.
  - Éligible mais write OFF → `can_switch=false`, `can_switch_reason="PRIVATE_MODE_DEVICE_WRITE_DISABLED"`.
- `POST /driver/private-mode` : garde-fou → lève `HTTP 503 PRIVATE_MODE_DEVICE_WRITE_DISABLED`
  si l'engine renvoie ce refus (le frontend désactive normalement déjà le bouton).

### Frontend (`DriverConsolePage.jsx`)

- **KM découplés du Mode Privé** : état `{pro, priv, label, hasValid, initialLoading, refreshing}`.
  - Refetch **non destructif** : erreur/timeout/refresh ne remettent **jamais** les km à vide.
  - `available:false` (aucun véhicule) → `N/A`. `null` ≠ `0` (jamais de 0 inventé).
  - Purge des km au **changement de véhicule** (pas de contamination A→B).
  - Indicateur discret « Actualisation… » pendant un refetch (sans masquer les chiffres).
- **`can_switch`** pilote l'activation des boutons (plus seulement `allowed`).
  - Write OFF → boutons grisés + message « Le changement de mode est temporairement indisponible. ».
  - Clic sur bouton désactivé → message immédiat, **aucun POST**, **aucun spinner infini**.
- Après une action : refetch **séparé** de l'état ET des km (non bloquant, non destructif).

---

## ENV (INCHANGÉ — NE RIEN MODIFIER)

```
APP_ENV=production
PRIVATE_MODE_ENABLED=true
PRIVATE_MODE_DEVICE_WRITE=0
ALLOW_GLOBAL_NAVIXY_FALLBACK=false
```

Aucune nouvelle allowlist, aucune migration DB, aucun changement crypto, aucune action device.

---

## COMMANDES VPS (DELTA)

> Backend **et** frontend modifiés → rebuild des deux services applicatifs.

```bash
# Backend
docker compose build journal_backend
docker compose up -d journal_backend

# Frontend (React web — journal.logitrak.ch/driver)
docker compose build journal_frontend
docker compose up -d journal_frontend
```

*(N'appliquez que le service pertinent si votre compose sépare différemment ; ne rebuildez pas les autres services.)*

---

## SMOKE TEST POST-DÉPLOIEMENT

```
backend healthy
frontend healthy

GET  /api/livre/driver/private-mode
  -> allowed = true
  -> can_switch = false
  -> can_switch_reason = PRIVATE_MODE_DEVICE_WRITE_DISABLED

POST /api/livre/driver/private-mode {mode:"PRIVATE"}
  -> refus immédiat (503) OU bouton déjà désactivé (aucun POST)
  -> état précédent conservé (aucun *_REQUESTED, aucun PENDING)
  -> aucune commande device

UI Chauffeur :
  -> Km Pro / Km Privé restent visibles (transition, erreur, refresh)
  -> boutons PRO/PRIVÉ non bloqués indéfiniment
  -> message « Le changement de mode est temporairement indisponible. »
  -> aucun jargon technique visible
```

---

## VALIDATION EFFECTUÉE EN FORK (avant déploiement)

- **Backend** : `pytest` 54/54 PASS (dont 6 nouveaux tests fail-fast dédiés).
- **Frontend** : build production OK ; test navigateur (build réel, API mockée) :
  - Km Pro/Privé affichés (842 / 117 km) ; conservés après clic + après erreur 500.
  - `can_switch=false` → bouton Privé grisé + message honnête, sans spinner.
  - `can_switch=true` → bouton activé.
  - Km `null` → **N/A** (jamais `0`).

> Un test navigateur **authentifié en prod** reste à la charge du smoke test post-déploiement
> (l'environnement fork ne dispose pas d'une session chauffeur/pilote réelle).
