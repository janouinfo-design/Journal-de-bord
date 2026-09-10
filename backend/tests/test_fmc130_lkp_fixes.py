"""Correctifs FMC130 781479 — snapshot AVL16 + timeout de confirmation.

Couvre :
  BUG 1 (snapshot AVL16 null) : T1 snapshot valide -> non null ; T2 indisponible -> null (jamais 0).
  BUG 2 (pending -> UNKNOWN) : T7 timeout previous=BUSINESS -> revient BUSINESS + transition_result=TIMEOUT ;
                               T8 timeout previous=UNKNOWN -> UNKNOWN mais historique conservé, pending=false.
  Sécurité : T9 double request pendant pending -> 0 device command ; T10 DEVICE_WRITE=0 -> 0 device command.

Tous les hooks device/odomètre sont MOCKÉS/INJECTÉS. Aucun appel Navixy/Teltonika réel.
"""
from __future__ import annotations

import asyncio
import os as _os
import pytest

from app import private_mode_engine as pm
from app import private_mode_gate as _gate
from app import integrations as _integrations
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER, AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


# --------- Faux DB minimal ---------
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

    async def insert_one(self, d):
        self.docs.append(dict(d))


class _DB:
    def __init__(self):
        self.vehicles = _Coll()
        self.private_mode_state = _Coll()
        self.vehicle_private_capabilities = _Coll()
        self.audit_log = _Coll()
        self.feature_flags = _Coll()
        self.tenants = _Coll()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# FMC130 field-validated (contexte terrain 781479, raw_avl_id=16, TELTONIKA_TOTAL_ODOMETER)
# est construit par _db_fmc130() ci-dessous.
def _db_fmc130():
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"},
         {"$set": {"id": "vA", "tenant_id": "default", "model": "telfmb130_fmc130",
                   "navixy_tracker_id": 781479, "plate": "LOGITRAK AUDI",
                   "private_mode_pilot": True}}, upsert=True))
    vc = VehicleOdometerCapability(
        vehicle_id="vA", tracker_id=781479, device_model="FMC130",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    _run(pm.upsert_vehicle_capability(db, vc))
    return db


async def _session_ok(db, driver_id):
    return {"vehicle_id": "vA", "driver_id": driver_id}


def _mock_command(applied=True, mode="MOCK"):
    async def _c(tid, cmd):
        assert "privatemode" in cmd and "11000" not in cmd
        return {"applied": applied, "mode": mode, "command": cmd}
    return _c


def _forbid_command():
    async def _c(tid, cmd):
        raise AssertionError("send_command ne doit JAMAIS être appelé (0 device command attendu)")
    return _c


def _confirm(state):
    async def _cf(tid, expected):
        return (expected if state == "ok" else None), "MOCK"
    return _cf


def _odo(seq):
    it = iter(seq)

    async def _r(tid):
        try:
            return next(it)
        except StopIteration:
            return seq[-1]
    return _r


def _odo_none():
    async def _r(tid):
        return None
    return _r


def setup_module(_m):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "781479"
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"  # MACHINE À ÉTATS (hooks mockés)

    def _stub_cred(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT", "api_url": None}
        return None
    setup_module._orig = _integrations.get_integration_credential
    _integrations.get_integration_credential = _stub_cred
    _gate.get_integration_credential = _stub_cred


def teardown_module(_m):
    for k in ("PRIVATE_MODE_ENABLED", "PRIVATE_MODE_PILOT_TENANTS",
              "PRIVATE_MODE_PILOT_TRACKERS", "PRIVATE_MODE_DEVICE_WRITE"):
        _os.environ.pop(k, None)
    _integrations.get_integration_credential = setup_module._orig


# ===========================================================================
# BUG 1 — snapshot AVL16
# ===========================================================================
def test_t1_private_snapshot_avl16_valid_not_null():
    """T1 — PRIVATE avec AVL16 valide -> private_start_odometer_km non null + status OK."""
    db = _db_fmc130()
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_confirm("ok"),
               read_odo_km=_odo([56000.0])))
    assert res["ok"] is True and res["state"] == pm.PRIVATE
    st = _run(pm.get_mode_state(db, "vA"))
    assert st["private_start_odometer_km"] == 56000.0
    assert st["odometer_snapshot_status"] == pm.ODO_SNAPSHOT_OK


def test_t2_private_snapshot_avl16_unavailable_null_never_zero():
    """T2 — PRIVATE avec AVL16 indisponible -> null conservé (JAMAIS 0) + status UNAVAILABLE."""
    db = _db_fmc130()
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_confirm("ok"),
               read_odo_km=_odo_none()))
    st = _run(pm.get_mode_state(db, "vA"))
    assert st["private_start_odometer_km"] is None        # null reste null
    assert st["private_start_odometer_km"] != 0           # jamais 0
    assert st["odometer_snapshot_status"] == pm.ODO_SNAPSHOT_UNAVAILABLE


def test_t2b_snapshot_helper_prod_uses_canonical_reader(monkeypatch):
    """Le path PROD (lecteur par défaut) réutilise read_live_avl16_km (aucun 2e moteur)."""
    db = _db_fmc130()
    calls = {"n": 0}

    async def _fake_reader(_db, *, tenant_id, vehicle_id):
        calls["n"] += 1
        return {"value_km": 123456.789, "reason": None}
    monkeypatch.setattr("app.odometer_calibration.read_live_avl16_km", _fake_reader)
    val, status = _run(pm._read_odometer_snapshot(
        db, "default", "vA", 781479, pm._default_read_odo_km))
    assert calls["n"] == 1                     # lecteur canonique appelé
    assert val == 123456.789 and status == pm.ODO_SNAPSHOT_OK


def test_t2c_snapshot_helper_prod_invalid_value(monkeypatch):
    """VALUE_INVALID -> status INVALID, valeur None (jamais 0)."""
    db = _db_fmc130()

    async def _fake_reader(_db, *, tenant_id, vehicle_id):
        return {"value_km": None, "reason": "VALUE_INVALID"}
    monkeypatch.setattr("app.odometer_calibration.read_live_avl16_km", _fake_reader)
    val, status = _run(pm._read_odometer_snapshot(
        db, "default", "vA", 781479, pm._default_read_odo_km))
    assert val is None and status == pm.ODO_SNAPSHOT_INVALID


# ===========================================================================
# BUG 2 — timeout de confirmation (previous state conservé + transition_result)
# ===========================================================================
def _make_pending(db, previous_state, requested, sent_iso):
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.PENDING_CONFIRMATION,
                   "previous_state": previous_state, "requested_target": requested,
                   "last_command": "setparam privatemode:1", "command_sent_at": sent_iso,
                   "tracker_id": 781479, "tenant_id": "default"}}, upsert=True))


def test_t7_pending_timeout_previous_business_restores_business():
    """T7 — timeout, previous=BUSINESS -> revient BUSINESS (dernier confirmé) + transition_result=TIMEOUT.
    Ne devient JAMAIS faussement PRIVATE ni UNKNOWN. Historique conservé, pending=false."""
    db = _db_fmc130()
    old = "2000-01-01T00:00:00+00:00"  # très ancien -> timeout garanti
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, old)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default",
              read_odo_km=_odo_none()))
    assert st["state"] == pm.BUSINESS                       # dernier état CONFIRMÉ restauré
    assert st["transition_result"] == pm.TRANSITION_TIMEOUT
    assert st["confirmation_source"] == pm.SRC_UNCONFIRMED
    assert st["requested_target"] == pm.PRIVATE             # historique conservé
    assert st["last_command"] == "setparam privatemode:1"
    assert st["command_sent_at"] == old
    assert st["state"] != pm.PENDING_CONFIRMATION           # pending libéré


def test_t8_pending_timeout_previous_unknown_keeps_history():
    """T8 — timeout, previous=UNKNOWN -> UNKNOWN acceptable MAIS historique conservé, pending=false."""
    db = _db_fmc130()
    old = "2000-01-01T00:00:00+00:00"
    _make_pending(db, pm.UNKNOWN, pm.PRIVATE, old)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default",
              read_odo_km=_odo_none()))
    assert st["state"] == pm.UNKNOWN
    assert st["transition_result"] == pm.TRANSITION_TIMEOUT
    assert st["requested_target"] == pm.PRIVATE
    assert st["last_command"] == "setparam privatemode:1"
    assert st["command_sent_at"] == old                     # historique NON perdu
    assert st["confirmation_source"] == pm.SRC_UNCONFIRMED


def test_t8b_pending_not_yet_timed_out_stays_pending():
    """Avant expiration : reste PENDING (aucun écrasement)."""
    from datetime import datetime, timezone
    db = _db_fmc130()
    now = datetime.now(timezone.utc).isoformat()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, now)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default", read_odo_km=_odo_none()))
    assert st["state"] == pm.PENDING_CONFIRMATION


def test_t7b_pending_timeout_confirmed_by_telemetry_wins():
    """Si la télémétrie confirme au moment du resolve -> transition CONFIRMED (pas timeout)."""
    db = _db_fmc130()
    old = "2000-01-01T00:00:00+00:00"
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, old)

    async def _tc(tenant_id, tracker_id, requested_state, command_sent_at_iso, capability,
                  *, state_doc=None, read_odo_km=None, fetch_samples=None):
        return requested_state, pm.SRC_TELEMETRY
    import app.private_mode_engine as _pm
    orig = _pm.telemetry_confirm
    _pm.telemetry_confirm = _tc
    try:
        st = _run(pm.resolve_pending_confirmation(db, "vA", "default", read_odo_km=_odo([56010.0])))
    finally:
        _pm.telemetry_confirm = orig
    assert st["state"] == pm.PRIVATE
    assert st["transition_result"] == pm.TRANSITION_CONFIRMED


# ===========================================================================
# SÉCURITÉ — 0 device command
# ===========================================================================
def test_t9_double_request_during_pending_no_second_command():
    """T9 — 2e request pendant PENDING -> R_TRANSITION_IN_PROGRESS, ZÉRO device command."""
    db = _db_fmc130()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, now)
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_forbid_command(), confirm=_confirm("ok"),
               read_odo_km=_odo([1.0])))
    assert res["ok"] is False and res["can_switch"] is False
    assert res["reason"] == _gate.R_TRANSITION_IN_PROGRESS


def test_t10_device_write_off_zero_command():
    """T10 — DEVICE_WRITE=0 -> aucune commande device, état INCHANGÉ."""
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "0"
    try:
        db = _db_fmc130()
        _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
             {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
        res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
                   send_command=_forbid_command(), confirm=_confirm("ok"),
                   read_odo_km=_odo([1.0])))
        assert res["ok"] is False and res["can_switch"] is False
        assert res["reason"] == _gate.R_DEVICE_WRITE_DISABLED
        st = _run(pm.get_mode_state(db, "vA"))
        assert st["state"] == pm.BUSINESS  # inchangé, aucun PENDING/REQUESTED
    finally:
        _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"


def test_t11_tenant_isolation_snapshot_cross_tenant(monkeypatch):
    """T11 — le snapshot prod passe tenant_id réel ; cross-tenant -> lecteur renvoie NO_VEHICLE (null)."""
    db = _db_fmc130()
    seen = {}

    async def _fake_reader(_db, *, tenant_id, vehicle_id):
        seen["tenant_id"] = tenant_id
        # Simule le comportement tenant-scopé : autre tenant -> pas de véhicule.
        if tenant_id != "default":
            return {"value_km": None, "reason": "NO_VEHICLE"}
        return {"value_km": 56000.0, "reason": None}
    monkeypatch.setattr("app.odometer_calibration.read_live_avl16_km", _fake_reader)
    val, status = _run(pm._read_odometer_snapshot(
        db, "tenantB", "vA", 781479, pm._default_read_odo_km))
    assert seen["tenant_id"] == "tenantB"   # tenant réel propagé (jamais forcé 'default')
    assert val is None and status == pm.ODO_SNAPSHOT_UNAVAILABLE
