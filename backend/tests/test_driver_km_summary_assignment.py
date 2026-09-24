"""Régression km-summary : le véhicule actif vient de l'affectation persistante.

Mode manuel mobile : aucune session BLE n'est requise. Les cartes Km Pro / Km Privé
ne doivent donc jamais tomber à « — » uniquement parce que le chauffeur est affecté
via vehicle_assignments.
"""
from __future__ import annotations

import asyncio

from app import ble_engine
from app import private_mileage
from app import vehicle_assignment
from app.routes import identification as ident


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def limit(self, _n):
        return self

    async def to_list(self, _n):
        return list(self.docs)


class _Trips:
    def find(self, query, projection=None):
        return _Cursor([
            {"distance_km": 4.4, "classification": "professional"},
            {"distance_km": 9.9, "classification": "personal"},
        ])


class _DB:
    def __init__(self):
        self.trips = _Trips()


def test_km_summary_uses_persistent_assignment_without_ble_session(monkeypatch):
    db = _DB()
    monkeypatch.setattr(ident, "get_db", lambda: db)

    async def resolve_driver(_db, _user):
        return "d1"

    monkeypatch.setattr(ident, "resolve_driver_id_for_user", resolve_driver)

    async def resolve_assignment(_db, driver_id, tenant_id):
        assert driver_id == "d1"
        assert tenant_id == "default"
        return "vA"

    monkeypatch.setattr(vehicle_assignment, "resolve_active_vehicle", resolve_assignment)

    async def ble_should_not_be_needed(_db, _driver):
        raise AssertionError("km-summary ne doit pas dépendre du BLE avec une affectation ACTIVE")

    monkeypatch.setattr(ble_engine, "get_current_session", ble_should_not_be_needed)

    async def aggregate_private(_db, **kwargs):
        assert kwargs["tenant_id"] == "default"
        assert kwargs["vehicle_id"] == "vA"
        return {
            "private_km": 1.2,
            "private_km_source": "AVL16",
            "session_count": 1,
        }

    monkeypatch.setattr(private_mileage, "aggregate_private_km", aggregate_private)

    out = _run(ident.driver_km_summary(
        period="today",
        user={"tenant_id": "default", "role": "driver", "id": "u1", "email": "d1@x"},
    ))

    assert out["vehicle_id"] == "vA"
    assert out["available"] is True
    assert out["pro_km"] == 4.4
    assert out["private_km"] == 1.2
    assert out["private_km_source"] == "AVL16"
