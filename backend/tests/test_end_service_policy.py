"""
Tests — politique AUTORITAIRE « Fin de service » ↔ Mode Privé (séparation stricte).

compute_private_mode_applicable() = applicabilité DURABLE (jamais transitoire),
alignée sur les helpers PROD (LEGACY actif ; ACCOUNT_MODEL supporté dynamiquement).
decide_end_service() = décision END à partir de (applicable, state, read_error).

Cas exigés :
  1. account disabled              -> applicable=false  -> END allowed
  2. capability/profile absent     -> applicable=false  -> END allowed
  3. applicable + BUSINESS         -> END allowed
  4. applicable + PRIVATE/PENDING/UNKNOWN -> END blocked
  5. applicable + kill switch (état illisible) -> END blocked (fail-closed)
  6. intégration indisponible      -> NE flippe PAS applicable
  7. erreur technique              -> fail-closed (blocked)
  + Ivan/S564 (legacy non applicable) et Orhan/Audi (legacy applicable)
"""
from app.end_service_policy import (
    compute_private_mode_applicable,
    decide_end_service,
    R_APPLICABLE_ACCOUNT,
    R_APPLICABLE_LEGACY,
    R_NOT_APPLICABLE_ACCOUNT,
    R_NOT_APPLICABLE_LEGACY,
    R_END_OK_NOT_APPLICABLE,
    R_END_OK_BUSINESS,
    R_END_BLOCKED_NOT_BUSINESS,
    R_END_BLOCKED_UNREADABLE,
)


# ===========================================================================
# compute_private_mode_applicable — ACCOUNT_MODEL
# ===========================================================================
def test_account_applicable_all_true():
    r = compute_private_mode_applicable(
        rollout="ACCOUNT_MODEL", tracker_present=True, account_ok=True,
        model_supported=True, profile_ready=True)
    assert r["private_mode_applicable"] is True
    assert r["reason"] == R_APPLICABLE_ACCOUNT


def test_account_disabled_not_applicable():
    # (1) account_ok=False (compte sans private_mode_enabled) -> non applicable
    r = compute_private_mode_applicable(
        rollout="ACCOUNT_MODEL", tracker_present=True, account_ok=False,
        model_supported=True, profile_ready=True)
    assert r["private_mode_applicable"] is False
    assert r["reason"] == R_NOT_APPLICABLE_ACCOUNT


def test_account_profile_absent_not_applicable():
    # (2) profil persistant pas prêt -> non applicable
    r = compute_private_mode_applicable(
        rollout="ACCOUNT_MODEL", tracker_present=True, account_ok=True,
        model_supported=True, profile_ready=False)
    assert r["private_mode_applicable"] is False


def test_account_no_tracker_not_applicable():
    r = compute_private_mode_applicable(
        rollout="ACCOUNT_MODEL", tracker_present=False, account_ok=True,
        model_supported=True, profile_ready=True)
    assert r["private_mode_applicable"] is False


def test_account_model_unsupported_not_applicable():
    r = compute_private_mode_applicable(
        rollout="ACCOUNT_MODEL", tracker_present=True, account_ok=True,
        model_supported=False, profile_ready=True)
    assert r["private_mode_applicable"] is False


# ===========================================================================
# compute_private_mode_applicable — LEGACY (chemin actif PROD)
# ===========================================================================
def test_legacy_applicable_all_true():
    r = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=True,
        tracker_present=True, capability_ready=True)
    assert r["private_mode_applicable"] is True
    assert r["reason"] == R_APPLICABLE_LEGACY


def test_legacy_not_pilot_not_applicable():
    r = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=False,
        tracker_present=True, capability_ready=True)
    assert r["private_mode_applicable"] is False
    assert r["reason"] == R_NOT_APPLICABLE_LEGACY


def test_legacy_capability_absent_not_applicable():
    # (2) capability absente -> non applicable (cas type Ivan/S564 en legacy)
    r = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=True,
        tracker_present=True, capability_ready=False)
    assert r["private_mode_applicable"] is False


def test_legacy_no_tracker_not_applicable():
    r = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=True,
        tracker_present=False, capability_ready=True)
    assert r["private_mode_applicable"] is False


# ===========================================================================
# decide_end_service
# ===========================================================================
def test_not_applicable_allows_end():
    d = decide_end_service(private_mode_applicable=False, state=None)
    assert d["end_service_allowed"] is True
    assert d["reason"] == R_END_OK_NOT_APPLICABLE


def test_not_applicable_allows_end_even_if_state_private():
    d = decide_end_service(private_mode_applicable=False, state="PRIVATE")
    assert d["end_service_allowed"] is True


def test_applicable_business_allows_end():
    d = decide_end_service(private_mode_applicable=True, state="BUSINESS")
    assert d["end_service_allowed"] is True
    assert d["reason"] == R_END_OK_BUSINESS


def test_applicable_private_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state="PRIVATE")
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_NOT_BUSINESS


def test_applicable_pending_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state="PENDING_CONFIRMATION")
    assert d["end_service_allowed"] is False


def test_applicable_requested_states_block_end():
    for s in ("PRIVATE_REQUESTED", "BUSINESS_REQUESTED"):
        assert decide_end_service(private_mode_applicable=True,
                                  state=s)["end_service_allowed"] is False, s


def test_applicable_unknown_blocks_end():
    assert decide_end_service(private_mode_applicable=True,
                              state="UNKNOWN")["end_service_allowed"] is False


# (5) kill switch -> état illisible -> read_error -> bloqué (fail-closed)
def test_applicable_killswitch_state_unreadable_blocks_end():
    d = decide_end_service(private_mode_applicable=True, state=None, read_error=True)
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_UNREADABLE


# (6) intégration indisponible -> NE flippe PAS applicable (aucun param d'intégration)
def test_integration_unavailable_does_not_flip_applicable():
    r = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=True,
        tracker_present=True, capability_ready=True)
    assert r["private_mode_applicable"] is True
    d = decide_end_service(private_mode_applicable=True, state=None, read_error=True)
    assert d["end_service_allowed"] is False


# (7) erreur technique -> fail-closed
def test_read_error_blocks_when_applicable():
    d = decide_end_service(private_mode_applicable=True, state=None, read_error=True)
    assert d["end_service_allowed"] is False
    assert d["reason"] == R_END_BLOCKED_UNREADABLE


# ---------------------------------------------------------------------------
# Cas métier nommés (preuves PROD)
# ---------------------------------------------------------------------------
def test_cas_ivan_s564_legacy_not_applicable_end_allowed():
    # Ivan/S564 FMC003 tracker 3661714 : vehicle_is_pilot=False + capability=False
    appl = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=False,
        tracker_present=True, capability_ready=False)
    d = decide_end_service(private_mode_applicable=appl["private_mode_applicable"],
                           state="UNKNOWN")
    assert appl["private_mode_applicable"] is False
    assert d["end_service_allowed"] is True


def test_cas_orhan_audi_legacy_applicable_private_blocks():
    # Orhan/Audi FMC130 tracker 781479 : pilot + capability -> applicable True
    appl = compute_private_mode_applicable(
        rollout="LEGACY", tenant_pilot=True, vehicle_pilot=True,
        tracker_present=True, capability_ready=True)
    assert appl["private_mode_applicable"] is True
    assert decide_end_service(private_mode_applicable=True,
                              state="PRIVATE")["end_service_allowed"] is False


def test_cas_orhan_audi_business_allows_end():
    assert decide_end_service(private_mode_applicable=True,
                              state="BUSINESS")["end_service_allowed"] is True


def test_cas_orhan_audi_killswitch_does_not_allow_end():
    # applicable=True + kill switch (état illisible) -> bloqué, JAMAIS autorisé.
    d = decide_end_service(private_mode_applicable=True, state=None, read_error=True)
    assert d["end_service_allowed"] is False
