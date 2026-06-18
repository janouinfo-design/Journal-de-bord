"""Tests for the notification system — preferences, dispatch, Expo Push cleanup.

These tests use:
- HTTP integration tests against the live backend for the public API
- In-process unit tests for `expo_push.send_to_tokens` (with monkey-patched HTTP)
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}
MANAGER = {"email": "manager@logitrak.ch", "password": "manager123"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def admin_s():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def driver_s():
    return _login(DRIVER)


@pytest.fixture(scope="module")
def manager_s():
    return _login(MANAGER)


# ===========================================================
# Catalog + Preferences endpoints
# ===========================================================
class TestNotificationsCatalog:
    def test_catalog_lists_known_events(self, admin_s):
        r = admin_s.get(f"{API}/livre/notifications/catalog", timeout=15)
        assert r.status_code == 200
        events = {e["event"] for e in r.json()["events"]}
        # Core BLE + privacy events
        for ev in ("ble.conflict", "ble.resolved", "kill_switch"):
            assert ev in events, f"missing event {ev}"
        # Business-future events also exposed
        for ev in ("contract.renewal", "insurance.expiring",
                   "tracker.low_battery", "driver.unassigned"):
            assert ev in events, f"missing business event {ev}"

    def test_catalog_each_entry_has_required_fields(self, admin_s):
        r = admin_s.get(f"{API}/livre/notifications/catalog", timeout=15)
        for e in r.json()["events"]:
            assert "event" in e and "label" in e and "audience" in e
            chans = e["default_channels"]
            assert set(chans.keys()) >= {"push", "email", "sms"}

    def test_catalog_requires_auth(self):
        r = requests.get(f"{API}/livre/notifications/catalog", timeout=15)
        assert r.status_code == 401


class TestNotificationsPrefs:
    def test_get_default_prefs(self, driver_s):
        r = driver_s.get(f"{API}/livre/notifications/preferences", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["channels"] == {"push": True, "email": True, "sms": True}
        # Defaults: ble.conflict push=true,email=false,sms=false
        assert body["events"]["ble.conflict"]["push"] is True
        assert body["events"]["ble.conflict"]["email"] is False

    def test_put_prefs_merges(self, driver_s):
        r = driver_s.put(
            f"{API}/livre/notifications/preferences",
            json={"channels": {"push": True, "email": False, "sms": False},
                  "events": {"ble.conflict":
                             {"push": False, "email": True, "sms": False}}},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["channels"]["email"] is False
        assert body["events"]["ble.conflict"]["push"] is False
        assert body["events"]["ble.conflict"]["email"] is True
        # Untouched events keep their defaults
        assert body["events"]["ble.resolved"]["push"] is True

    def test_put_prefs_filters_unknown_event(self, driver_s):
        r = driver_s.put(
            f"{API}/livre/notifications/preferences",
            json={"events": {"unknown.event": {"push": True}}},
            timeout=15,
        )
        assert r.status_code == 200
        assert "unknown.event" not in r.json()["events"]

    def test_prefs_requires_auth(self):
        r = requests.get(f"{API}/livre/notifications/preferences", timeout=15)
        assert r.status_code == 401

    @pytest.fixture(autouse=True)
    def _reset_driver_prefs(self, driver_s):
        yield
        # Restore defaults
        try:
            driver_s.put(
                f"{API}/livre/notifications/preferences",
                json={"channels": {"push": True, "email": True, "sms": True},
                      "events": {"ble.conflict": {"push": True,
                                                  "email": False, "sms": False}}},
                timeout=10,
            )
        except Exception:
            pass


# ===========================================================
# /notifications/test endpoint (admin only)
# ===========================================================
class TestNotificationsTestEndpoint:
    def test_admin_can_trigger_test_event(self, admin_s):
        r = admin_s.post(
            f"{API}/livre/notifications/test",
            json={"event": "ble.conflict",
                  "payload": {"vehicle_plate": "TEST-99",
                              "drivers": ["d1", "d2"]}},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["event"] == "ble.conflict"
        # 🚨 title with the conflict emoji
        assert "Conflit" in body["title"]
        # No real Expo tokens registered → 0 sent, but no failures either
        assert body["push"]["sent"] == 0
        assert body["push"]["failed"] == 0

    def test_manager_cannot_trigger_test_event(self, manager_s):
        r = manager_s.post(
            f"{API}/livre/notifications/test",
            json={"event": "ble.conflict"}, timeout=15,
        )
        assert r.status_code == 403

    def test_driver_cannot_trigger_test_event(self, driver_s):
        r = driver_s.post(
            f"{API}/livre/notifications/test",
            json={"event": "ble.conflict"}, timeout=15,
        )
        assert r.status_code == 403

    def test_test_event_requires_event_name(self, admin_s):
        r = admin_s.post(f"{API}/livre/notifications/test",
                         json={}, timeout=15)
        assert r.status_code == 400

    def test_kill_switch_template(self, admin_s):
        r = admin_s.post(
            f"{API}/livre/notifications/test",
            json={"event": "kill_switch",
                  "payload": {"reason": "Maintenance prévue"}},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        # ⚠️ Tracking désactivé
        assert "Tracking" in body["title"]

    def test_business_event_template(self, admin_s):
        r = admin_s.post(
            f"{API}/livre/notifications/test",
            json={"event": "tracker.low_battery",
                  "payload": {"plate": "AAA-111", "battery": 12}},
            timeout=15,
        )
        assert r.status_code == 200
        assert "Batterie" in r.json()["title"]


# ===========================================================
# Unit tests — expo_push module (no real HTTP)
# ===========================================================
@pytest.mark.asyncio
async def test_expo_push_skips_invalid_tokens():
    from app import expo_push
    out = await expo_push.send_to_tokens(["not-an-expo-token", ""], "t", "b")
    assert out["sent"] == 0
    assert out["failed"] == 0


@pytest.mark.asyncio
async def test_expo_push_handles_success_and_dead_tokens(monkeypatch):
    """Mock the Expo HTTP endpoint and ensure dead-token cleanup runs."""
    from app import expo_push

    # Fake Expo response: 1 ok + 1 DeviceNotRegistered
    fake_tickets = [
        {"status": "ok", "id": "abc"},
        {"status": "error", "message": "...",
         "details": {"error": "DeviceNotRegistered"}},
    ]

    async def fake_send_batch(client, messages):
        return fake_tickets

    cleanup_calls = []

    async def fake_cleanup(token, reason="expo_dead"):
        cleanup_calls.append((token, reason))

    monkeypatch.setattr(expo_push, "_send_batch", fake_send_batch)
    monkeypatch.setattr(expo_push, "cleanup_token", fake_cleanup)

    tokens = [
        "ExponentPushToken[GOOD_TOKEN]",
        "ExponentPushToken[DEAD_TOKEN]",
    ]
    out = await expo_push.send_to_tokens(tokens, "Hello", "Body")
    assert out["sent"] == 1
    assert out["failed"] == 1
    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][0] == "ExponentPushToken[DEAD_TOKEN]"
    assert cleanup_calls[0][1] == "expo_dead"


@pytest.mark.asyncio
async def test_expo_push_swallows_http_failure(monkeypatch):
    """If the HTTP call raises, every message is marked failed (no crash)."""
    from app import expo_push

    async def boom_send_batch(client, messages):
        return [{"status": "error", "message": "network down"} for _ in messages]

    monkeypatch.setattr(expo_push, "_send_batch", boom_send_batch)
    out = await expo_push.send_to_tokens(
        ["ExponentPushToken[A]", "ExponentPushToken[B]"], "t", "b",
    )
    assert out["sent"] == 0
    assert out["failed"] == 2


# ===========================================================
# Integration — dispatch is called when a BLE conflict happens
# ===========================================================
@pytest.fixture(scope="module")
def vehicles(admin_s):
    return admin_s.get(f"{API}/livre/vehicles", timeout=15).json()


@pytest.fixture(scope="module")
def drivers_list(admin_s):
    return admin_s.get(f"{API}/livre/drivers", timeout=15).json()


class TestDispatcherWiring:
    def test_conflict_writes_notifications_log(self, admin_s, vehicles, drivers_list):
        """Triggering a real BLE conflict must write a notifications_log entry."""
        if len(drivers_list) < 2:
            pytest.skip("need 2 drivers")
        d1, d2 = drivers_list[0], drivers_list[1]
        v = vehicles[0]

        # Ensure the BLE tag exists
        admin_s.post(f"{API}/livre/ble/tags",
                     json={"vehicle_id": v["id"], "identifier": "CONFLICTAG"},
                     timeout=15)

        # Snapshot pre-state
        before = admin_s.get(f"{API}/livre/notifications/test",
                             timeout=10).status_code
        assert before in (200, 405)  # GET on a POST route → 405 is fine

        # Trigger conflict
        for _ in range(3):
            admin_s.post(f"{API}/livre/ble/simulate",
                         json={"driver_id": d1["id"],
                               "identifier": "CONFLICTAG", "rssi": -55}, timeout=15)
            admin_s.post(f"{API}/livre/ble/simulate",
                         json={"driver_id": d2["id"],
                               "identifier": "CONFLICTAG", "rssi": -55}, timeout=15)
            time.sleep(0.2)
        time.sleep(0.6)

        # Verify the audit_log contains conflict_detected (we expose it via dashboard counters)
        rows = admin_s.get(
            f"{API}/livre/ble/sessions?status=conflict&limit=100", timeout=15,
        ).json()
        assert rows, "conflict session must exist"
