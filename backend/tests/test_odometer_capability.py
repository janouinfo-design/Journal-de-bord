"""Tests du registre de capacités odomètre par modèle (stratégie par modèle Teltonika).

Vérifie : stratégies cibles par modèle, FMU130 DEPRECATED, FMC003 VEHICLE_DEPENDENT (gate
par véhicule), aucune capacité 'verified' sans preuve terrain, pas d'AVL16 universel,
résolution modèle depuis le code Navixy (piège telfmu130_fmc130 -> FMC130).
"""
from __future__ import annotations

from app.odometer_capability import (
    REGISTRY, resolve_model, get_capability, private_mode_allowed,
    vehicle_private_mode_allowed, VehicleOdometerCapability,
    STATUS_VALIDATED, STATUS_DEPRECATED,
    STRATEGY_TELTONIKA_TOTAL_ODOMETER, STRATEGY_VEHICLE_OBD_CAN_MILEAGE,
    STRATEGY_HARDWARE_CAN_FMS_TACHO, STRATEGY_DEPRECATED,
    AVAIL_VEHICLE_DEPENDENT, VC_CAN_MILEAGE_VALIDATED, VC_NO_HARDWARE_ODOMETER,
)


def test_all_expected_models_present():
    for m in ("FMC003", "FMC130", "FMU130", "FMC640", "FMC650"):
        assert m in REGISTRY, f"modèle manquant: {m}"


def test_target_strategies_per_model():
    assert REGISTRY["FMC003"].strategy == STRATEGY_VEHICLE_OBD_CAN_MILEAGE
    assert REGISTRY["FMC003"].availability == AVAIL_VEHICLE_DEPENDENT
    assert REGISTRY["FMC130"].strategy == STRATEGY_TELTONIKA_TOTAL_ODOMETER
    assert REGISTRY["FMU130"].strategy == STRATEGY_DEPRECATED
    assert REGISTRY["FMC640"].strategy == STRATEGY_HARDWARE_CAN_FMS_TACHO
    assert REGISTRY["FMC650"].strategy == STRATEGY_HARDWARE_CAN_FMS_TACHO


def test_fmu130_deprecated():
    cap = get_capability("FMU130")
    assert cap.status == STATUS_DEPRECATED
    assert private_mode_allowed("FMU130") is False


def test_no_model_is_verified_without_field_proof():
    for m, cap in REGISTRY.items():
        assert cap.verified is False, f"{m} ne doit pas être verified sans preuve terrain"


def test_private_mode_gate_blocks_all_models_now():
    for m in REGISTRY:
        assert private_mode_allowed(m) is False, f"{m} ne doit pas autoriser le mode privé"
    assert private_mode_allowed("FMXUNKNOWN") is False
    assert private_mode_allowed(None) is False


def test_no_universal_avl16():
    for m, cap in REGISTRY.items():
        assert cap.raw_avl_id is None, f"{m}: aucun AVL figé sans preuve terrain"
    assert REGISTRY["FMC130"].navixy_input == "can_mileage"
    assert REGISTRY["FMC130"].strategy == STRATEGY_TELTONIKA_TOTAL_ODOMETER


def test_resolve_model_from_navixy_code():
    assert resolve_model("telfmu130") == "FMU130"
    assert resolve_model("telfmu130_fmc130") == "FMC130"   # piège de nommage
    assert resolve_model("telfmb003_fmc003") == "FMC003"
    assert resolve_model("unknowncode") is None
    assert resolve_model(None) is None


def test_fmc003_gate_is_per_vehicle():
    """Même modèle FMC003 field-validated : la gate reste PAR VÉHICULE."""
    cap = get_capability("FMC003")
    cap.verified = True
    cap.status = STATUS_VALIDATED
    try:
        assert private_mode_allowed("FMC003") is False
        assert private_mode_allowed("FMC003", vehicle_capability=VC_NO_HARDWARE_ODOMETER) is False
        assert private_mode_allowed("FMC003", vehicle_capability=VC_CAN_MILEAGE_VALIDATED) is True
        vc_ok = VehicleOdometerCapability(vehicle_id="vA", device_model="FMC003",
                                          capability=VC_CAN_MILEAGE_VALIDATED, field_validated=True)
        vc_ko = VehicleOdometerCapability(vehicle_id="vB", device_model="FMC003",
                                          capability=VC_CAN_MILEAGE_VALIDATED, field_validated=False)
        assert vehicle_private_mode_allowed("FMC003", vc_ok) is True
        assert vehicle_private_mode_allowed("FMC003", vc_ko) is False
    finally:
        cap.verified = False
        cap.status = "NOT_TESTED"
