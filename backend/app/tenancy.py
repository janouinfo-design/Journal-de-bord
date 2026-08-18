"""Bootstrap multi-tenant : tenant par défaut, backfill des données, superadmin."""
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"

BUSINESS_COLLECTIONS = [
    "vehicles", "drivers", "trips", "geofences", "settings", "fines",
    "ble_tags", "ble_detections", "ble_aliases", "driver_sessions",
    "assignments", "schedules", "tracker_privacy_state", "trip_tracks",
    "audit_log", "notification_preferences", "notifications_log",
]


async def fetch_navixy_identity(api_url: str, nav_hash: str) -> dict | None:
    """user/get_info (best effort) pour identifier le compte maître d'une clé API."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(f"{api_url.rstrip('/')}/user/get_info", json={"hash": nav_hash})
        data = r.json()
        if not data.get("success"):
            return None
        info = data.get("user_info", {}) or {}
        master = data.get("master") or {}
        return {
            "navixy_master_user_id": master.get("id") or info.get("id"),
            "navixy_login": info.get("login"),
        }
    except Exception:
        return None


async def ensure_tenancy(db):
    """Migration idempotente. `db` doit être la base NON scopée."""
    now = datetime.now(timezone.utc).isoformat()
    api_url = os.environ.get("NAVIXY_API_URL", "https://api.navixy.com/v2")
    env_hash = os.environ.get("NAVIXY_HASH", "").strip()

    tenant = await db.tenants.find_one({"id": DEFAULT_TENANT_ID})
    if not tenant:
        doc = {
            "id": DEFAULT_TENANT_ID, "name": "Logitrak",
            "navixy_api_url": api_url, "navixy_hash": env_hash or None,
            "navixy_master_user_id": None, "navixy_login": None,
            "status": "active", "created_at": now,
        }
        if env_hash:
            ident = await fetch_navixy_identity(api_url, env_hash)
            if ident:
                doc.update(ident)
        await db.tenants.insert_one(doc)
        logger.info("Tenant par défaut 'Logitrak' créé")
    elif not tenant.get("navixy_master_user_id") and (tenant.get("navixy_hash") or env_hash):
        ident = await fetch_navixy_identity(
            tenant.get("navixy_api_url") or api_url, tenant.get("navixy_hash") or env_hash)
        if ident:
            await db.tenants.update_one({"id": DEFAULT_TENANT_ID}, {"$set": ident})

    for coll in BUSINESS_COLLECTIONS:
        r = await db[coll].update_many(
            {"tenant_id": {"$exists": False}}, {"$set": {"tenant_id": DEFAULT_TENANT_ID}})
        if r.modified_count:
            logger.info("Backfill tenant_id: %s (%d docs)", coll, r.modified_count)

    await db.users.update_many(
        {"tenant_id": {"$exists": False}, "role": {"$ne": "superadmin"}},
        {"$set": {"tenant_id": DEFAULT_TENANT_ID}})

    # Superadmin Logitrak (séparé des comptes clients, tenant_id=None)
    from app.auth import hash_password, verify_password
    email = os.environ.get("SUPERADMIN_EMAIL", "superadmin@logitrak.ch").lower()
    password = os.environ.get("SUPERADMIN_PASSWORD", "superadmin123")
    existing = await db.users.find_one({"email": email})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": email, "name": "Super Admin Logitrak",
            "role": "superadmin", "tenant_id": None,
            "password_hash": hash_password(password), "created_at": now,
        })
        logger.info("Compte superadmin créé: %s", email)
    elif existing.get("password_hash") and not verify_password(password, existing["password_hash"]):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(password)}})

    await db.tenants.create_index("id", unique=True)
    await db.tenants.create_index("navixy_master_user_id")
    await db.audit_log.create_index([("tenant_id", 1), ("at", -1)])

    from app.tenant_context import refresh_tenant_cache
    await refresh_tenant_cache(db)
