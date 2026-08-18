"""Phase 1 — Gestion des amendes (fines) — full backend coverage.

Covers:
- /api/livre/fines/meta enums + vehicles/drivers lists
- POST create (admin, manager OK / driver 403)
- GET list filters/sort/pagination/totals + driver 403
- PATCH update (validation, paid_at auto-stamp, denorm refresh, total recompute)
- DELETE (admin OK / manager 403)
- GET /stats/summary
- Audit log persistence (via subsequent reads; mongo direct read optional)

Run: cd /app/backend && pytest tests/test_fines_phase1.py -v
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


# ---------- helpers ----------
def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.status_code} {r.text}"
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


@pytest.fixture(scope="module")
def created_ids(admin_s):
    """Track ids created during the run for cleanup."""
    ids = []
    yield ids
    for fid in ids:
        try:
            admin_s.delete(f"{API}/livre/fines/{fid}", timeout=15)
        except Exception:
            pass


# ============================================================
# 1. /fines/meta
# ============================================================
class TestFinesMeta:
    def test_meta_enums(self, meta):
        assert len(meta["statuses"]) == 10
        assert "received" in meta["statuses"] and "paid" in meta["statuses"]
        assert len(meta["infraction_types"]) == 8
        assert "speeding" in meta["infraction_types"]
        assert len(meta["priorities"]) == 4

    def test_meta_vehicles_drivers(self, meta):
        assert isinstance(meta["vehicles"], list)
        assert isinstance(meta["drivers"], list)
        assert len(meta["vehicles"]) >= 1
        assert len(meta["drivers"]) >= 1
        v = meta["vehicles"][0]
        assert "id" in v and "plate" in v
        d = meta["drivers"][0]
        assert "id" in d and "name" in d


# ============================================================
# 2. POST /fines — create
# ============================================================
class TestCreateFine:
    def test_create_admin_full(self, admin_s, meta, created_ids):
        v = meta["vehicles"][0]
        d = meta["drivers"][0]
        payload = {
            "ref_fine": f"TEST-{uuid.uuid4().hex[:6]}",
            "authority": "Police Cantonale",
            "canton": "VD",
            "city": "Lausanne",
            "location": "Av. de la Gare 1",
            "vehicle_id": v["id"],
            "driver_id": d["id"],
            "infraction_type": "speeding",
            "infraction_details": "20 km/h au-dessus",
            "amount": 250,
            "admin_fees": 30,
            "due_date": "2026-03-01",
            "infraction_at": "2026-01-10T08:30:00Z",
            "received_at": "2026-01-12",
        }
        r = admin_s.post(f"{API}/livre/fines", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        created_ids.append(body["id"])
        # Auto-fill checks
        assert body["dossier_number"].startswith("AMD-")
        parts = body["dossier_number"].split("-")
        assert len(parts) == 3 and len(parts[2]) == 4  # NNNN
        # Computed total
        assert body["total_amount"] == 280.0
        # Denormalization
        assert body["vehicle_plate"] == v["plate"]
        assert body["driver_name"] == d["name"]
        # Defaults
        assert body["status"] == "received"
        assert body["created_at"]
        assert body["created_by"] == ADMIN["email"]

    def test_dossier_sequential(self, admin_s, meta, created_ids):
        # Create two fines back to back, second number must be > first
        v = meta["vehicles"][0]
        p = {"vehicle_id": v["id"], "amount": 50, "admin_fees": 0,
             "infraction_type": "parking"}
        r1 = admin_s.post(f"{API}/livre/fines", json=p, timeout=15)
        r2 = admin_s.post(f"{API}/livre/fines", json=p, timeout=15)
        assert r1.status_code == 200 and r2.status_code == 200
        created_ids.extend([r1.json()["id"], r2.json()["id"]])
        n1 = int(r1.json()["dossier_number"].split("-")[-1])
        n2 = int(r2.json()["dossier_number"].split("-")[-1])
        assert n2 == n1 + 1

    def test_create_manager_ok(self, manager_s, meta, created_ids):
        v = meta["vehicles"][0]
        r = manager_s.post(f"{API}/livre/fines",
                           json={"vehicle_id": v["id"], "amount": 100,
                                 "admin_fees": 10, "infraction_type": "parking"},
                           timeout=15)
        assert r.status_code == 200, r.text
        created_ids.append(r.json()["id"])

    def test_create_driver_403(self, driver_s):
        r = driver_s.post(f"{API}/livre/fines",
                         json={"amount": 100, "infraction_type": "parking"},
                         timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_create_invalid_enum_400(self, admin_s):
        r = admin_s.post(f"{API}/livre/fines",
                        json={"amount": 50, "infraction_type": "not_valid"},
                        timeout=15)
        assert r.status_code == 400
        assert "infraction" in r.json().get("detail", "").lower() or "valeurs" in r.json().get("detail", "").lower()


# ============================================================
# 3. GET /fines — list + filters + sort + pagination
# ============================================================
class TestListFines:
    def test_driver_forbidden(self, driver_s):
        r = driver_s.get(f"{API}/livre/fines", timeout=15)
        assert r.status_code == 403

    def test_list_admin(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "rows" in body and "total" in body and "totals" in body
        assert "total_amount" in body["totals"]
        assert "paid_amount" in body["totals"]
        assert "open_amount" in body["totals"]

    def test_filter_status(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines?status=received", timeout=15)
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert row["status"] == "received"

    def test_filter_infraction_type(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines?infraction_type=parking", timeout=15)
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert row["infraction_type"] == "parking"

    def test_filter_min_max_amount(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines?min_amount=200&max_amount=400", timeout=15)
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert 200 <= row["total_amount"] <= 400

    def test_pagination(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines?page=1&page_size=1", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert len(body["rows"]) <= 1
        total = body["total"]
        # Total must be a stable count across pages
        r2 = admin_s.get(f"{API}/livre/fines?page=2&page_size=1", timeout=15)
        assert r2.json()["total"] == total

    def test_sort_desc_total_amount(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines?sort=-total_amount&page_size=50",
                        timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        amounts = [row["total_amount"] for row in rows]
        assert amounts == sorted(amounts, reverse=True)

    def test_sort_asc_total_amount(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines?sort=total_amount&page_size=50",
                        timeout=15)
        assert r.status_code == 200
        amounts = [row["total_amount"] for row in r.json()["rows"]]
        assert amounts == sorted(amounts)

    def test_totals_aggregated_across_filtered_set(self, admin_s):
        """totals must include all rows matching the filter, not just current page."""
        # Get all rows in one call to compute expected total
        full = admin_s.get(f"{API}/livre/fines?page_size=200", timeout=15).json()
        expected_total_amount = round(sum(r.get("total_amount") or 0 for r in full["rows"]), 2)
        # Reported totals must match (assumes total <= 200; for our seed this is true)
        assert abs(full["totals"]["total_amount"] - expected_total_amount) < 0.01
        # Paged call must report the same aggregate totals
        paged = admin_s.get(f"{API}/livre/fines?page_size=1", timeout=15).json()
        assert abs(paged["totals"]["total_amount"] - expected_total_amount) < 0.01


# ============================================================
# 4. PATCH /fines/{id} — update logic
# ============================================================
class TestUpdateFine:
    @pytest.fixture
    def fid(self, admin_s, meta, created_ids):
        v = meta["vehicles"][0]
        d = meta["drivers"][0]
        r = admin_s.post(f"{API}/livre/fines",
                       json={"vehicle_id": v["id"], "driver_id": d["id"],
                             "amount": 200, "admin_fees": 20,
                             "infraction_type": "speeding"},
                       timeout=15)
        assert r.status_code == 200
        fid = r.json()["id"]
        created_ids.append(fid)
        return fid

    def test_patch_invalid_status(self, admin_s, fid):
        r = admin_s.patch(f"{API}/livre/fines/{fid}",
                         json={"status": "invalid_status"}, timeout=15)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "received" in detail or "Statut" in detail or "Valeurs" in detail

    def test_patch_invalid_infraction(self, admin_s, fid):
        r = admin_s.patch(f"{API}/livre/fines/{fid}",
                         json={"infraction_type": "not_valid"}, timeout=15)
        assert r.status_code == 400

    def test_patch_paid_autostamps_paid_at(self, admin_s, fid):
        r = admin_s.patch(f"{API}/livre/fines/{fid}",
                         json={"status": "paid"}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "paid"
        assert body.get("paid_at"), "paid_at must be auto-stamped"
        prev_paid_at = body["paid_at"]
        # Re-PATCH to disputed: paid_at should NOT be cleared
        r2 = admin_s.patch(f"{API}/livre/fines/{fid}",
                          json={"status": "disputed"}, timeout=15)
        assert r2.status_code == 200
        assert r2.json().get("paid_at") == prev_paid_at

    def test_patch_recomputes_total(self, admin_s, fid):
        r = admin_s.patch(f"{API}/livre/fines/{fid}",
                         json={"amount": 300, "admin_fees": 50}, timeout=15)
        assert r.status_code == 200
        assert r.json()["total_amount"] == 350.0

    def test_patch_changes_vehicle_refreshes_plate(self, admin_s, meta, fid):
        if len(meta["vehicles"]) < 2:
            pytest.skip("need >=2 vehicles to test plate refresh")
        v2 = meta["vehicles"][1]
        r = admin_s.patch(f"{API}/livre/fines/{fid}",
                         json={"vehicle_id": v2["id"]}, timeout=15)
        assert r.status_code == 200
        assert r.json()["vehicle_plate"] == v2["plate"]

    def test_patch_changes_driver_refreshes_name(self, admin_s, meta, fid):
        if len(meta["drivers"]) < 2:
            pytest.skip("need >=2 drivers to test name refresh")
        d2 = meta["drivers"][1]
        r = admin_s.patch(f"{API}/livre/fines/{fid}",
                         json={"driver_id": d2["id"]}, timeout=15)
        assert r.status_code == 200
        assert r.json()["driver_name"] == d2["name"]


# ============================================================
# 5. DELETE — admin-only
# ============================================================
class TestDeleteFine:
    def test_delete_manager_403(self, admin_s, manager_s, meta):
        v = meta["vehicles"][0]
        r = admin_s.post(f"{API}/livre/fines",
                       json={"vehicle_id": v["id"], "amount": 10,
                             "infraction_type": "parking"}, timeout=15)
        fid = r.json()["id"]
        rd = manager_s.delete(f"{API}/livre/fines/{fid}", timeout=15)
        assert rd.status_code == 403
        # cleanup
        admin_s.delete(f"{API}/livre/fines/{fid}", timeout=15)

    def test_delete_admin_then_404(self, admin_s, meta):
        v = meta["vehicles"][0]
        r = admin_s.post(f"{API}/livre/fines",
                       json={"vehicle_id": v["id"], "amount": 10,
                             "infraction_type": "parking"}, timeout=15)
        fid = r.json()["id"]
        rd = admin_s.delete(f"{API}/livre/fines/{fid}", timeout=15)
        assert rd.status_code == 200
        rg = admin_s.get(f"{API}/livre/fines/{fid}", timeout=15)
        assert rg.status_code == 404


# ============================================================
# 6. /fines/stats/summary
# ============================================================
class TestStatsSummary:
    def test_summary_shape(self, admin_s):
        r = admin_s.get(f"{API}/livre/fines/stats/summary", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "total" in body and "by_status" in body
        # all 10 statuses
        for s in ["received", "to_analyze", "driver_to_identify", "awaiting_driver",
                  "disputed", "to_pay", "paid", "recharged", "closed", "cancelled"]:
            assert s in body["by_status"]
        assert "total_amount" in body and "paid_amount" in body


# ============================================================
# 7. Audit log persistence (via mongo direct read if available)
# ============================================================
class TestAuditLog:
    def test_audit_entries_present(self, admin_s, meta, created_ids):
        """Create+patch+delete and verify audit_log entries via mongo read."""
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            import asyncio
        except Exception:
            pytest.skip("motor not available in test env")

        v = meta["vehicles"][0]
        # CREATE
        r = admin_s.post(f"{API}/livre/fines",
                       json={"vehicle_id": v["id"], "amount": 60,
                             "infraction_type": "phone"}, timeout=15)
        assert r.status_code == 200
        fid = r.json()["id"]
        # PATCH
        admin_s.patch(f"{API}/livre/fines/{fid}", json={"status": "to_pay"}, timeout=15)
        # DELETE
        admin_s.delete(f"{API}/livre/fines/{fid}", timeout=15)

        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        if not mongo_url or not db_name:
            pytest.skip("mongo env not exposed to test env")

        async def _check():
            client = AsyncIOMotorClient(mongo_url)
            db = client[db_name]
            docs = await db.audit_log.find(
                {"scope": "fines", "fine_id": fid}
            ).to_list(20)
            client.close()
            return docs

        docs = asyncio.get_event_loop().run_until_complete(_check())
        actions = sorted([d.get("action") for d in docs])
        assert "create" in actions
        assert "update" in actions
        assert "delete" in actions
        for d in docs:
            assert d.get("actor") == ADMIN["email"]
            assert d.get("ts")
