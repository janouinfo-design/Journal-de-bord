"""Tests — cohérence Km Privé des RAPPORTS avec l'agrégateur canonique AVL16.

Vérifie aggregate_private_km_for_scope (multi-véhicule) utilisé par le rapport fiscal :
flag OFF -> GPS legacy (mêmes chiffres qu'avant) ; flag ON + cutover -> AVL16 /
GPS_FALLBACK / MIXED_TRANSITION / UNAVAILABLE, sans double comptage. null != 0.
Fake DB async. Aucun réseau/commande device.
"""
from __future__ import annotations

import asyncio
import os as _os
from datetime import datetime, timezone

from app import private_mileage as pm


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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
                if "$gte" in v and not (d.get(k) is not None and d.get(k) >= v["$gte"]):
                    return False
                if "$lte" in v and not (d.get(k) is not None and d.get(k) <= v["$lte"]):
                    return False
            elif d.get(k) != v:
                return False
        return True

    def find(self, q, proj=None):
        return _Cursor([dict(d) for d in self.docs if self._match(d, q)])


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


def _closed(vid, ended_iso, km):
    return {"tenant_id": "default", "vehicle_id": vid, "state": pm.S_CLOSED,
            "private_ended_at": ended_iso, "private_km": km}


def _y(y=2026):
    return datetime(y, 1, 1, tzinfo=timezone.utc), datetime(y, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


# GPS legacy par véhicule (simule la somme des trajets 'personal').
_GPS = {"vA": 350.0, "vB": 120.0}


async def _gps_for_vehicle(vid, s, e):
    return _GPS.get(vid, 0.0)


def test_flag_off_scope_equals_gps_legacy_sum():
    _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "0"
    try:
        db = _DB()
        s, e = _y()
        r = _run(pm.aggregate_private_km_for_scope(
            db, tenant_id="default", vehicle_ids=["vA", "vB"],
            start_utc=s, end_utc=e, gps_fallback_km_for_vehicle=_gps_for_vehicle))
        assert r["private_km"] == 470.0          # 350 + 120 (mêmes chiffres qu'avant)
        assert r["private_km_source"] == pm.SRC_GPS_FALLBACK
    finally:
        _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "1"


def test_scope_post_cutover_all_avl16():
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-01-01T00:00:00Z"  # tout l'an post-cutover
    try:
        db = _DB()
        db._c.docs += [_closed("vA", "2026-06-10T10:00:00+00:00", 200.0),
                       _closed("vB", "2026-07-01T10:00:00+00:00", 55.0)]
        s, e = _y()
        r = _run(pm.aggregate_private_km_for_scope(
            db, tenant_id="default", vehicle_ids=["vA", "vB"],
            start_utc=s, end_utc=e, gps_fallback_km_for_vehicle=_gps_for_vehicle))
        assert r["private_km"] == 255.0
        assert r["private_km_source"] == pm.SRC_AVL16
        assert r["session_count"] == 2
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def test_scope_post_cutover_no_session_is_unavailable_not_gps():
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-01-01T00:00:00Z"
    try:
        db = _DB()  # aucune session
        s, e = _y()
        r = _run(pm.aggregate_private_km_for_scope(
            db, tenant_id="default", vehicle_ids=["vA", "vB"],
            start_utc=s, end_utc=e, gps_fallback_km_for_vehicle=_gps_for_vehicle))
        assert r["private_km"] is None                    # null != 0
        assert r["private_km_source"] == pm.SRC_UNAVAILABLE
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def test_scope_crossing_cutover_is_mixed_no_double_count():
    # cutover en milieu d'année : GPS avant + AVL16 après, intervalles disjoints
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-07-01T00:00:00Z"
    try:
        db = _DB()
        # sessions AVL16 APRÈS cutover uniquement (rattachées par private_ended_at)
        db._c.docs += [_closed("vA", "2026-08-10T10:00:00+00:00", 220.0)]
        s, e = _y()

        async def gps(vid, s2, e2):
            # doit être borné à [start, cutover]
            assert e2 == datetime(2026, 7, 1, tzinfo=timezone.utc)
            return _GPS.get(vid, 0.0)
        r = _run(pm.aggregate_private_km_for_scope(
            db, tenant_id="default", vehicle_ids=["vA", "vB"],
            start_utc=s, end_utc=e, gps_fallback_km_for_vehicle=gps))
        # vA: GPS 350 (avant) + AVL16 220 (après) ; vB: GPS 120 (avant) + AVL16 0
        assert r["private_km"] == 690.0
        assert r["private_km_source"] == pm.SRC_MIXED
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)


def test_pct_perso_uses_aggregated_private_km():
    """% privé mensuel/fiscal cohérent avec la source AVL16 (pas GPS post-cutover)."""
    _os.environ["PRIVATE_KM_AVL16_CUTOVER_AT"] = "2026-01-01T00:00:00Z"
    try:
        db = _DB()
        db._c.docs += [_closed("vA", "2026-05-01T10:00:00+00:00", 250.0)]
        s, e = _y()
        priv = _run(pm.aggregate_private_km_for_scope(
            db, tenant_id="default", vehicle_ids=["vA"],
            start_utc=s, end_utc=e, gps_fallback_km_for_vehicle=_gps_for_vehicle))
        pro_km = 750.0
        perso_km = priv["private_km"]          # 250 (AVL16), PAS 350 (GPS legacy)
        total = pro_km + perso_km
        pct_perso = round(perso_km / total * 100, 1)
        assert perso_km == 250.0
        assert pct_perso == 25.0               # 250 / 1000
    finally:
        _os.environ.pop("PRIVATE_KM_AVL16_CUTOVER_AT", None)
