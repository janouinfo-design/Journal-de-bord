# Spécification contrat Energy → Journal v1 — prompt envoyé au projet ÉNERGIE

Archivé le 25/08/2026. Source de vérité : `backend/app/energy_client.py` (client Journal, NON modifié).
Décision utilisateur : ne pas connecter tant que (1) auth backend→backend et (2) routes métier v1
ne sont pas réellement développées côté Energy. URL preview Energy reconnue mais NON autorisée
comme ENERGY_API_BASE_URL pour l'instant.

Le Journal enverra, sans modification de son client :
- Header `Authorization: Bearer <token>` (variable Journal : ENERGY_API_TOKEN)
- Header `X-Tenant-Id: <tenant>`
- Timeout 10 s par appel
- contract_version "1.0"

Routes attendues (préfixe exact `/api/energy/v1`) :
1. GET  /api/energy/v1/health
2. POST /api/energy/v1/trips/energy:batch
3. GET  /api/energy/v1/fleet/summary?from&to&tenant_id
4. GET  /api/energy/v1/vehicles/{vehicle_ref}/summary?from&to&tenant_id&navixy_tracker_id&vin

Enveloppe métrique : {value, unit, availability, measurement_type, source, timestamp}
availability ∈ {AVAILABLE, STALE, UNAVAILABLE} · measurement_type ∈ {MEASURED, ESTIMATED, REFERENCE} ou null
null = inconnu, jamais 0 · powertrain ∈ {ICE, HEV, PHEV, BEV, UNKNOWN} · UNKNOWN jamais converti en ICE
Résolution des véhicules par navixy_tracker_id UNIQUEMENT (12/12 confirmés des deux côtés) :
781479, 1067937, 1067938, 1067939, 1075587, 3076994, 3079431, 3131157, 3218549, 3218550, 3218553, 3353695
