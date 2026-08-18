"""Tenant context — contextvar per-request + in-memory tenant cache (single process)."""
from contextvars import ContextVar

DEFAULT_TENANT_ID = "default"
NO_TENANT = "__none__"  # superadmin sans client sélectionné → aucune donnée métier

_current_tenant: ContextVar = ContextVar("current_tenant", default=None)
_tenant_cache: dict = {}


def set_current_tenant(tenant_id):
    return _current_tenant.set(tenant_id)


def reset_current_tenant(token):
    _current_tenant.reset(token)


def get_tenant_id():
    return _current_tenant.get()


def get_effective_tenant_id():
    """Tenant utilisable pour l'audit/données (None si superadmin sans sélection)."""
    tid = _current_tenant.get()
    return None if tid == NO_TENANT else tid


def get_tenant_doc(tenant_id=None):
    tid = tenant_id or _current_tenant.get()
    return _tenant_cache.get(tid)


async def refresh_tenant_cache(db):
    global _tenant_cache
    rows = await db.tenants.find({}, {"_id": 0}).to_list(1000)
    _tenant_cache = {t["id"]: t for t in rows}
    return _tenant_cache
