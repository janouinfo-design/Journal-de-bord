import asyncio

from app.routes import identification as route
from app import navixy_driver_sync as nds


DRIVER_ID = "driver-orhan"
VEHICLE_ID = "vehicle-audi"
SESSION_ID = "session-app-1"
ACTOR = "orhan@logitrak.ch"


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def setup_route(monkeypatch):
    db = object()

    monkeypatch.setattr(route, "get_db", lambda: db)

    async def resolve_driver(_db, _user):
        return DRIVER_ID

    async def authorized(_db, _driver_id):
        return [VEHICLE_ID]

    monkeypatch.setattr(
        route,
        "resolve_driver_id_for_user",
        resolve_driver,
    )
    monkeypatch.setattr(
        route,
        "get_authorized_vehicle_ids_for_driver",
        authorized,
    )

    return db


def test_confirmed_claim_calls_navixy_sync(monkeypatch):
    db = setup_route(monkeypatch)
    calls = []

    async def claim(
        _db, driver_id, vehicle_id, actor,
        client_timestamp=None,
    ):
        assert _db is db
        assert driver_id == DRIVER_ID
        assert vehicle_id == VEHICLE_ID
        assert actor == ACTOR
        return {
            "status": "confirmed",
            "session": {
                "id": SESSION_ID,
                "vehicle_id": VEHICLE_ID,
            },
        }

    async def sync_claim(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        calls.append(
            (_db, driver_id, vehicle_id, session_id, actor)
        )
        return {
            "status": "dry_run",
            "employee_id": 269807,
            "tracker_id": 781479,
        }

    monkeypatch.setattr(route.ble_engine, "claim_driving", claim)
    monkeypatch.setattr(nds, "sync_claim", sync_claim)

    out = run(route.driver_claim(
        route.ClaimIn(vehicle_id=VEHICLE_ID),
        user={"email": ACTOR},
    ))

    assert out["status"] == "confirmed"
    assert out["navixy_sync"]["status"] == "dry_run"
    assert calls == [
        (db, DRIVER_ID, VEHICLE_ID, SESSION_ID, ACTOR)
    ]


def test_conflict_claim_does_not_touch_navixy(monkeypatch):
    setup_route(monkeypatch)

    async def claim(*args, **kwargs):
        return {
            "status": "conflict",
            "session": {"id": SESSION_ID},
        }

    async def must_not_run(*args, **kwargs):
        raise AssertionError(
            "Navixy sync must not run for conflict"
        )

    monkeypatch.setattr(route.ble_engine, "claim_driving", claim)
    monkeypatch.setattr(nds, "sync_claim", must_not_run)

    out = run(route.driver_claim(
        route.ClaimIn(vehicle_id=VEHICLE_ID),
        user={"email": ACTOR},
    ))

    assert out["status"] == "conflict"
    assert "navixy_sync" not in out


def test_stop_calls_navixy_sync(monkeypatch):
    db = setup_route(monkeypatch)
    calls = []

    async def stop(_db, driver_id, actor):
        assert _db is db
        return {
            "stopped": True,
            "session": {
                "id": SESSION_ID,
                "driver_id": DRIVER_ID,
                "vehicle_id": VEHICLE_ID,
                "status": "closed",
            },
        }

    async def sync_stop(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        calls.append(
            (_db, driver_id, vehicle_id, session_id, actor)
        )
        return {
            "status": "dry_run",
            "tracker_id": 781479,
            "employee_id": 269807,
        }

    monkeypatch.setattr(route.ble_engine, "stop_driving", stop)
    monkeypatch.setattr(nds, "sync_stop", sync_stop)

    out = run(route.driver_stop(
        user={"email": ACTOR},
    ))

    assert out["stopped"] is True
    assert out["navixy_sync"]["status"] == "dry_run"
    assert calls == [
        (db, DRIVER_ID, VEHICLE_ID, SESSION_ID, ACTOR)
    ]


def test_idempotent_stop_does_not_touch_navixy(monkeypatch):
    setup_route(monkeypatch)

    async def stop(*args, **kwargs):
        return {
            "stopped": False,
            "message": "Aucune session active",
        }

    async def must_not_run(*args, **kwargs):
        raise AssertionError(
            "Navixy sync must not run without active session"
        )

    monkeypatch.setattr(route.ble_engine, "stop_driving", stop)
    monkeypatch.setattr(nds, "sync_stop", must_not_run)

    out = run(route.driver_stop(
        user={"email": ACTOR},
    ))

    assert out["stopped"] is False
    assert "navixy_sync" not in out
