"""Défense en profondeur anti-stale — endpoint GET /driver/private-mode.

RÈGLE : un cycle PRIVÉ OUVERT (state==PRIVATE) n'a pas de fin -> l'endpoint
n'expose JAMAIS de valeur terminale (private_distance_km) même si un reliquat
d'un cycle antérieur subsiste dans private_mode_state (bug terrain ancien PROD :
nouveau START mais ancien END/DIST). Hors état PRIVATE, la valeur (ex. cycle clos
BUSINESS) reste exposée normalement.

Tous les accès sont MOCKÉS (aucun réseau, aucune commande device, DEVICE_WRITE non requis).
La gate est neutralisée pour isoler la logique d'exposition (allowed=True stub).
"""
from __future__ import annotations

import asyncio
import os as _os

from app import private_mode_engine as pm
from app import private_mode_gate as _gate
from app import ble_engine as _ble
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
    """Prépare un DB fake + monkeypatch minimal ; renvoie (db, restore)."""
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
    }

    ident.get_db = lambda: db
    _gate.feature_enabled = lambda: True

    async def _kill(_db):
        return False
    _gate.kill_switch_active = _kill
    ident.gate = _gate  # s'assure que la route voit nos stubs

    async def _resolve(_db, _user):
        return "d1"
    _h.resolve_driver_id_for_user = _resolve
    ident.resolve_driver_id_for_user = _resolve

    async def _session(_db, _driver):
        return {"vehicle_id": "vA", "status": "confirmed"}
    _ble.get_current_session = _session

    async def _can_use(_db, **kw):
        return {"allowed": True, "reason": None, "http": 200, "level": "ok"}
    _gate.can_use_private_mode = _can_use

    async def _cap(_db, _tid, _model):
        return None  # capability non requise pour la logique d'exposition
    pm.resolve_vehicle_capability = _cap

    pm.device_write_enabled = lambda: False  # PROD-like ; n'affecte pas allowed

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

    return db, restore


def _get():
    return _run(ident.driver_private_mode_get(user={"tenant_id": "default",
                                                    "email": "d1@x", "role": "driver",
                                                    "id": "u1"}))


def test_open_private_cycle_never_exposes_stale_distance():
    """state==PRIVATE avec reliquats d'un cycle antérieur -> private_distance_km=None."""
    db, restore = _seed({
        "state": pm.PRIVATE,
        # reliquats d'un ANCIEN cycle (bug terrain) — ne doivent PAS être exposés :
        "private_end_odometer_km": 57175.96,
        "private_distance_km": 1.68,
        # bornes du cycle courant :
        "private_start_odometer_km": 57308.13,
    })
    try:
        out = _get()
        assert out["state"] == pm.PRIVATE
        assert out["private_distance_km"] is None  # défense en profondeur
    finally:
        restore()


def test_closed_business_cycle_still_exposes_distance():
    """Hors état PRIVATE (ex. cycle clos), la distance légitime reste exposée."""
    db, restore = _seed({
        "state": pm.BUSINESS,
        "private_start_odometer_km": 57308.13,
        "private_end_odometer_km": 57309.29,
        "private_distance_km": 1.16,          # cycle clos validé terrain
    })
    try:
        out = _get()
        assert out["state"] == pm.BUSINESS
        assert out["private_distance_km"] == 1.16
    finally:
        restore()


def test_unknown_state_exposes_none_distance():
    """UNKNOWN sans distance -> None (aucune valeur inventée)."""
    db, restore = _seed({"state": pm.UNKNOWN})
    try:
        out = _get()
        assert out["private_distance_km"] is None
    finally:
        restore()
