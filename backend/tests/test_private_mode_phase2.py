"""Tests Phase 2 — bascule Privé/Professionnel (backend autoritaire).

Couvre la machine à états, la gate par tracker, l'idempotence, la distance AVL16,
la rédaction de position en PRIVATE, la non-généralisation, l'absence de Deep Sleep.
Les hooks device/odomètre sont MOCKÉS (aucun appel Navixy réel).
"""
from __future__ import annotations

import asyncio
import pytest

from app import private_mode_engine as pm
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER, SOURCE_NAVIXY_GPS_CALCULATED,
    AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


# --------- Faux DB minimal en mémoire (async) ---------
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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --------- Fixtures / helpers ---------
FIELD_VALIDATED_VC = VehicleOdometerCapability(
    vehicle_id="vA", tracker_id=3657864, device_model="FMC003",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)


def _db_with_vehicle(tracker_id=3657864, model="telfmb003_fmc003", capability=None):
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"},
         {"$set": {"id": "vA", "tenant_id": "default", "model": model,
                   "navixy_tracker_id": tracker_id, "plate": "GE-TEST"}}, upsert=True))
    if capability is not None:
        _run(pm.upsert_vehicle_capability(db, capability))
    return db


async def _session_ok(db, driver_id):
    return {"vehicle_id": "vA", "driver_id": driver_id}


def _mock_command(applied=True):
    async def _c(tid, cmd):
        assert "privatemode" in cmd and "11000" not in cmd  # jamais Deep Sleep
        return {"applied": applied, "mode": "MOCK", "command": cmd}
    return _c


def _mock_confirm(state):
    async def _cf(tid, expected):
        return (expected if state == "ok" else None), "MOCK"
    return _cf


def _mock_odo(seq):
    it = iter(seq)

    async def _r(tid):
        try:
            return next(it)
        except StopIteration:
            return seq[-1]
    return _r


# --------- Tests ---------
def test_gate_blocks_non_validated_tracker():
    """Tracker inconnu (ni Mongo ni registre pilote) -> refus (pas de commande)."""
    db = _db_with_vehicle(tracker_id=999999, capability=None)  # 999999 non validé
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x",
               resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([100.0])))
    assert res["ok"] is False
    assert res["allowed"] is False
    assert res["reason"] == "capability_not_field_validated"


def test_business_to_private_confirmed():
    """BUSINESS -> PRIVATE_REQUESTED -> PRIVATE seulement après confirmation."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x",
               resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([140000.0])))
    assert res["ok"] is True
    assert res["state"] == pm.PRIVATE
    st = _run(pm.get_mode_state(db, "vA"))
    assert st["state"] == pm.PRIVATE
    assert st["private_start_odometer_km"] == 140000.0


def test_not_confirmed_stays_requested_or_failed():
    """Sans confirmation device -> PAS de passage optimiste à PRIVATE."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x",
               resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("no"),
               read_odo_km=_mock_odo([140000.0])))
    assert res["ok"] is False
    assert res["state"] != pm.PRIVATE  # jamais PRIVATE sans confirmation


def test_private_distance_via_avl16_only():
    """Distance privée = AVL16_end - AVL16_start (pas de GPS). Cycle complet."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    # entrée privé (odo start = 140000)
    _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
         send_command=_mock_command(), confirm=_mock_confirm("ok"),
         read_odo_km=_mock_odo([140000.0])))
    # retour business (odo end = 140005.5) -> distance = 5.5
    res = _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([140005.5])))
    assert res["ok"] is True
    assert res["state"] == pm.BUSINESS
    assert res["private_distance_km"] == 5.5


def test_private_distance_unavailable_if_no_odometer():
    """Odomètre indisponible -> distance UNAVAILABLE, jamais inventée."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
         send_command=_mock_command(), confirm=_mock_confirm("ok"),
         read_odo_km=_mock_odo([None])))
    res = _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([None])))
    assert res.get("private_distance_km") is None
    assert res.get("distance_status") == "UNAVAILABLE"


def test_idempotent_same_mode():
    """Demander PRIVATE alors que déjà PRIVATE -> no-op (aucune commande)."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.PRIVATE}}, upsert=True))
    calls = {"n": 0}

    async def _cmd(tid, c):
        calls["n"] += 1
        return {"applied": True, "mode": "MOCK"}
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_cmd, confirm=_mock_confirm("ok"), read_odo_km=_mock_odo([1])))
    assert res["ok"] is True and res.get("idempotent") is True
    assert calls["n"] == 0  # aucune commande device renvoyée


def test_no_active_vehicle():
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)

    async def _no_sess(_db, _d):
        return None
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_no_sess))
    assert res["ok"] is False and res["reason"] == "no_active_vehicle"


def test_redact_private_location():
    """En PRIVATE : toute position neutralisée ; jamais 0,0 comme donnée métier."""
    obj = {"vehicle_id": "vA", "private_distance_km": 5.5,
           "lat": 46.5, "lng": 6.5, "address": "Lausanne",
           "gps": {"lat": 46.5, "lng": 6.5}, "polyline": "abc"}
    red = pm.redact_private_location(obj, pm.PRIVATE)
    assert red["lat"] is None and red["lng"] is None and red["address"] is None
    assert red["polyline"] is None and red["gps"] is None  # bloc gps entier masqué (plus sûr)
    assert red["private_distance_km"] == 5.5  # champ métier conservé
    # en BUSINESS : rien n'est masqué
    assert pm.redact_private_location(obj, pm.BUSINESS)["lat"] == 46.5


def test_private_trip_dto_has_no_position():
    doc = {"vehicle_id": "vA", "driver_id": "d1", "private_start_time": "t0",
           "private_end_time": "t1", "private_start_odometer_km": 100.0,
           "private_end_odometer_km": 106.0, "private_distance_km": 6.0,
           "odometer_source": SOURCE_TELTONIKA_TOTAL_ODOMETER, "state": pm.PRIVATE,
           "lat": 46.5, "lng": 6.5}
    dto = pm.private_trip_dto(doc)
    for forbidden in ("lat", "lng", "latitude", "longitude", "address", "polyline", "gps"):
        assert forbidden not in dto
    assert dto["private_distance_km"] == 6.0
    assert dto["odometer_source"] == SOURCE_TELTONIKA_TOTAL_ODOMETER


def test_gps_source_never_allowed_for_private_distance():
    """Une capability sur source GPS Navixy -> gate refuse (jamais de distance GPS privée)."""
    vc_gps = VehicleOdometerCapability(
        vehicle_id="vA", tracker_id=3657864, device_model="FMC003",
        private_distance_source=SOURCE_NAVIXY_GPS_CALCULATED, raw_avl_id=16,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    db = _db_with_vehicle(capability=vc_gps)
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([1])))
    assert res["ok"] is False and res["allowed"] is False


def test_deep_sleep_never_used():
    """Le mapping de commandes n'utilise jamais Deep Sleep 11000."""
    assert "11000" not in pm._CMD[pm.PRIVATE]
    assert "11000" not in pm._CMD[pm.BUSINESS]
    assert pm._CMD[pm.PRIVATE] == "privatemode ON"
    assert pm._CMD[pm.BUSINESS] == "privatemode OFF"


def test_device_write_gated_by_default(monkeypatch):
    """Par défaut, l'envoi device réel est désactivé (simulation)."""
    monkeypatch.delenv("PRIVATE_MODE_DEVICE_WRITE", raising=False)
    assert pm.device_write_enabled() is False
    monkeypatch.setenv("PRIVATE_MODE_DEVICE_WRITE", "1")
    assert pm.device_write_enabled() is True
