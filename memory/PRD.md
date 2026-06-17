# Logitrak — Livre de Bord Professionnel / Personnel

## Problem statement (verbatim)
Créer un nouveau module "Livre de Bord Professionnel / Personnel" dans Logitrak,
entièrement connecté à Navixy via les API de tracking et l'historique GPS.
Distinction km pro / perso, 3 modes confidentialité, rapport fiscal suisse,
affectation manuelle, droits par rôle.

## User choices
- Standalone app, JWT custom auth, backend Python (reportlab + openpyxl)
- Navixy hash fourni (`a25480874b7492bd01ff1d926061e491`) — branché en prod (api.navixy.com/v2)

## Architecture (mise à jour)
- **Backend**: FastAPI + Motor + APScheduler. Modules `/app/backend/app/` :
  `auth.py`, `db.py`, `mock_navixy.py`, `rules.py`, `reports.py`, `routes.py`,
  `navixy_client.py` (HTTP async httpx), `navixy_sync.py` (sync trackers/employees/zones/tracks),
  `scheduler.py` (auto-sync), `assignments.py` (driver↔vehicle time-aware).
- **Frontend**: React 19, sidebar dark + secondary white, IBM Plex Sans/Mono, Recharts.
- **DB**: `users`, `drivers`, `vehicles`, `trips`, `geofences`, `settings`, `audit_log`,
  `app_state` (scheduler), `assignments` (driver↔vehicle assignments).

## Implemented — 16/06/2026
### Iteration 1 (MVP)
- JWT auth + 3 demo roles
- Mock Navixy seed (6 véhicules, 6 chauffeurs, ~600 trajets)
- Moteur de règles auto (mode véhicule → géofence → horaires)
- Dashboard 6 KPIs + pie + line 30j + table chauffeur
- Historique pro/perso, mode B masquant pour gestionnaires
- Settings : 3 modes (A/B/C), règles, modes véhicules
- Rapports PDF/Excel/CSV, rapport fiscal suisse PDF
- Affectation manuelle (audit log)
- Driver visibility filter

### Iteration 2 — Navixy live
- Client async httpx, sync trackers/employees/zones/tracks (chunks 7 jours)
- Détection auto type de zone (mots-clés sur labels)
- Endpoint admin `POST /api/livre/navixy/sync`
- UI Settings : carte "Synchronisation Navixy" avec bouton + période
- Fuel estimé 8.5L/100km (Navixy ne fournit pas fuel_l dans track/list)

### Iteration 3 — APScheduler + assignments
- **APScheduler** : sync auto périodique configurable
  (intervalle 1-1440 min, période 1-365 jours, on/off)
  - State persisté dans `db.app_state` ; `last_run`, `last_result`, `next_run`
  - Endpoints `GET/PUT /api/livre/navixy/scheduler`, `POST /api/livre/navixy/scheduler/run-now`
  - UI dans Settings : toggle, inputs, "Lancer maintenant", "Appliquer"
- **Assignments time-aware** (driver↔vehicle many-to-many)
  - Collection `assignments` : `{vehicle_id, driver_id, from_date, to_date, is_primary, source}`
  - `resolve_driver_for_trip()` → trajets attribués au bon chauffeur selon la fenêtre temporelle
  - `reassign_all_trips()` appelé automatiquement après chaque ajout/suppression
  - Endpoints `GET/POST/DELETE /api/livre/assignments`
  - UI : bouton "Chauffeurs" par véhicule ouvre Dialog avec liste + formulaire d'ajout
  - Visibilité chauffeur étendue : voit ses trajets + ceux des véhicules qui lui ont été assignés
  - Optimistic UI updates pour ajout/suppression

## Bug fixes

### Iteration 9 — Carte MapLibre dans l'historique
- Dépendances ajoutées : `maplibre-gl@5.24`, `react-map-gl@8.1` (via yarn)
- Composant `frontend/src/components/livre/TripsMap.jsx` (NOUVEAU) :
  * Tuiles **OpenStreetMap raster** (gratuit, sans clé API)
  * Polylignes droites départ→arrivée par trajet, color-coding :
    - Pro = `#2196F3`, Perso = `#F59E0B`, N/C = `#94A3B8`
  * Markers verts au départ
  * Popup HTML au clic : date, classification, plaque, adresses, distance, chauffeur
  * Auto-fit bounds, contrôles zoom/orientation MapLibre
  * Légende Pro/Privé/N/C dans le header
- **Invariant Personnel Masqué STRICT (même pour admin)** :
  * Filtre client-side : `if settingsMode==="masked" → keep only trips where classification==="professional"`
  * Bandeau jaune « Mode Personnel Masqué — N trajet(s) personnel(s) masqué(s) sur la carte »
  * data-testid `trips-map-masked-notice` pour les tests
  * Testé end-to-end : admin + masked + perso page → **0 trajet** affiché alors que 500 dans la liste
- Intégration dans `pages/HistoryPage.jsx` (sous les filtres, avant le tableau)
- Pas de modification backend (utilise les `start_lat/lng` + `end_lat/lng` déjà présents)

### Iteration 8 — MVP Phase A : Identification BLE chauffeur ↔ véhicule
- Backend `app/ble_engine.py` (NOUVEAU 350+ lignes) :
  * Modèles MongoDB : `ble_tags`, `ble_detections`, `driver_sessions`
  * `ingest_detection()` : ignore si rssi < seuil ou tag inconnu, sinon
    open/extend session, ferme les autres sessions actives du chauffeur, recompute confidence
  * `_compute_confidence()` : 0..100 = 35 % stabilité + 25 % force + 20 % durée + 20 % historique
  * `driver_set_mode()` : stamp `mobile_override` sur session + propage aux trips à venir, audit log
- Backend `rules.classify_trip` : cascade **mobile_override > vehicle.mode > geofence > schedule**
- Backend endpoints : CRUD /ble/tags, /ble/detections (driver), /ble/simulate (admin),
  /ble/sessions (read+amend), /ble/dashboard, /ble/settings, /driver/current-session,
  /driver/manual-mode
- Frontend `IdentificationPage.jsx` : 8 KPIs + filtres + tableau sessions + actions + Dialog
- Frontend `DriverConsolePage.jsx` (PWA /driver) : mobile-first sombre, 2 gros boutons PRO/PRIVÉ,
  vehicle card pulse + RSSI + confidence, banner override, simulateur BLE, polling 10s
- Frontend Settings Sheet : colonne « Tag BLE » avec inline editor
- Navigation : section « Identification BLE » gated admin
- Tests : pytest 32/32 PASS ; bug ObjectId leak corrigé
- État final : mode=mixte, allow_driver_override=true, ble_enabled=true

### Iteration 6 — Privacy Phase 2 (Tracker enforcement)
- Backend `app/privacy_enforcer.py` (NOUVEAU) :
  * `compute_expected_state(vehicle, schedule, now)` → 'tracking' | 'private'
  * `enforce_all_vehicles(db)` : itère, skip incompatibles, envoie (ou simule) via `send_raw_command`
  * `kill_switch(db)` : force tous les véhicules privés à revenir en tracking (réel par design)
  * `list_states(db)` : ne retourne que les véhicules compatibles
  * Constantes : REAFFIRM_AFTER=12h, PRIVATE_MAX_AGE=24h
  * Commands Teltonika : `setparam 11000:4` (private/deep sleep) / `setparam 11000:0` (tracking)
  * Commands Queclink : `AT+GTCFG=,privacy_mode=1` / `=0`
- Backend `app/navixy_client.py` : `send_raw_command(tracker_id, command, reliable=true)` via `tracker/raw_command/send`
- Backend `app/scheduler.py` : nouveau job `_run_privacy_enforcement` toutes les 5 min (IntervalTrigger),
  enregistré inconditionnellement au startup ; le job lui-même no-op si `settings.privacy_enforcement_enabled=False`
- Backend endpoints :
  * `GET /api/livre/privacy/enforcement-config` (admin/manager)
  * `PUT /api/livre/privacy/enforcement-config` (admin) + audit_log
  * `GET /api/livre/privacy/state` (admin/manager) — véhicules compatibles uniquement
  * `POST /api/livre/privacy/enforce-now` (admin)
  * `POST /api/livre/privacy/kill-switch` (admin)
- Frontend `PrivacyEnforcementCard.jsx` : 2 toggles (enabled / simulation), 2 boutons (Forcer / Kill switch),
  tableau d'état par véhicule, bannière rouge si mode réel actif, confirm() avant kill switch
- Safety nets : simulation=true par défaut, REAFFIRM 12h, expiry 24h, kill switch, skip incompatibles,
  RBAC strict, audit_log de toute modif config
- Tests : pytest 20/20 PASS (test_iteration6_privacy_enforcement.py), frontend e2e admin/manager/driver OK
- État final laissé sain : enabled=false, simulation=true

### Iteration 5 — Privacy Phase 1 (Tracker compatibility scan, read-only)
- Backend : `GET /api/livre/privacy/tracker-compatibility` et `/{vehicle_id}` (admin/manager only)
  → détection par modèle de traceur synchronisé Navixy ; aucune commande sortante
- Modèles répertoriés :
  * Teltonika FMC130 / FMC230 / FMC003 / FMB* → `full` (`setparam 1004:0 (sleep mode)`)
  * Queclink GV/GL/GMT → `full` (`AT+GTCFG,privacy=1`)
  * Concox JM-01 / GT06 → `partial` (SMS seulement)
  * Smartphones Navixy (iOS/Android) → `none`
  * Autres → `unknown`
- Frontend : `<PrivacyCompatCard />` injecté dans Paramètres (admin/manager only)
  4 compteurs + tableau (plaque, modèle, famille, statut, commande prévue) + Re-scanner
- Sur la flotte réelle : 10 Teltonika compatibles, 2 smartphones non supportés,
  6 véhicules mock à vérifier (modèles génériques type "Mercedes Sprinter")
- Garde-fous Phase 1 : endpoint requireRoles(admin/manager), composant masqué pour drivers,
  AUCUN appel à `tracker/raw_command/send` (vérifié par AST static check du testing agent)
- Tests : backend pytest 10/10 PASS, frontend admin+driver flows OK après fix `canEdit && <PrivacyCompatCard />`

### Iteration 4 — Filtres Groupe/Société + KPI complets + always_perso strict
- Backend : nouveaux endpoints `GET /api/livre/groups` (premier token des plaques) et
  `GET /api/livre/companies` (distinct tenant_id, label "Logitrak" pour default).
- Backend : `/dashboard`, `/trips`, `/reports/export` propagent désormais
  les filtres `group` et `company`.
- Backend KPI étendus : `kpi.unclassified_km`, `kpi.pro_fuel`, `kpi.perso_fuel`.
- Backend `rules.apply_rules_to_all()` : les véhicules en mode `always_pro` /
  `always_perso` reclassifient TOUS leurs trajets (override manuel inclus) au lieu
  des seuls trajets auto-classifiés — sémantique "100 % Personnel" stricte.
- Frontend : Dashboard expose 6 filtres (Chauffeur / Véhicule / Groupe / Société /
  Du / Au) + 8 KPI dont "Km non classifiés" et "Carburant personnel".
- Frontend : HistoryPage Pro/Perso ajoute Groupe + Société, exports PDF/Excel/CSV
  respectent désormais tous les filtres actifs (group/company inclus).
- Privacy invariant validé end-to-end : en mode "Personnel Masqué" pour gestionnaires,
  /trips renvoie {id, classification, distance_km, masked:true}, /reports/export renvoie
  une seule ligne agrégée ("—"), et l'UI HistoryPage cache list+exports.
- Tests : backend pytest 16/16 PASS (iteration 4), frontend e2e 100%.

### Bug fixes
- xlsx export merged-cell crash
- Driver-user mapping (chauffeur ↔ Jean Dupont)
- AssignmentsDialog refresh timing (optimistic insert)

## Tests
- Backend pytest : 19/19 PASS (iteration 3)
- Frontend e2e : tous les flows validés via testing_agent_v3

## P1 backlog
- Carte Leaflet/Mapbox dans l'historique (polylignes Navixy via `track/read`)
- Carburant réel via `tracker/get_diagnostics` au lieu de l'estimation
- Webhook Navixy (push temps réel au lieu de polling APScheduler)
- Page admin pour gérer utilisateurs Logitrak
- CRUD UI pour géofences
- Multi-tenant via header `X-Tenant-ID`

## P2 backlog
- Rapports programmés (email)
- Notifications WebSocket nouveaux trajets
- Mode sombre
- Tests Pytest/Jest formalisés
- Module "Avantage en nature" (calcul fiscal CHF)

## Next tasks
- Brancher la carte Leaflet
- Récupérer le carburant réel
- Investiguer un webhook Navixy
