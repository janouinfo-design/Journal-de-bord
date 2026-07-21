"""MongoDB singleton + proxy d'isolation multi-tenant.

Toute collection métier est automatiquement filtrée/estampillée avec le
`tenant_id` du contexte courant (posé par `get_current_user`). Les collections
globales (users, tenants, push_tokens, app_state) ne sont pas scopées.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient

from app.tenant_context import get_tenant_id

_client = None
_db = None

GLOBAL_COLLECTIONS = {"users", "tenants", "push_tokens", "app_state"}


class _ScopedCollection:
    def __init__(self, coll, tenant_id):
        self._c = coll
        self._tid = tenant_id

    def _f(self, flt):
        return {**(flt or {}), "tenant_id": self._tid}

    def _stamp(self, doc):
        doc["tenant_id"] = self._tid
        return doc

    def _fix_update(self, update):
        if isinstance(update, dict):
            for op in ("$set", "$setOnInsert"):
                if op in update and isinstance(update[op], dict) and "tenant_id" in update[op]:
                    update[op]["tenant_id"] = self._tid
        return update

    def find(self, flt=None, *a, **k):
        return self._c.find(self._f(flt), *a, **k)

    def find_one(self, flt=None, *a, **k):
        return self._c.find_one(self._f(flt), *a, **k)

    def count_documents(self, flt=None, *a, **k):
        return self._c.count_documents(self._f(flt), *a, **k)

    def distinct(self, key, flt=None, *a, **k):
        return self._c.distinct(key, self._f(flt), *a, **k)

    def aggregate(self, pipeline, *a, **k):
        return self._c.aggregate([{"$match": {"tenant_id": self._tid}}] + list(pipeline), *a, **k)

    def insert_one(self, doc, *a, **k):
        return self._c.insert_one(self._stamp(doc), *a, **k)

    def insert_many(self, docs, *a, **k):
        return self._c.insert_many([self._stamp(d) for d in docs], *a, **k)

    def update_one(self, flt, update, *a, **k):
        return self._c.update_one(self._f(flt), self._fix_update(update), *a, **k)

    def update_many(self, flt, update, *a, **k):
        return self._c.update_many(self._f(flt), self._fix_update(update), *a, **k)

    def replace_one(self, flt, doc, *a, **k):
        return self._c.replace_one(self._f(flt), self._stamp(doc), *a, **k)

    def delete_one(self, flt=None, *a, **k):
        return self._c.delete_one(self._f(flt), *a, **k)

    def delete_many(self, flt=None, *a, **k):
        return self._c.delete_many(self._f(flt), *a, **k)

    def find_one_and_update(self, flt, update, *a, **k):
        return self._c.find_one_and_update(self._f(flt), self._fix_update(update), *a, **k)

    def find_one_and_delete(self, flt=None, *a, **k):
        return self._c.find_one_and_delete(self._f(flt), *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


class TenantScopedDB:
    def __init__(self, db, tenant_id):
        self._db = db
        self._tid = tenant_id

    def __getattr__(self, name):
        coll = self._db[name]
        if name in GLOBAL_COLLECTIONS:
            return coll
        return _ScopedCollection(coll, self._tid)

    def __getitem__(self, name):
        return self.__getattr__(name)


def init_db():
    global _client, _db
    _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    _db = _client[os.environ["DB_NAME"]]
    return _db


def get_db():
    tid = get_tenant_id()
    if tid:
        return TenantScopedDB(_db, tid)
    return _db


def get_raw_db():
    """Accès non scopé (auth, admin, migrations, scheduler)."""
    return _db


def close_db():
    if _client is not None:
        _client.close()
