"""Couche d'autorisation CENTRALE du Mode Privé (pilote sécurisé, fail-closed).

Une seule source de vérité pour décider si le Mode Privé peut être utilisé, selon
la hiérarchie stricte (chaque niveau doit passer, sinon `allowed=False`) :

    FEATURE global activée
       -> TENANT autorisé (allowlist)
          -> VEHICLE/tracker pilote autorisé (allowlist)
             -> HARDWARE capability field_validated (registre par tracker)
                -> INTEGRATION Navixy disponible pour le tenant
                   -> KILL SWITCH non activé

FAIL-CLOSED : en cas de doute / config absente / erreur -> allowed=False.
Le frontend n'est JAMAIS source d'autorisation : il n'affiche le contrôle que si
le backend renvoie allowed=True.

Aucune commande device n'est envoyée ici (pure décision). Aucun secret n'est lu/loggé.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Raisons de refus normalisées (exposables au frontend — non sensibles).
REASON_OK = None
R_FEATURE_DISABLED = "PRIVATE_MODE_FEATURE_DISABLED"
R_KILL_SWITCH = "PRIVATE_MODE_KILL_SWITCH_ACTIVE"
R_TENANT_NOT_ALLOWED = "PRIVATE_MODE_TENANT_NOT_ALLOWED"
R_VEHICLE_NOT_PILOT = "PRIVATE_MODE_VEHICLE_NOT_PILOT"
R_NO_TRACKER = "PRIVATE_MODE_NO_TRACKER"
R_NOT_SUPPORTED = "PRIVATE_MODE_NOT_SUPPORTED"          # hardware non field_validated
R_INTEGRATION_UNAVAILABLE = "PRIVATE_MODE_INTEGRATION_UNAVAILABLE"
R_NO_VEHICLE = "PRIVATE_MODE_NO_VEHICLE"

# Codes HTTP recommandés par raison (pour les endpoints).
HTTP_BY_REASON = {
    R_FEATURE_DISABLED: 403,
    R_KILL_SWITCH: 403,
    R_TENANT_NOT_ALLOWED: 403,
    R_VEHICLE_NOT_PILOT: 403,
    R_NO_TRACKER: 409,
    R_NOT_SUPPORTED: 409,
    R_INTEGRATION_UNAVAILABLE: 503,
    R_NO_VEHICLE: 409,
}


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Niveau 1 — Feature flag GLOBAL (fail-closed : absent/invalide -> désactivé).
# ---------------------------------------------------------------------------
def feature_enabled() -> bool:
    """PRIVATE_MODE_ENABLED. Défaut = FALSE (fail-closed).
    Ne devient JAMAIS actif par défaut."""
    return _truthy(os.environ.get("PRIVATE_MODE_ENABLED", "false"))


# ---------------------------------------------------------------------------
# Niveau 2 — Kill switch backend (désactivation immédiate, sans redéploiement).
# Source : collection Mongo `feature_flags` (doc id="private_mode"). Fail-closed.
# ---------------------------------------------------------------------------
async def kill_switch_active(db) -> bool:
    """True si le kill switch Mode Privé est activé côté backend.
    En cas d'erreur de lecture -> True (fail-closed : on bloque)."""
    try:
        doc = await db.feature_flags.find_one({"id": "private_mode"}, {"_id": 0, "kill_switch": 1})
        return bool(doc and doc.get("kill_switch") is True)
    except Exception as e:
        logger.warning("kill_switch read error (fail-closed=blocked): %s", type(e).__name__)
        return True


async def set_kill_switch(db, active: bool, actor: str) -> dict:
    """Active/désactive le kill switch (admin). Empêche toute NOUVELLE activation.
    N'altère PAS l'état privé d'un véhicule déjà en PRIVATE (décision produit :
    on ne révèle jamais une position en coupant la confidentialité)."""
    from datetime import datetime, timezone
    await db.feature_flags.update_one(
        {"id": "private_mode"},
        {"$set": {"id": "private_mode", "kill_switch": bool(active),
                  "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": actor}},
        upsert=True,
    )
    return {"kill_switch": bool(active)}


# ---------------------------------------------------------------------------
# Niveau 3 — Allowlist TENANT.
# Source : tenant.private_mode_pilot == True  (champ métier, jamais le frontend).
# Optionnel : env PRIVATE_MODE_PILOT_TENANTS (CSV) en complément dev/pilot.
# ---------------------------------------------------------------------------
def _env_tenant_allowlist() -> set[str]:
    raw = os.environ.get("PRIVATE_MODE_PILOT_TENANTS", "").strip()
    return {t.strip() for t in raw.split(",") if t.strip()}


def tenant_allowed(tenant_doc: Optional[dict], tenant_id: Optional[str]) -> bool:
    if not tenant_id:
        return False
    if tenant_doc and tenant_doc.get("private_mode_pilot") is True:
        return True
    return tenant_id in _env_tenant_allowlist()


# ---------------------------------------------------------------------------
# Niveau 4 — Allowlist VÉHICULE/TRACKER pilote (identité canonique, pas un label).
# Source : vehicle.private_mode_pilot == True  OU tracker ∈ env allowlist.
# ---------------------------------------------------------------------------
def _env_tracker_allowlist() -> set[str]:
    raw = os.environ.get("PRIVATE_MODE_PILOT_TRACKERS", "").strip()
    return {t.strip() for t in raw.split(",") if t.strip()}


def vehicle_is_pilot(vehicle_doc: Optional[dict]) -> bool:
    if not vehicle_doc:
        return False
    if vehicle_doc.get("private_mode_pilot") is True:
        return True
    tid = vehicle_doc.get("navixy_tracker_id")
    return tid is not None and str(tid) in _env_tracker_allowlist()


# ---------------------------------------------------------------------------
# Décision CENTRALE : can_use_private_mode(...)
# ---------------------------------------------------------------------------
async def can_use_private_mode(db, *, tenant_id: Optional[str], tenant_doc: Optional[dict],
                               vehicle_doc: Optional[dict], capability=None) -> dict:
    """Décision unique et fail-closed. Retour :
       {allowed: bool, reason: str|None, http: int, level: str}
    Ne lit aucun secret, n'envoie aucune commande. `capability` = VehicleOdometerCapability|None.
    """
    def deny(reason, level):
        return {"allowed": False, "reason": reason,
                "http": HTTP_BY_REASON.get(reason, 403), "level": level}

    # 1. Feature globale
    if not feature_enabled():
        return deny(R_FEATURE_DISABLED, "feature")

    # 2. Kill switch
    if await kill_switch_active(db):
        return deny(R_KILL_SWITCH, "kill_switch")

    # 3. Tenant
    if not tenant_allowed(tenant_doc, tenant_id):
        return deny(R_TENANT_NOT_ALLOWED, "tenant")

    # 4. Véhicule présent
    if not vehicle_doc:
        return deny(R_NO_VEHICLE, "vehicle")

    # 4b. Véhicule pilote (allowlist)
    if not vehicle_is_pilot(vehicle_doc):
        return deny(R_VEHICLE_NOT_PILOT, "vehicle_pilot")

    # 5. Tracker présent
    tracker_id = vehicle_doc.get("navixy_tracker_id")
    if not tracker_id:
        return deny(R_NO_TRACKER, "tracker")

    # 6. Hardware capability field_validated (ne JAMAIS inventer)
    from app.odometer_capability import resolve_model, vehicle_private_mode_allowed
    model = resolve_model(vehicle_doc.get("model"))
    if not vehicle_private_mode_allowed(model, capability):
        return deny(R_NOT_SUPPORTED, "hardware")

    # 7. Intégration Navixy disponible POUR CE TENANT (fail-closed, jamais cross-tenant)
    from app.integrations import get_integration_credential
    cred = get_integration_credential(tenant_id, "NAVIXY")
    if not cred or not cred.get("credential"):
        return deny(R_INTEGRATION_UNAVAILABLE, "integration")

    return {"allowed": True, "reason": REASON_OK, "http": 200, "level": "ok"}
