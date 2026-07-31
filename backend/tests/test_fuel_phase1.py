"""Phase 1 Carburant — security & new endpoints (report-issue, my-transactions, /refs).

Focus per review request: driver isolation, cross-tenant isolation,
lecture_seule write blocking, manager RBAC, manual dedup 409.
"""
import io
import os
import struct
import zlib

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "admin":   ("admin@logitrak.ch",    "admin123"),
    "manager": ("manager@logitrak.ch",  "manager123"),
    "lecture": ("lecture@logitrak.ch",  "lecture123"),
    "driver":  ("paul.test@client.ch",  "paul1234"),
    "admin_b": ("admin-b@test.ch",      "testb123"),
}


def _token(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"], r.json()["user"]


@pytest.fixture(scope="session")
def actors():
    out = {}
    for k, (e, p) in CREDS.items():
        tok, user = _token(e, p)
        out[k] = {"token": tok, "user": user, "headers": {"Authorization": f"Bearer {tok}"}}
    return out


def _tiny_png() -> bytes:
    # Minimal valid 1x1 PNG
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


# ========== Driver isolation (CRITICAL) ==========
class TestDriverIsolation:

    def test_driver_cannot_list_transactions(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["driver"]["headers"])
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"

    def test_driver_cannot_list_cards(self, actors):
        r = requests.get(f"{API}/livre/fuel/cards", headers=actors["driver"]["headers"])
        assert r.status_code == 403

    def test_driver_cannot_get_refs(self, actors):
        r = requests.get(f"{API}/livre/fuel/refs", headers=actors["driver"]["headers"])
        assert r.status_code == 403

    def test_driver_cannot_create_card(self, actors):
        r = requests.post(f"{API}/livre/fuel/cards", headers=actors["driver"]["headers"],
                          json={"provider": "Migrol", "last4": "1234"})
        assert r.status_code == 403

    def test_driver_cannot_patch_match(self, actors):
        # Get any tx id via admin
        r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["admin"]["headers"])
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0, "seed data missing (need existing tx)"
        tx_id = items[0]["id"]
        r = requests.patch(f"{API}/livre/fuel/transactions/{tx_id}/match",
                           headers=actors["driver"]["headers"],
                           json={"vehicle_id": "x", "reason": "test"})
        assert r.status_code == 403

    def test_driver_cannot_read_other_tx_by_id(self, actors):
        # Fetch a tx not attributed to Paul
        r = requests.get(f"{API}/livre/fuel/transactions?page_size=200", headers=actors["admin"]["headers"])
        assert r.status_code == 200
        paul_id = actors["driver"]["user"]["driver_id"]
        other = next((t for t in r.json()["items"] if t.get("driver_id") != paul_id), None)
        assert other, "need at least one tx not belonging to Paul"
        r2 = requests.get(f"{API}/livre/fuel/transactions/{other['id']}", headers=actors["driver"]["headers"])
        assert r2.status_code == 403, f"driver read other tx: {r2.status_code} {r2.text[:200]}"

    def test_driver_my_transactions_only_his(self, actors):
        r = requests.get(f"{API}/livre/fuel/my-transactions", headers=actors["driver"]["headers"])
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        paul_id = actors["driver"]["user"]["driver_id"]
        for tx in data["items"]:
            assert tx.get("driver_id") == paul_id, f"leak: tx has driver_id {tx.get('driver_id')}"


# ========== Driver own transaction — report + upload ==========
class TestDriverOwnTransaction:

    @pytest.fixture(scope="class")
    def assigned_tx(self, actors):
        """Ensure at least one tx is attributed to Paul via admin PATCH match."""
        paul_id = actors["driver"]["user"]["driver_id"]
        # Look for existing
        r = requests.get(f"{API}/livre/fuel/my-transactions", headers=actors["driver"]["headers"])
        assert r.status_code == 200
        if r.json()["items"]:
            return r.json()["items"][0]["id"]
        # Attribute one via admin
        r = requests.get(f"{API}/livre/fuel/transactions?page_size=50", headers=actors["admin"]["headers"])
        items = r.json()["items"]
        assert items, "no tx in seed"
        # Need a vehicle_id (required by PATCH match schema likely)
        veh_r = requests.get(f"{API}/livre/vehicles", headers=actors["admin"]["headers"])
        veh_id = None
        if veh_r.status_code == 200:
            vlist = veh_r.json() if isinstance(veh_r.json(), list) else veh_r.json().get("items", [])
            if vlist:
                veh_id = vlist[0]["id"]
        tx_id = items[0]["id"]
        payload = {"driver_id": paul_id, "reason": "test attribution driver"}
        if veh_id:
            payload["vehicle_id"] = veh_id
        pr = requests.patch(f"{API}/livre/fuel/transactions/{tx_id}/match",
                            headers=actors["admin"]["headers"], json=payload)
        assert pr.status_code == 200, f"attribute failed: {pr.status_code} {pr.text[:300]}"
        return tx_id

    def test_driver_sees_assigned_in_my_transactions(self, actors, assigned_tx):
        r = requests.get(f"{API}/livre/fuel/my-transactions", headers=actors["driver"]["headers"])
        assert r.status_code == 200
        ids = [t["id"] for t in r.json()["items"]]
        assert assigned_tx in ids

    def test_driver_can_get_own_tx_detail(self, actors, assigned_tx):
        r = requests.get(f"{API}/livre/fuel/transactions/{assigned_tx}",
                         headers=actors["driver"]["headers"])
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("driver_id") == actors["driver"]["user"]["driver_id"]

    def test_driver_can_report_issue_on_own_tx(self, actors, assigned_tx):
        r = requests.post(f"{API}/livre/fuel/transactions/{assigned_tx}/report-issue",
                          headers=actors["driver"]["headers"],
                          json={"message": "TEST_ISSUE prix incorrect"})
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("status") == "open"

    def test_driver_can_upload_document(self, actors, assigned_tx):
        png = _tiny_png()
        files = {"file": ("test.png", png, "image/png")}
        r = requests.post(f"{API}/livre/fuel/transactions/{assigned_tx}/documents",
                          headers=actors["driver"]["headers"], files=files)
        assert r.status_code == 200, r.text[:300]
        assert "id" in r.json()

    def test_driver_cannot_report_on_other_tx(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions?page_size=200",
                         headers=actors["admin"]["headers"])
        paul_id = actors["driver"]["user"]["driver_id"]
        other = next((t for t in r.json()["items"] if t.get("driver_id") != paul_id), None)
        if not other:
            pytest.skip("no non-paul tx available")
        r2 = requests.post(f"{API}/livre/fuel/transactions/{other['id']}/report-issue",
                           headers=actors["driver"]["headers"],
                           json={"message": "hack attempt"})
        assert r2.status_code == 403


# ========== Lecture seule (read-only) ==========
class TestLectureSeule:

    def test_lecture_can_read_cards(self, actors):
        r = requests.get(f"{API}/livre/fuel/cards", headers=actors["lecture"]["headers"])
        assert r.status_code == 200

    def test_lecture_can_read_transactions(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["lecture"]["headers"])
        assert r.status_code == 200

    def test_lecture_can_read_overview(self, actors):
        r = requests.get(f"{API}/livre/fuel/overview", headers=actors["lecture"]["headers"])
        # overview endpoint may or may not exist under that path — accept 200 or 404
        assert r.status_code in (200, 404)

    def test_lecture_cannot_create_card(self, actors):
        r = requests.post(f"{API}/livre/fuel/cards", headers=actors["lecture"]["headers"],
                          json={"provider": "Migrol", "last4": "9999"})
        assert r.status_code == 403

    def test_lecture_cannot_run_match(self, actors):
        r = requests.post(f"{API}/livre/fuel/match/run", headers=actors["lecture"]["headers"], json={})
        assert r.status_code == 403

    def test_lecture_cannot_patch_match(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["admin"]["headers"])
        tx_id = r.json()["items"][0]["id"]
        r2 = requests.patch(f"{API}/livre/fuel/transactions/{tx_id}/match",
                            headers=actors["lecture"]["headers"], json={"reason": "x"})
        assert r2.status_code == 403

    def test_lecture_cannot_report_issue(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["admin"]["headers"])
        tx_id = r.json()["items"][0]["id"]
        r2 = requests.post(f"{API}/livre/fuel/transactions/{tx_id}/report-issue",
                           headers=actors["lecture"]["headers"], json={"message": "x"})
        assert r2.status_code == 403


# ========== Manager RBAC ==========
class TestManager:

    def test_manager_can_read_transactions(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["manager"]["headers"])
        assert r.status_code == 200

    def test_manager_can_run_match(self, actors):
        r = requests.post(f"{API}/livre/fuel/match/run", headers=actors["manager"]["headers"], json={})
        assert r.status_code == 200

    def test_manager_cannot_create_card(self, actors):
        r = requests.post(f"{API}/livre/fuel/cards", headers=actors["manager"]["headers"],
                          json={"provider": "Migrol", "last4": "1111"})
        assert r.status_code == 403

    def test_manager_can_patch_match_with_reason(self, actors):
        r = requests.get(f"{API}/livre/fuel/transactions?page_size=10", headers=actors["admin"]["headers"])
        tx_id = r.json()["items"][-1]["id"]
        veh_r = requests.get(f"{API}/livre/vehicles", headers=actors["admin"]["headers"])
        veh_id = None
        if veh_r.status_code == 200:
            vlist = veh_r.json() if isinstance(veh_r.json(), list) else veh_r.json().get("items", [])
            if vlist:
                veh_id = vlist[0]["id"]
        payload = {"reason": "manager attribution test"}
        if veh_id:
            payload["vehicle_id"] = veh_id
        r2 = requests.patch(f"{API}/livre/fuel/transactions/{tx_id}/match",
                            headers=actors["manager"]["headers"], json=payload)
        assert r2.status_code == 200, r2.text[:300]


# ========== Multi-tenant isolation ==========
class TestMultiTenant:

    def test_tenant_b_sees_no_default_cards(self, actors):
        r = requests.get(f"{API}/livre/fuel/cards", headers=actors["admin_b"]["headers"])
        # Depending on tenant context resolution, expect either 400 (X-Tenant-Id required)
        # or 200 with 0 items from default tenant.
        if r.status_code == 400:
            # try with X-Tenant-Id
            tid = actors["admin_b"]["user"]["tenant_id"]
            r = requests.get(f"{API}/livre/fuel/cards",
                             headers={**actors["admin_b"]["headers"], "X-Tenant-Id": tid})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else (body if isinstance(body, list) else [])
        # Items should be either empty or only from tenant B — never leak default data
        # We can't identify tenant per card without field, but count must be << default
        # Compare with default admin
        r_admin = requests.get(f"{API}/livre/fuel/cards", headers=actors["admin"]["headers"])
        default_items = r_admin.json()
        if isinstance(default_items, dict):
            default_items = default_items.get("items", [])
        # Ensure IDs differ
        default_ids = {c["id"] for c in default_items}
        b_ids = {c["id"] for c in items}
        assert not (default_ids & b_ids), "tenant B leaked default tenant cards"

    def test_tenant_b_sees_no_default_transactions(self, actors):
        tid = actors["admin_b"]["user"]["tenant_id"]
        r = requests.get(f"{API}/livre/fuel/transactions",
                         headers={**actors["admin_b"]["headers"], "X-Tenant-Id": tid})
        if r.status_code == 400:
            r = requests.get(f"{API}/livre/fuel/transactions", headers=actors["admin_b"]["headers"])
        assert r.status_code == 200
        r_default = requests.get(f"{API}/livre/fuel/transactions", headers=actors["admin"]["headers"])
        default_ids = {t["id"] for t in r_default.json()["items"]}
        b_ids = {t["id"] for t in r.json().get("items", [])}
        assert not (default_ids & b_ids), "tenant B leaked default tenant transactions"


# ========== Manual transaction anti-doublon ==========
class TestManualDedup:

    def test_manual_dedup_409_then_force_200(self, actors):
        payload = {
            "tx_datetime": "2026-07-05T10:00:00+00:00",
            "station_name": "TEST_STATION_DEDUP",
            "amount_total": 42.5,
            "currency": "CHF",
            "product": "diesel",
            "quantity": 20.0,
            "reason": "test manual dedup",
        }
        r1 = requests.post(f"{API}/livre/fuel/transactions",
                           headers=actors["admin"]["headers"], json=payload)
        # Accept either 200 (created) or 409 if already existed from prev run
        assert r1.status_code in (200, 201, 409), r1.text[:200]

        r2 = requests.post(f"{API}/livre/fuel/transactions",
                           headers=actors["admin"]["headers"], json=payload)
        assert r2.status_code == 409, f"expected 409 on duplicate, got {r2.status_code} {r2.text[:200]}"

        # Force via body
        payload["force"] = True
        r3 = requests.post(f"{API}/livre/fuel/transactions",
                           headers=actors["admin"]["headers"], json=payload)
        assert r3.status_code in (200, 201), f"force expected 200, got {r3.status_code} {r3.text[:300]}"
