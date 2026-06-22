"""Phase 2 — Gestion des amendes — auto-identification du conducteur.

Tests covered:
- POST /api/livre/fines auto-identifies on create (BLE / GPS / Assignment)
- POST /api/livre/fines auto-identifies returns null when no source matches
- POST /api/livre/fines/{id}/identify-driver recomputes + persists
- POST /api/livre/fines/{id}/identify-driver returns 400 if missing inputs
- GET  /api/livre/fines/{id}/identify-candidates is read-only (no mutation)
- PATCH /api/livre/fines/{id} with driver_id sets driver_validated_manually=true
- Confidence aggregation: BLE=95, GPS=85, Assignment=60, +5 per extra source, cap 98
- RBAC: manager OK on identify-driver, driver gets 403

Run: cd /app/backend && pytest tests/test_fines_phase2_identify.py -v
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}

# Fixed timestamps used across tests
T_INFR = "2026-06-19T14:17:00Z"
T_START = "2026-06-19T13:00:00Z"
T_END = "2026-06-19T15:00:00Z"


# ---------- helpers ----------
def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def admin_s():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def manager_s():
    return _login(MANAGER)


@pytest.fixture(scope="module")
def driver_s():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def meta(admin_s):
    r = admin_s.get(f"{API}/livre/fines/meta", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _mongo_do(coro_factory):
    """Run a coroutine that uses a fresh motor client bound to a fresh loop."""
    if not MONGO_URL or not DB_NAME:
        pytest.skip("MONGO_URL/DB_NAME not exposed to tests")

    async def _wrap():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            return await coro_factory(db)
        finally:
            client.close()
    return asyncio.run(_wrap())


# Backwards-compat shims so test code stays readable
class _MongoShim:
    """Light shim that exposes attribute access -> _mongo_do execution."""
    pass


mongo = _MongoShim()  # placeholder so signatures stay simple
event_loop = None     # not used anymore but kept for signature compat


@pytest.fixture(scope="module")
def cleanup_tracker():
    """Track created records for end-of-module cleanup."""
    return {"fine_ids": [], "session_ids": [], "trip_ids": [], "assignment_ids": []}


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module(cleanup_tracker, admin_s):
    yield
    for fid in cleanup_tracker["fine_ids"]:
        try:
            admin_s.delete(f"{API}/livre/fines/{fid}", timeout=15)
        except Exception:
            pass

    async def _purge(db):
        if cleanup_tracker["session_ids"]:
            await db.driver_sessions.delete_many({"id": {"$in": cleanup_tracker["session_ids"]}})
        if cleanup_tracker["trip_ids"]:
            await db.trips.delete_many({"id": {"$in": cleanup_tracker["trip_ids"]}})
        if cleanup_tracker["assignment_ids"]:
            await db.assignments.delete_many({"id": {"$in": cleanup_tracker["assignment_ids"]}})
    try:
        _mongo_do(_purge)
    except Exception:
        pass


# ---------- seed helpers ----------
def _pick_v_d(meta):
    v = meta["vehicles"][0]
    d = meta["drivers"][0]
    d2 = meta["drivers"][1] if len(meta["drivers"]) > 1 else d
    return v, d, d2


def _seed_ble(_mongo, _loop, vehicle_id, driver_id, tracker, start=T_START, end=T_END):
    sid = f"TEST-SESS-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": sid, "tenant_id": "default", "driver_id": driver_id,
        "vehicle_id": vehicle_id, "status": "confirmed",
        "started_at": start, "ended_at": end,
        "source": "ble", "confidence": 95,
    }
    _mongo_do(lambda db: db.driver_sessions.insert_one(doc))
    tracker["session_ids"].append(sid)
    return sid


def _seed_trip(_mongo, _loop, vehicle_id, driver_id, driver_name, tracker,
               start=T_START, end=T_END):
    tid = f"TEST-TRIP-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tid, "tenant_id": "default", "vehicle_id": vehicle_id,
        "driver_id": driver_id, "driver_name": driver_name,
        "start_time": start, "end_time": end,
        "classification": "professional", "distance_km": 12.5,
    }
    _mongo_do(lambda db: db.trips.insert_one(doc))
    tracker["trip_ids"].append(tid)
    return tid


def _seed_assignment(_mongo, _loop, vehicle_id, driver_id, tracker,
                     start=T_START, end=T_END, is_primary=True):
    aid = f"TEST-ASGN-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": aid, "tenant_id": "default", "driver_id": driver_id,
        "vehicle_id": vehicle_id, "from_date": start, "to_date": end,
        "is_primary": is_primary,
    }
    _mongo_do(lambda db: db.assignments.insert_one(doc))
    tracker["assignment_ids"].append(aid)
    return aid


def _create_fine(admin_s, vehicle_id, infraction_at, tracker, driver_id=None):
    payload = {"vehicle_id": vehicle_id, "infraction_at": infraction_at,
               "amount": 100, "admin_fees": 10, "infraction_type": "speeding"}
    if driver_id:
        payload["driver_id"] = driver_id
    r = admin_s.post(f"{API}/livre/fines", json=payload, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    tracker["fine_ids"].append(body["id"])
    return body


# ============================================================
# Auto-identify on CREATE
# ============================================================
class TestAutoIdentifyOnCreate:
    def test_gps_match_creates_fine_with_driver(self, admin_s, meta, cleanup_tracker):
        _, d, _ = _pick_v_d(meta)
        v_id = f"TEST-V-GPS-{uuid.uuid4().hex[:8]}"
        _seed_trip(None, None, v_id, d["id"], d["name"], cleanup_tracker)
        body = _create_fine(admin_s, v_id, T_INFR, cleanup_tracker)
        assert body["driver_id"] == d["id"]
        assert body["driver_name"] == d["name"]
        assert body["driver_confidence"] == 85
        assert body["driver_sources"] == ["GPS"]
        assert body["gps_trip_id"]
        assert body.get("driver_validated_manually") is False

    def test_ble_only_match_gives_95(self, admin_s, meta, cleanup_tracker):
        _, d, _ = _pick_v_d(meta)
        v_id = f"TEST-V-BLE-{uuid.uuid4().hex[:8]}"
        ts_unique = "2026-07-04T10:30:00Z"
        st, en = "2026-07-04T09:00:00Z", "2026-07-04T12:00:00Z"
        _seed_ble(None, None, v_id, d["id"], cleanup_tracker, st, en)
        body = _create_fine(admin_s, v_id, ts_unique, cleanup_tracker)
        assert body["driver_id"] == d["id"]
        assert body["driver_confidence"] == 95
        assert body["driver_sources"] == ["BLE"]

    def test_multi_source_boost_capped(self, admin_s, meta, cleanup_tracker):
        _, d, _ = _pick_v_d(meta)
        v_id = f"TEST-V-MULTI-{uuid.uuid4().hex[:8]}"
        ts = "2026-08-12T11:00:00Z"
        st, en = "2026-08-12T08:00:00Z", "2026-08-12T18:00:00Z"
        _seed_ble(None, None, v_id, d["id"], cleanup_tracker, st, en)
        _seed_trip(None, None, v_id, d["id"], d["name"], cleanup_tracker, st, en)
        _seed_assignment(None, None, v_id, d["id"], cleanup_tracker, st, en, True)
        body = _create_fine(admin_s, v_id, ts, cleanup_tracker)
        assert body["driver_id"] == d["id"]
        # 3 sources -> 95 + 5*2 = 105 capped at 98
        assert body["driver_confidence"] == 98
        srcs = set(body["driver_sources"])
        assert srcs == {"BLE", "GPS", "Assignment"}

    def test_assignment_only_match_gives_60(self, admin_s, meta, cleanup_tracker):
        _, d, _ = _pick_v_d(meta)
        v_id = f"TEST-V-ASGN-{uuid.uuid4().hex[:8]}"
        ts = "2026-09-01T10:00:00Z"
        st, en = "2026-09-01T08:00:00Z", "2026-09-01T18:00:00Z"
        _seed_assignment(None, None, v_id, d["id"], cleanup_tracker, st, en, True)
        body = _create_fine(admin_s, v_id, ts, cleanup_tracker)
        assert body["driver_id"] == d["id"]
        assert body["driver_confidence"] == 60
        assert body["driver_sources"] == ["Assignment"]

    def test_no_match_creates_clean_fine(self, admin_s, meta, cleanup_tracker):
        # Random vehicle id with no seeded data, far-future timestamp
        v_id = f"NON-EXISTENT-{uuid.uuid4().hex[:8]}"
        body = _create_fine(admin_s, v_id, "2030-01-01T00:00:00Z", cleanup_tracker)
        assert body.get("driver_id") in (None, "", )
        assert body.get("driver_confidence") in (None, 0)
        assert body.get("driver_sources") in (None, [])
        assert body.get("gps_trip_id") in (None, "")


# ============================================================
# identify-driver endpoint
# ============================================================
class TestIdentifyDriverEndpoint:
    def test_recompute_persists_and_audits(self, admin_s, meta, cleanup_tracker):
        v, d, _ = _pick_v_d(meta)
        ts = "2026-10-05T09:00:00Z"
        # Use a unique vehicle id (not in real fleet) so initial create finds nothing
        unique_v = f"TEST-V-{uuid.uuid4().hex[:8]}"
        body = _create_fine(admin_s, unique_v, ts, cleanup_tracker)
        assert body.get("driver_id") in (None, "")
        # Now seed a BLE session covering ts for the real vehicle, then PATCH the
        # fine to point to that vehicle, then trigger identify
        _seed_ble(None, None, v["id"], d["id"], cleanup_tracker,
                  "2026-10-05T07:00:00Z", "2026-10-05T12:00:00Z")
        # Patch vehicle_id (this is a manual change, not identify)
        admin_s.patch(f"{API}/livre/fines/{body['id']}",
                      json={"vehicle_id": v["id"]}, timeout=15)
        r = admin_s.post(f"{API}/livre/fines/{body['id']}/identify-driver", timeout=20)
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        assert result["driver_id"] == d["id"]
        assert result["confidence"] == 95
        # Persisted on doc
        rg = admin_s.get(f"{API}/livre/fines/{body['id']}", timeout=15).json()
        assert rg["driver_id"] == d["id"]
        assert rg["driver_confidence"] == 95
        assert "BLE" in rg["driver_sources"]
        assert rg["driver_validated_manually"] is False

        # Audit log entry created
        async def _check(db):
            return await db.audit_log.find(
                {"scope": "fines", "fine_id": body["id"], "action": "auto_identify"}
            ).to_list(5)
        docs = _mongo_do(_check)
        assert len(docs) >= 1
        assert docs[-1]["actor"] == ADMIN["email"]

    def test_identify_missing_inputs_400(self, admin_s, cleanup_tracker):
        # Create fine without vehicle_id / infraction_at
        r = admin_s.post(f"{API}/livre/fines",
                         json={"amount": 50, "infraction_type": "parking"},
                         timeout=15)
        assert r.status_code == 200
        fid = r.json()["id"]
        cleanup_tracker["fine_ids"].append(fid)
        r2 = admin_s.post(f"{API}/livre/fines/{fid}/identify-driver", timeout=15)
        assert r2.status_code == 400

    def test_identify_404_unknown_id(self, admin_s):
        r = admin_s.post(f"{API}/livre/fines/NO-SUCH-ID/identify-driver", timeout=15)
        assert r.status_code == 404

    def test_manager_can_identify(self, manager_s, admin_s, meta, cleanup_tracker):
        v, d, _ = _pick_v_d(meta)
        ts = "2026-11-11T11:11:00Z"
        body = _create_fine(admin_s, v["id"], ts, cleanup_tracker)
        _seed_assignment(None, None, v["id"], d["id"], cleanup_tracker,
                         "2026-11-11T00:00:00Z", "2026-11-11T23:59:00Z", True)
        r = manager_s.post(f"{API}/livre/fines/{body['id']}/identify-driver", timeout=20)
        assert r.status_code == 200, r.text

    def test_driver_role_forbidden(self, driver_s, admin_s, meta, cleanup_tracker):
        v, _, _ = _pick_v_d({"vehicles": [{"id": "v"}], "drivers": [{"id": "d", "name": "n"}]})
        # Need a real fine id; create with admin
        body = _create_fine(admin_s, "ANY", "2026-12-01T00:00:00Z", cleanup_tracker)
        r = driver_s.post(f"{API}/livre/fines/{body['id']}/identify-driver", timeout=15)
        assert r.status_code == 403


# ============================================================
# identify-candidates (read-only)
# ============================================================
class TestIdentifyCandidates:
    def test_returns_all_sources_and_does_not_mutate(self, admin_s, meta, cleanup_tracker):
        v, d, _ = _pick_v_d(meta)
        ts = "2026-05-22T15:00:00Z"
        st, en = "2026-05-22T08:00:00Z", "2026-05-22T20:00:00Z"
        _seed_ble(None, None, v["id"], d["id"], cleanup_tracker, st, en)
        _seed_trip(None, None, v["id"], d["id"], d["name"], cleanup_tracker, st, en)

        # Create fine WITHOUT auto-identify by passing manual driver=None and timestamp
        # but PATCH it to clear driver after creation
        body = _create_fine(admin_s, v["id"], ts, cleanup_tracker)
        before = admin_s.get(f"{API}/livre/fines/{body['id']}", timeout=15).json()

        r = admin_s.get(f"{API}/livre/fines/{body['id']}/identify-candidates", timeout=15)
        assert r.status_code == 200, r.text
        out = r.json()
        sources = [c.get("source") for c in out["candidates"]]
        assert "BLE" in sources and "GPS" in sources
        # Each candidate must have driver_id + confidence
        for c in out["candidates"]:
            assert "driver_id" in c and "confidence" in c

        # Fine must not have been mutated
        after = admin_s.get(f"{API}/livre/fines/{body['id']}", timeout=15).json()
        assert before.get("driver_confidence") == after.get("driver_confidence")
        assert before.get("driver_sources") == after.get("driver_sources")
        assert before.get("updated_at") == after.get("updated_at")

    def test_candidates_400_missing_inputs(self, admin_s, cleanup_tracker):
        r = admin_s.post(f"{API}/livre/fines",
                         json={"amount": 10, "infraction_type": "parking"},
                         timeout=15)
        fid = r.json()["id"]
        cleanup_tracker["fine_ids"].append(fid)
        r2 = admin_s.get(f"{API}/livre/fines/{fid}/identify-candidates", timeout=15)
        assert r2.status_code == 400


# ============================================================
# Manual driver -> driver_validated_manually=true
# ============================================================
class TestManualDriverValidation:
    def test_patch_with_driver_id_sets_validated_manually(self, admin_s, meta, cleanup_tracker):
        v, d, d2 = _pick_v_d(meta)
        # Create fine without driver
        v_unknown = f"NONE-{uuid.uuid4().hex[:6]}"
        body = _create_fine(admin_s, v_unknown, "2030-02-02T02:02:00Z", cleanup_tracker)
        assert body.get("driver_validated_manually") in (False, None)
        # PATCH with explicit driver_id
        r = admin_s.patch(f"{API}/livre/fines/{body['id']}",
                          json={"driver_id": d["id"]}, timeout=15)
        assert r.status_code == 200, r.text
        body2 = r.json()
        assert body2["driver_id"] == d["id"]
        assert body2["driver_validated_manually"] is True

    def test_patch_respects_explicit_false(self, admin_s, meta, cleanup_tracker):
        """If client passes driver_validated_manually explicitly, server keeps it."""
        v, d, _ = _pick_v_d(meta)
        body = _create_fine(admin_s, f"NONE-{uuid.uuid4().hex[:6]}",
                            "2030-03-03T03:03:00Z", cleanup_tracker)
        r = admin_s.patch(f"{API}/livre/fines/{body['id']}",
                          json={"driver_id": d["id"],
                                "driver_validated_manually": False}, timeout=15)
        assert r.status_code == 200
        assert r.json()["driver_validated_manually"] is False
