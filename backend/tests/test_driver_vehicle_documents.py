"""Tests de régression UNITAIRES — Documents véhicule (App Driver V2).

Approche B : DB fake en mémoire + object_storage/OCR mockés. AUCUN réseau, AUCUN
Object Storage réel, AUCUN OCR réel, AUCUN secret, AUCUNE écriture PROD.
Les RÈGLES MÉTIER et les fonctions de route sont réellement exercées :
  - autorisation véhicule réelle (vehicle_access.assert_vehicle_authorized) ;
  - validation MIME/type/taille ;
  - liaison vehicle_id/driver_id figée à la création ;
  - validation / archive ; OCR success/failure graceful.
"""
from __future__ import annotations

import asyncio
import pytest
from fastapi import HTTPException

from app.routes import documents as doc


# --------------------------------------------------------------------------
# Fake Mongo (async) — supporte find_one / find().sort().to_list() / insert / update
# --------------------------------------------------------------------------
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
        if upsert:
            nd = dict(q)
            nd.update(upd.get("$set", {}))
            self.docs.append(nd)


class _DB:
    def __init__(self):
        self.vehicles = _Coll()
        self.drivers = _Coll()
        self.vehicle_documents = _Coll()
        self.audit_log = _Coll()
        self.driver_sessions = _Coll()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeUpload:
    def __init__(self, filename, content_type, data):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self):
        return self._data


DRIVER = {"email": "chauffeur@logitrak.ch", "role": "driver", "driver_id": "drvA", "tenant_id": "default"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


@pytest.fixture
def db(monkeypatch):
    _db = _DB()
    # Chauffeur avec accès ALL (donc autorisé sur tout véhicule actif du tenant).
    _run(_db.drivers.insert_one({"id": "drvA", "vehicle_access_mode": "ALL", "name": "Orhan"}))
    _run(_db.vehicles.insert_one({"id": "vA", "plate": "FR 275924", "model": "VW Tiguan",
                                  "active": True}))
    # Route utilise get_db() -> fake ; resolve_driver_id -> driver_id du user ;
    # ble_engine.get_current_session -> pas de session (force vehicle_id explicite).
    monkeypatch.setattr(doc, "get_db", lambda: _db)
    async def _resolve(_db2, user):
        return user.get("driver_id")
    monkeypatch.setattr(doc, "resolve_driver_id_for_user", _resolve)
    async def _sess(_db2, _drv):
        return None
    monkeypatch.setattr(doc.ble_engine, "get_current_session", _sess)
    # Storage mocké (aucun réseau).
    import app.object_storage as store
    async def _put(path, data, ctype):
        return {"path": path, "size": len(data), "etag": "x"}
    async def _get(path):
        return (PNG, "image/png")
    monkeypatch.setattr(store, "put_object", _put)
    monkeypatch.setattr(store, "get_object", _get)
    # OCR mocké success par défaut (chaque test peut surcharger).
    import app.ocr_engine as ocr
    async def _ocr(data, ctype, session_id):
        return {"document_type": "assurance", "vehicle_plate": None,
                "document_date": None, "expiry_date": None}
    monkeypatch.setattr(ocr, "extract_vehicle_document", _ocr)
    return _db


# --------------------------------------------------------------------------
# TESTS
# --------------------------------------------------------------------------
def test_auth_guard_driver_missing(db, monkeypatch):
    """Utilisateur non lié à un chauffeur -> 400 (garde d'auth métier)."""
    async def _none(_db, user):
        return None
    monkeypatch.setattr(doc, "resolve_driver_id_for_user", _none)
    with pytest.raises(HTTPException) as e:
        _run(doc.list_vehicle_documents(vehicle_id="vA", user=DRIVER))
    assert e.value.status_code == 400


def test_upload_authorized_vehicle_links_server_side(db):
    up = _FakeUpload("assurance.png", "image/png", PNG)
    res = _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    assert res["vehicle_id"] == "vA"          # liaison véhicule = celui envoyé
    assert res["driver_id"] == "drvA"          # driver_id posé par le serveur
    assert res["created_by"] == DRIVER["email"]
    assert res["type"] == "assurance"
    assert res["status"] == "a_traiter"


def test_upload_unauthorized_vehicle_forbidden(db):
    """Véhicule hors périmètre / autre tenant -> 403 (assert_vehicle_authorized réel)."""
    up = _FakeUpload("x.png", "image/png", PNG)
    with pytest.raises(HTTPException) as e:
        _run(doc.upload_vehicle_document(file=up, type="assurance",
                                         vehicle_id="11111111-2222-3333-4444-555555555555", document_date=None, expiry_date=None, user=DRIVER))
    assert e.value.status_code == 403


def test_upload_invalid_mime_rejected(db):
    up = _FakeUpload("note.txt", "text/plain", b"hello")
    with pytest.raises(HTTPException) as e:
        _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    assert e.value.status_code == 400


def test_upload_invalid_type_rejected(db):
    up = _FakeUpload("x.png", "image/png", PNG)
    with pytest.raises(HTTPException) as e:
        _run(doc.upload_vehicle_document(file=up, type="not_a_type", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    assert e.value.status_code == 400


def test_upload_too_large_rejected(db):
    big = b"0" * (doc.DOCUMENT_MAX_BYTES + 1)
    up = _FakeUpload("big.png", "image/png", big)
    with pytest.raises(HTTPException) as e:
        _run(doc.upload_vehicle_document(file=up, type="autre", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    assert e.value.status_code == 413


def test_list_and_download_with_storage_mock(db):
    up = _FakeUpload("a.png", "image/png", PNG)
    created = _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    listing = _run(doc.list_vehicle_documents(vehicle_id="vA", user=DRIVER))
    assert any(d["id"] == created["id"] for d in listing["documents"])
    resp = _run(doc.download_vehicle_document(doc_id=created["id"], user=DRIVER))
    assert resp.status_code == 200 and resp.body  # bytes servis (storage mocké)


def test_download_unauthorized_vehicle_forbidden(db):
    """Un document rattaché à un véhicule hors périmètre -> download 403."""
    _run(db.vehicle_documents.insert_one({
        "id": "docX", "vehicle_id": "vFOREIGN", "driver_id": "drvA", "type": "autre",
        "filename": "f.png", "content_type": "image/png", "storage_path": "p", "status": "a_traiter",
        "archived": False}))
    with pytest.raises(HTTPException) as e:
        _run(doc.download_vehicle_document(doc_id="docX", user=DRIVER))
    assert e.value.status_code == 403


def test_validate_sets_status(db):
    up = _FakeUpload("a.png", "image/png", PNG)
    created = _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    res = _run(doc.validate_vehicle_document(doc_id=created["id"], user=DRIVER))
    assert res["status"] == "valide"


def test_archive_soft_deletes(db):
    up = _FakeUpload("a.png", "image/png", PNG)
    created = _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    res = _run(doc.archive_vehicle_document(doc_id=created["id"], user=DRIVER))
    assert res["archived"] is True
    listing = _run(doc.list_vehicle_documents(vehicle_id="vA", user=DRIVER))
    assert all(d["id"] != created["id"] for d in listing["documents"])  # retiré de la liste


def test_ocr_success_populates_extracted(db):
    up = _FakeUpload("a.png", "image/png", PNG)
    created = _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    assert created.get("ocr_extracted") is not None  # OCR mocké -> dict


def test_ocr_failure_graceful(db, monkeypatch):
    """Échec OCR -> la création réussit quand même (status a_traiter, jamais 500)."""
    import app.ocr_engine as ocr
    async def _boom(data, ctype, session_id):
        raise RuntimeError("OCR indispo")
    monkeypatch.setattr(ocr, "extract_vehicle_document", _boom)
    up = _FakeUpload("a.png", "image/png", PNG)
    created = _run(doc.upload_vehicle_document(file=up, type="assurance", vehicle_id="vA", document_date=None, expiry_date=None, user=DRIVER))
    assert created["status"] == "a_traiter"
    assert created.get("ocr_extracted") is None  # jamais inventé
