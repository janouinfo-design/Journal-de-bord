# DRIVER_PRIVATE_MODE_PHASE2_IMPLEMENTATION.md
## Phase 2 — Bouton Privé/Professionnel (backend autoritaire) — IMPLÉMENTÉ (gated)

> Pilote FIELD-VALIDATED : tracker 3657864 (FMC003). `PRIVATE_MODE_PRODUCTION` GLOBAL = **DISABLED**.
> Commandes device réelles **GATED** (flag `PRIVATE_MODE_DEVICE_WRITE=1`) — défaut = SIMULATION.

## A. Architecture
```
App Chauffeur (intention: PRIVATE|BUSINESS)
  -> POST /api/livre/driver/private-mode (backend autoritaire)
  -> résout driver -> tenant(default) -> vehicle -> tracker -> capability(gate)
  -> commande device Navixy `privatemode ON/OFF` (GATED)  [JAMAIS Deep Sleep 11000:4]
  -> confirmation RÉELLE (relecture)  -> état final
```
Fichiers : `app/private_mode_engine.py` (logique), `app/routes/identification.py` (endpoints),
`app/odometer_capability.py` (gate + capability), app mobile : `src/api/privateMode.ts`,
`src/hooks/usePrivateMode.ts`, `src/screens/DriverScreen.tsx` (section « Confidentialité »).

## B. Endpoints
- `GET  /api/livre/driver/private-mode` -> {state, allowed, reason, vehicle_id, tracker_id, last_transition_at}
- `POST /api/livre/driver/private-mode` body {"mode":"PRIVATE"|"BUSINESS"} -> {ok, state, reason?, private_distance_km?}
L'app n'envoie JAMAIS : tracker_id, raw command, tenant_id, AVL id, credentials.

## C. Machine à états
`BUSINESS | PRIVATE_REQUESTED | PRIVATE | BUSINESS_REQUESTED | FAILED | UNKNOWN`
Transitions : BUSINESS→PRIVATE_REQUESTED→PRIVATE ; PRIVATE→BUSINESS_REQUESTED→BUSINESS ;
non-confirmation/timeout → FAILED/UNKNOWN. Aucun changement optimiste (front ni back).

## D. Chemin commande Navixy
`privatemode ON` (PRIVATE) / `privatemode OFF` (BUSINESS) via `tracker/raw_command/send`
(réutilise `navixy_client.send_raw_command`). GATED : `device_write_enabled()` (env
`PRIVATE_MODE_DEVICE_WRITE`) — défaut False -> SIMULATION (aucun appel Navixy). Deep Sleep INTERDIT.

## E. Confirmation d'état
`PRIVATE_STATE_CONFIRMATION_SOURCE` / `BUSINESS_STATE_CONFIRMATION_SOURCE` :
- SIMULATION : non confirmé côté device -> reste REQUESTED (jamais succès optimiste).
- REAL (terrain) : relecture d'état (privatemode ?/signaux). NE PAS se fier à la seule position
  gelée (cf. D3-B : en privé la position Navixy reste figée). Hooks `confirm`/`read_odo` injectables.

## F. Snapshots AVL16
À l'entrée PRIVATE confirmée : `private_start_odometer_km` (AVL16 normalisé km, source
TELTONIKA_TOTAL_ODOMETER). À la sortie BUSINESS : `private_end_odometer_km`.

## G. Calcul distance privée
`private_distance_km = end - start` (mêmes source/scale/tracker, y>=x). JAMAIS le compteur GPS
Navixy. Si odomètre indisponible -> `distance_status=UNAVAILABLE` (jamais inventée).

## H. Masquage confidentialité
`redact_private_location(obj, state)` neutralise en PRIVATE : lat/lng/adresse/polyline/points/
route/replay/breadcrumb/gps (mis à None, JAMAIS 0,0). `private_trip_dto()` = champs métier
uniquement (temps, odomètres, distance, source) — aucune position. Même si Navixy garde une
last known position, LOGITRAK ne l'expose PAS comme position actuelle en PRIVATE.

## I. Sécurité / RBAC / multi-tenant
Backend autoritaire : chauffeur -> son véhicule de session uniquement (tenant `default`,
`resolve_driver_id_for_user` + `ble_engine.get_current_session`). Aucun tracker/tenant libre.
Audit `audit_log` scope `private_mode` : tenant/driver/vehicle/tracker/requested/prev/result/
reason. Secrets/raw device JAMAIS loggés ni renvoyés.

## J. Erreurs / récupération
Non-confirmation -> FAILED/UNKNOWN + message honnête (l'app propose de réessayer, pas de succès
affiché). Retour Business non confirmé -> ne PAS afficher Professionnel. Réseau absent ->
« impossible de confirmer ». Idempotence : même mode -> no-op (aucune commande). Anti-concurrence :
transition en cours -> refus `transition_in_progress`.

## K. Feature gating
- Gate par tracker : `vehicle_private_mode_allowed(model, vc)` (source AVL16 + raw_avl_id=16 +
  runtime+cumulative+private_increment+field_validated).
- Persistance capability : Mongo `vehicle_private_capabilities` (source de vérité) ; fallback
  registre pilote `PILOT_VEHICLE_CAPABILITIES` (constante = seed/preuve/tests, non destructif).
- `PRIVATE_MODE_PRODUCTION` GLOBAL = DISABLED. Autorisation restreinte au pilote 3657864.

## L. Tests
`tests/test_private_mode_phase2.py` (12) + `tests/test_odometer_capability.py` (19) = 31 PASS.
Couverts : BUSINESS→PRIVATE (confirmé/non-confirmé), distance AVL16, distance UNAVAILABLE,
idempotence, no_active_vehicle, redaction position, DTO sans position, source GPS refusée,
Deep Sleep jamais utilisé, device write gated, tracker non validé refusé, non-généralisation.

## M. Reste à faire (hors mission)
- **D3 FMC130** séparé (non field-validated).
- **Confirmation REAL terrain** : implémenter `confirm()` réel (lecture `privatemode ?`/signaux)
  quand on activera le device write — sur GO explicite.
- **Décision de rollout** : activer `PRIVATE_MODE_PRODUCTION` (feature flag pilote d'abord).
- Persister les capabilities des véhicules validés dans `vehicle_private_capabilities`.

## SORTIE
```
PHASE2_BACKEND              = IMPLEMENTED (gated, simulation par défaut)
PHASE2_DRIVER_APP          = IMPLEMENTED (section Confidentialité, machine à états, non optimiste)
STATE_MACHINE              = IMPLEMENTED
AVL16_PRIVATE_DISTANCE     = IMPLEMENTED (delta AVL16, GPS exclu)
PRIVATE_LOCATION_REDACTION = IMPLEMENTED
REMOTE_COMMAND_PATH        = IMPLEMENTED (gated ; privatemode ON/OFF ; pas de Deep Sleep)
TRACKER_3657864            = FIELD_VALIDATED
FMC130                     = NOT_FIELD_VALIDATED
PRIVATE_MODE_PRODUCTION    = DISABLED
TESTS                      = 31 passed (12 phase2 + 19 capability)
NEXT_SAFE_STEP             = brancher confirm() REAL + décision rollout (flag pilote) sur GO explicite
```

## GARDE-FOUS
Aucune commande device réelle envoyée (SIMULATION par défaut). Aucune activation prod. Aucune
modif config Teltonika / sensor Navixy. Pas de généralisation FIELD_VALIDATED. Pas de test FMC130.
Deep Sleep jamais réactivé. Toute action terrain réelle => STOP + GO explicite requis.
