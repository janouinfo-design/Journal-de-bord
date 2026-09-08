"""API Super-Admin Logitrak — gestion des clients (tenants), utilisateurs et audit.

Réservée au rôle `superadmin`. Utilise la base NON scopée (get_raw_db) car elle
opère volontairement à travers tous les tenants.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.audit import log_audit
from app.auth import get_current_user, hash_password
from app.db import get_raw_db
from app.tenancy import fetch_navixy_identity, BUSINESS_COLLECTIONS
from app.tenant_context import refresh_tenant_cache

router = APIRouter(prefix="/admin", tags=["superadmin"])

TENANT_ROLES = ("admin", "manager", "driver", "lecture_seule")


async def require_superadmin(user=Depends(get_current_user)):
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Réservé au super-administrateur Logitrak")
    return user


def _mask_hash(h: Optional[str]) -> Optional[str]:
    if not h:
        return None
    return f"••••{h[-4:]}" if len(h) > 4 else "••••"


def _tenant_out(t: dict) -> dict:
    out = {k: v for k, v in t.items() if k not in ("navixy_hash", "_id")}
    out["navixy_hash_masked"] = _mask_hash(t.get("navixy_hash"))
    out["has_navixy_hash"] = bool(t.get("navixy_hash"))
    # Statut non sensible (jamais la valeur) : credential chiffré ou clair legacy.
    h = t.get("navixy_hash")
    out["navixy_credential_encrypted"] = bool(h and str(h).startswith("enc::"))
    return out


# ---------- Tenants ----------
class TenantIn(BaseModel):
    name: str
    navixy_hash: Optional[str] = None
    navixy_api_url: Optional[str] = None


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    navixy_hash: Optional[str] = None
    navixy_api_url: Optional[str] = None
    status: Optional[str] = None  # active | suspended


@router.get("/tenants")
async def list_tenants(current=Depends(require_superadmin)):
    db = get_raw_db()
    tenants = await db.tenants.find({}, {"_id": 0}).sort("created_at", 1).to_list(500)
    out = []
    for t in tenants:
        tid = t["id"]
        stats = {
            "users": await db.users.count_documents({"tenant_id": tid}),
            "vehicles": await db.vehicles.count_documents({"tenant_id": tid}),
            "trips": await db.trips.count_documents({"tenant_id": tid}),
            "fines": await db.fines.count_documents({"tenant_id": tid}),
        }
        row = _tenant_out(t)
        row["stats"] = stats
        out.append(row)
    return out


@router.post("/tenants")
async def create_tenant(payload: TenantIn, current=Depends(require_superadmin)):
    db = get_raw_db()
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Nom du client requis")
    api_url = (payload.navixy_api_url or "https://api.navixy.com/v2").rstrip("/")

    doc = {
        "id": str(uuid.uuid4()), "name": name,
        "navixy_api_url": api_url,
        "navixy_hash": None, "navixy_master_user_id": None, "navixy_login": None,
        "status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.navixy_hash:
        ident = await fetch_navixy_identity(api_url, payload.navixy_hash.strip())
        if not ident:
            raise HTTPException(400, "Clé API Navixy invalide ou API injoignable")
        dup = await db.tenants.find_one(
            {"navixy_master_user_id": ident["navixy_master_user_id"]}, {"_id": 0, "name": 1})
        if dup:
            raise HTTPException(400, f"Ce compte Navixy est déjà rattaché au client « {dup['name']} »")
        # Chiffrement au repos si INTEGRATION_ENCRYPTION_KEY présente (sinon clair legacy).
        from app.integrations import encrypt_secret
        doc["navixy_hash"] = encrypt_secret(payload.navixy_hash.strip())
        doc.update(ident)

    await db.tenants.insert_one(dict(doc))
    await refresh_tenant_cache(db)
    await log_audit("tenant.create", current, {"name": name}, tenant_id=doc["id"])
    return _tenant_out(doc)


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, payload: TenantUpdate, current=Depends(require_superadmin)):
    db = get_raw_db()
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(404, "Client introuvable")

    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.status is not None:
        if payload.status not in ("active", "suspended"):
            raise HTTPException(400, "Statut invalide (active | suspended)")
        if tenant_id == "default" and payload.status == "suspended":
            raise HTTPException(400, "Le tenant Logitrak par défaut ne peut pas être suspendu")
        updates["status"] = payload.status
    if payload.navixy_api_url is not None:
        updates["navixy_api_url"] = payload.navixy_api_url.rstrip("/")
    if payload.navixy_hash is not None:
        new_hash = payload.navixy_hash.strip()
        api_url = updates.get("navixy_api_url") or tenant.get("navixy_api_url") or "https://api.navixy.com/v2"
        ident = await fetch_navixy_identity(api_url, new_hash)
        if not ident:
            raise HTTPException(400, "Clé API Navixy invalide ou API injoignable")
        dup = await db.tenants.find_one(
            {"navixy_master_user_id": ident["navixy_master_user_id"], "id": {"$ne": tenant_id}},
            {"_id": 0, "name": 1})
        if dup:
            raise HTTPException(400, f"Ce compte Navixy est déjà rattaché au client « {dup['name']} »")
        # Chiffrement au repos si INTEGRATION_ENCRYPTION_KEY présente (sinon clair legacy).
        from app.integrations import encrypt_secret
        updates["navixy_hash"] = encrypt_secret(new_hash)
        updates.update(ident)

    if not updates:
        raise HTTPException(400, "Aucun champ à mettre à jour")
    await db.tenants.update_one({"id": tenant_id}, {"$set": updates})
    await refresh_tenant_cache(db)
    await log_audit("tenant.update", current,
                    {"fields": [k for k in updates if k != "navixy_hash"] +
                     (["navixy_hash"] if "navixy_hash" in updates else [])},
                    tenant_id=tenant_id)
    fresh = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    return _tenant_out(fresh)


@router.post("/tenants/{tenant_id}/sync")
async def sync_tenant_now(tenant_id: str, current=Depends(require_superadmin)):
    """Déclenche manuellement la synchronisation Navixy d'un client."""
    from app.navixy_sync import sync_navixy
    from app.tenant_context import set_current_tenant, reset_current_tenant

    db = get_raw_db()
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(404, "Client introuvable")
    if not tenant.get("navixy_hash"):
        raise HTTPException(400, "Aucune clé API Navixy configurée pour ce client")

    started = datetime.now(timezone.utc).isoformat()
    token = set_current_tenant(tenant_id)
    try:
        result = await sync_navixy(days=7, force_reclassify=True)
    except Exception as e:
        result = {"error": str(e)}
    finally:
        reset_current_tenant(token)

    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"last_sync_at": started, "last_sync_result": result}})
    await log_audit("tenant.sync_manual", current,
                    {"result": "error" if result.get("error") else "ok"}, tenant_id=tenant_id)
    if result.get("error"):
        raise HTTPException(502, f"Échec de synchronisation : {result['error']}")
    return {"tenant_id": tenant_id, "last_sync_at": started, "result": result}


# ---------- Accès Navixy (onglet fiche client) ----------
def _navixy_access_status(t: dict) -> str:
    """État d'accès SSO — indépendant de l'état de synchronisation."""
    if not t.get("navixy_hash") or not t.get("navixy_master_user_id"):
        return "incomplete"
    st = t.get("last_navixy_test_status")
    if st == "error":
        return "error"
    if st == "ok":
        return "configured"
    return "untested"


def _navixy_sync_status(t: dict) -> dict:
    if not t.get("last_sync_at"):
        return {"status": "never", "last_sync_at": None, "error": None}
    res = t.get("last_sync_result") or {}
    err = res.get("error") or ((res.get("errors") or [None])[0])
    return {"status": "error" if err else "ok", "last_sync_at": t.get("last_sync_at"),
            "error": str(err)[:200] if err else None}


@router.get("/tenants/{tenant_id}/navixy-access")
async def tenant_navixy_access(tenant_id: str, current=Depends(require_superadmin)):
    """Fiche « Accès Navixy » d'un client — aucun secret dans la réponse."""
    db = get_raw_db()
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Client introuvable")
    recent = await db.audit_log.find(
        {"action": "auth.sso_failed", "tenant_id": tenant_id},
        {"_id": 0, "at": 1, "details": 1}).sort("at", -1).to_list(10)
    return {
        "tenant": {"id": t["id"], "name": t["name"], "status": t["status"]},
        "master": {"login": t.get("navixy_login"), "id": t.get("navixy_master_user_id")},
        "access_status": _navixy_access_status(t),
        "sync": _navixy_sync_status(t),
        "last_sso_at": t.get("last_sso_at"),
        "last_test": {"at": t.get("last_navixy_test_at"),
                      "status": t.get("last_navixy_test_status"),
                      "error": t.get("last_navixy_test_error")},
        "recent_errors": [{"at": r.get("at"),
                           "category": (r.get("details") or {}).get("category")} for r in recent],
    }


@router.post("/tenants/{tenant_id}/test-navixy")
async def tenant_test_navixy(tenant_id: str, current=Depends(require_superadmin)):
    """Teste la clé API permanente du client auprès de Navixy.
    Ne crée NI utilisateur NI session NI cookie ; ne touche jamais last_sso_at."""
    db = get_raw_db()
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Client introuvable")
    now = datetime.now(timezone.utc).isoformat()
    ident = None
    if not t.get("navixy_hash"):
        status, error = "error", "no_key"
    else:
        ident = await fetch_navixy_identity(
            t.get("navixy_api_url") or "https://api.navixy.com/v2", t["navixy_hash"])
        if not ident:
            status, error = "error", "invalid_key_or_unreachable"
        elif t.get("navixy_master_user_id") \
                and ident["navixy_master_user_id"] != t["navixy_master_user_id"]:
            status, error = "error", "master_mismatch"
        else:
            status, error = "ok", None
    await db.tenants.update_one({"id": tenant_id}, {"$set": {
        "last_navixy_test_at": now, "last_navixy_test_status": status,
        "last_navixy_test_error": error}})
    await log_audit("tenant.navixy_test", current, {"status": status, "error": error},
                    tenant_id=tenant_id)
    return {"ok": status == "ok", "status": status, "error": error, "tested_at": now,
            "master": ({"login": ident.get("navixy_login"),
                        "id": ident.get("navixy_master_user_id")} if status == "ok" else None)}


# ---------- Utilisateurs ----------
class UserIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "driver"
    tenant_id: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    tenant_id: Optional[str] = None


@router.get("/users")
async def list_all_users(tenant_id: Optional[str] = None, current=Depends(require_superadmin)):
    db = get_raw_db()
    q = {"tenant_id": tenant_id} if tenant_id else {}
    rows = await db.users.find(q, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(2000)
    return rows


@router.post("/users")
async def admin_create_user(payload: UserIn, current=Depends(require_superadmin)):
    db = get_raw_db()
    if payload.role not in TENANT_ROLES:
        raise HTTPException(400, f"Rôle invalide ({', '.join(TENANT_ROLES)})")
    if not await db.tenants.find_one({"id": payload.tenant_id}):
        raise HTTPException(404, "Client introuvable")
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email déjà utilisé")
    user = {
        "id": str(uuid.uuid4()), "email": email, "name": payload.name,
        "role": payload.role, "tenant_id": payload.tenant_id,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(user))
    user.pop("password_hash")
    await log_audit("user.create", current, {"email": email, "role": payload.role},
                    tenant_id=payload.tenant_id)
    return user


@router.patch("/users/{user_id}")
async def admin_update_user(user_id: str, payload: UserUpdate, current=Depends(require_superadmin)):
    db = get_raw_db()
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    if target.get("role") == "superadmin":
        raise HTTPException(400, "Le compte superadmin ne peut pas être modifié ici")

    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.role is not None:
        if payload.role not in TENANT_ROLES:
            raise HTTPException(400, f"Rôle invalide ({', '.join(TENANT_ROLES)})")
        updates["role"] = payload.role
    if payload.tenant_id is not None:
        if not await db.tenants.find_one({"id": payload.tenant_id}):
            raise HTTPException(404, "Client introuvable")
        updates["tenant_id"] = payload.tenant_id
    if payload.password:
        updates["password_hash"] = hash_password(payload.password)
    if not updates:
        raise HTTPException(400, "Aucun champ à mettre à jour")

    await db.users.update_one({"id": user_id}, {"$set": updates})
    await log_audit("user.update", current,
                    {"email": target["email"],
                     "fields": [k.replace("password_hash", "password") for k in updates]},
                    tenant_id=updates.get("tenant_id") or target.get("tenant_id"))
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return fresh


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: str, current=Depends(require_superadmin)):
    db = get_raw_db()
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    if target.get("role") == "superadmin":
        raise HTTPException(400, "Impossible de supprimer un superadmin")
    await db.users.delete_one({"id": user_id})
    await log_audit("user.delete", current, {"email": target["email"]},
                    tenant_id=target.get("tenant_id"))
    return {"deleted": True, "id": user_id}


# ---------- Audit global ----------
@router.get("/audit")
async def global_audit(tenant_id: Optional[str] = None, action: Optional[str] = None,
                       limit: int = 200, current=Depends(require_superadmin)):
    db = get_raw_db()
    q: dict = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if action:
        q["action"] = {"$regex": action, "$options": "i"}
    rows = await db.audit_log.find(q, {"_id": 0}).sort("at", -1).to_list(min(limit, 1000))
    return rows
