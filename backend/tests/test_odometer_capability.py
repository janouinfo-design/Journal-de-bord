"""Tests du registre de capacités odomètre — STRATÉGIE V2 (socle commun AVL 16).

Vérifie : FMC003 & FMC130 -> TELTONIKA_TOTAL_ODOMETER (AVL 16) ; AVL 389 plus requis (secondaire) ;
présence AVL 16 seule != private_mode_allowed ; FIELD_VALIDATED requis (par traceur) ;
FMU130 DEPRECATED ; FMC640/650 pas auto-compatibles ; aucun fallback GPS ; pas de régression.
"""
from __future__ import annotations

from app.odometer_capability import (
    REGISTRY, resolve_model, get_capability, private_mode_allowed,
    vehicle_private_mode_allowed, VehicleOdometerCapability,
    normalize_teltonika_total_odometer, private_mode_production_allowed,
    STATUS_VALIDATED, STATUS_DEPRECATED, STATUS_NOT_PRESENT,
    STRATEGY_TELTONIKA_TOTAL_ODOMETER, STRATEGY_HARDWARE_CAN_FMS_TACHO, STRATEGY_DEPRECATED,
    SOURCE_TELTONIKA_TOTAL_ODOMETER, SOURCE_OBD_OEM_TOTAL_MILEAGE, SOURCE_CAN_MILEAGE,
    SOURCE_NAVIXY_GPS_CALCULATED, AVL_TOTAL_ODOMETER,
    AVAIL_DEVICE_CONFIG, SCALE_UNVERIFIED, SCALE_VERIFIED,
    VC_CAN_MILEAGE_VALIDATED, VC_NO_HARDWARE_ODOMETER,
)


def test_all_expected_models_present():
    for m in ("FMC003", "FMC130", "FMU130", "FMC640", "FMC650"):
        assert m in REGISTRY, f"modèle manquant: {m}"


def test_v2_common_strategy_fmc003_fmc130():
    """V2 : FMC003 ET FMC130 -> TELTONIKA_TOTAL_ODOMETER (AVL 16) en source PRIMAIRE."""
    for m in ("FMC003", "FMC130"):
        cap = REGISTRY[m]
        assert cap.strategy == STRATEGY_TELTONIKA_TOTAL_ODOMETER, m
        assert cap.primary_source == SOURCE_TELTONIKA_TOTAL_ODOMETER, m
        assert cap.availability == AVAIL_DEVICE_CONFIG, m


def test_avl389_is_secondary_for_fmc003_not_required():
    """AVL 389 devient SECONDAIRE pour FMC003 et n'est plus requis."""
    cap = REGISTRY["FMC003"]
    assert cap.secondary_source == SOURCE_OBD_OEM_TOTAL_MILEAGE
    assert cap.primary_source != SOURCE_OBD_OEM_TOTAL_MILEAGE


def test_fmc130_secondary_can_mileage():
    assert REGISTRY["FMC130"].secondary_source == SOURCE_CAN_MILEAGE


def test_fmu130_deprecated():
    cap = get_capability("FMU130")
    assert cap.status == STATUS_DEPRECATED
    assert cap.strategy == STRATEGY_DEPRECATED
    assert private_mode_allowed("FMU130") is False


def test_fmc640_650_not_auto_compatible():
    """Poids lourds : ne PAS appliquer AVL 16 automatiquement."""
    for m in ("FMC640", "FMC650"):
        cap = REGISTRY[m]
        assert cap.strategy == STRATEGY_HARDWARE_CAN_FMS_TACHO
        assert cap.primary_source != SOURCE_TELTONIKA_TOTAL_ODOMETER
        assert cap.status == STATUS_NOT_PRESENT
        assert private_mode_allowed(m) is False


def test_no_model_is_verified_without_field_proof():
    for m, cap in REGISTRY.items():
        assert cap.verified is False, f"{m} ne doit pas être verified sans preuve terrain"


def test_no_universal_avl16_hardcoded():
    """AVL 16 est la CIBLE mais n'est jamais figé comme 'prouvé' au niveau modèle."""
    for m, cap in REGISTRY.items():
        assert cap.raw_avl_id is None, f"{m}: aucun AVL figé sans preuve terrain"


def test_gps_never_admissible_source():
    """Le compteur GPS Navixy n'est jamais une source primaire admissible (sauf FMU130 deprecated)."""
    for m, cap in REGISTRY.items():
        if m == "FMU130":
            continue
        assert cap.primary_source != SOURCE_NAVIXY_GPS_CALCULATED, m


def test_resolve_model_from_navixy_code():
    assert resolve_model("telfmu130") == "FMU130"
    assert resolve_model("telfmu130_fmc130") == "FMC130"   # piège de nommage
    assert resolve_model("telfmb003_fmc003") == "FMC003"
    assert resolve_model("unknowncode") is None
    assert resolve_model(None) is None


def test_presence_of_avl16_alone_is_not_enough():
    """La simple présence d'avl_io_16 (runtime) NE suffit PAS à autoriser le mode privé."""
    vc = VehicleOdometerCapability(
        vehicle_id="mancity", tracker_id=3467714, device_model="FMC003",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16", runtime_verified=True,   # présent seulement
        cumulative_verified=False, private_increment_verified=False, field_validated=False,
    )
    assert vehicle_private_mode_allowed("FMC003", vc) is False


def test_full_field_validation_required_per_tracker():
    """Toutes les étapes requises -> allowed. Une seule manquante -> refusé."""
    base = dict(vehicle_id="mancity", tracker_id=3467714, device_model="FMC003",
                private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER,
                raw_avl_id=AVL_TOTAL_ODOMETER, navixy_input="avl_io_16")
    full = VehicleOdometerCapability(**base, runtime_verified=True, cumulative_verified=True,
                                     private_increment_verified=True, field_validated=True)
    assert vehicle_private_mode_allowed("FMC003", full) is True
    assert vehicle_private_mode_allowed("FMC130", full) is True  # même socle AVL 16

    for missing in ("runtime_verified", "cumulative_verified",
                    "private_increment_verified", "field_validated"):
        flags = dict(runtime_verified=True, cumulative_verified=True,
                     private_increment_verified=True, field_validated=True)
        flags[missing] = False
        vc = VehicleOdometerCapability(**base, **flags)
        assert vehicle_private_mode_allowed("FMC003", vc) is False, f"manquant={missing}"


def test_wrong_source_or_avl_blocks_gate():
    """Source != AVL16 ou raw_avl_id != 16 -> refusé même si tout field-validated."""
    vc_badsrc = VehicleOdometerCapability(
        vehicle_id="v", device_model="FMC003",
        private_distance_source=SOURCE_OBD_OEM_TOTAL_MILEAGE, raw_avl_id=389,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    assert vehicle_private_mode_allowed("FMC003", vc_badsrc) is False

    vc_gps = VehicleOdometerCapability(
        vehicle_id="v", device_model="FMC003",
        private_distance_source=SOURCE_NAVIXY_GPS_CALCULATED, raw_avl_id=16,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    assert vehicle_private_mode_allowed("FMC003", vc_gps) is False


def test_deprecated_and_notpresent_never_allowed_even_if_flags():
    for m in ("FMU130", "FMC640", "FMC650"):
        vc = VehicleOdometerCapability(
            vehicle_id="v", device_model=m,
            private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=16,
            runtime_verified=True, cumulative_verified=True,
            private_increment_verified=True, field_validated=True)
        assert vehicle_private_mode_allowed(m, vc) is False, m


def test_production_gate_disabled_by_default():
    assert private_mode_production_allowed() is False


def test_scale_normalization_explicit():
    """La normalisation AVL 16 n'invente PAS de km sans mapping validé."""
    # Sans mapping validé -> UNVERIFIED, pas de valeur contractuelle
    r = normalize_teltonika_total_odometer(140258496)
    assert r["scale_status"] == SCALE_UNVERIFIED
    assert r["normalized_value"] is None
    # Avec mapping validé (m->km) -> valeur calculée
    r2 = normalize_teltonika_total_odometer(
        140258496, {"multiplier": 1, "divider": 1000, "normalized_unit": "km",
                    "scale_status": SCALE_VERIFIED})
    assert r2["scale_status"] == SCALE_VERIFIED
    assert r2["normalized_value"] == 140258.496
    # raw non numérique -> pas de crash
    r3 = normalize_teltonika_total_odometer(None)
    assert r3["normalized_value"] is None


def test_legacy_model_gate_still_false_by_default():
    """Rétrocompat : la gate niveau modèle reste False tant que non field-validated."""
    for m in REGISTRY:
        assert private_mode_allowed(m) is False
    assert private_mode_allowed("FMXUNKNOWN") is False
    assert private_mode_allowed(None) is False
