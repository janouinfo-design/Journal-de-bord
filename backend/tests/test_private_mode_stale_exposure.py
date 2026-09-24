"""Défense en profondeur anti-stale — endpoint GET /driver/private-mode."""
from __future__ import annotations

import asyncio

from app import private_mode_engine as pm
from app import private_mode_gate as _gate
from app import ble_engine as _ble
from app import vehicle_assignment as _va
from app.routes import identification as ident
from app.routes import _helpers as _h


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
        self.vehicles = _Coll()
        self.private_mode_state = _Coll()
        self.vehicle_private_capabilities = _Coll()


def _seed(state_doc: dict):
    db = _DB()
    _run(db.vehicles.update_one(
        {"id": "vA"},
        {"$set": {"id": "vA", "tenant_id": "default", "model": "telfmu130_fmc130",
                  "navixy_tracker_id": 781479, "plate": "LOGITRAK AUDI",
                  "private_mode_pilot": True}}, upsert=True))
    _run(db.private_mode_state.update_one(
        {"vehicle_id": "vA"}, {"$set": {"vehicle_id": "vA", **state_doc}}, upsert=True))

    saved = {
        "get_db": ident.get_db,
        "feature_enabled": _gate.feature_enabled,
        "kill_switch_active": _gate.kill_switch_active,
        "resolve": _h.resolve_driver_id_for_user,
        "session": _ble.get_current_session,
        "can_use": _gate.can_use_private_mode,
        "resolve_cap": pm.resolve_vehicle_capability,
        "device_write": pm.device_write_enabled,
        "resolve_active_vehicle": _va.resolve_active_vehicle,
    }

    ident.get_db = lambda: db
    _gate.feature_enabled = lambda: True

    async def _kill(_db):
        return False
    _gate.kill_switch_active = _kill
    ident.gate = _gate

    async def _resolve(_db, _user):
        return "d1"
    _h.resolve_driver_id_for_user = _resolve
    ident.resolve_driver_id_for_user = _resolve

    async def _session(_db, _driver):
        return {"vehicle_id": "vA", "status": "confirmed"}
    _ble.get_current_session = _session

    # Nouvelle architecture : la route résout le véhicule actif via l'affectation.
    async def _resolve_active(_db, _driver, _tenant):
        return "vA"
    _va.resolve_active_vehicle = _resolve_active

    async def _can_use(_db, **kw):
        return {"allowed": True, "reason": None, "http": 200, "level": "ok"}
    _gate.can_use_private_mode = _can_use

    async def _cap(_db, _tid, _model):
        return None
    pm.resolve_vehicle_capability = _cap

    pm.device_write_enabled = lambda: False

    def restore():
        ident.get_db = saved["get_db"]
        _gate.feature_enabled = saved["feature_enabled"]
        _gate.kill_switch_active = saved["kill_switch_active"]
        _h.resolve_driver_id_for_user = saved["resolve"]
        ident.resolve_driver_id_for_user = saved["resolve"]
        _ble.get_current_session = saved["session"]
        _gate.can_use_private_mode = saved["can_use"]
        pm.resolve_vehicle_capability = saved["resolve_cap"]
        pm.device_write_enabled = saved["device_write"]
        _va.resolve_active_vehicle = saved["resolve_active_vehicle"]

    return db, restore


def _get():
    return _run(ident.driver_private_mode_get(user={"tenant_id": "default",
                                                    "email": "d1@x", "role": "driver",
                                                    "id": "u1"}))


def test_open_private_cycle_never_exposes_stale_distance():
    db, restore = _seed({
        "state": pm.PRIVATE,
        "private_end_odometer_km": 57175.96,
        "private_distance_km": 1.68,
        "private_start_odometer_km": 57308.13,
    })
    try:
        out = _get()
        assert out["state"] == pm.PRIVATE
        assert out["private_distance_km"] is None
    finally:
        restore()


def test_closed_business_cycle_still_exposes_distance():
    db, restore = _seed({
        "state": pm.BUSINESS,
        "private_start_odometer_km": 57308.13,
        "private_end_odometer_km": 57309.29,
        "private_distance_km": 1.16,
    })
    try:
        out = _get()
        assert out["state"] == pm.BUSINESS
        assert out["private_distance_km"] == 1.16
    finally:
        restore()


def test_unknown_state_exposes_none_distance_even_if_stale_value_exists():
    db, restore = _seed({
        "state": pm.UNKNOWN,
        "private_distance_km": 1.68,
        "private_end_odometer_km": 57175.96,
    })
    try:
        out = _get()
        assert out["private_distance_km"] is None
    finally:
        restore()


def test_requested_state_never_exposes_previous_cycle_distance():
    db, restore = _seed({
        "state": pm.PRIVATE_REQUESTED,
        "private_distance_km": 1.68,
        "private_end_odometer_km": 57175.96,
    })
    try:
        out = _get()
        assert out["private_distance_km"] is None
    finally:
        restore()
