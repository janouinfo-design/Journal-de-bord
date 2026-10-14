"""
Tests — politique AUTORITAIRE « Fin de service » ↔ Mode Privé
(app.end_service_policy.decide_end_service).

Cas métier (bug Ivan/S564) :
  1. compte sans Mode Privé + véhicule sans capability  -> END AUTORISÉ
  2. Mode Privé applicable + BUSINESS                    -> END AUTORISÉ
  3. Mode Privé applicable + PRIVATE                     -> END REFUSÉ
  4. Mode Privé applicable + PENDING                     -> END REFUSÉ
  5. Mode Privé applicable + UNKNOWN / erreur lecture    -> END REFUSÉ
"""
from app.end_service_policy import (
    decide_end_service,
    R_END_OK_NOT_APPLICABLE,
    R_END_OK_BUSINESS,
    R_END_BLOCKED_NOT_BUSINESS,
    R_END_BLOCKED_UNREADABLE,
)


# 1) NON applicable (compte sans Mode Privé / véhicule sans capability) -> END OK
def test_not_applicable_allows_end_regardless_of_state():
    d = decide_end_service(private_mode_applicable=False, state=None)
    assert d["private_mode_applicable"] is False
    assert d["end_service_allowed"] is True
    assert d["reason"] == R_END_OK_NOT_APPLICABLE


def test_not_applicable_allows_end_even_if_state_private():
    # Même si un état "PRIVATE" traînait, non applicable -> END autorisée.
    d = decide_end_service(private_mode_applicable=False, state="PRIVATE")
    assert d["end_service_allowed"] is True
    assert d["reason"] == R_END_OK_NOT_APPLICABLE


# 2) Applicable + BUSINESS -> END OK
def test_applicable_business_allows_end():
    d = decide_end_service(private_mode_applicable=True, state="BUSINESS")
    assert d["private_mode_applicable"] is True
    assert d["end_service_allowed"] is True
    assert d["reason"] == R_END_OK_BUSINESS


# 3) Applicable + PRIVATE -> END REFUSÉ
def test_applicable_private_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state="PRIVATE")
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_NOT_BUSINESS


# 4) Applicable + PENDING -> END REFUSÉ
def test_applicable_pending_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state="PENDING_CONFIRMATION")
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_NOT_BUSINESS


def test_applicable_requested_states_block_end():
    for s in ("PRIVATE_REQUESTED", "BUSINESS_REQUESTED"):
        d = decide_end_service(private_mode_applicable=True, state=s)
        assert d["end_service_allowed"] is False, s
        assert d["reason"] == R_END_BLOCKED_NOT_BUSINESS


# 5) Applicable + UNKNOWN / erreur lecture -> END REFUSÉ (fail-closed)
def test_applicable_unknown_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state="UNKNOWN")
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_NOT_BUSINESS


def test_applicable_read_error_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state=None, read_error=True)
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_UNREADABLE


def test_applicable_missing_state_blocks_end():
    # état absent (None) alors que applicable -> fail-closed
    d = decide_end_service(private_mode_applicable=True, state=None)
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_UNREADABLE
