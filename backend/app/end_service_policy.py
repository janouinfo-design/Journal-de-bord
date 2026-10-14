"""Politique AUTORITAIRE « Fin de service » ↔ Mode Privé.

Règle métier (backend = source de vérité ; l'app ne déduit pas depuis `state`) :

    private mode NON applicable
        => Fin de service AUTORISÉE  (compte sans Mode Privé / véhicule sans capability)

    private mode applicable + BUSINESS confirmé
        => Fin de service AUTORISÉE

    private mode applicable + PRIVATE / PENDING / REQUESTED / UNKNOWN / erreur lecture
        => Fin de service BLOQUÉE  (fail-closed conservé pour les éligibles)

« applicable » = éligibilité calculée par private_mode_gate.can_use_private_mode()
(decision["allowed"]). Si allowed=False, le Mode Privé n'est pas applicable à ce
couple (tenant, chauffeur, véhicule) -> on NE bloque PAS la Fin de service.

NE MODIFIE NI le moteur AVL16 NI la logique de confirmation PRIVATE/BUSINESS :
cette fonction ne fait QUE combiner des signaux déjà calculés ailleurs.
"""
from __future__ import annotations

from typing import Optional

# États "non confirmés BUSINESS" qui bloquent END lorsque le mode est applicable.
# (Alignés sur private_mode_engine : BUSINESS est le SEUL état confirmé autorisant END.)
_BUSINESS = "BUSINESS"

# Raisons renvoyées (stables, testables).
R_END_OK_NOT_APPLICABLE = "END_OK_PRIVATE_MODE_NOT_APPLICABLE"
R_END_OK_BUSINESS = "END_OK_BUSINESS_CONFIRMED"
R_END_BLOCKED_NOT_BUSINESS = "END_BLOCKED_PRIVATE_MODE_NOT_BUSINESS"
R_END_BLOCKED_UNREADABLE = "END_BLOCKED_PRIVATE_MODE_UNREADABLE"


def decide_end_service(
    *,
    private_mode_applicable: bool,
    state: Optional[str],
    read_error: bool = False,
) -> dict:
    """Décision autoritaire de Fin de service.

    Args:
        private_mode_applicable: éligibilité du couple (tenant, chauffeur, véhicule)
            au Mode Privé (= gate.can_use_private_mode(...)["allowed"]).
        state: état Mode Privé courant (private_mode_engine), ex. "BUSINESS",
            "PRIVATE", "PENDING_CONFIRMATION", "UNKNOWN"... Ignoré si non applicable.
        read_error: True si l'état n'a pas pu être lu (fail-closed si applicable).

    Returns:
        {
          "private_mode_applicable": bool,
          "end_service_allowed": bool,
          "reason": str,
        }
    """
    # 1) Mode Privé NON applicable -> Fin de service toujours autorisée.
    if not private_mode_applicable:
        return {
            "private_mode_applicable": False,
            "end_service_allowed": True,
            "reason": R_END_OK_NOT_APPLICABLE,
        }

    # 2) Applicable mais état illisible -> fail-closed (bloqué).
    if read_error or not state:
        return {
            "private_mode_applicable": True,
            "end_service_allowed": False,
            "reason": R_END_BLOCKED_UNREADABLE,
        }

    # 3) Applicable + BUSINESS confirmé -> autorisé. Tout le reste -> bloqué.
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
