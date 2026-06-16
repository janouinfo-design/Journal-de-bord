# Logitrak — Livre de Bord Professionnel / Personnel

## Problem statement (verbatim)
Créer un nouveau module "Livre de Bord Professionnel / Personnel" dans Logitrak,
entièrement connecté à Navixy via les API de tracking et l'historique GPS.
Permettre aux entreprises de distinguer kilomètres professionnels et personnels,
avec rapports séparés et respect de la vie privée (3 modes : visible/masqué/100% pro),
rapport fiscal suisse annuel, affectation manuelle pro/perso et droits par rôle.

## User choices
- Standalone app (no existing repo)
- Mock Navixy data based on official API structure (track/list, history/tracks, reports/trips)
- JWT custom auth with roles (admin / manager / driver)
- Backend Python for PDF (reportlab) + Excel (openpyxl)
- MVP first: Dashboard + Historique pro/perso + Paramètres confidentialité + Affectation manuelle

## Architecture
- **Backend**: FastAPI + Motor (MongoDB), `/api` prefixed router. Modules under `/app/backend/app/`:
  `auth.py` (JWT cookies + role enforcement), `db.py`, `mock_navixy.py` (seed Navixy-shaped data),
  `rules.py` (auto-classification engine), `reports.py` (PDF/Excel/CSV/Fiscal CH), `routes.py` (`/api/livre/*`).
- **Frontend**: React 19 + react-router-dom + axios (withCredentials), Tailwind + shadcn/ui,
  Recharts, IBM Plex Sans/Mono. Layout = dark primary sidebar (w-16) + white secondary sidebar (w-64)
  + top header. Pages: Login, Dashboard, History (Pro/Perso), Reports (Pro/Perso), Tax Swiss, Settings.
- **DB**: collections `users`, `drivers`, `vehicles`, `trips`, `geofences`, `settings`, `audit_log`.

## User personas
1. **Admin** — full access, audit log, user management. (`admin@logitrak.ch`)
2. **Manager / Gestionnaire** — access filtered by privacy policy modes A/B/C. (`manager@logitrak.ch`)
3. **Driver / Chauffeur** — sees only their own trips (mapped via DRIVER_EMAIL env). (`chauffeur@logitrak.ch`)

## Implemented — 16/06/2026 (Iteration 1, MVP)
- JWT auth + 3 demo roles seeded on startup
- Mock Navixy data: 6 drivers, 6 vehicles, ~600 trips over 45 days, 7 geofences
- Auto-classification rule engine: vehicle mode override → geofence → time-based weekday/weekend
- Dashboard with 6 KPI cards (pro km, perso km, total, %pro, %perso, fuel) + pie chart + 30-day line chart + per-driver table
- Historique professionnel & personnel with filters (driver, vehicle, date) and inline manual classification (Pro/Perso toggle)
- Settings page: 3 privacy modes (A/B/C), time rules (start/end hour, weekend days), geofence toggle, per-vehicle mode (mixte/always_pro/always_perso)
- Reports: PDF, Excel, CSV exports for pro/perso; annual Swiss fiscal PDF
- Privacy enforcement: Mode B masks personal trip details (carte, adresses, GPS) for managers; admin always sees full
- Driver visibility filter: chauffeur user sees only their own trips
- Audit log of manual classification changes

## Bug fixes — iteration 1
- xlsx export crash on merged title row (column_letter on merged cell) — fixed via `get_column_letter`
- Driver-user mapping mismatch (chauffeur user not linked to Jean Dupont driver record) — fixed by using DRIVER_EMAIL env for first seeded driver

## P1 backlog
- Carte Leaflet/Mapbox réelle dans l'historique (actuellement adresses textuelles uniquement)
- Rapports programmés (cron) avec envoi email
- Vrai connecteur Navixy (clé API + hash de session) en remplacement du mock
- Géofences éditables UI (CRUD complet)
- Multi-tenant via header `X-Tenant-ID`
- Page de gestion des utilisateurs (admin)

## P2 backlog
- Notifications temps réel (WebSocket) sur nouveaux trajets
- Export multi-période agrégée (mensuel/trimestriel)
- Tableaux de bord chauffeur (vue self-service)
- Tests unitaires Pytest et frontend Jest formalisés
- Mode sombre

## Next tasks
- Vérifier conformité fiscale CH avec un comptable suisse
- Implémenter la carte (Leaflet) dans l'historique
- Brancher Navixy en prod (track/list, history/tracks, reports/trips)
