"""Tests unitaires — agrégateur Km Privé AVL16 avec CUTOVER (app.private_mileage).

Couvre : flag OFF (legacy GPS), cutover pré/post/traversant, absence de session
post-cutover -> UNAVAILABLE (jamais GPS silencieux), delta négatif, null != 0.
Fake DB async minimal. Aucun réseau, aucune commande device.
"""
from __future__ import annotations

import asyncio
import os as _os
from datetime import datetime, timezone

from app import private_mileage as pm


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---- Fake async collection (juste ce dont l'agrégateur a besoin) ----
class _Cursor:
    def __init__(self, docs):
        self._docs = docs

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

    def find(self, q, proj=None):
        out = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and ("$gte" in v or "$lte" in v):
                    val = d.get(k)
                    if "$gte" in v and not (val is not None and val >= v["$gte"]):
                        ok = False
                    if "$lte" in v and not (val is not None and val <= v["$lte"]):
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok:
                out.append(dict(d))
        return _Cursor(out)


class _DB:
    def __init__(self):
        self._c = _Coll()

    def __getitem__(self, name):
        return self._c


def setup_module(_m):
    _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "1"
    _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def teardown_module(_m):
    _os.environ.pop("PRIVATE_KM_SOURCE_AVL16", None)
    _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _closed(vehicle_id, ended_iso, km):
    return {"tenant_id": "default", "vehicle_id": vehicle_id, "state": pm.S_CLOSED,
            "private_ended_at": ended_iso, "private_km": km}


async def _gps_zero(s, e):
    return 0.0


def test_flag_off_uses_gps_legacy():
    _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "0"
    try:
        db = _DB()

        async def gps(s, e):
            return 350.0
        r = _run(pm.aggregate_private_km(db, tenant_id="default", vehicle_id="vA",
                 start_utc=_dt("2026-09-01T00:00:00"), end_utc=_dt("2026-09-30T23:59:59"),
                 gps_fallback_km=gps))
        assert r["private_km"] == 350.0
        assert r["private_km_source"] == pm.SRC_GPS_FALLBACK
    finally:
        _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "1"


def test_no_cutover_uses_avl16_when_sessions_exist():
    db = _DB()
    db["x"].docs.append(_closed("vA", "2026-09-20T10:00:00+00:00", 12.4))
    r = _run(pm.aggregate_private_km(db, tenant_id="default", vehicle_id="vA",
             start_utc=_dt("2026-09-01T00:00:00"), end_utc=_dt("2026-09-30T23:59:59"),
             gps_fallback_km=_gps_zero))
    assert r["private_km"] == 12.4
    assert r["private_km_source"] == pm.SRC_AVL16
    assert r["session_count"] == 1


def test_period_entirely_pre_cutover_is_gps():
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-09-15T00:00:00Z"
    try:
        db = _DB()

        async def gps(s, e):
            return 350.0
        r = _run(pm.aggregate_private_km(db, tenant_id="default", vehicle_id="vA",
                 start_utc=_dt("2026-09-01T00:00:00"), end_utc=_dt("2026-09-14T23:59:59"),
                 gps_fallback_km=gps))
        assert r["private_km"] == 350.0
        assert r["private_km_source"] == pm.SRC_GPS_FALLBACK
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def test_period_entirely_post_cutover_avl16_or_unavailable():
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-09-15T00:00:00Z"
    try:
        # avec session -> AVL16
        db = _DB()
        db["x"].docs.append(_closed("vA", "2026-09-20T10:00:00+00:00", 20.0))
        r = _run(pm.aggregate_private_km(db, tenant_id="default", vehicle_id="vA",
                 start_utc=_dt("2026-09-16T00:00:00"), end_utc=_dt("2026-09-30T23:59:59"),
                 gps_fallback_km=_gps_zero))
        assert r["private_km"] == 20.0 and r["private_km_source"] == pm.SRC_AVL16

        # sans session post-cutover -> UNAVAILABLE (null), JAMAIS GPS silencieux
        db2 = _DB()

        async def gps(s, e):
            return 999.0  # ne doit PAS être utilisé post-cutover
        r2 = _run(pm.aggregate_private_km(db2, tenant_id="default", vehicle_id="vA",
                  start_utc=_dt("2026-09-16T00:00:00"), end_utc=_dt("2026-09-30T23:59:59"),
                  gps_fallback_km=gps))
        assert r2["private_km"] is None
        assert r2["private_km_source"] == pm.SRC_UNAVAILABLE
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def test_period_crossing_cutover_is_mixed_disjoint():
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-09-15T00:00:00Z"
    try:
        db = _DB()
        db["x"].docs.append(_closed("vA", "2026-09-20T10:00:00+00:00", 220.0))  # après cutover

        async def gps(s, e):
            # doit être appelé sur [start, cutover] -> 350 km legacy
            assert e == _dt("2026-09-15T00:00:00")
            return 350.0
        r = _run(pm.aggregate_private_km(db, tenant_id="default", vehicle_id="vA",
                 start_utc=_dt("2026-09-01T00:00:00"), end_utc=_dt("2026-09-30T23:59:59"),
                 gps_fallback_km=gps))
        assert r["private_km"] == 570.0            # 350 (GPS avant) + 220 (AVL16 après)
        assert r["private_km_source"] == pm.SRC_MIXED
        assert r["gps_km"] == 350.0 and r["avl16_km"] == 220.0
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def test_private_distance_helpers():
    assert pm.private_distance(10000.0, 10012.4) == 12.4
    assert pm.private_distance(10012.4, 10000.0) is None   # delta négatif -> None
    assert pm.private_distance(None, 10.0) is None
    assert pm.private_distance(10.0, None) is None


def test_finalize_fields_fail_closed():
    # odo manquant -> UNAVAILABLE
    f = pm._finalize_fields(None, 10.0, "AVL16", "X", False)
    assert f["private_km"] is None and f["quality"] == pm.Q_UNAVAILABLE
    # delta négatif -> UNAVAILABLE + NEGATIVE_DELTA
    f2 = pm._finalize_fields(20.0, 10.0, "AVL16", "X", False)
    assert f2["private_km"] is None and f2["reason"] == "NEGATIVE_DELTA"
    # ok -> OK
    f3 = pm._finalize_fields(100.0, 112.4, "AVL16", "X", False)
    assert f3["private_km"] == 12.4 and f3["quality"] == pm.Q_OK
    # degraded flag -> DEGRADED
    f4 = pm._finalize_fields(100.0, 112.4, "AVL16", "X", True)
    assert f4["private_km"] == 12.4 and f4["quality"] == pm.Q_DEGRADED
