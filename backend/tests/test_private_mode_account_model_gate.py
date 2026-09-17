"""Gate Privé/Pro généralisée : compte + modèle + profil technique tracker.

Aucun réseau. Aucune commande device. Aucun secret.
Le rollout est activé uniquement dans ces tests.
"""
import asyncio
import os

from app import private_mode_gate as gate
from app import private_mode_engine as pm
from app import integrations
from app.odometer_capability import (
    VehicleOdometerCapability,
    SOURCE_TELTONIKA_TOTAL_ODOMETER,
    AVL_TOTAL_ODOMETER,
    SCALE_VERIFIED,
    CONFIRM_STRATEGY_FROZEN_POSITION,
    CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, q, proj=None):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in q.items()):
                return dict(doc)
        return None


class _DB:
    def __init__(
        self,
        *,
        entitled=True,
        role="driver",
        active=True,
        capability_docs=None,
    ):
        self.feature_flags = _Coll()
        self.vehicle_private_capabilities = _Coll(capability_docs)

        self.users = _Coll([{
            "id": "u1",
            "tenant_id": "T1",
            "email": "driver@example.test",
            "role": role,
            "active": active,
            "private_mode_enabled": entitled,
        }])

        self.drivers = _Coll([{
            "id": "d1",
            "tenant_id": "T1",
            "email": "driver@example.test",
            "user_id": "u1",
            "active": active,
        }])


def _vehicle(model="telfmu130_fmc130", tracker=999001):
    return {
        "id": "v1",
        "tenant_id": "T1",
        "model": model,
        "navixy_tracker_id": tracker,
        "private_mode_pilot": False,
    }


def _ready_cap(
    model="FMC130",
    tracker=999001,
    *,
    profile_ready=True,
    field_validated=False,
    sensor_id=7001,
    strategy=None,
):
    if strategy is None:
        strategy = (
            CONFIRM_STRATEGY_LAST_KNOWN_POSITION
            if model == "FMC130"
            else CONFIRM_STRATEGY_FROZEN_POSITION
        )

    return VehicleOdometerCapability(
        vehicle_id="v1",
        tracker_id=tracker,
        device_model=model,
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER,
        raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16",
        navixy_sensor_id=sensor_id,
        raw_unit="m",
        normalized_unit="km",
        multiplier=1.0,
        divider=1000.0,
        scale_status=SCALE_VERIFIED,
        runtime_verified=True,
        cumulative_verified=True,
        private_increment_verified=True,
        field_validated=field_validated,
        profile_ready=profile_ready,
        profile_ready_source="PROVISIONING_VERIFIED" if profile_ready else None,
        private_confirmation_strategy=strategy,
        source_type=SOURCE_TELTONIKA_TOTAL_ODOMETER,
        unit="km",
    )


def _decision(db, *, model="telfmu130_fmc130", tracker=999001, cap=None):
    return _run(gate.can_use_private_mode(
        db,
        tenant_id="T1",
        tenant_doc={"id": "T1"},
        vehicle_doc=_vehicle(model, tracker),
        capability=cap,
        driver_id="d1",
    ))


def _cred(tenant_id=None, provider="NAVIXY"):
    return {"credential": "X", "source": "TENANT"} if tenant_id == "T1" else None


def setup_function(_):
    os.environ["PRIVATE_MODE_ENABLED"] = "1"
    os.environ["PRIVATE_MODE_ACCOUNT_MODEL_GATE"] = "1"
    os.environ.pop("PRIVATE_MODE_PILOT_TENANTS", None)
    os.environ.pop("PRIVATE_MODE_PILOT_TRACKERS", None)


def teardown_function(_):
    os.environ.pop("PRIVATE_MODE_ENABLED", None)
    os.environ.pop("PRIVATE_MODE_ACCOUNT_MODEL_GATE", None)


def test_entitled_driver_ready_fmc130_allowed(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap("FMC130", 999001)
    d = _decision(_DB(), cap=cap)
    assert d["allowed"] is True
    assert d["level"] == "account_model"


def test_entitled_driver_ready_fmc003_allowed(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap("FMC003", 999002)
    d = _decision(
        _DB(),
        model="telfmb003_fmc003",
        tracker=999002,
        cap=cap,
    )
    assert d["allowed"] is True


def test_model_alone_never_allows(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    d = _decision(_DB(), cap=None)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_PROFILE_NOT_READY


def test_profile_ready_attestation_required(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap("FMC130", 999001, profile_ready=False)
    d = _decision(_DB(), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_PROFILE_NOT_READY


def test_historical_field_validated_is_accepted(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap(
        "FMC130", 999001,
        profile_ready=False,
        field_validated=True,
    )
    d = _decision(_DB(), cap=cap)
    assert d["allowed"] is True


def test_sensor_mapping_required(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap("FMC130", 999001, sensor_id=None)
    d = _decision(_DB(), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_PROFILE_NOT_READY


def test_tracker_capability_must_match_vehicle(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap("FMC130", 999999)
    d = _decision(_DB(), tracker=999001, cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_PROFILE_NOT_READY


def test_fmc130_requires_explicit_lkp_strategy(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap(
        "FMC130", 999001,
        strategy=CONFIRM_STRATEGY_FROZEN_POSITION,
    )
    d = _decision(_DB(), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_PROFILE_NOT_READY


def test_account_entitlement_required(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap()
    d = _decision(_DB(entitled=False), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_ACCOUNT_NOT_ENABLED


def test_only_active_driver_account_allowed(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap()
    d = _decision(_DB(active=False), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_DRIVER_ACCOUNT_NOT_LINKED


def test_only_driver_role_can_use_entitlement(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap()
    d = _decision(_DB(role="manager"), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_DRIVER_ACCOUNT_NOT_LINKED


def test_unsupported_model_stays_fail_closed(monkeypatch):
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)
    cap = _ready_cap()
    d = _decision(
        _DB(),
        model="iosnavixytracker_xgps",
        cap=cap,
    )
    assert d["allowed"] is False
    assert d["reason"] == gate.R_NOT_SUPPORTED


def test_navixy_integration_still_required(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY": None,
    )
    cap = _ready_cap()
    d = _decision(_DB(), cap=cap)
    assert d["allowed"] is False
    assert d["reason"] == gate.R_INTEGRATION_UNAVAILABLE


def test_rollout_flag_off_preserves_legacy_gate(monkeypatch):
    os.environ["PRIVATE_MODE_ACCOUNT_MODEL_GATE"] = "0"
    monkeypatch.setattr(integrations, "get_integration_credential", _cred)

    cap = _ready_cap()
    d = _decision(_DB(), cap=cap)

    # Pas de tenant/vehicle pilot dans ce test :
    # le chemin legacy reste donc fermé.
    assert d["allowed"] is False
    assert d["reason"] == gate.R_TENANT_NOT_ALLOWED


def test_generalized_resolver_never_invents_model_profile():
    db = _DB()
    cap = _run(pm.resolve_vehicle_capability(db, 999001, "FMC130"))
    assert cap is None


def test_generalized_resolver_uses_persisted_profile():
    cap = _ready_cap("FMC130", 999001)
    db = _DB(capability_docs=[cap.to_dict()])

    resolved = _run(pm.resolve_vehicle_capability(db, 999001, "FMC130"))

    assert resolved is not None
    assert resolved.tracker_id == 999001
    assert resolved.profile_ready is True
    assert resolved.navixy_sensor_id == 7001


def test_legacy_pilot_registry_still_available_when_rollout_off():
    os.environ["PRIVATE_MODE_ACCOUNT_MODEL_GATE"] = "0"

    cap = _run(pm.resolve_vehicle_capability(_DB(), 3657864, "FMC003"))

    assert cap is not None
    assert cap.tracker_id == 3657864
    assert cap.field_validated is True


def test_private_odometer_supported_accepts_profile_ready_in_generalized_mode():
    from app.routes.identification import _private_odometer_supported

    cap = _ready_cap(
        "FMC130",
        999001,
        profile_ready=True,
        field_validated=False,
    )

    assert _private_odometer_supported(
        "FMC130",
        cap,
        999001,
        generalized=True,
    ) is True


def test_private_odometer_supported_model_only_stays_false():
    from app.routes.identification import _private_odometer_supported

    assert _private_odometer_supported(
        "FMC130",
        None,
        999001,
        generalized=True,
    ) is False


def test_private_odometer_supported_preserves_legacy_field_validated():
    from app.routes.identification import _private_odometer_supported

    cap = _ready_cap(
        "FMC130",
        999001,
        profile_ready=False,
        field_validated=True,
    )

    assert _private_odometer_supported(
        "FMC130",
        cap,
        999001,
        generalized=False,
    ) is True
