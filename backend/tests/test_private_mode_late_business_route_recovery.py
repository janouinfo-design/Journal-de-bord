"""GET /driver/private-mode — récupération tardive BUSINESS après timeout.

Régression terrain FMC130:
- OFF envoyé;
- confirmation non obtenue dans la fenêtre PENDING -> UNKNOWN/TIMEOUT;
- le moteur garde awaiting_async_confirm=True pendant sa fenêtre de récupération;
- une trame GPS valide arrive ensuite;
- GET doit rappeler resolve_pending_confirmation() pour promouvoir BUSINESS
  sans nouvelle commande device.

Aucun réseau, aucune commande device, aucune DB réelle.
"""
from __future__ import annotations

import asyncio

from app import private_mode_engine as pm
from app import private_mode_gate as gate
from app import vehicle_assignment as va
from app.routes import identification as ident
from app import tenant_context


VEHICLE_ID = "vA"
TRACKER_ID = 781479
TENANT = "default"


def _run(coro):
    """Run async helpers without closing the process-wide default event loop.

    Several legacy backend tests still use asyncio.get_event_loop().
    asyncio.run() would close/unset that loop and make following test modules
    fail depending on execution order.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _Vehicles:
    async def find_one(self, query, projection=None):
        if query.get("id") != VEHICLE_ID or query.get("tenant_id") != TENANT:
            return None
        return {
            "id": VEHICLE_ID,
            "tenant_id": TENANT,
            "model": "telfmu130_fmc130",
            "navixy_tracker_id": TRACKER_ID,
            "plate": "LOGITRAK AUDI",
            "private_mode_pilot": True,
        }


class _DB:
    def __init__(self):
        self.vehicles = _Vehicles()


def _install_common(monkeypatch, state_doc, *, resolver=None):
    db = _DB()
    monkeypatch.setattr(ident, "get_db", lambda: db)

    async def _driver(_db, _user):
        return "driver-orhan"

    async def _active(_db, driver_id, tenant_id):
        assert driver_id == "driver-orhan"
        assert tenant_id == TENANT
        return VEHICLE_ID

    async def _kill(_db):
        return False

    async def _can_use(_db, **kwargs):
        return {
            "allowed": True,
            "reason": None,
            "http": 200,
            "level": "ok",
        }

    async def _cap(_db, tracker_id, model):
        assert tracker_id == TRACKER_ID
        return None

    async def _state(_db, vehicle_id):
        assert vehicle_id == VEHICLE_ID
        return dict(state_doc)

    monkeypatch.setattr(ident, "resolve_driver_id_for_user", _driver)
    monkeypatch.setattr(va, "resolve_active_vehicle", _active)
    monkeypatch.setattr(gate, "feature_enabled", lambda: True)
    monkeypatch.setattr(gate, "kill_switch_active", _kill)
    monkeypatch.setattr(gate, "can_use_private_mode", _can_use)
    monkeypatch.setattr(gate, "account_model_gate_enabled", lambda: False)
    monkeypatch.setattr(tenant_context, "get_tenant_doc", lambda _tenant: None)
    monkeypatch.setattr(pm, "resolve_vehicle_capability", _cap)
    monkeypatch.setattr(pm, "device_write_enabled", lambda: True)
    monkeypatch.setattr(pm, "get_mode_state", _state)

    if resolver is not None:
        monkeypatch.setattr(pm, "resolve_pending_confirmation", resolver)

    return db


def _get():
    return _run(ident.driver_private_mode_get(user={
        "id": "u-orhan",
        "email": "orhan@logitrak.ch",
        "role": "driver",
        "tenant_id": TENANT,
    }))


def test_get_retries_unknown_timeout_business_awaiting_and_promotes(monkeypatch):
    """Bug terrain : UNKNOWN/TIMEOUT BUSINESS en attente async doit être retenté par GET."""
    before = {
        "vehicle_id": VEHICLE_ID,
        "tracker_id": TRACKER_ID,
        "tenant_id": TENANT,
        "state": pm.UNKNOWN,
        "requested_target": pm.BUSINESS,
        "transition_result": pm.TRANSITION_TIMEOUT,
        "awaiting_async_confirm": True,
        "confirmation_source": pm.SRC_UNCONFIRMED,
        "command_sent_at": "2026-09-25T13:04:24+00:00",
    }
    calls = []

    async def _resolve(_db, vehicle_id, tenant_id):
        calls.append((vehicle_id, tenant_id))
        return {
            **before,
            "state": pm.BUSINESS,
            "requested_target": None,
            "transition_result": pm.TRANSITION_CONFIRMED_LATE,
            "awaiting_async_confirm": False,
            "confirmation_source": pm.SRC_TELEMETRY,
            "confirmed_at": "2026-09-25T14:21:34+00:00",
        }

    _install_common(monkeypatch, before, resolver=_resolve)
    out = _get()

    assert calls == [(VEHICLE_ID, TENANT)]
    assert out["state"] == pm.BUSINESS
    assert out["pending"] is False
    assert out["transition_result"] == pm.TRANSITION_CONFIRMED_LATE
    assert out["confirmation_source"] == pm.SRC_TELEMETRY
    assert out["requested_target"] is None


def test_get_does_not_retry_unknown_timeout_business_when_window_closed(monkeypatch):
    """awaiting_async_confirm=False -> GET ne doit pas relancer le moteur."""
    state = {
        "state": pm.UNKNOWN,
        "requested_target": pm.BUSINESS,
        "transition_result": pm.TRANSITION_TIMEOUT,
        "awaiting_async_confirm": False,
        "confirmation_source": pm.SRC_UNCONFIRMED,
    }

    async def _forbidden(*args, **kwargs):
        raise AssertionError("resolver must not run after async window is closed")

    _install_common(monkeypatch, state, resolver=_forbidden)
    out = _get()

    assert out["state"] == pm.UNKNOWN
    assert out["transition_result"] == pm.TRANSITION_TIMEOUT


def test_get_never_retries_unknown_private_timeout(monkeypatch):
    """Timeout PRIVATE reste fail-closed : pas de promotion tardive via GET."""
    state = {
        "state": pm.UNKNOWN,
        "requested_target": pm.PRIVATE,
        "transition_result": pm.TRANSITION_TIMEOUT,
        "awaiting_async_confirm": True,
        "confirmation_source": pm.SRC_UNCONFIRMED,
    }

    async def _forbidden(*args, **kwargs):
        raise AssertionError("PRIVATE timeout must not use late BUSINESS recovery")

    _install_common(monkeypatch, state, resolver=_forbidden)
    out = _get()

    assert out["state"] == pm.UNKNOWN
    assert out["requested_target"] == pm.PRIVATE


def test_get_still_resolves_classic_pending_confirmation(monkeypatch):
    """Non-régression : PENDING classique continue d'être résolu à chaque GET."""
    before = {
        "state": pm.PENDING_CONFIRMATION,
        "requested_target": pm.BUSINESS,
        "transition_result": None,
        "awaiting_async_confirm": False,
        "confirmation_source": pm.SRC_UNCONFIRMED,
    }
    calls = []

    async def _resolve(_db, vehicle_id, tenant_id):
        calls.append((vehicle_id, tenant_id))
        return {
            **before,
            "state": pm.BUSINESS,
            "requested_target": None,
            "transition_result": pm.TRANSITION_CONFIRMED,
            "confirmation_source": pm.SRC_TELEMETRY,
            "confirmed_at": "2026-09-25T14:30:00+00:00",
        }

    _install_common(monkeypatch, before, resolver=_resolve)
    out = _get()

    assert calls == [(VEHICLE_ID, TENANT)]
    assert out["state"] == pm.BUSINESS
    assert out["transition_result"] == pm.TRANSITION_CONFIRMED
