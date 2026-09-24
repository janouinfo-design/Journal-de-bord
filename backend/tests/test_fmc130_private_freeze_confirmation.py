"""Tests terrain FMC130: gel persistant multi-polls + timezone Navixy.

Aucun reseau, aucune commande device. Reproduit le terrain 781479 du 24.09.2026:
- gps.updated avance;
- coordonnees restent figees;
- AVL16 augmente;
- le point fige peut etre loin de l'ancre pre-PRIVATE.
"""
import asyncio
from datetime import datetime, timezone, timedelta

from app import private_mode_engine as pm


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Coll:
    def __init__(self):
        self.docs = []

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            d = dict(q)
            d.update(upd.get("$set", {}))
            self.docs.append(d)


class _DB:
    def __init__(self):
        self.private_mode_state = _Coll()


def test_navixy_local_time_europe_zurich_is_normalized_to_utc():
    d = pm._parse_navixy_time("2026-09-24 17:40:41", "Europe/Zurich")
    assert d is not None
    assert d.tzinfo == timezone.utc
    assert d.isoformat() == "2026-09-24T15:40:41+00:00"


def test_navixy_naive_time_without_account_timezone_fails_closed():
    assert pm._parse_navixy_time("2026-09-24 17:40:41", None) is None


def test_fmc130_private_confirmed_by_persistent_frozen_position_and_avl16(monkeypatch):
    db = _DB()
    sent = datetime(2026, 9, 24, 15, 33, 7, tzinfo=timezone.utc)
    state = {
        "vehicle_id": "vA",
        "tenant_id": "default",
        "tracker_id": 781479,
        "state": pm.PENDING_CONFIRMATION,
        "requested_target": pm.PRIVATE,
        "command_sent_at": sent.isoformat(),
        # Terrain: ancre differente du point fige. Le nouveau probe ne doit pas
        # utiliser cette distance comme critere de confirmation.
        "private_gps_anchor_lat": 46.5394933,
        "private_gps_anchor_lng": 6.5790733,
    }

    gps_values = iter([
        {"lat": 46.5410, "lng": 6.5805, "gps_updated": (sent + timedelta(seconds=5)).isoformat()},
        {"lat": 46.5410, "lng": 6.5805, "gps_updated": (sent + timedelta(seconds=15)).isoformat()},
        {"lat": 46.5410, "lng": 6.5805, "gps_updated": (sent + timedelta(seconds=25)).isoformat()},
    ])
    odo_values = iter([57784.00, 57784.08, 57784.16])

    async def fake_gps(_tenant, _tracker):
        return next(gps_values)

    async def fake_odo(_tracker):
        return next(odo_values)

    monkeypatch.setattr(pm, "_fetch_gps_state", fake_gps)

    ok, state = _run(pm._persistent_lkp_private_probe(
        db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
        state_doc=state, read_odo_km=fake_odo))
    assert ok is False
    assert state["private_lkp_probe_count"] == 1

    ok, state = _run(pm._persistent_lkp_private_probe(
        db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
        state_doc=state, read_odo_km=fake_odo))
    assert ok is False
    assert state["private_lkp_probe_count"] == 2

    ok, state = _run(pm._persistent_lkp_private_probe(
        db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
        state_doc=state, read_odo_km=fake_odo))
    assert ok is True
    assert state["private_lkp_probe_count"] == 3


def test_fmc130_private_probe_resets_if_position_moves(monkeypatch):
    db = _DB()
    sent = datetime.now(timezone.utc) - timedelta(seconds=30)
    state = {
        "vehicle_id": "vA",
        "command_sent_at": sent.isoformat(),
    }

    gps_values = iter([
        {"lat": 46.5000, "lng": 6.6000, "gps_updated": (sent + timedelta(seconds=5)).isoformat()},
        {"lat": 46.5100, "lng": 6.6100, "gps_updated": (sent + timedelta(seconds=15)).isoformat()},
        {"lat": 46.5200, "lng": 6.6200, "gps_updated": (sent + timedelta(seconds=25)).isoformat()},
    ])
    odo_values = iter([100.00, 100.10, 100.20])

    async def fake_gps(_tenant, _tracker):
        return next(gps_values)

    async def fake_odo(_tracker):
        return next(odo_values)

    monkeypatch.setattr(pm, "_fetch_gps_state", fake_gps)

    for _ in range(3):
        ok, state = _run(pm._persistent_lkp_private_probe(
            db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
            state_doc=state, read_odo_km=fake_odo))
        assert ok is False
        assert state["private_lkp_probe_count"] == 1


def test_fmc130_private_probe_does_not_confirm_without_odometer_progress(monkeypatch):
    db = _DB()
    sent = datetime.now(timezone.utc) - timedelta(seconds=30)
    state = {
        "vehicle_id": "vA",
        "command_sent_at": sent.isoformat(),
    }

    ticks = iter([5, 15, 25])

    async def fake_gps(_tenant, _tracker):
        sec = next(ticks)
        return {
            "lat": 46.5000,
            "lng": 6.6000,
            "gps_updated": (sent + timedelta(seconds=sec)).isoformat(),
        }

    async def fake_odo(_tracker):
        return 100.0

    monkeypatch.setattr(pm, "_fetch_gps_state", fake_gps)

    for _ in range(3):
        ok, state = _run(pm._persistent_lkp_private_probe(
            db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
            state_doc=state, read_odo_km=fake_odo))
        assert ok is False
