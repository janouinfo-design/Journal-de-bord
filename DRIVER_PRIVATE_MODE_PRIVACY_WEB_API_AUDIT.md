# DRIVER_PRIVATE_MODE_PRIVACY_WEB_API_AUDIT.md
## Audit privacy Web/API — fuites de localisation en mode Privé (Phase A READ-ONLY)

> Contexte : PRIVATE_MODE_PRODUCTION = DISABLED (aucun véhicule en PRIVATE en prod aujourd'hui →
> pas de fuite ACTIVE ; le risque est FUTUR, à couvrir avant rollout). Aucun device/Navixy touché.

## A. Surfaces auditées (backend `app/routes/`)
misc (trips, /trips/{id}/track, /vehicles), dashboard, identification (driver-facing),
realtime (websocket), reports/fuel/fines (exports), _helpers (apply_privacy), navixy_sync,
private_mode_engine (redact_private_location).

## B/C. Mécanisme de confidentialité ACTUEL (constat)
- `apply_privacy(trip, settings, role)` masque les trajets `classification=="personal"` en mode
  `settings.mode=="masked"` pour les non-admins (GET /trips).
- `/trips/{id}/track` renvoie 403 pour un trajet `personal` en mode masked (pas de points GPS).
- => La confidentialité repose sur **`classification` (personal/professional)** — c'est la **Phase 1
  (classement)**. Elle N'EST PAS reliée à l'état **PRIVATE du mode device (Phase 2)**.

## Matrice de risque
| Composant | Endpoint/vue | Champs localisation | Redaction PRIVATE présente | Risque | Fix requis |
|---|---|---|---|---|---|
| Trips (liste) | GET /livre/trips | start/end_lat/lng, addresses | via `classification` (Phase 1), PAS via état PRIVATE | MOYEN (si trajet PRIVATE classé professional) | Lier PRIVATE→masquage |
| Trip track | GET /livre/trips/{id}/track | polyline (lng/lat) | 403 si personal+masked ; PAS si professional | MOYEN | Idem |
| Vehicles | GET /livre/vehicles | — | N/A (aucune position stockée : sync ne met que plate/model/mode) | FAIBLE | Aucun (vérifié) |
| Dashboard | GET /livre/dashboard | agrégats (pas de coords) | N/A | FAIBLE | Aucun |
| Realtime | WS /livre/realtime | messages events (pas de position brute véhicule) | N/A | FAIBLE (à confirmer si push position ajouté un jour) | Surveiller |
| Driver my-vehicle | GET /livre/driver/my-vehicle | vehicle {id,plate,model} — pas de coords | N/A | FAIBLE | Aucun |
| Exports (reports/fuel/fines) | divers | adresses/positions via trips | héritent de classification | MOYEN | À couvrir si PRIVATE |
| Odometer | GET /livre/driver/vehicle/odometer | km only (pas de position) | N/A | FAIBLE | Aucun |

## D. Realtime
`realtime.py` = websocket d'événements génériques (ble.conflict, kill_switch…), ne pousse PAS la
position brute du véhicule. Pas de fuite constatée. À re-surveiller si un push "position live" est ajouté.

## E. Trips
Localisation réelle = dans les documents `trips` (start/end_lat/lng, adresses) + cache `trip_tracks`
(polyline). Masqués aujourd'hui SEULEMENT via `classification=="personal"` + mode `masked`.

## F. Replay / track
`/trips/{id}/track` : cache `trip_tracks.points`. 403 si personal+masked. Pas de garde par état PRIVATE.

## G. Events / notifications — à auditer plus finement si push position ajouté (non constaté ici).
## H. Exports — héritent de la donnée trips ; contrôle backend à étendre si trajet PRIVATE.
## I. Frontend web — hors périmètre de ce backend ; à auditer séparément (vues carte/marker stale).
## J. Logs — pas de log de position privée constaté dans les routes ; navixy_sync logge des compteurs.

## K. Multi-tenant / RBAC
`apply_privacy` exempte le rôle `admin` (voit tout). RBAC/tenant OK par ailleurs.
`SUPERADMIN_PRIVATE_LOCATION_POLICY = UNDECIDED` (aucune politique explicite -> par défaut REDACTED
recommandé ; ne pas inventer d'exception).

## LACUNE CENTRALE (le vrai sujet)
Le **mode PRIVATE device (Phase 2, `private_mode_state`)** n'est **pas relié** au masquage des
données web. Concrètement :
- Un trajet effectué pendant une période PRIVATE n'est pas garanti `redacted` par les endpoints web
  (il dépend de sa `classification`).
- `redact_private_location` (Phase 2) **n'est appelée par AUCUN endpoint web** (seulement dans le DTO
  privé du moteur).
Protection « par construction » actuelle : en PRIVATE, Navixy gèle la position -> `track/read` renvoie
peu/pas de points pour cette période. Mais ce n'est PAS une garantie LOGITRAK explicite.

## VERDICT PHASE A
```
PRIVACY_API_AUDIT = NEEDS_FIX (établir le lien PRIVATE(device) -> masquage web ; brancher
                    redact_private_location ; garde track/trips par période PRIVATE)
```
Risque non-actif aujourd'hui (rollout DISABLED) mais à corriger AVANT activation.

## Phase B (correctifs minimaux proposés — sur constat)
1. Helper `is_period_private()` / marquage des trajets chevauchant une période PRIVATE.
2. Étendre `apply_privacy` + `/trips/{id}/track` pour masquer aussi quand le trajet est PRIVATE
   (device), indépendamment de la classification.
3. Brancher `redact_private_location` sur les endpoints exposant une position courante si un tel
   endpoint apparaît.
4. Tests de non-fuite.
