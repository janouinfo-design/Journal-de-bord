import asyncio

from app import navixy_driver_sync as nds


def _run(coro):
    return asyncio.run(coro)


def _session(**overrides):
    value = {
        "id": "closed-1",
        "driver_id": "driver-1",
        "vehicle_id": "vehicle-1",
        "status": "closed",
        "started_at": "2026-09-14T06:00:00+00:00",
        "ended_at": "2026-09-14T07:00:00+00:00",
        "navixy_sync_status": "synced",
        "navixy_employee_id": 269807,
        "navixy_tracker_id": 781479,
    }
    value.update(overrides)
    return value


class _Cursor:
    def __init__(self, docs):
        self.docs = [dict(x) for x in docs]

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, length=None):
        return self.docs[:length] if length else self.docs


class _Sessions:
    def __init__(self, docs, newer=None):
        self.docs = docs
        self.newer = newer
        self.updates = []

    def find(self, *args, **kwargs):
        return _Cursor(self.docs)

    async def find_one(self, *args, **kwargs):
        return dict(self.newer) if self.newer else None

    async def update_one(self, query, update):
        self.updates.append((query, update))

        sid = query.get("id")
        for doc in self.docs:
            if doc.get("id") != sid:
                continue
            for key, value in update.get("$set", {}).items():
                doc[key] = value
            for key, value in update.get("$inc", {}).items():
                doc[key] = doc.get(key, 0) + value

        class Result:
            modified_count = 1

        return Result()


class _DB:
    def __init__(self, docs, newer=None):
        self.driver_sessions = _Sessions(docs, newer=newer)


def _enable(monkeypatch, unassign="0"):
    monkeypatch.setenv("NAVIXY_DRIVER_SYNC_ENABLED", "1")
    monkeypatch.setenv("NAVIXY_DRIVER_SYNC_WRITE", "1")
    monkeypatch.setenv(
        "NAVIXY_DRIVER_SYNC_UNASSIGN_WRITE",
        unassign,
    )


def test_closed_synced_session_runs_one_dry_run(monkeypatch):
    _enable(monkeypatch, "0")
    db = _DB([_session()])

    calls = []

    async def fake_sync_stop(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "dry_run",
            "result": None,
        }

    monkeypatch.setattr(nds, "sync_stop", fake_sync_stop)

    result = _run(nds.reconcile_closed_sessions(db))

    assert len(calls) == 1
    assert result["processed"] == 1
    assert result["dry_run"] == 1
    assert db.driver_sessions.docs[0]["navixy_unassign_status"] == "dry_run"
    assert db.driver_sessions.docs[0]["navixy_unassign_attempts"] == 1


def test_existing_dry_run_is_deferred_while_gate_off(monkeypatch):
    _enable(monkeypatch, "0")

    db = _DB([
        _session(navixy_unassign_status="dry_run")
    ])

    async def forbidden(*args, **kwargs):
        raise AssertionError("sync_stop must not run repeatedly in dry-run")

    monkeypatch.setattr(nds, "sync_stop", forbidden)

    result = _run(nds.reconcile_closed_sessions(db))

    assert result["processed"] == 0
    assert result["deferred"] == 1


def test_dry_run_is_retried_when_unassign_gate_enabled(monkeypatch):
    _enable(monkeypatch, "1")

    db = _DB([
        _session(
            navixy_unassign_status="dry_run",
            navixy_unassign_attempts=1,
        )
    ])

    async def fake_sync_stop(*args, **kwargs):
        return {
            "status": "synced",
            "result": "unassigned",
        }

    monkeypatch.setattr(nds, "sync_stop", fake_sync_stop)

    result = _run(nds.reconcile_closed_sessions(db))

    assert result["success"] == 1
    assert db.driver_sessions.docs[0]["navixy_unassign_status"] == "success"
    assert db.driver_sessions.docs[0]["navixy_unassign_attempts"] == 2


def test_newer_active_session_supersedes_old_closed_session(monkeypatch):
    _enable(monkeypatch, "1")

    newer = {
        "id": "active-2",
        "driver_id": "driver-1",
        "vehicle_id": "vehicle-1",
        "status": "confirmed",
        "started_at": "2026-09-14T07:30:00+00:00",
        "ended_at": None,
    }

    db = _DB([_session()], newer=newer)

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "old session must never unassign a newer active session"
        )

    monkeypatch.setattr(nds, "sync_stop", forbidden)

    result = _run(nds.reconcile_closed_sessions(db))

    assert result["superseded"] == 1
    doc = db.driver_sessions.docs[0]
    assert doc["navixy_unassign_status"] == "superseded"
    assert doc["navixy_unassign_superseded_by"] == "active-2"


def test_changed_navixy_driver_becomes_final_skip(monkeypatch):
    _enable(monkeypatch, "1")
    db = _DB([_session()])

    async def fake_sync_stop(*args, **kwargs):
        return {
            "status": "skipped",
            "result": "current_driver_changed",
            "current_employee_id": 123,
        }

    monkeypatch.setattr(nds, "sync_stop", fake_sync_stop)

    result = _run(nds.reconcile_closed_sessions(db))

    assert result["driver_changed"] == 1
    assert (
        db.driver_sessions.docs[0]["navixy_unassign_status"]
        == "driver_changed"
    )
