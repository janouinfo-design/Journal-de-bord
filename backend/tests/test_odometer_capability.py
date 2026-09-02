"""Tests du registre de capacités odomètre par modèle (multi-modèles Teltonika).

Vérifie la règle absolue : aucune capacité 'verified' sans preuve terrain, gate
production par modèle, résolution modèle depuis le code Navixy, pas d'AVL16 universel.
"""
from __future__ import annotations

from app.odometer_capability import (
    REGISTRY, resolve_model, get_capability, private_mode_allowed,
    STATUS_VALIDATED, STATUS_NOT_TESTED, RUNTIME_VERIFIED, NOT_SUPPORTED,
)


def test_all_expected_models_present():
    for m in ("FMC003", "FMC130", "FMU130", "FMC640", "FMC650"):
        assert m in REGISTRY, f"modèle manquant: {m}"


def test_no_model_is_verified_without_field_proof():
    # RÈGLE ABSOLUE : aucun modèle ne doit être verified=True à ce stade (aucune preuve terrain).
    for m, cap in REGISTRY.items():
        assert cap.verified is False, f"{m} ne doit pas être verified sans preuve terrain"


def test_private_mode_gate_blocks_unvalidated_models():
    # Aucun modèle validé terrain -> mode privé interdit partout.
    for m in REGISTRY:
        assert private_mode_allowed(m) is False, f"{m} ne doit pas autoriser le mode privé"
    # Modèle inconnu -> interdit aussi.
    assert private_mode_allowed("FMXUNKNOWN") is False
    assert private_mode_allowed(None) is False


def test_no_universal_avl16():
    # AVL16 ne doit PAS être imposé comme constante universelle.
    for m, cap in REGISTRY.items():
        assert cap.raw_avl_id is None, f"{m}: aucun AVL ne doit être figé sans preuve terrain"
    # FMU130 (pilote) : source constatée GPS-calculée, pas de sensor HW
    assert REGISTRY["FMU130"].source_type == "NAVIXY_GPS_CALCULATED"
    assert REGISTRY["FMU130"].navixy_sensor_exposable == NOT_SUPPORTED
    # FMC130 : sensor can_mileage présent MAIS donnée morte (2022) -> non exploitable
    assert REGISTRY["FMC130"].navixy_input == "can_mileage"
    assert REGISTRY["FMC130"].source_type == "NAVIXY_GPS_CALCULATED"
    assert REGISTRY["FMC130"].navixy_sensor_exposable == NOT_SUPPORTED
    assert REGISTRY["FMC130"].odometer_during_private == NOT_SUPPORTED


def test_resolve_model_from_navixy_code():
    assert resolve_model("telfmu130") == "FMU130"
    assert resolve_model("telfmu130_fmc130") == "FMC130"   # piège de nommage: c'est un FMC130
    assert resolve_model("telfmb003_fmc003") == "FMC003"
    assert resolve_model("unknowncode") is None
    assert resolve_model(None) is None


def test_fmu130_pilot_status():
    cap = get_capability("FMU130")
    assert cap.status == "PILOT"
    assert cap.evidence_level == RUNTIME_VERIFIED  # constat "pas de mileage HW exposé"
    assert cap.verified is False


def test_fmc6xx_documented_avl_not_marked_verified():
    # Les AVL 199/216/192 documentés pour FMX6xx ne doivent PAS être 'verified'.
    cap = REGISTRY["FMC650"]
    assert cap.verified is False
    assert cap.raw_avl_id is None  # pas d'AVL figé sans preuve
