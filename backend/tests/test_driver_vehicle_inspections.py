"""Tests de régression UNITAIRES — Inspection véhicule (App Driver V2).

Approche B : DB fake en mémoire + object_storage mocké. AUCUN réseau, AUCUN Object
Storage réel, AUCUN secret, AUCUNE écriture PROD. Les règles métier et les fonctions
de route sont réellement exercées (autorisation véhicule, checklist, immutabilité,
anomalie-sans-commentaire, RBAC manager, liaison figée).
"""
from __future__ import annotations

import asyncio
import pytest
from fastapi import HTTPException

from app.routes import inspections as insp
from app.auth import require_roles


# --------------------------------------------------------------------------
# Fake Mongo (async)
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
        self.vehicle_inspections = _Coll()
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
ADMIN = {"email": "admin@logitrak.ch", "role": "admin", "tenant_id": "default"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


@pytest.fixture
def db(monkeypatch):
    _db = _DB()
    _run(_db.drivers.insert_one({"id": "drvA", "vehicle_access_mode": "ALL", "name": "Orhan"}))
    _run(_db.vehicles.insert_one({"id": "vA", "plate": "FR 275924", "model": "VW Tiguan", "active": True}))
    monkeypatch.setattr(insp, "get_db", lambda: _db)
    async def _resolve(_db2, user):
        return user.get("driver_id")
    monkeypatch.setattr(insp, "resolve_driver_id_for_user", _resolve)
    async def _sess(_db2, _drv):
        return None
    monkeypatch.setattr(insp.ble_engine, "get_current_session", _sess)
    import app.object_storage as store
    async def _put(path, data, ctype):
        return {"path": path, "size": len(data), "etag": "x"}
    async def _get(path):
        return (PNG, "image/png")
    monkeypatch.setattr(store, "put_object", _put)
    monkeypatch.setattr(store, "get_object", _get)
    return _db


def _new(db):
    from app.routes.inspections import NewInspectionIn
    return _run(insp.create_inspection(NewInspectionIn(vehicle_id="vA"), user=DRIVER))


# --------------------------------------------------------------------------
# TESTS
# --------------------------------------------------------------------------
def test_auth_guard_driver_missing(db, monkeypatch):
    async def _none(_db, user):
        return None
    monkeypatch.setattr(insp, "resolve_driver_id_for_user", _none)
    from app.routes.inspections import NewInspectionIn
    with pytest.raises(HTTPException) as e:
        _run(insp.create_inspection(NewInspectionIn(vehicle_id="vA"), user=DRIVER))
    assert e.value.status_code == 400


def test_create_then_resume_same_id(db):
    a = _new(db)
    b = _new(db)  # même (véhicule, chauffeur) in_progress -> reprise
    assert a["id"] == b["id"]
    assert a["status"] == "in_progress"
    assert a["vehicle_id"] == "vA" and a["driver_id"] == "drvA"
    assert a["vehicle_snapshot"]["plate"] == "FR 275924"  # snapshot serveur


def test_create_unauthorized_vehicle_forbidden(db):
    from app.routes.inspections import NewInspectionIn
    with pytest.raises(HTTPException) as e:
        _run(insp.create_inspection(NewInspectionIn(vehicle_id="vFOREIGN"), user=DRIVER))
    assert e.value.status_code == 403


def test_checklist_valid_and_invalid(db):
    i = _new(db)
    from app.routes.inspections import ChecklistIn, ChecklistItemIn
    ok = _run(insp.save_checklist(i["id"], ChecklistIn(items=[
        ChecklistItemIn(item="pneus", state="OK"),
        ChecklistItemIn(item="carrosserie", state="ANOMALIE", comment="rayure"),
    ]), user=DRIVER))
    states = {c["item"]: c["state"] for c in ok["checklist"]}
    assert states["pneus"] == "OK" and states["carrosserie"] == "ANOMALIE"
    # item inconnu -> 400
    with pytest.raises(HTTPException) as e1:
        _run(insp.save_checklist(i["id"], ChecklistIn(items=[ChecklistItemIn(item="zzz", state="OK")]), user=DRIVER))
    assert e1.value.status_code == 400
    # état invalide -> 400
    with pytest.raises(HTTPException) as e2:
        _run(insp.save_checklist(i["id"], ChecklistIn(items=[ChecklistItemIn(item="pneus", state="MAYBE")]), user=DRIVER))
    assert e2.value.status_code == 400


def test_photo_upload_download_and_invalid_mime(db):
    i = _new(db)
    up = _FakeUpload("p.png", "image/png", PNG)
    photo = _run(insp.add_photo(i["id"], item="carrosserie", file=up, user=DRIVER))
    assert photo["id"] and photo["filename"]
    resp = _run(insp.download_photo(i["id"], photo["id"], user=DRIVER))
    assert resp.status_code == 200 and resp.body
    bad = _FakeUpload("n.txt", "text/plain", b"x")
    with pytest.raises(HTTPException) as e:
        _run(insp.add_photo(i["id"], item="carrosserie", file=bad, user=DRIVER))
    assert e.value.status_code == 400


def test_validate_requires_comment_on_anomaly(db):
    i = _new(db)
    from app.routes.inspections import ChecklistIn, ChecklistItemIn
    # ANOMALIE sans commentaire
    _run(insp.save_checklist(i["id"], ChecklistIn(items=[
        ChecklistItemIn(item="pneus", state="ANOMALIE"),
    ]), user=DRIVER))
    with pytest.raises(HTTPException) as e:
        _run(insp.validate_inspection(i["id"], user=DRIVER))
    assert e.value.status_code == 400
    # avec commentaire -> validée
    _run(insp.save_checklist(i["id"], ChecklistIn(items=[
        ChecklistItemIn(item="pneus", state="ANOMALIE", comment="usure"),
    ]), user=DRIVER))
    res = _run(insp.validate_inspection(i["id"], user=DRIVER))
    assert res["status"] == "validated" and res["validated_at"]


def test_immutable_after_validation(db):
    i = _new(db)
    from app.routes.inspections import ChecklistIn, ChecklistItemIn
    _run(insp.save_checklist(i["id"], ChecklistIn(items=[ChecklistItemIn(item="pneus", state="OK")]), user=DRIVER))
    _run(insp.validate_inspection(i["id"], user=DRIVER))
    # toute mutation -> 409
    with pytest.raises(HTTPException) as e1:
        _run(insp.save_checklist(i["id"], ChecklistIn(items=[ChecklistItemIn(item="pneus", state="N/A")]), user=DRIVER))
    assert e1.value.status_code == 409
    up = _FakeUpload("p.png", "image/png", PNG)
    with pytest.raises(HTTPException) as e2:
        _run(insp.add_photo(i["id"], item="pneus", file=up, user=DRIVER))
    assert e2.value.status_code == 409


def test_history_lists_inspection(db):
    i = _new(db)
    hist = _run(insp.list_inspections(vehicle_id="vA", user=DRIVER))
    assert any(x["id"] == i["id"] for x in hist["inspections"])


def test_vehicle_id_stable_across_ops(db):
    i = _new(db)
    from app.routes.inspections import ChecklistIn, ChecklistItemIn
    _run(insp.save_checklist(i["id"], ChecklistIn(items=[ChecklistItemIn(item="pneus", state="OK")]), user=DRIVER))
    detail = _run(insp.get_inspection(i["id"], user=DRIVER))
    assert detail["vehicle_id"] == "vA"  # jamais réattribué


def test_manager_rbac(db):
    """require_roles('admin','manager') : admin OK, driver -> 403."""
    dep = require_roles("admin", "manager")
    assert _run(dep(user=ADMIN)) == ADMIN
    with pytest.raises(HTTPException) as e:
        _run(dep(user=DRIVER))
    assert e.value.status_code == 403


def test_manager_list_scoped(db):
    """manager_list_inspections renvoie les inspections du tenant (via proxy fake)."""
    i = _new(db)
    out = _run(insp.manager_list_inspections(vehicle_id=None, driver_id=None, status=None, user=ADMIN))
    assert any(x["id"] == i["id"] for x in out["inspections"])
