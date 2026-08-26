# CHANGELOG — Livre de bord LOGITRAK

## 26/08/2026 — MAPPING TENANT ENERGY + CAMPAGNE REAL ENERGY (energie.logitrak.ch)

### Contexte
- Le projet ÉNERGIE (externe, jamais modifié depuis ce workspace) est déployé en production
  sur le VPS utilisateur : `https://energie.logitrak.ch` (TLS valide, auth Bearer active).
- `backend/.env` : `ENERGY_API_BASE_URL=https://energie.logitrak.ch` (bascule depuis l'URL preview),
  `ENERGY_API_TOKEN` inchangé (64 car., jamais affiché).

### Lot mapping tenant (vérifié puis complété)
- `settings.energy_tenant_id` par tenant Journal (doc settings tenant-scoped via proxy Mongo),
  fail-closed : AUCUN appel HTTP Energy tenant-specific sans mapping explicite. Pas de variable globale.
- Routes : GET/PUT `/api/livre/energy/tenant-mapping` (GET admin+manager, PUT admin seul,
  validation `^[A-Za-z0-9_.-]{1,64}$`, audit `log_audit` sans token).
- Fail-closed appliqué dans `/status`, `/trips`, `/overview` et `_build_reconciliation`
  (preview + exports + candidats d'alertes).
- Mapping persisté via PUT admin audité : `default → paas_13588`. Client Test B : AUCUN mapping
  (fail-closed prouvé, aucune fuite des données paas_13588).
- UI : `EnergyTenantCard.jsx` dans Paramètres (admin modifie, manager lecture disabled,
  chauffeur/lecture_seule sans accès page ; badge Configuré/Non configuré ; jamais de token).

### Correctifs client Journal prouvés pendant la campagne (energy_client.py)
1. Batch : Energy résout le véhicule par `ref` (= navixy_tracker_id) + fenêtre `start`/`end`
   → items wire enrichis (`ref`, `start`, `end`), champs Journal conservés.
2. Vehicle summary : `{ref}` du path = navixy_tracker_id (le query param n'est PAS résolu par Energy).

### Correctifs exports/UI
- `reports.py` : suffixe « (périmé) » sur le type de mesure quand availability=STALE (XLSX + PDF rapprochement).
- `EnergyOverviewPage` : « contrat vv1 » corrigé, unité technique `count` masquée.
- `EnergyReconciliationPage` : nesting <div> dans <p> corrigé (drawer).
- `TripEnergyBlock` : REASON_LABEL += no_per_trip_energy, mapping_invalid, energy_tenant_not_configured.

### Preuves HTTP réelles (agent-tested, https://energie.logitrak.ch)
- Health : 200, contract_version "v1" (ÉCART documenté vs batch "1.0"), navixy_configured true.
- Auth : sans token 401 / bon token 200.
- Batch direct : contract "1.0", fuel/electric DIRECTS, pas de clé `energy`, null jamais 0,
  ref 781479 résolu, ref 999999 → mapping_invalid, powertrain UNKNOWN conservé.
- Fleet : 6 métriques exactes (nulls honnêtes, obd_coverage 25% ESTIMATED, vehicles_with_data 3).
- Vehicle 781479 : fuel_liters_total 28.0 L / STALE / MEASURED / NAVIXY_CAN (ts 2024-06-20).
- Via Journal : batch trip pilote → UNAVAILABLE `no_per_trip_energy` (honnête, tracker résolu) ;
  overview réel ; rapprochement 18 lignes / 6 non mappés, AUDI 28.0 L badge Périmé, statut
  IMPOSSIBLE (0 achat carburant — achats ≠ conso respecté) ; XLSX « Mesuré (périmé) » ;
  PDF rapprochement conforme ; PDF fiscal « Estimé* » conservé.
- Résilience réelle : Energy down (404 avant déploiement VPS) → indisponibilité propre, rien inventé.

### Tests
- Ciblés : 26/26 PASS (test_energy_tenant_mapping complet avec Energy réel + test_energy_contract).
- 6 tests legacy adaptés (comportement voulu : fail-closed avant trip_not_found, mode connecté réel,
  suffixe (périmé), raison batch appartenant à Energy).
- RÉGRESSION COMPLÈTE : **582 PASS / 0 FAIL / 3 SKIP** (run isolé propre).
  Note : 1 faux échec `test_no_dispatch_to_notifications` lors de 2 runs pytest concurrents
  (course sur notifications_log par événements ble.resolved d'une autre suite) — 41/41 PASS en isolation,
  la préparation d'alertes ne touche JAMAIS notifications_log.
- Testing agent frontend iteration_29.json : **7/7 PASS** (carte tenant admin/manager, RBAC chauffeur,
  overview réel sans zéro, rapprochement réel + badge Périmé, exports téléchargés, bloc trajet honnête).
  Mapping production restauré par le testing agent après son test d'écriture.

### Décision real_energy_validated : FALSE (inchangé)
Bloquants exacts :
1. Energy ne fournit pas encore d'énergie PAR TRAJET (no_per_trip_energy honnête) —
   la consommation réelle par trajet n'est pas prouvable aujourd'hui.
2. Risque legacy latent BEV : 0,085 L/km appliqué à la synchro sans filtre motorisation
   (aucun BEV actuel ; jamais présenté comme mesuré — étiqueté Estimé partout).
3. Le GO utilisateur exigeait explicitement « real_energy_validated reste false » — flip
   uniquement sur décision utilisateur explicite.

### Risques externes Energy (P1, non modifiables d'ici)
- Energy accepte un tenant optionnel avec fallback tenant par défaut côté Energy
  (prouvé : mapping sans tenant → tenant Energy par défaut avec les 12 trackers).
  Neutralisé côté Journal par tenant explicite fail-closed.
- Écarts contrat : health "v1" vs batch "1.0" ; fleet/vehicle summary sans contract_version.

### Non modifié (conformément aux règles)
Projet ÉNERGIE, legacy 0,085 (navixy_sync.py:39/275), 6 véhicules non mappés,
Mongo historique (5 421 trips), PDF fiscal legacy, alertes réelles (désactivées),
real_energy_validated (false).
