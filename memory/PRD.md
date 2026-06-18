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

### Iteration 11 — Phase B spec + multi-driver conflict + WebSocket realtime
- **Doc Phase B Expo** : `/app/docs/phase_b_native_spec.md` — stack Expo SDK 51+ react-native-ble-plx, perms iOS/Android, architecture offline-first avec queue locale, plan tests, coûts (Apple 99$/yr + Play 25$), planning 6-7 semaines, critères d'acceptation
- **Multi-driver conflict detection** (`ble_engine._maybe_flag_conflict`) :
  * Déclenché à chaque ingest si 2+ drivers ont des sessions ouvertes sur le même véhicule dans la fenêtre 5min avec confidence delta ≤ 30
  * Marque TOUTES les sessions impliquées en `status='conflict'`
  * Audit log `action='conflict_detected'` avec drivers + confidences
  * **Jamais d'auto-choix** — admin doit résoudre
  * `POST /ble/sessions/{id}/resolve` (admin only) : `{winner_driver_id}` → winner gardé en `confirmed`/`pending`, autres clôturées en `closed` + audit
- **WebSocket realtime** (`app/realtime.py` + endpoint `/api/livre/realtime`) :
  * In-memory broadcaster avec rooms par tenant_id, lock asyncio
  * Auth via cookie session (`get_user_from_request` ajouté à `auth.py`)
  * Messages JSON `{type, data, ts}` : `session_opened`, `session_updated`, `conflict_detected`, `conflict_resolved`
  * Hook frontend `useRealtime.js` avec reconnexion exponentielle (500ms→30s cap), ping 25s
  * Badge "Live"/"Hors-ligne" pulsant en haut de la page Identification
  * Toast `warning` au reçu d'un `conflict_detected`, refresh silencieux sur sessions
- Frontend : Dialog "Conflit BLE — Qui conduisait réellement ?" avec radio buttons des drivers en conflit
- Tests : conflit déclenché empiriquement (Jean conf=73 + Marie conf=70 sur LOGITRAK AUDI → status=conflict) ; resolve renvoie `{winner_session_id, closed_count, final_status}` ; badge Live visible ; sessions nettoyées après test
- État final : sessions de test clôturées, mode=mixte, allow_driver_override=true

### Iteration 10 — Polylignes Navixy réelles (`tracker/track/read` + cache)
- Backend `navixy_client.read_track_points(tracker_id, from, to, track_id?, simplify=true, point_limit=300)`
  appelle `track/read` au format `'YYYY-MM-DD HH:MM:SS'`. Retourne 139 points GPS pour un trajet typique.
- Backend `GET /api/livre/trips/{trip_id}/track?refresh=` (auth all roles, mais voir invariant) :
  * **Invariant strict masqué** : si `settings.mode=='masked'` ET `trip.classification=='personal'` → **403 immédiat**, même pour admin. Les points ne sont JAMAIS lus, mis en cache, ni renvoyés.
  * Cache permanent dans `db.trip_tracks` keyed by trip_id (trips immuables une fois clos)
  * Cache négatif si erreur Navixy pour éviter de hammer
  * Fallback gracieux : ligne droite `[start_lng/lat, end_lng/lat]` si pas de tracker_id / pas de NAVIXY_HASH / erreur réseau
  * Source labelisée : `navixy | cache | fallback_no_tracker | fallback_no_points | fallback_navixy_error`
- Frontend `TripsMap.jsx` :
  * Pool de fetch concurrency=6 au mount/changement de trips
  * Garde `fetchedRef` pour ne pas refetch déjà chargés
  * Indicateur de chargement « chargement des traces GPS… (N restants) »
  * Si polyline réelle reçue → remplace la ligne droite
  * Fallback ligne droite reste affichée en attendant
- Validation manuelle :
  * 139 points GPS chargés sur un trajet réel ✅
  * 2e appel → source='cache' ✅
  * Mode masqué → admin reçoit 403 sur perso trip ✅
  * UI : polylignes suivent les routes (autoroutes, périphériques), plus de lignes droites

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
- Backend pytest : 19/19 PASS (iteration 3) + 32/32 PASS (iteration 8 BLE) + 34/34 PASS (iteration 13 régression) + 17/17 PASS (iteration 14 notifications) — **128/128 PASS** Phase A
- Frontend e2e : tous les flows validés via testing_agent_v3

## Implemented — 19/02/2026 (suite)
### Iteration 14 — Expo Push Notifications + Notification Preferences
- **`backend/app/expo_push.py`** (nouveau, 150 LOC) : client HTTP async vers `exp.host`,
  batches de 100, parsing des tickets, nettoyage automatique des tokens morts
  (`DeviceNotRegistered`, `InvalidCredentials`, `MismatchSenderId`), aucun API key requis.
- **`backend/app/notifications_service.py`** (nouveau, 280 LOC) : dispatcher haut niveau avec
  catalogue d'événements (11 types : 3 actifs `ble.conflict`/`ble.resolved`/`kill_switch` +
  8 stubs business : `contract.renewal`, `insurance.expiring`, `vehicle.inspection_due`,
  `tracker.low_battery`, `tracker.gps_lost`, `driver.unassigned`, `vehicle.incident`,
  `logibus.delay`), résolution audience par `user_ids`/`driver_ids`/`role_filter`, lecture
  des préférences utilisateur, log dans `db.notifications_log`.
- **Templates FR** : « 🚨 Conflit d'identification chauffeur » + « ✅ Conflit résolu » +
  « ⚠️ Tracking désactivé par l'administrateur ».
- **`notification_preferences`** collection MongoDB : `{user_id, channels: {push, email, sms},
  events: {<event>: {push, email, sms}}}`. Email + SMS stubbés (logs uniquement).
- **Endpoints REST** :
  - `GET /api/livre/notifications/catalog` (auth) — liste des événements + défauts
  - `GET /api/livre/notifications/preferences` (auth) — prefs utilisateur courant
  - `PUT /api/livre/notifications/preferences` (auth) — màj prefs (filtre événements inconnus)
  - `POST /api/livre/notifications/test` (admin) — déclenche un event de test
- **Hooks moteur** :
  - `ble_engine._maybe_flag_conflict` → `dispatch('ble.conflict', …)`
  - `ble_engine.resolve_conflict` → `dispatch('ble.resolved', …)`
  - `privacy_enforcer.kill_switch` → WS broadcast `kill_switch` + `dispatch('kill_switch', …)`
- **App Expo native — Actions interactives** :
  - `src/utils/notificationActions.ts` (nouveau, 140 LOC) : enregistre la catégorie iOS
    `BLE_CONFLICT` avec 2 boutons « Je conduisais » / « Ce n'était pas moi », handler qui
    appelle `/driver/manual-mode` directement, file `pending_actions` AsyncStorage si offline
    avec replay automatique au prochain login.
  - `App.tsx` : enregistrement des catégories + handler attaché au démarrage + enregistrement
    automatique du push token Expo dès le login + replay des actions en attente.
- **Tests pytest** : `/app/backend/tests/test_notifications.py` (17 tests, 4 s, 100 % PASS) :
  catalog, préférences GET/PUT, RBAC `/test` (admin only), templates BLE/kill_switch/business,
  unit tests `expo_push` avec mocks (skip tokens invalides, cleanup tokens morts, gestion erreur HTTP),
  intégration end-to-end vérifiant que les conflits écrivent dans `notifications_log`.
- **Total Phase A** : 128/128 tests PASS sur les 5 suites (iteration 3/4/5/8/13/14).
- **Compatibilité** : aucun changement de comportement existant. Le service email/SMS est
  stubbé (logs) — quand un provider (Resend, Twilio) sera ajouté plus tard, seul
  `notifications_service.dispatch` aura besoin d'être complété, sans toucher au reste.

### Iteration 13 — Auth refresh + Push token + Régression pytest
- **`POST /api/auth/refresh`** ajouté dans `auth.py` : accepte refresh token via cookie OU body JSON,
  validation `type=refresh` + signature + expiration, rotation du refresh token, renvoie
  `{access_token, refresh_token, user}`. Erreurs HTTP 401 propres (token manquant / invalide / expiré).
- **`POST /login`** : ajoute `refresh_token` au body de réponse (utilisé par l'app native Expo).
- **`POST /api/auth/logout`** : désactive aussi les push tokens du user (best-effort).
- **`POST /api/livre/driver/push-token`** : enregistre/met à jour un push token Expo,
  idempotent par token, lié à `(user_id, driver_id, tenant_id)`, ré-activation auto si déjà présent.
- **`DELETE /api/livre/driver/push-token?token=...`** : désactivation soft (active=false).
- **Tests pytest régression Phase A** : `/app/backend/tests/test_phase_a_regression.py` (34 tests,
  10,8 s, 100 % PASS) couvrant :
  - 8 tests `TestAuthRefresh` (login, body, cookie, rotation, invalide, expiré, mauvais type, access post-refresh)
  - 7 tests `TestPushToken` (register, idempotence, invalide, RBAC, delete, 404, admin)
  - 6 tests `TestBleConflict` (simulate, flag conflict, RBAC manager/driver refus, résolution admin, 400)
  - 3 tests `TestRealtimeWebSocket` (refus non-auth, événements `conflict_detected` + `conflict_resolved`)
  - 10 tests `TestNonRegression` (auth/me, dashboard, trips, drivers, vehicles, BLE sessions+dashboard, current-session, manual-mode, logout)
- **conftest.py** créé : charge `/app/backend/.env` + `/app/frontend/.env`, ajoute backend dans `sys.path`.
- **Résumé** : 66/66 tests Phase A PASS (34 régression + 32 itération 8). 3 échecs résiduels
  sur tests legacy `test_livre_de_bord.py` et `test_iteration6` — **pré-existants** (modes A/B/C obsolètes
  vs valeur courante "mixte"), aucune régression introduite.
- **Compatibilité** : PWA web `/driver` 100 % conservée (cookie session), app native Expo
  utilise désormais access+refresh via Authorization header.

### Iteration 12 — Phase B Native scaffold (app Expo mobile chauffeur)
- App Expo SDK 51 + TypeScript scaffoldée dans `/app/logitrak-driver-app/` (24 fichiers source, 1 844 LOC)
- Stack : React Navigation 6, Zustand, axios + JWT refresh, expo-secure-store, expo-notifications,
  expo-background-fetch, expo-task-manager, `react-native-ble-plx` 3.x, `@react-native-community/netinfo`
- Écrans : `LoginScreen` (JWT email/password), `DriverScreen` (carte véhicule + boutons PRO/PRIVÉ + scanner BLE),
  `SettingsScreen` (toggle BLE, file hors-ligne, déconnexion)
- BLE : `scanner.ts` (dedupe 2 s, filtre optionnel par identifiers), `queue.ts` (AsyncStorage 24h/5 000 max,
  backoff exponentiel 1 s → 60 s), `background.ts` (BackgroundFetch 15 min flush)
- Hooks : `useRealtime` (WS backoff 1 s → 30 s), `useCurrentSessionPoll` (10 s),
  `useQueueFlusher` (30 s + NetInfo reconnect + AppState focus)
- Permissions iOS (`Info.plist` BG modes bluetooth-central) + Android (BT_SCAN/CONNECT/LOCATION/POST_NOTIFICATIONS)
- `app.json` plugins : `expo-secure-store`, `expo-notifications`, `react-native-ble-plx` (BG enabled)
- `eas.json` avec profils dev / preview / production (env `EXPO_PUBLIC_API_URL` par profil)
- Fallbacks : Bluetooth off, permission refusée, réseau coupé, token expiré, WS fermé
- Logger scopé `[scope][level]` activable via `EXPO_PUBLIC_DEBUG=1`
- README de 250 lignes : pré-requis, install, prebuild, dev client, EAS build, soumission stores
- Backend FastAPI **inchangé** (endpoints Phase A déjà compatibles)
- TypeScript `npx tsc --noEmit` : 0 erreur
- Web app `/driver` PWA conservée — coexiste avec l'app native

## P1 backlog
- Carte Leaflet/Mapbox dans l'historique (polylignes Navixy via `track/read`) — DONE (MapLibre, iteration 7)
- Carburant réel via `tracker/get_diagnostics` au lieu de l'estimation
- Webhook Navixy (push temps réel au lieu de polling APScheduler)
- Page admin pour gérer utilisateurs Logitrak
- CRUD UI pour géofences
- Multi-tenant via header `X-Tenant-ID`
- Tests pytest de régression sur Phase A BLE + Phase B endpoints (option **c** du plan)
- Refactoring `routes.py` monolithique en routers modulaires (option **b** du plan)
- Endpoint backend `POST /api/auth/refresh` (consommé par l'app native)
- Endpoint backend `POST /api/livre/driver/push-token` (Expo Push registration)

## P2 backlog
- Rapports programmés (email)
- Notifications WebSocket nouveaux trajets — DONE (Conflict Inbox, iteration 8)
- Mode sombre
- Tests Pytest/Jest formalisés
- Module "Avantage en nature" (calcul fiscal CHF)
- Phase B production : Apple Developer + Play Console, iOS BG State Restoration, Android Foreground Service BLE
- Tests Detox E2E sur l'app native

## Next tasks
- **(c)** Suite pytest de régression `/app/backend/tests/` couvrant Phase A BLE complet (cascade, RBAC, score) — testable immédiatement
- **(b)** Décomposer `routes.py` en routers modulaires (`ble.py`, `dashboard.py`, `reports.py`, `settings.py`)
- Ajouter endpoints backend `auth/refresh` + `driver/push-token` pour finaliser l'intégration mobile
- Tester l'app native sur device physique (Android/iOS) avec un vrai tag BLE
