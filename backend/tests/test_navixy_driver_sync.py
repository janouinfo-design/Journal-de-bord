import os
import asyncio

import app.navixy_driver_sync as sync


DRIVER_ID = "driver-orhan"
VEHICLE_ID = "vehicle-audi"
SESSION_ID = "session-1"
TENANT = "default"
EMPLOYEE = 269807
TRACKER = 781479


class Result:
    modified_count = 1


class Collection:
    def __init__(self, docs=None):
        self.docs = [dict(x) for x in (docs or [])]

    @staticmethod
    def _matches(doc, query):
        for k, v in query.items():
            if isinstance(v, dict):
                # Unit tests only need direct equality for these collections.
                continue
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, query, projection=None, **kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def update_one(self, query, update, **kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                doc.update(update.get("$set", {}))
                return Result()
        return Result()

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return Result()


class DB:
    def __init__(self, *, driver=None, vehicle=None):
        self.drivers = Collection([driver] if driver else [])
        self.vehicles = Collection([vehicle] if vehicle else [])
        self.driver_sessions = Collection([{
            "id": SESSION_ID,
            "driver_id": DRIVER_ID,
            "vehicle_id": VEHICLE_ID,
        }])
        self.audit_log = Collection([])


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def driver(**extra):
    d = {
        "id": DRIVER_ID,
        "tenant_id": TENANT,
        "name": "Orhan",
        "navixy_employee_id": EMPLOYEE,
    }
    d.update(extra)
    return d


def vehicle(**extra):
    v = {
        "id": VEHICLE_ID,
        "tenant_id": TENANT,
        "plate": "LOGITRAK AUDI",
        "navixy_tracker_id": TRACKER,
    }
    v.update(extra)
    return v


def setup_function():
    os.environ["NAVIXY_DRIVER_SYNC_ENABLED"] = "1"
    os.environ["NAVIXY_DRIVER_SYNC_WRITE"] = "0"


def teardown_function():
    os.environ.pop("NAVIXY_DRIVER_SYNC_ENABLED", None)
    os.environ.pop("NAVIXY_DRIVER_SYNC_WRITE", None)


def test_sync_disabled_does_nothing(monkeypatch):
    os.environ["NAVIXY_DRIVER_SYNC_ENABLED"] = "0"

    async def explode(*a, **k):
        raise AssertionError("Navixy must not be called")

    monkeypatch.setattr(sync, "read_tracker_employee", explode)

    db = DB(driver=driver(), vehicle=vehicle())
    out = run(sync.sync_claim(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
    ))

    assert out["status"] == "disabled"
    assert db.audit_log.docs == []


def test_claim_dry_run_detects_marcio_without_write(monkeypatch):
    db = DB(driver=driver(), vehicle=vehicle())

    async def read_current(*a, **k):
        return {"id": 255794, "first_name": "Marcio", "tracker_id": TRACKER}

    async def no_write(*a, **k):
        raise AssertionError("assign must not run with WRITE=0")

    monkeypatch.setattr(sync, "read_tracker_employee", read_current)
    monkeypatch.setattr(sync, "assign_tracker_employee", no_write)

    out = run(sync.sync_claim(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
        actor="orhan@logitrak.ch",
    ))

    assert out["status"] == "dry_run"
    assert out["previous_employee_id"] == 255794
    assert out["employee_id"] == EMPLOYEE


def test_claim_noop_when_orhan_already_assigned(monkeypatch):
    db = DB(driver=driver(), vehicle=vehicle())

    async def read_current(*a, **k):
        return {"id": EMPLOYEE, "first_name": "Orhan", "tracker_id": TRACKER}

    monkeypatch.setattr(sync, "read_tracker_employee", read_current)

    out = run(sync.sync_claim(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
    ))

    assert out["status"] == "synced"
    assert out["result"] == "already_assigned"


def test_claim_write_assigns_and_verifies(monkeypatch):
    os.environ["NAVIXY_DRIVER_SYNC_WRITE"] = "1"

    db = DB(driver=driver(), vehicle=vehicle())
    calls = []
    reads = [
        {"id": 255794, "first_name": "Marcio", "tracker_id": TRACKER},
        {"id": EMPLOYEE, "first_name": "Orhan", "tracker_id": TRACKER},
    ]

    async def read_current(*a, **k):
        return reads.pop(0)

    async def assign(tenant, tracker, employee):
        calls.append((tenant, tracker, employee))

    monkeypatch.setattr(sync, "read_tracker_employee", read_current)
    monkeypatch.setattr(sync, "assign_tracker_employee", assign)

    out = run(sync.sync_claim(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
    ))

    assert out["status"] == "synced"
    assert out["result"] == "assigned"
    assert calls == [(TENANT, TRACKER, EMPLOYEE)]


def test_stop_never_removes_another_current_driver(monkeypatch):
    os.environ["NAVIXY_DRIVER_SYNC_WRITE"] = "1"

    db = DB(driver=driver(), vehicle=vehicle())

    async def read_current(*a, **k):
        return {"id": 255794, "first_name": "Marcio", "tracker_id": TRACKER}

    async def no_unassign(*a, **k):
        raise AssertionError("must not unassign a different current driver")

    monkeypatch.setattr(sync, "read_tracker_employee", read_current)
    monkeypatch.setattr(sync, "unassign_employee_from_tracker", no_unassign)

    out = run(sync.sync_stop(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
    ))

    assert out["status"] == "skipped"
    assert out["result"] == "current_driver_changed"
    assert out["current_employee_id"] == 255794


def test_stop_write_unassigns_expected_driver_and_verifies(monkeypatch):
    os.environ["NAVIXY_DRIVER_SYNC_WRITE"] = "1"

    db = DB(driver=driver(), vehicle=vehicle())
    calls = []
    reads = [
        {"id": EMPLOYEE, "first_name": "Orhan", "tracker_id": TRACKER},
        None,
    ]

    async def read_current(*a, **k):
        return reads.pop(0)

    async def unassign(tenant, tracker, employee):
        calls.append((tenant, tracker, employee))

    monkeypatch.setattr(sync, "read_tracker_employee", read_current)
    monkeypatch.setattr(sync, "unassign_employee_from_tracker", unassign)

    out = run(sync.sync_stop(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
    ))

    assert out["status"] == "synced"
    assert out["result"] == "unassigned"
    assert calls == [(TENANT, TRACKER, EMPLOYEE)]


def test_cross_tenant_is_refused_before_navixy(monkeypatch):
    db = DB(
        driver=driver(tenant_id="tenant-A"),
        vehicle=vehicle(tenant_id="tenant-B"),
    )

    async def explode(*a, **k):
        raise AssertionError("Navixy must not be called cross-tenant")

    monkeypatch.setattr(sync, "read_tracker_employee", explode)

    out = run(sync.sync_claim(
        db, DRIVER_ID, VEHICLE_ID,
        session_id=SESSION_ID,
    ))

    assert out["status"] == "error"
