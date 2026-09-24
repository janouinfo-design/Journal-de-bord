"""Lot 2.1 — résolution du véhicule actif pour km-summary + odometer.

But :
- vehicle_assignments ACTIVE = source prioritaire ;
- session BLE = fallback rétro-compatible uniquement ;
- tenant réel conservé ;
- anti-IDOR fail-closed ;
- aucune donnée inventée si aucun véhicule.
Aucun réseau, aucune DB réelle, aucun appel Navixy réel.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.routes import identification
from app import vehicle_assignment as va
from app import ble_engine
from app import private_mileage
from app import odometer_audit


def _run(coro):
    return asyncio.run(coro)


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def limit(self, _n):
        return self

    async def to_list(self, _n):
        return list(self.rows)


class _Trips:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def find(self, query, projection=None):
        self.queries.append(query)
        rows = []
        for row in self.rows:
            ok = True
            for k, v in query.items():
                if k == "start_time":
                    continue
                if isinstance(v, dict):
                    continue
                if row.get(k) != v:
                    ok = False
                    break
            if ok:
                rows.append(row)
        return _Cursor(rows)


class _Vehicles:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.last_query = None

    async def find_one(self, query, projection=None):
        self.last_query = dict(query)
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None


class _DB:
    def __init__(self, trips=None, vehicles=None):
        self.trips = _Trips(trips)
        self.vehicles = _Vehicles(vehicles)


async def _driver_id(_db, _user):
    return "driver-1"


def _user(tenant="tenant-A"):
    return {
        "email": "driver@test.ch",
        "role": "driver",
        "tenant_id": tenant,
    }


def test_km_summary_prefers_lot2_assignment(monkeypatch):
    """Une affectation Lot 2 ACTIVE doit gagner sur toute ancienne session BLE."""
    db = _DB(
        trips=[
            {
                "tenant_id": "tenant-A",
                "vehicle_id": "v-lot2",
                "classification": "professional",
                "distance_km": 12.5,
            }
        ]
    )

    monkeypatch.setattr(identification, "get_db", lambda: db)
    monkeypatch.setattr(
        identification,
        "resolve_driver_id_for_user",
        _driver_id,
    )

    async def _active(_db, driver_id, tenant_id):
        assert driver_id == "driver-1"
        assert tenant_id == "tenant-A"
        return "v-lot2"

    async def _legacy_must_not_run(_db, _driver_id):
        raise AssertionError("fallback BLE ne doit pas être appelé")

    async def _private(*args, **kwargs):
        assert kwargs["tenant_id"] == "tenant-A"
        assert kwargs["vehicle_id"] == "v-lot2"
        return {
            "private_km": 3.4,
            "private_km_source": "TEST",
        }

    monkeypatch.setattr(va, "resolve_active_vehicle", _active)
    monkeypatch.setattr(ble_engine, "get_current_session", _legacy_must_not_run)
    monkeypatch.setattr(private_mileage, "aggregate_private_km", _private)

    result = _run(
        identification.driver_km_summary(
            period="today",
            user=_user(),
        )
    )

    assert result["vehicle_id"] == "v-lot2"
    assert result["pro_km"] == 12.5
    assert result["private_km"] == 3.4
    assert result["available"] is True


def test_km_summary_falls_back_to_legacy_session(monkeypatch):
    """Sans affectation Lot 2, conserver la rétro-compatibilité BLE."""
    db = _DB()

    monkeypatch.setattr(identification, "get_db", lambda: db)
    monkeypatch.setattr(
        identification,
        "resolve_driver_id_for_user",
        _driver_id,
    )

    async def _no_assignment(_db, _driver_id, _tenant_id):
        return None

    async def _legacy(_db, driver_id):
        assert driver_id == "driver-1"
        return {"vehicle_id": "v-legacy"}

    async def _private(*args, **kwargs):
        assert kwargs["vehicle_id"] == "v-legacy"
        return {
            "private_km": 0.0,
            "private_km_source": "TEST",
        }

    monkeypatch.setattr(va, "resolve_active_vehicle", _no_assignment)
    monkeypatch.setattr(ble_engine, "get_current_session", _legacy)
    monkeypatch.setattr(private_mileage, "aggregate_private_km", _private)

    result = _run(
        identification.driver_km_summary(
            period="today",
            user=_user(),
        )
    )

    assert result["vehicle_id"] == "v-legacy"
    assert result["available"] is True


def test_odometer_prefers_assignment_and_uses_real_tenant(monkeypatch):
    """Odomètre : Lot 2 prioritaire + lookup véhicule strictement dans le tenant réel."""
    db = _DB(
        vehicles=[
            {
                "id": "v-lot2",
                "tenant_id": "tenant-A",
                "plate": "VD TEST",
                "navixy_tracker_id": 781479,
            }
        ]
    )

    monkeypatch.setattr(identification, "get_db", lambda: db)
    monkeypatch.setattr(
        identification,
        "resolve_driver_id_for_user",
        _driver_id,
    )

    async def _active(_db, _driver_id, tenant_id):
        assert tenant_id == "tenant-A"
        return "v-lot2"

    async def _legacy_must_not_run(_db, _driver_id):
        raise AssertionError("fallback BLE ne doit pas être appelé")

    async def _read(tracker_id):
        assert tracker_id == 781479
        return {
            "odometer_km": 12345.6,
            "source": "TEST",
            "status": "OK",
        }

    monkeypatch.setattr(va, "resolve_active_vehicle", _active)
    monkeypatch.setattr(ble_engine, "get_current_session", _legacy_must_not_run)
    monkeypatch.setattr(odometer_audit, "read_vehicle_odometer", _read)

    result = _run(
        identification.driver_vehicle_odometer(
            vehicle_id=None,
            user=_user("tenant-A"),
        )
    )

    assert db.vehicles.last_query == {
        "id": "v-lot2",
        "tenant_id": "tenant-A",
    }
    assert result["vehicle_id"] == "v-lot2"
    assert result["odometer_km"] == 12345.6
    assert result["status"] == "OK"


def test_odometer_explicit_other_vehicle_is_forbidden(monkeypatch):
    """Un ID explicitement différent du véhicule actif reste interdit."""
    db = _DB()

    monkeypatch.setattr(identification, "get_db", lambda: db)
    monkeypatch.setattr(
        identification,
        "resolve_driver_id_for_user",
        _driver_id,
    )

    async def _active(_db, _driver_id, _tenant_id):
        return "v-active"

    monkeypatch.setattr(va, "resolve_active_vehicle", _active)

    with pytest.raises(HTTPException) as exc:
        _run(
            identification.driver_vehicle_odometer(
                vehicle_id="v-other",
                user=_user(),
            )
        )

    assert exc.value.status_code == 403
    assert db.vehicles.last_query is None


def test_odometer_no_assignment_no_session_is_unavailable(monkeypatch):
    """Aucun véhicule actif => UNAVAILABLE, jamais faux 0 km."""
    db = _DB()

    monkeypatch.setattr(identification, "get_db", lambda: db)
    monkeypatch.setattr(
        identification,
        "resolve_driver_id_for_user",
        _driver_id,
    )

    async def _no_assignment(_db, _driver_id, _tenant_id):
        return None

    async def _no_session(_db, _driver_id):
        return None

    async def _read_must_not_run(_tracker_id):
        raise AssertionError("aucune lecture odomètre sans véhicule actif")

    monkeypatch.setattr(va, "resolve_active_vehicle", _no_assignment)
    monkeypatch.setattr(ble_engine, "get_current_session", _no_session)
    monkeypatch.setattr(odometer_audit, "read_vehicle_odometer", _read_must_not_run)

    result = _run(
        identification.driver_vehicle_odometer(
            vehicle_id=None,
            user=_user(),
        )
    )

    assert result["vehicle_id"] is None
    assert result["odometer_km"] is None
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "no_active_vehicle"
    assert result["odometer_km"] != 0
