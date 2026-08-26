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

## 26/08/2026 (après-midi) — GARDE-FOU BEV : legacy 0,085 L/km filtré par motorisation

### Règle métier (centralisée dans app/navixy_sync.py)
- `POWERTRAIN_FROM_FUEL_TYPE` (mapping canonique unique, réutilisé par routes/energy.py — plus de duplication)
  + `powertrain_from_fuel_type()` + `legacy_fuel_estimation_allowed(vehicle)`.
- Source motorisation : UNIQUEMENT `vehicles.fuel_type` (jamais nom/modèle/plaque/label).
- ICE (ice/diesel/essence/petrol) → legacy autorisé.
- BEV (electric/bev/ev) → legacy INTERDIT → fuel_l ABSENT (jamais 0).
- HEV/PHEV → cas ambigu, aucune convention 8,5 L/100 validée pour hybrides → PAS de calcul (documenté).
- UNKNOWN → legacy CONSERVÉ (dette résiduelle documentée : flotte actuelle 0/18 motorisations
  renseignées, fiscalité existante préservée). UNKNOWN jamais converti en BEV/ICE.
- `_build_trip_doc` : fuel_l écrit conditionnellement. AUCUNE migration Mongo (historique intact,
  pilot trip fuel_l=0.66 vérifié). Seed mock démo : véhicules sans fuel_type → UNKNOWN → inchangé.

### Affichages corrigés (absence fuel_l → jamais 0)
- HistoryPage : « — » (testid trip-fuel-na-{id}) au lieu de 0.00 L.
- reports.py : CSV/XLSX cellule vide (t.get("fuel_l") sans défaut 0) ; PDF trajets « — ».
- Totaux/PDF fiscal : sommes inchangées (un BEV ne contribue aucun litre — vérifié tax-swiss 2023 test).

### Tests
- Nouveau `tests/test_legacy_fuel_guard.py` : 22/22 PASS (T1-T15 sauf T11 UI ; helper, _build_trip_doc,
  historique intact, API trips null, exports CSV/XLSX/PDF, PDF fiscal, TripEnergyBlock indépendant).
- RÉGRESSION COMPLÈTE : 603 PASS / 0 FAIL réel / 3 SKIP (1 flaky infra : OCR amendes 502 ingress
  preview pendant appel Gemini — 5/5 PASS en re-run isolé, module non touché par le lot).
- Testing agent iteration_30.json : 5/5 PASS frontend (HistoryPage —/8.50 L, TripEnergyBlock honnête,
  exports XLSX vide + PDF —, non-régression Énergie : AUDI 28.0 L Périmé, motorisations Inconnue).
- real_energy_validated : toujours false (flag non modifié). Projet ÉNERGIE non modifié. Mongo non migré.

### Dette résiduelle / P-liste
- P2 : UNKNOWN reçoit encore le legacy (par choix documenté) — se résorbera quand fuel_type sera renseigné.
- P3 : total fiscal d'une période 100% BEV afficherait « 0.00 » (somme réelle vide) — cosmétique, non traité.
- P3 : date inputs natifs (mm/dd/yyyy) au lieu du Calendar shadcn (pré-existant, relevé 2× par testing agent).

## 26/08/2026 (soir) — MOTORISATIONS RÉELLES : vehicles.fuel_type depuis sources prouvées

### Sources examinées (18 véhicules, lecture seule d'abord)
- Source A (DB structurée) : fuel_type 0/18, VIN 0/18, pas de powertrain/engine_type.
  tank_capacity_l=65 sur « 1-Enyaq 01 Bern » (saisie référence capacité, PAS une preuve de motorisation).
- Source B (VIN) : NON DISPONIBLE (0/18 + aucun décodeur VIN configuré).
- Source C (Documents) : NON DISPONIBLE (aucune collection documents véhicule).
- Source D (Navixy garage, API réelle vehicle/list) : 10 véhicules Navixy, 5 liés par tracker_id.
  2 avec champ structuré fuel_type : Audi A3 2018 (tracker 781479) = petrol + « Sans plomb 95 » +
  VIN WAUZZZ8VJA151370 ; Toyota Previa (tracker 3131157) = petrol (VIN non normalisé, non utilisé).
- Source E (Energy) : powertrain UNKNOWN partout — rien d'utilisable, non falsifié.

### Écritures (2/18, via nouvel endpoint audité)
- LOGITRAK AUDI → fuel_type=essence (normalisation canonique petrol→essence, mapping ICE).
- 5-Alliance 01 → fuel_type=essence.
- 16 restants → UNKNOWN (dont Zoe/Enyaq×3/Volvo EX30 : noms évocateurs, déduction INTERDITE ;
  6 GE-* archivés démo ; iPhone/Tab traceurs ; ORHAN/IVAN/NEDIR sans source).

### Code
- Backend misc.py : PUT /api/livre/vehicles/{id}/fuel-type — admin only, valeurs contrôlées
  (diesel/essence/hybrid/phev/electric/null), audit vehicle.fuel_type_updated (before/after/source).
- Frontend SettingsPage : colonne « Motorisation » (Select contrôlé, admin only, manager disabled)
  dans le sheet Gérer les véhicules. testid settings-vehicle-fueltype-{plate}.
- Aucun changement du helper garde-fou. Aucun recalcul des 5 435 trips historiques.
- Effet dérivé attendu : rapprochement affiche AUDI/Alliance = Thermique (ICE) ; Energy garde
  son powertrain UNKNOWN (JOURNAL=ICE vs ENERGY=UNKNOWN documenté, aucune falsification).

### Tests
- tests/test_vehicle_fuel_type.py : 17/17 PASS (T1-T18 ; T UI via testing agent).
- 1 test legacy adapté : test_powertrain_never_inferred (powertrain == mapping du fuel_type prouvé).
- RÉGRESSION COMPLÈTE : 621 PASS / 0 FAIL / 3 SKIP (run final propre ; flaky OCR infra 502 re-testé 5/5).
- Testing agent iteration_31 : 5/5 PASS (colonne, valeurs, edit admin + restauration, RBAC manager
  disabled, rapprochement Thermique + 28.0 L Périmé conservé, historique intact).

### P3 notés (testing agent, non corrigés — hors périmètre)
- Flicker du sheet véhicules après changement (load() complet au lieu d'un update local).
- Double mécanisme RBAC dans la même table (canEdit vs role==='admin').
- SettingsPage.jsx 527 lignes (extraction composant possible).
