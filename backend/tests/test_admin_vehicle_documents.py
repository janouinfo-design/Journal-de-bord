"""Tests — Fédération Documents gestionnaire (Proposition A).

Vérifie GET /admin/vehicle-documents : documents chauffeur (mobile) GROUPÉS PAR
VÉHICULE, avec « added_by_label » (nom chauffeur) et source=MOBILE_DRIVER.
Fake DB en mémoire, aucun réseau/Object Storage/secret.
"""
from __future__ import annotations

import asyncio
import pytest

from app.routes import documents as doc


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, n):
        return list(self._docs)


class _Coll:
    def __init__(self):
        self.docs = []

    def _match(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$ne" in v:
                if d.get(k) == v["$ne"]:
                    return False
            elif isinstance(v, dict) and "$in" in v:
                if d.get(k) not in v["$in"]:
                    return False
            else:
                if d.get(k) != v:
                    return False
        return True

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    def find(self, q, proj=None):
        return _Cursor([dict(d) for d in self.docs if self._match(d, q)])

    async def insert_one(self, d):
        self.docs.append(dict(d))

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                return


class _DB:
    def __init__(self):
        self.vehicles = _Coll()
        self.drivers = _Coll()
        self.vehicle_documents = _Coll()
        self.audit_log = _Coll()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


ADMIN = {"email": "admin@logitrak.ch", "role": "admin", "tenant_id": "default"}


@pytest.fixture
def db(monkeypatch):
    _db = _DB()
    # 2 véhicules + 2 chauffeurs (noms) + documents mobiles.
    _run(_db.vehicles.insert_one({"id": "vA", "tenant_id": "default", "plate": "LOGITRAK AUDI", "model": "FMC130"}))
    _run(_db.vehicles.insert_one({"id": "vB", "tenant_id": "default", "plate": "GE 123", "model": "VW"}))
    _run(_db.drivers.insert_one({"id": "d1", "name": "Orhan", "email": "orhan@logitrak.ch"}))
    _run(_db.drivers.insert_one({"id": "d2", "name": "Ivan", "email": "ivan@logitrak.ch"}))
    # 3 documents (2 sur vA, 1 sur vB), statuts variés.
    _run(_db.vehicle_documents.insert_one({
        "id": "doc1", "tenant_id": "default", "vehicle_id": "vA", "driver_id": "d1",
        "type": "autre", "filename": "4016.jpg", "content_type": "image/jpeg",
        "status": "a_traiter", "created_at": "2026-09-23T08:54:30Z", "created_by": "orhan@logitrak.ch"}))
    _run(_db.vehicle_documents.insert_one({
        "id": "doc2", "tenant_id": "default", "vehicle_id": "vA", "driver_id": "d1",
        "type": "carte_grise", "filename": "cg.jpeg", "content_type": "image/jpeg",
        "status": "valide", "created_at": "2026-09-23T08:47:19Z", "created_by": "orhan@logitrak.ch"}))
    _run(_db.vehicle_documents.insert_one({
        "id": "doc3", "tenant_id": "default", "vehicle_id": "vB", "driver_id": "d2",
        "type": "assurance", "filename": "ass.pdf", "content_type": "application/pdf",
        "status": "a_traiter", "created_at": "2026-09-22T10:00:00Z", "created_by": "ivan@logitrak.ch"}))
    # doc archivé -> ne doit PAS apparaître
    _run(_db.vehicle_documents.insert_one({
        "id": "doc4", "tenant_id": "default", "vehicle_id": "vA", "driver_id": "d1",
        "type": "autre", "filename": "old.jpg", "status": "a_traiter", "archived": True,
        "created_at": "2026-01-01T00:00:00Z", "created_by": "orhan@logitrak.ch"}))
    monkeypatch.setattr(doc, "get_db", lambda: _db)
    # _effective_status : on neutralise l'expiration (statut tel quel) pour le test.
    monkeypatch.setattr(doc, "_effective_status", lambda d: d.get("status"))
    return _db


def test_admin_list_grouped_by_vehicle(db):
    res = _run(doc.admin_list_vehicle_documents(vehicle_id=None, status=None, user=ADMIN))
    assert res["count"] == 3                       # archivé exclu
    vehicles = {g["vehicle_id"]: g for g in res["vehicles"]}
    assert set(vehicles.keys()) == {"vA", "vB"}    # groupé par véhicule
    assert len(vehicles["vA"]["documents"]) == 2
    assert len(vehicles["vB"]["documents"]) == 1
    assert vehicles["vA"]["vehicle_plate"] == "LOGITRAK AUDI"


def test_admin_added_by_label_uses_driver_name(db):
    res = _run(doc.admin_list_vehicle_documents(vehicle_id=None, status=None, user=ADMIN))
    vehicles = {g["vehicle_id"]: g for g in res["vehicles"]}
    for d in vehicles["vA"]["documents"]:
        assert d["added_by_label"] == "Orhan"      # « ajouté par [chauffeur] »
        assert d["source"] == "MOBILE_DRIVER"
        assert d["download_url"].endswith(f"/{d['id']}/download")
        assert "storage_path" not in d             # jamais exposé
    assert vehicles["vB"]["documents"][0]["added_by_label"] == "Ivan"


def test_admin_filter_by_vehicle(db):
    res = _run(doc.admin_list_vehicle_documents(vehicle_id="vB", status=None, user=ADMIN))
    assert res["count"] == 1
    assert res["vehicles"][0]["vehicle_id"] == "vB"


def test_admin_filter_by_status(db):
    res = _run(doc.admin_list_vehicle_documents(vehicle_id=None, status="valide", user=ADMIN))
    assert res["count"] == 1
    ids = [d["id"] for g in res["vehicles"] for d in g["documents"]]
    assert ids == ["doc2"]


def test_admin_archived_excluded(db):
    res = _run(doc.admin_list_vehicle_documents(vehicle_id=None, status=None, user=ADMIN))
    all_ids = [d["id"] for g in res["vehicles"] for d in g["documents"]]
    assert "doc4" not in all_ids                   # archivé exclu
