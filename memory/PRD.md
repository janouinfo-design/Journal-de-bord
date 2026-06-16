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
