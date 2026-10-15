"""Politique AUTORITAIRE « Fin de service » ↔ Mode Privé.

SÉPARATION STRICTE (corrige la faille : can_use_private_mode().allowed MÉLANGE
applicabilité durable et conditions transitoires — kill switch, feature flag,
intégration Navixy indisponible — donc allowed=False NE signifie PAS « Mode Privé
non applicable »).

Deux notions distinctes :

  1) private_mode_applicable = APPLICABILITÉ DURABLE du couple (chauffeur, véhicule).
     Elle NE dépend QUE de signaux durables :
        - rollout ACCOUNT_MODEL : compte chauffeur lié + private_mode_enabled=True
          + modèle supporté + capability/profile persistant prêt pour ce tracker ;
        - rollout legacy       : tenant pilote + véhicule/tracker pilote
          + capability compatible.
     Les conditions TRANSITOIRES (feature globale, kill switch, intégration Navixy
     indisponible, erreur technique de lecture) NE transforment JAMAIS applicable
     en False.

  2) end_service_allowed = décision Fin de service, à partir de (applicable, state) :
        applicable=false                                  => END AUTORISÉE
        applicable=true + BUSINESS confirmé               => END AUTORISÉE
        applicable=true + PRIVATE/PENDING/REQUESTED/
                          UNKNOWN / read_error            => END BLOQUÉE (fail-closed)

Ainsi, pour un véhicule RÉELLEMENT Mode Privé (applicable=true) dont l'état n'est
pas prouvé BUSINESS (kill switch actif, Navixy indisponible, erreur lecture...),
la Fin de service reste BLOQUÉE — jamais ouverte par erreur.

NE MODIFIE NI le moteur AVL16 NI la logique de confirmation PRIVATE/BUSINESS.
"""
from __future__ import annotations

from typing import Optional

_BUSINESS = "BUSINESS"

# Raisons applicabilité (stables, testables).
R_APPLICABLE_ACCOUNT = "APPLICABLE_ACCOUNT_MODEL"
R_APPLICABLE_LEGACY = "APPLICABLE_LEGACY_PILOT"
R_NOT_APPLICABLE_ACCOUNT = "NOT_APPLICABLE_ACCOUNT"
R_NOT_APPLICABLE_LEGACY = "NOT_APPLICABLE_LEGACY"

# Raisons décision END.
R_END_OK_NOT_APPLICABLE = "END_OK_PRIVATE_MODE_NOT_APPLICABLE"
R_END_OK_BUSINESS = "END_OK_BUSINESS_CONFIRMED"
R_END_BLOCKED_NOT_BUSINESS = "END_BLOCKED_PRIVATE_MODE_NOT_BUSINESS"
R_END_BLOCKED_UNREADABLE = "END_BLOCKED_PRIVATE_MODE_UNREADABLE"


def compute_private_mode_applicable(
    *,
    rollout: str,
    account_ok: bool = False,
    tenant_pilot: bool = False,
    vehicle_pilot: bool = False,
    tracker_present: bool = False,
    model_supported: bool = False,
    capability_ready: bool = False,
    profile_ready: bool = False,
) -> dict:
    """APPLICABILITÉ DURABLE (pure). N'utilise AUCUN signal transitoire.

    Aligné sur les helpers PROD (private_mode_gate) :

      ACCOUNT_MODEL (gate.account_model_gate_enabled() == True) :
        applicable = tracker_present AND account_ok AND model_supported
                     AND profile_ready
        - account_ok      = gate.driver_account_private_mode_enabled(...)[0]
          (compte lié actif + role driver + private_mode_enabled == True)
        - model_supported = model_private_mode_supported(model)
        - profile_ready   = vehicle_private_profile_ready(model, capability,
                                                          tracker_id=tracker_id)

      LEGACY (rollout par défaut, actuellement actif en PROD) :
        applicable = tenant_pilot AND vehicle_pilot AND tracker_present
                     AND capability_ready
        - tenant_pilot     = gate.tenant_allowed(tenant_doc, tenant_id)
        - vehicle_pilot    = gate.vehicle_is_pilot(vehicle)
        - capability_ready = vehicle_private_mode_allowed(model, capability)

    IMPORTANT : cette fonction ne connaît PAS feature flag / kill switch /
    intégration Navixy / DEVICE_WRITE / état courant / erreurs techniques.
    Ces conditions transitoires NE PEUVENT PAS rendre applicable=False.
    """
    if rollout == "ACCOUNT_MODEL":
        applicable = bool(
            tracker_present
            and account_ok
            and model_supported
            and profile_ready
        )
        return {
            "private_mode_applicable": applicable,
            "reason": R_APPLICABLE_ACCOUNT if applicable else R_NOT_APPLICABLE_ACCOUNT,
        }

    # LEGACY (défaut ; chemin actuellement actif en PROD).
    applicable = bool(
        tenant_pilot
        and vehicle_pilot
        and tracker_present
        and capability_ready
    )
    return {
        "private_mode_applicable": applicable,
        "reason": R_APPLICABLE_LEGACY if applicable else R_NOT_APPLICABLE_LEGACY,
    }


def decide_end_service(
    *,
    private_mode_applicable: bool,
    state: Optional[str],
    read_error: bool = False,
) -> dict:
    """Décision autoritaire de Fin de service à partir de (applicable, state).

    `private_mode_applicable` DOIT être l'applicabilité DURABLE (jamais dérivée
    d'un allowed transitoire). `read_error`/kill switch/intégration n'influencent
    PAS applicable : s'ils empêchent de prouver BUSINESS alors que applicable=true,
    la décision est fail-closed (bloquée).

    Returns:
        {"private_mode_applicable": bool, "end_service_allowed": bool, "reason": str}
    """
    if not private_mode_applicable:
        return {
            "private_mode_applicable": False,
            "end_service_allowed": True,
            "reason": R_END_OK_NOT_APPLICABLE,
        }

    if read_error or not state:
        return {
            "private_mode_applicable": True,
            "end_service_allowed": False,
            "reason": R_END_BLOCKED_UNREADABLE,
        }

    if state == _BUSINESS:
        return {
            "private_mode_applicable": True,
            "end_service_allowed": True,
            "reason": R_END_OK_BUSINESS,
        }

    return {
        "private_mode_applicable": True,
        "end_service_allowed": False,
        "reason": R_END_BLOCKED_NOT_BUSINESS,
    }
