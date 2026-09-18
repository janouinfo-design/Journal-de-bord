"""Terrain 18.09.2026 — confirmation tardive + hygiène d'état Privé/Pro.

Couvre les deux défauts révélés sur LOGITRAK AUDI / FMC130 :
1) une preuve stricte arrivée après le timeout 5 min doit pouvoir récupérer UNKNOWN
   sans renvoyer de commande device ;
2) un nouveau cycle ne doit jamais réutiliser private_end/private_distance/ancre
   d'un cycle précédent.

Tous les appels device/réseau sont mockés. Aucun secret, aucune commande réelle.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from app import private_mode_engine as pm
from app import private_mode_gate as gate
from app import integrations
from app.odometer_capability import (
    VehicleOdometerCapability,
    SOURCE_TELTONIKA_TOTAL_ODOMETER,
    AVL_TOTAL_ODOMETER,
    SCALE_VERIFIED,
)


class _Coll:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None, sort=None):
        rows = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict):
                    # Ces tests n'utilisent pas les opérateurs complexes ici.
                    ok = False
                    break
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                rows.append(dict(d))
        if not rows:
            return None
        return rows[0]

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            nd = dict(q)
            nd.update(upd.get("$set", {}))
            self.docs.append(nd)

    async def insert_one(self, d):
        self.docs.append(dict(d))


class _DB:
    def __init__(self):
        self.vehicles = _Coll()
        self.private_mode_state = _Coll()
        self.vehicle_private_capabilities = _Coll()
        self.audit_log = _Coll()
        self.feature_flags = _Coll()


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _cap():
    return VehicleOdometerCapability(
        vehicle_id="vA",
        tracker_id=781479,
        device_model="FMC130",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER,
        raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16",
        scale_status=SCALE_VERIFIED,
        private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
        runtime_verified=True,
        cumulative_verified=True,
        private_increment_verified=True,
        field_validated=True,
    )


def _db():
    db = _DB()
    _run(db.vehicles.update_one(
        {"id": "vA"},
        {"$set": {
            "id": "vA",
            "tenant_id": "default",
            "model": "telfmu130_fmc130",
            "navixy_tracker_id": 781479,
            "plate": "LOGITRAK AUDI",
            "private_mode_pilot": True,
        }},
        upsert=True,
    ))
    _run(pm.upsert_vehicle_capability(db, _cap()))
    return db


def _enable_legacy_gate(monkeypatch):
    monkeypatch.setenv("PRIVATE_MODE_ENABLED", "1")
    monkeypatch.setenv("PRIVATE_MODE_PILOT_TENANTS", "default")
    monkeypatch.setenv("PRIVATE_MODE_PILOT_TRACKERS", "781479")
    monkeypatch.setenv("PRIVATE_MODE_DEVICE_WRITE", "1")
    monkeypatch.setenv("PRIVATE_MODE_ACCOUNT_MODEL_GATE", "0")

    def _cred(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT"}
        return None

    monkeypatch.setattr(integrations, "get_integration_credential", _cred)


async def _session_ok(_db, driver_id):
    return {"vehicle_id": "vA", "driver_id": driver_id}


async def _real_send(_tracker_id, cmd):
    return {
        "applied": True,
        "mode": "REAL",
        "command": cmd,
        "navixy_command_id": "mock-command-id",
    }


async def _confirm_none(_tracker_id, _expected):
    return None, pm.SRC_UNCONFIRMED


def test_recent_timeout_is_resolution_candidate(monkeypatch):
    now = datetime.now(timezone.utc)
    st = {
        "state": pm.UNKNOWN,
        "transition_result": pm.TRANSITION_TIMEOUT,
        "requested_target": pm.PRIVATE,
        "command_sent_at": (
            now - timedelta(seconds=pm.PENDING_TIMEOUT_S + 10)
        ).isoformat(),
    }
    monkeypatch.setattr(pm, "LATE_CONFIRM_GRACE_S", 1800)
    assert pm.confirmation_resolution_needed(st) is True


def test_old_timeout_is_not_resolution_candidate(monkeypatch):
    now = datetime.now(timezone.utc)
    st = {
        "state": pm.UNKNOWN,
        "transition_result": pm.TRANSITION_TIMEOUT,
        "requested_target": pm.PRIVATE,
        "command_sent_at": (
            now - timedelta(
                seconds=pm.PENDING_TIMEOUT_S + pm.LATE_CONFIRM_GRACE_S + 60
            )
        ).isoformat(),
    }
    assert pm.confirmation_resolution_needed(st) is False


def test_late_private_proof_recovers_unknown_timeout(monkeypatch):
    db = _db()
    now = datetime.now(timezone.utc)
    timeout_at = (now - timedelta(seconds=5)).isoformat()
    sent = (now - timedelta(seconds=pm.PENDING_TIMEOUT_S + 5)).isoformat()

    _run(db.private_mode_state.update_one(
        {"vehicle_id": "vA"},
        {"$set": {
            "vehicle_id": "vA",
            "tenant_id": "default",
            "tracker_id": 781479,
            "state": pm.UNKNOWN,
            "previous_state": pm.BUSINESS,
            "requested_target": pm.PRIVATE,
            "last_command": "privatemode ON",
            "command_sent_at": sent,
            "pending_timeout_at": timeout_at,
            "transition_result": pm.TRANSITION_TIMEOUT,
            "confirmation_source": pm.SRC_UNCONFIRMED,
        }},
        upsert=True,
    ))

    async def _proof(*args, **kwargs):
        return pm.PRIVATE, pm.SRC_TELEMETRY

    monkeypatch.setattr(pm, "telemetry_confirm", _proof)

    out = _run(pm.resolve_pending_confirmation(db, "vA", "default"))

    assert out["state"] == pm.PRIVATE
    assert out["transition_result"] == pm.TRANSITION_CONFIRMED
    assert out["confirmation_source"] == pm.SRC_TELEMETRY
    assert out["pending_timeout_at"] is None
    assert out["recovered_from_timeout_at"] == timeout_at
    assert "requested_target" not in out


def test_late_timeout_without_proof_stays_unknown(monkeypatch):
    db = _db()
    now = datetime.now(timezone.utc)
    sent = (now - timedelta(seconds=pm.PENDING_TIMEOUT_S + 5)).isoformat()

    original = {
        "vehicle_id": "vA",
        "tenant_id": "default",
        "tracker_id": 781479,
        "state": pm.UNKNOWN,
        "requested_target": pm.BUSINESS,
        "last_command": "privatemode OFF",
        "command_sent_at": sent,
        "pending_timeout_at": now.isoformat(),
        "transition_result": pm.TRANSITION_TIMEOUT,
        "confirmation_source": pm.SRC_UNCONFIRMED,
    }
    _run(db.private_mode_state.update_one(
        {"vehicle_id": "vA"}, {"$set": original}, upsert=True
    ))

    async def _no_proof(*args, **kwargs):
        return None, pm.SRC_UNCONFIRMED

    monkeypatch.setattr(pm, "telemetry_confirm", _no_proof)
    out = _run(pm.resolve_pending_confirmation(db, "vA", "default"))

    assert out["state"] == pm.UNKNOWN
    assert out["transition_result"] == pm.TRANSITION_TIMEOUT
    assert out["requested_target"] == pm.BUSINESS


def test_new_private_cycle_clears_old_end_distance_and_anchor(monkeypatch):
    _enable_legacy_gate(monkeypatch)
    db = _db()

    _run(db.private_mode_state.update_one(
        {"vehicle_id": "vA"},
        {"$set": {
            "vehicle_id": "vA",
            "state": pm.BUSINESS,
            "private_end_time": "OLD",
            "private_end_odometer_km": 57175.96,
            "private_distance_km": 1.68,
            "private_gps_anchor_lat": 1.23,
            "private_gps_anchor_lng": 4.56,
            "requested_target": pm.BUSINESS,
            "last_command": "OLD",
            "command_sent_at": "2000-01-01T00:00:00+00:00",
            "navixy_command_id": "OLD",
            "confirmation_source": pm.SRC_UNCONFIRMED,
            "pending_timeout_at": "OLD",
            "transition_result": pm.TRANSITION_TIMEOUT,
        }},
        upsert=True,
    ))

    async def _odo(_tracker):
        return 57308.13

    async def _no_gps(*args, **kwargs):
        return None

    monkeypatch.setattr(pm, "_fetch_gps_state", _no_gps)

    res = _run(pm.request_mode(
        db,
        "d1",
        pm.PRIVATE,
        "driver@example.test",
        resolve_session=_session_ok,
        tenant_id="default",
        send_command=_real_send,
        confirm=_confirm_none,
        read_odo_km=_odo,
    ))

    assert res["state"] == pm.PENDING_CONFIRMATION
    st = _run(pm.get_mode_state(db, "vA"))

    assert st["private_start_odometer_km"] == 57308.13
    assert st["private_end_time"] is None
    assert st["private_end_odometer_km"] is None
    assert st["private_distance_km"] is None
    assert st["private_gps_anchor_lat"] is None
    assert st["private_gps_anchor_lng"] is None
    assert st["pending_timeout_at"] is None
    assert st["transition_result"] is None


def test_business_request_clears_old_end_result_but_preserves_current_start(monkeypatch):
    _enable_legacy_gate(monkeypatch)
    db = _db()

    _run(db.private_mode_state.update_one(
        {"vehicle_id": "vA"},
        {"$set": {
            "vehicle_id": "vA",
            "state": pm.UNKNOWN,
            "private_start_time": "CURRENT_START",
            "private_start_odometer_km": 57308.13,
            "private_gps_anchor_lat": 46.5,
            "private_gps_anchor_lng": 6.6,
            "private_end_time": "STALE_END",
            "private_end_odometer_km": 57175.96,
            "private_distance_km": 1.68,
            "requested_target": pm.PRIVATE,
            "transition_result": pm.TRANSITION_TIMEOUT,
            "pending_timeout_at": "OLD_TIMEOUT",
        }},
        upsert=True,
    ))

    async def _odo(_tracker):
        return 57309.29

    res = _run(pm.request_mode(
        db,
        "d1",
        pm.BUSINESS,
        "driver@example.test",
        resolve_session=_session_ok,
        tenant_id="default",
        send_command=_real_send,
        confirm=_confirm_none,
        read_odo_km=_odo,
    ))

    assert res["state"] == pm.PENDING_CONFIRMATION
    st = _run(pm.get_mode_state(db, "vA"))

    assert st["private_start_odometer_km"] == 57308.13
    assert st["private_gps_anchor_lat"] == 46.5
    assert st["private_gps_anchor_lng"] == 6.6
    assert st["private_end_time"] is None
    assert st["private_end_odometer_km"] is None
    assert st["private_distance_km"] is None
    assert st["pending_timeout_at"] is None
    assert st["transition_result"] is None
