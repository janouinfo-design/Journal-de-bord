"""Test d'intégration — request_mode() crée/ferme une session AVL16 (Q4b + END symétrique).

Vérifie le câblage réel dans private_mode_engine.request_mode :
- PRIVATE accepté (REAL) -> session OPEN avec odometer_start (Q4b, à l'envoi accepté) ;
- BUSINESS confirmé      -> session CLOSED avec private_km = end - start.
Hooks device MOCKÉS. Flag PRIVATE_KM_SOURCE_AVL16=1. Aucun réseau/commande réelle.
"""
from __future__ import annotations

import asyncio
import os as _os

from app import private_mode_engine as pm
from app import private_mileage as pmil
from app import private_mode_gate as _gate
from app import integrations as _integrations
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER, AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Fake DB avec collection private_mileage_session (index OPEN unique simulé) ---
class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self):
        self.docs = []

    def _match(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict):
                if "$ne" in v and d.get(k) == v["$ne"]:
                    return False
                if "$gte" in v and not (d.get(k) is not None and d.get(k) >= v["$gte"]):
                    return False
                if "$lte" in v and not (d.get(k) is not None and d.get(k) <= v["$lte"]):
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    async def insert_one(self, d):
        self.docs.append(dict(d))

    async def insert_many(self, ds):
        self.docs.extend(dict(d) for d in ds)

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            nd = dict(q)
            nd.update(upd.get("$set", {}))
            self.docs.append(nd)

    async def update_many(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))

    def find(self, q, proj=None):
        return _Cursor([dict(d) for d in self.docs if self._match(d, q)])


class _DB:
    def __init__(self):
        self._named = {}
        self.vehicles = _Coll()
        self.private_mode_state = _Coll()
        self.vehicle_private_capabilities = _Coll()
        self.audit_log = _Coll()
        self.feature_flags = _Coll()
        self.tenants = _Coll()

    def __getitem__(self, name):
        return self._named.setdefault(name, _Coll())


_ORIG = _integrations.get_integration_credential


def setup_module(_m):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "781479"
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"
    _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "1"
    _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)

    def _stub(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT", "api_url": None}
        return None
    _integrations.get_integration_credential = _stub
    _gate.get_integration_credential = _stub


def teardown_module(_m):
    for k in ("PRIVATE_MODE_ENABLED", "PRIVATE_MODE_PILOT_TENANTS", "PRIVATE_MODE_PILOT_TRACKERS",
              "PRIVATE_MODE_DEVICE_WRITE", "PRIVATE_KM_SOURCE_AVL16"):
        _os.environ.pop(k, None)
    _integrations.get_integration_credential = _ORIG


_VC = VehicleOdometerCapability(
    vehicle_id="vA", tracker_id=781479, device_model="FMC130",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)


def _db():
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"},
         {"$set": {"id": "vA", "tenant_id": "default", "model": "telfmu130_fmc130",
                   "navixy_tracker_id": 781479, "plate": "GE-AUDI",
                   "private_mode_pilot": True}}, upsert=True))
    _run(pm.upsert_vehicle_capability(db, _VC))
    return db


async def _session_ok(db, driver_id):
    return {"vehicle_id": "vA", "driver_id": driver_id}


def _real_cmd():
    async def _c(tid, cmd):
        return {"applied": True, "mode": "REAL", "command": cmd, "navixy_command_id": 1}
    return _c


def _confirm(state):
    async def _cf(tid, expected):
        return (expected if state == "ok" else None), pm.SRC_TELEMETRY
    return _cf


def _odo(seq):
    it = iter(seq)

    async def _r(tid):
        try:
            return next(it)
        except StopIteration:
            return seq[-1]
    return _r


def test_private_then_business_creates_and_closes_session_1024():
    db = _db()
    coll = db["private_mileage_session"]

    # 1) PRIVATE confirmé immédiat -> odo_start=10000.0 -> session OPEN créée (Q4b, à l'envoi).
    _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
         send_command=_real_cmd(), confirm=_confirm("ok"), read_odo_km=_odo([10000.0]),
         tenant_id="default"))
    opens = [d for d in coll.docs if d["state"] == pmil.S_OPEN]
    assert len(opens) == 1
    assert opens[0]["odometer_start_km"] == 10000.0
    assert opens[0]["tracker_id"] == 781479

    # 2) BUSINESS confirmé -> odo_end=10012.4 -> session CLOSED, private_km=12.4
    _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
         send_command=_real_cmd(), confirm=_confirm("ok"), read_odo_km=_odo([10012.4]),
         tenant_id="default"))
    closed = [d for d in coll.docs if d["state"] == pmil.S_CLOSED]
    assert len(closed) == 1
    assert closed[0]["private_km"] == 12.4
    assert closed[0]["quality"] == pmil.Q_OK


def test_private_command_refused_creates_no_session():
    """DEVICE_WRITE=0 -> commande refusée avant envoi -> AUCUNE session (Q4b)."""
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "0"
    try:
        db = _db()
        coll = db["private_mileage_session"]

        def _forbid():
            async def _c(tid, cmd):
                raise AssertionError("aucune commande avec DEVICE_WRITE=0")
            return _c
        res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
                   send_command=_forbid(), confirm=_confirm("ok"), read_odo_km=_odo([10000.0]),
                   tenant_id="default"))
        assert res["ok"] is False
        assert coll.docs == []   # aucune session ouverte
    finally:
        _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"
