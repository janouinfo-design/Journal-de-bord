"""Tests de la gate CENTRALE Mode Privé (sécurisation pilote, fail-closed).

Couvre la hiérarchie : feature global -> kill switch -> tenant -> véhicule pilote
-> tracker -> hardware capability -> intégration Navixy. Isolation multi-tenant.
Aucun appel réseau, aucun secret, aucune commande device.
"""
import asyncio
import os

import pytest

from app import private_mode_gate as gate
from app import integrations as integrations
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER,
    AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Coll:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            nd = dict(q)
            nd.update(upd.get("$set", {}))
            self.docs.append(nd)


class _DB:
    def __init__(self):
        self.feature_flags = _Coll()


VALID_VC = VehicleOdometerCapability(
    vehicle_id="vA", tracker_id=3657864, device_model="FMC003",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)

PILOT_VEHICLE = {"id": "vA", "tenant_id": "T1", "model": "telfmb003_fmc003",
                 "navixy_tracker_id": 3657864, "private_mode_pilot": True}
PILOT_TENANT_DOC = {"id": "T1", "private_mode_pilot": True}

_ORIG_CRED = integrations.get_integration_credential


def setup_function(_f):
    os.environ["PRIVATE_MODE_ENABLED"] = "1"
    os.environ.pop("PRIVATE_MODE_PILOT_TENANTS", None)
    os.environ.pop("PRIVATE_MODE_PILOT_TRACKERS", None)

    def _cred(tenant_id=None, provider="NAVIXY"):
        return {"credential": "X", "source": "TENANT"} if tenant_id == "T1" else None
    integrations.get_integration_credential = _cred
    gate.get_integration_credential = _cred


def teardown_function(_f):
    os.environ.pop("PRIVATE_MODE_ENABLED", None)
    integrations.get_integration_credential = _ORIG_CRED


_SENTINEL = object()


def _decide(db=None, tenant_id="T1", tenant_doc=None, vehicle=_SENTINEL, cap=VALID_VC):
    db = db or _DB()
    veh = PILOT_VEHICLE if vehicle is _SENTINEL else vehicle
    return _run(gate.can_use_private_mode(
        db, tenant_id=tenant_id,
        tenant_doc=tenant_doc if tenant_doc is not None else PILOT_TENANT_DOC,
        vehicle_doc=veh, capability=cap))


# --------- Hiérarchie fail-closed ---------
def test_all_conditions_met_allows():
    d = _decide()
    assert d["allowed"] is True and d["reason"] is None


def test_feature_disabled_blocks():
    os.environ["PRIVATE_MODE_ENABLED"] = "false"
    d = _decide()
    assert d["allowed"] is False and d["reason"] == gate.R_FEATURE_DISABLED


def test_feature_absent_is_failclosed():
    os.environ.pop("PRIVATE_MODE_ENABLED", None)
    d = _decide()
    assert d["allowed"] is False and d["reason"] == gate.R_FEATURE_DISABLED


def test_kill_switch_blocks():
    db = _DB()
    _run(db.feature_flags.update_one({"id": "private_mode"},
         {"$set": {"id": "private_mode", "kill_switch": True}}, upsert=True))
    d = _decide(db=db)
    assert d["allowed"] is False and d["reason"] == gate.R_KILL_SWITCH


def test_tenant_not_allowed_blocks():
    d = _decide(tenant_doc={"id": "T1"})  # pas de private_mode_pilot
    assert d["allowed"] is False and d["reason"] == gate.R_TENANT_NOT_ALLOWED


def test_vehicle_not_pilot_blocks():
    veh = dict(PILOT_VEHICLE)
    veh["private_mode_pilot"] = False
    d = _decide(vehicle=veh)
    assert d["allowed"] is False and d["reason"] == gate.R_VEHICLE_NOT_PILOT


def test_no_tracker_blocks():
    veh = dict(PILOT_VEHICLE)
    veh["navixy_tracker_id"] = None
    d = _decide(vehicle=veh)
    assert d["allowed"] is False and d["reason"] == gate.R_NO_TRACKER


def test_hardware_not_validated_blocks():
    d = _decide(cap=None)
    assert d["allowed"] is False and d["reason"] == gate.R_NOT_SUPPORTED


def test_integration_unavailable_blocks():
    # tenant T2 : la stub credential renvoie None -> intégration indisponible
    veh = dict(PILOT_VEHICLE)
    veh["tenant_id"] = "T2"
    d = _decide(tenant_id="T2", tenant_doc={"id": "T2", "private_mode_pilot": True}, vehicle=veh)
    assert d["allowed"] is False and d["reason"] == gate.R_INTEGRATION_UNAVAILABLE


def test_no_vehicle_blocks():
    d = _decide(vehicle=None)
    assert d["allowed"] is False and d["reason"] == gate.R_NO_VEHICLE


# --------- Allowlist par ENV (dev/pilot) ---------
def test_env_tenant_and_tracker_allowlist():
    os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "T1"
    os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "3657864"
    # tenant_doc sans flag, mais présent dans l'allowlist env
    veh = dict(PILOT_VEHICLE)
    veh["private_mode_pilot"] = False  # pas de flag DB, mais tracker dans env allowlist
    d = _decide(tenant_doc={"id": "T1"}, vehicle=veh)
    assert d["allowed"] is True


# --------- Isolation multi-tenant ---------
def test_cross_tenant_integration_isolation():
    """Tenant T2 autorisé mais SANS credential -> refus (jamais le credential de T1)."""
    veh = dict(PILOT_VEHICLE)
    veh["tenant_id"] = "T2"
    d = _decide(tenant_id="T2", tenant_doc={"id": "T2", "private_mode_pilot": True}, vehicle=veh)
    assert d["allowed"] is False and d["reason"] == gate.R_INTEGRATION_UNAVAILABLE


# --------- Kill switch API ---------
def test_set_and_read_kill_switch():
    db = _DB()
    _run(gate.set_kill_switch(db, True, actor="admin@x"))
    assert _run(gate.kill_switch_active(db)) is True
    _run(gate.set_kill_switch(db, False, actor="admin@x"))
    assert _run(gate.kill_switch_active(db)) is False


def test_http_codes_mapping():
    assert gate.HTTP_BY_REASON[gate.R_FEATURE_DISABLED] == 403
    assert gate.HTTP_BY_REASON[gate.R_NOT_SUPPORTED] == 409
    assert gate.HTTP_BY_REASON[gate.R_INTEGRATION_UNAVAILABLE] == 503
