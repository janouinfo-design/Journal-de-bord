"""Gate Privé/Pro généralisée par compte chauffeur + modèle.

Aucune commande device, aucun réseau, aucun secret.
Le rollout est explicitement activé uniquement dans ces tests.
"""
import asyncio
import os

from app import private_mode_gate as gate
from app import private_mode_engine as pm
from app import integrations
from app.odometer_capability import (
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
    def __init__(self, *, entitled=True, role="driver", linked=True):
        self.feature_flags = _Coll()
        self.vehicle_private_capabilities = _Coll()

        user = {
            "id": "u1",
            "tenant_id": "T1",
            "email": "driver@example.test",
            "role": role,
            "active": True,
            "private_mode_enabled": entitled,
        }
        driver = {
            "id": "d1",
            "tenant_id": "T1",
            "email": "driver@example.test",
            "active": True,
        }
        if linked:
            driver["user_id"] = "u1"

        self.users = _Coll([user])
        self.drivers = _Coll([driver])


def _vehicle(model="telfmu130_fmc130"):
    return {
        "id": "v1",
        "tenant_id": "T1",
        "model": model,
        "navixy_tracker_id": 999001,
        "private_mode_pilot": False,
    }


def _decision(db, model="telfmu130_fmc130"):
    return _run(gate.can_use_private_mode(
        db,
        tenant_id="T1",
        tenant_doc={"id": "T1"},  # aucun flag pilot volontairement
        vehicle_doc=_vehicle(model),
        capability=None,
        driver_id="d1",
    ))


def setup_function(_):
    os.environ["PRIVATE_MODE_ENABLED"] = "1"
    os.environ["PRIVATE_MODE_ACCOUNT_MODEL_GATE"] = "1"
    os.environ.pop("PRIVATE_MODE_PILOT_TENANTS", None)
    os.environ.pop("PRIVATE_MODE_PILOT_TRACKERS", None)


def teardown_function(_):
    os.environ.pop("PRIVATE_MODE_ENABLED", None)
    os.environ.pop("PRIVATE_MODE_ACCOUNT_MODEL_GATE", None)


def test_entitled_driver_fmc130_allowed_without_tracker_allowlist(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY":
            {"credential": "X", "source": "TENANT"} if tenant_id == "T1" else None,
    )
    d = _decision(_DB(), "telfmu130_fmc130")
    assert d["allowed"] is True
    assert d["level"] == "account_model"


def test_entitled_driver_fmc003_allowed_without_tracker_allowlist(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY":
            {"credential": "X", "source": "TENANT"} if tenant_id == "T1" else None,
    )
    d = _decision(_DB(), "telfmb003_fmc003")
    assert d["allowed"] is True


def test_account_entitlement_required(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY": {"credential": "X"},
    )
    d = _decision(_DB(entitled=False))
    assert d["allowed"] is False
    assert d["reason"] == gate.R_ACCOUNT_NOT_ENABLED


def test_only_driver_role_can_use_account_entitlement(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY": {"credential": "X"},
    )
    d = _decision(_DB(entitled=True, role="manager"))
    assert d["allowed"] is False
    assert d["reason"] == gate.R_DRIVER_ACCOUNT_NOT_LINKED


def test_unsupported_model_stays_fail_closed(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY": {"credential": "X"},
    )
    d = _decision(_DB(), "iosnavixytracker_xgps")
    assert d["allowed"] is False
    assert d["reason"] == gate.R_NOT_SUPPORTED


def test_navixy_integration_still_required(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY": None,
    )
    d = _decision(_DB())
    assert d["allowed"] is False
    assert d["reason"] == gate.R_INTEGRATION_UNAVAILABLE


def test_model_profile_fmc130_is_last_known_position():
    cap = _run(pm.resolve_vehicle_capability(_DB(), 999001, "FMC130"))
    assert cap is not None
    assert cap.validation_scope == "MODEL"
    assert cap.device_model == "FMC130"
    assert cap.private_confirmation_strategy == CONFIRM_STRATEGY_LAST_KNOWN_POSITION


def test_model_profile_fmc003_is_frozen_position():
    cap = _run(pm.resolve_vehicle_capability(_DB(), 999002, "FMC003"))
    assert cap is not None
    assert cap.validation_scope == "MODEL"
    assert cap.device_model == "FMC003"
    assert cap.private_confirmation_strategy == CONFIRM_STRATEGY_FROZEN_POSITION


def test_rollout_flag_off_preserves_legacy_gate(monkeypatch):
    os.environ["PRIVATE_MODE_ACCOUNT_MODEL_GATE"] = "0"
    monkeypatch.setattr(
        integrations,
        "get_integration_credential",
        lambda tenant_id=None, provider="NAVIXY": {"credential": "X"},
    )
    d = _decision(_DB())
    assert d["allowed"] is False
    # Aucun tenant/vehicle pilot : le chemin legacy reste bien fermé.
    assert d["reason"] in (
        gate.R_TENANT_NOT_ALLOWED,
        gate.R_VEHICLE_NOT_PILOT,
        gate.R_NOT_SUPPORTED,
    )
