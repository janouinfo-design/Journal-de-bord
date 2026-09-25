import asyncio

from app.routes import identification as route
from app import navixy_driver_sync as nds
from app import vehicle_assignment as va


DRIVER_ID = "driver-orhan"
VEHICLE_A = "vehicle-audi"
VEHICLE_B = "vehicle-b"
VEHICLE_C = "vehicle-c"
ACTOR = "orhan@logitrak.ch"
TENANT = "default"


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _Events:
    def __init__(self):
        self.event = None

    async def find_one(self, query, projection=None):
        if not self.event:
            return None
        return dict(self.event)


class _DB:
    def __init__(self):
        self.vehicle_assignment_events = _Events()


def setup_route(monkeypatch):
    db = _DB()
    monkeypatch.setattr(route, "get_db", lambda: db)

    async def resolve_driver(_db, _user):
        return DRIVER_ID

    async def authorized(_db, _driver_id):
        return [VEHICLE_A, VEHICLE_B, VEHICLE_C]

    async def passthrough_assignment(_db, _tenant, assignment):
        return dict(assignment) if assignment else None

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
    monkeypatch.setattr(
        route,
        "_assign_with_vehicle",
        passthrough_assignment,
    )

    return db


def user():
    return {
        "email": ACTOR,
        "tenant_id": TENANT,
        "role": "driver",
    }


def test_take_success_projects_current_assignment_to_navixy(monkeypatch):
    db = setup_route(monkeypatch)
    calls = []

    async def take(*args, **kwargs):
        return {
            "result": "ok",
            "assignment": {
                "vehicle_id": VEHICLE_A,
                "status": "ACTIVE",
            },
        }

    async def sync_claim(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        calls.append((_db, driver_id, vehicle_id, actor))
        return {"status": "synced", "result": "assigned"}

    monkeypatch.setattr(va, "take", take)
    monkeypatch.setattr(nds, "sync_claim", sync_claim)

    out = run(route.vehicle_assignment_take(
        route.AssignIn(vehicle_id=VEHICLE_A, request_id="take-1"),
        user=user(),
    ))

    assert out["ok"] is True
    assert out["navixy_sync"]["status"] == "synced"
    assert calls == [(db, DRIVER_ID, VEHICLE_A, ACTOR)]


def test_take_conflict_never_writes_navixy(monkeypatch):
    setup_route(monkeypatch)

    async def take(*args, **kwargs):
        return {
            "result": "conflict",
            "reason": "VEHICLE_OCCUPIED",
            "assignment": None,
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("Navixy must not be written on conflict")

    monkeypatch.setattr(va, "take", take)
    monkeypatch.setattr(nds, "sync_claim", forbidden)

    out = run(route.vehicle_assignment_take(
        route.AssignIn(vehicle_id=VEHICLE_A, request_id="take-conflict"),
        user=user(),
    ))

    assert out["ok"] is False
    assert out["http_status"] == 409
    assert "navixy_sync" not in out


def test_take_old_idempotent_retry_cannot_reassign_previous_vehicle(monkeypatch):
    setup_route(monkeypatch)

    async def take(*args, **kwargs):
        # Old TAKE(A) request replayed after the Journal already moved to B.
        return {
            "result": "ok",
            "idempotent": True,
            "assignment": {
                "vehicle_id": VEHICLE_B,
                "status": "ACTIVE",
            },
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("stale TAKE retry must not write Navixy")

    monkeypatch.setattr(va, "take", take)
    monkeypatch.setattr(nds, "sync_claim", forbidden)

    out = run(route.vehicle_assignment_take(
        route.AssignIn(vehicle_id=VEHICLE_A, request_id="old-take-a"),
        user=user(),
    ))

    assert out["ok"] is True
    assert out["navixy_sync"]["status"] == "skipped"
    assert out["navixy_sync"]["result"] == "superseded"
    assert out["navixy_sync"]["current_vehicle_id"] == VEHICLE_B


def test_change_success_stops_previous_then_claims_current(monkeypatch):
    db = setup_route(monkeypatch)
    order = []

    async def get_active(*args, **kwargs):
        return {"vehicle_id": VEHICLE_A, "status": "ACTIVE"}

    async def change(*args, **kwargs):
        return {
            "result": "ok",
            "assignment": {
                "vehicle_id": VEHICLE_B,
                "previous_vehicle_id": VEHICLE_A,
                "status": "ACTIVE",
            },
        }

    async def sync_stop(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        order.append(("stop", vehicle_id))
        return {"status": "synced", "result": "unassigned"}

    async def sync_claim(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        order.append(("claim", vehicle_id))
        return {"status": "synced", "result": "assigned"}

    monkeypatch.setattr(va, "get_active", get_active)
    monkeypatch.setattr(va, "change", change)
    monkeypatch.setattr(nds, "sync_stop", sync_stop)
    monkeypatch.setattr(nds, "sync_claim", sync_claim)

    out = run(route.vehicle_assignment_change(
        route.AssignIn(vehicle_id=VEHICLE_B, request_id="change-a-b"),
        user=user(),
    ))

    assert out["ok"] is True
    assert order == [
        ("stop", VEHICLE_A),
        ("claim", VEHICLE_B),
    ]
    assert (
        out["navixy_sync"]["previous_vehicle"]["vehicle_id"]
        == VEHICLE_A
    )
    assert (
        out["navixy_sync"]["current_vehicle"]["vehicle_id"]
        == VEHICLE_B
    )


def test_change_idempotent_retry_can_heal_same_a_to_b_transition(monkeypatch):
    db = setup_route(monkeypatch)
    db.vehicle_assignment_events.event = {
        "type": "VEHICLE_CHANGED",
        "result": "OK",
        "from_vehicle_id": VEHICLE_A,
        "to_vehicle_id": VEHICLE_B,
    }
    order = []

    async def get_active(*args, **kwargs):
        return {"vehicle_id": VEHICLE_B, "status": "ACTIVE"}

    async def change(*args, **kwargs):
        return {
            "result": "ok",
            "idempotent": True,
            "assignment": {
                "vehicle_id": VEHICLE_B,
                "status": "ACTIVE",
            },
        }

    async def sync_stop(*args, **kwargs):
        order.append(("stop", args[2]))
        return {"status": "synced", "result": "already_unassigned"}

    async def sync_claim(*args, **kwargs):
        order.append(("claim", args[2]))
        return {"status": "synced", "result": "already_assigned"}

    monkeypatch.setattr(va, "get_active", get_active)
    monkeypatch.setattr(va, "change", change)
    monkeypatch.setattr(nds, "sync_stop", sync_stop)
    monkeypatch.setattr(nds, "sync_claim", sync_claim)

    out = run(route.vehicle_assignment_change(
        route.AssignIn(vehicle_id=VEHICLE_B, request_id="change-a-b"),
        user=user(),
    ))

    assert out["ok"] is True
    assert order == [
        ("stop", VEHICLE_A),
        ("claim", VEHICLE_B),
    ]


def test_change_old_retry_after_newer_change_is_superseded(monkeypatch):
    db = setup_route(monkeypatch)
    db.vehicle_assignment_events.event = {
        "type": "VEHICLE_CHANGED",
        "result": "OK",
        "from_vehicle_id": VEHICLE_A,
        "to_vehicle_id": VEHICLE_B,
    }

    async def get_active(*args, **kwargs):
        return {"vehicle_id": VEHICLE_C, "status": "ACTIVE"}

    async def change(*args, **kwargs):
        return {
            "result": "ok",
            "idempotent": True,
            "assignment": {
                "vehicle_id": VEHICLE_C,
                "status": "ACTIVE",
            },
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("superseded CHANGE retry must not write Navixy")

    monkeypatch.setattr(va, "get_active", get_active)
    monkeypatch.setattr(va, "change", change)
    monkeypatch.setattr(nds, "sync_stop", forbidden)
    monkeypatch.setattr(nds, "sync_claim", forbidden)

    out = run(route.vehicle_assignment_change(
        route.AssignIn(vehicle_id=VEHICLE_B, request_id="old-change-a-b"),
        user=user(),
    ))

    assert out["ok"] is True
    assert out["navixy_sync"]["status"] == "skipped"
    assert out["navixy_sync"]["result"] == "superseded"
    assert out["navixy_sync"]["current_vehicle_id"] == VEHICLE_C


def test_change_conflict_never_touches_navixy(monkeypatch):
    setup_route(monkeypatch)

    async def get_active(*args, **kwargs):
        return {"vehicle_id": VEHICLE_A, "status": "ACTIVE"}

    async def change(*args, **kwargs):
        return {
            "result": "conflict",
            "reason": "VEHICLE_OCCUPIED",
            "assignment": {"vehicle_id": VEHICLE_A, "status": "ACTIVE"},
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("Navixy must not be written on conflict")

    monkeypatch.setattr(va, "get_active", get_active)
    monkeypatch.setattr(va, "change", change)
    monkeypatch.setattr(nds, "sync_stop", forbidden)
    monkeypatch.setattr(nds, "sync_claim", forbidden)

    out = run(route.vehicle_assignment_change(
        route.AssignIn(vehicle_id=VEHICLE_B, request_id="conflict"),
        user=user(),
    ))

    assert out["ok"] is False
    assert out["http_status"] == 409
    assert "navixy_sync" not in out


def test_end_success_unassigns_vehicle_that_was_active(monkeypatch):
    db = setup_route(monkeypatch)
    calls = []

    async def get_active(*args, **kwargs):
        return {"vehicle_id": VEHICLE_A, "status": "ACTIVE"}

    async def end(*args, **kwargs):
        return {
            "result": "ok",
            "vehicle_id": VEHICLE_A,
        }

    async def sync_stop(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        calls.append((_db, driver_id, vehicle_id, actor))
        return {"status": "synced", "result": "unassigned"}

    monkeypatch.setattr(va, "get_active", get_active)
    monkeypatch.setattr(va, "end", end)
    monkeypatch.setattr(nds, "sync_stop", sync_stop)

    out = run(route.vehicle_assignment_end(
        route.AssignEndIn(request_id="end-a"),
        user=user(),
    ))

    assert out["ok"] is True
    assert out["navixy_sync"]["result"] == "unassigned"
    assert calls == [(db, DRIVER_ID, VEHICLE_A, ACTOR)]


def test_end_idempotent_retry_uses_original_event_not_new_active_vehicle(monkeypatch):
    db = setup_route(monkeypatch)
    db.vehicle_assignment_events.event = {
        "type": "VEHICLE_RELEASED",
        "result": "OK",
        "from_vehicle_id": VEHICLE_A,
        "to_vehicle_id": None,
    }
    calls = []

    async def get_active(*args, **kwargs):
        # A newer TAKE(B) happened after END(A).
        return {"vehicle_id": VEHICLE_B, "status": "ACTIVE"}

    async def end(*args, **kwargs):
        return {
            "result": "ok",
            "idempotent": True,
        }

    async def sync_stop(
        _db, driver_id, vehicle_id,
        session_id=None, actor=None,
    ):
        calls.append(vehicle_id)
        return {"status": "synced", "result": "already_unassigned"}

    monkeypatch.setattr(va, "get_active", get_active)
    monkeypatch.setattr(va, "end", end)
    monkeypatch.setattr(nds, "sync_stop", sync_stop)

    out = run(route.vehicle_assignment_end(
        route.AssignEndIn(request_id="old-end-a"),
        user=user(),
    ))

    assert out["ok"] is True
    assert calls == [VEHICLE_A]
    assert VEHICLE_B not in calls


def test_navixy_failure_never_rolls_back_successful_journal_take(monkeypatch):
    setup_route(monkeypatch)

    async def take(*args, **kwargs):
        return {
            "result": "ok",
            "assignment": {
                "vehicle_id": VEHICLE_A,
                "status": "ACTIVE",
            },
        }

    async def explode(*args, **kwargs):
        raise RuntimeError("Navixy unavailable")

    monkeypatch.setattr(va, "take", take)
    monkeypatch.setattr(nds, "sync_claim", explode)

    out = run(route.vehicle_assignment_take(
        route.AssignIn(vehicle_id=VEHICLE_A, request_id="take-local-ok"),
        user=user(),
    ))

    assert out["ok"] is True
    assert out["assignment"]["vehicle_id"] == VEHICLE_A
    assert out["navixy_sync"] == {
        "status": "error",
        "error": "HOOK_FAILURE",
    }
