"""Administration client (tenant admin) — gestion des utilisateurs et des chauffeurs.

Réservé au rôle `admin` (de l'entreprise) — le superadmin y accède via impersonation.
Toutes les données sont automatiquement scopées au tenant courant (proxy DB).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.audit import log_audit
from app.auth import get_current_user, require_roles, hash_password
from app.db import get_db, get_raw_db
from app.tenant_context import get_effective_tenant_id

router = APIRouter(prefix="/team", tags=["team"])

TEAM_ROLES = ("admin", "manager", "driver")


def _tenant_or_400() -> str:
    tid = get_effective_tenant_id()
    if not tid:
        raise HTTPException(400, "Sélectionnez d'abord un client")
    return tid


# ====================== UTILISATEURS (accès à l'application) ======================
class TeamUserIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "driver"


class TeamUserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


@router.get("/users")
async def team_list_users(current=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    raw = get_raw_db()
    users = await raw.users.find(
        {"tenant_id": tid}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(1000)
    db = get_db()
    drivers = await db.drivers.find({}, {"_id": 0, "id": 1, "name": 1, "user_id": 1, "email": 1}).to_list(1000)
    by_user = {d.get("user_id"): d for d in drivers if d.get("user_id")}
    by_email = {d.get("email"): d for d in drivers if d.get("email")}
    for u in users:
        drv = by_user.get(u["id"]) or by_email.get(u["email"])
        u["linked_driver"] = {"id": drv["id"], "name": drv["name"]} if drv else None
    return users


@router.post("/users")
async def team_create_user(payload: TeamUserIn, current=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    if payload.role not in TEAM_ROLES:
        raise HTTPException(400, f"Rôle invalide ({', '.join(TEAM_ROLES)})")
    raw = get_raw_db()
    email = payload.email.lower()
    if await raw.users.find_one({"email": email}):
        raise HTTPException(400, "Email déjà utilisé")
    user = {
        "id": str(uuid.uuid4()), "email": email, "name": payload.name,
        "role": payload.role, "tenant_id": tid,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await raw.users.insert_one(dict(user))
    user.pop("password_hash")
    await log_audit("user.create", current, {"email": email, "role": payload.role})
    return user


@router.patch("/users/{user_id}")
async def team_update_user(user_id: str, payload: TeamUserUpdate,
                           current=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    raw = get_raw_db()
    target = await raw.users.find_one({"id": user_id, "tenant_id": tid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.role is not None:
        if payload.role not in TEAM_ROLES:
            raise HTTPException(400, f"Rôle invalide ({', '.join(TEAM_ROLES)})")
        if target["id"] == current["id"] and payload.role != "admin":
            raise HTTPException(400, "Vous ne pouvez pas rétrograder votre propre compte")
        updates["role"] = payload.role
    if payload.password:
        updates["password_hash"] = hash_password(payload.password)
    if not updates:
        raise HTTPException(400, "Aucun champ à mettre à jour")
    await raw.users.update_one({"id": user_id, "tenant_id": tid}, {"$set": updates})
    await log_audit("user.update", current,
                    {"email": target["email"],
                     "fields": [k.replace("password_hash", "password") for k in updates]})
    fresh = await raw.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return fresh


@router.delete("/users/{user_id}")
async def team_delete_user(user_id: str, current=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    raw = get_raw_db()
    target = await raw.users.find_one({"id": user_id, "tenant_id": tid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    if target["id"] == current["id"]:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte")
    await raw.users.delete_one({"id": user_id, "tenant_id": tid})
    await get_db().drivers.update_many({"user_id": user_id}, {"$unset": {"user_id": ""}})
    await log_audit("user.delete", current, {"email": target["email"]})
    return {"deleted": True, "id": user_id}


@router.post("/users/{user_id}/impersonate")
async def team_impersonate_user(user_id: str, request: Request,
                                current=Depends(require_roles("admin"))):
    """Génère un token d'aperçu à usage unique (60 s) pour « Se connecter comme… »."""
    import hashlib
    import secrets
    from datetime import timedelta

    tid = _tenant_or_400()
    if current.get("impersonated_by"):
        raise HTTPException(403, "Impossible d'imbriquer les sessions d'aperçu")
    raw = get_raw_db()
    target = await raw.users.find_one({"id": user_id, "tenant_id": tid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable dans votre entreprise")
    if target.get("role") == "superadmin":
        raise HTTPException(400, "Ce compte ne peut pas être ouvert en aperçu")
    if target["id"] == current["id"]:
        raise HTTPException(400, "Vous êtes déjà connecté avec ce compte")

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    auth_source = ("super_admin_impersonation" if current.get("role") == "superadmin"
                   else "admin_client_impersonation")
    rec = {
        "id": str(uuid.uuid4()),
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "actor_user_id": current["id"], "actor_email": current["email"],
        "target_user_id": target["id"], "target_email": target["email"],
        "tenant_id": tid, "auth_source": auth_source,
        "used": False,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=60)).isoformat(),
        "ip": request.client.host if request.client else None,
    }
    await raw.impersonation_tokens.insert_one(dict(rec))
    await log_audit("user.impersonate_start", current,
                    {"target": target["email"], "target_role": target["role"],
                     "session_id": rec["id"], "auth_source": auth_source,
                     "ip": rec["ip"]})
    return {"token": token, "expires_in": 60,
            "target": {"name": target.get("name"), "email": target["email"], "role": target["role"]}}


# ====================== CHAUFFEURS (personnes qui conduisent) ======================
class DriverIn(BaseModel):
    name: str
    internal_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    active: bool = True
    ibutton_id: Optional[str] = None
    rfid_id: Optional[str] = None
    ble_id: Optional[str] = None
    group: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class DriverUpdate(BaseModel):
    name: Optional[str] = None
    internal_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    active: Optional[bool] = None
    ibutton_id: Optional[str] = None
    rfid_id: Optional[str] = None
    ble_id: Optional[str] = None
    group: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


DRIVER_FIELDS = ("name", "internal_number", "phone", "email", "active",
                 "ibutton_id", "rfid_id", "ble_id", "group", "start_date", "end_date")


@router.get("/drivers")
async def team_list_drivers(user=Depends(require_roles("admin", "manager"))):
    _tenant_or_400()
    db = get_db()
    drivers = await db.drivers.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    raw = get_raw_db()
    user_ids = [d["user_id"] for d in drivers if d.get("user_id")]
    users = await raw.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "email": 1}).to_list(1000) if user_ids else []
    by_id = {u["id"]: u for u in users}
    for d in drivers:
        acc = by_id.get(d.get("user_id"))
        d["account"] = {"user_id": acc["id"], "email": acc["email"]} if acc else None
    return drivers


@router.post("/drivers")
async def team_create_driver(payload: DriverIn, current=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    doc = {"id": str(uuid.uuid4()),
           "created_at": datetime.now(timezone.utc).isoformat(),
           **{k: getattr(payload, k) for k in DRIVER_FIELDS}}
    doc["email"] = (doc.get("email") or "").lower() or ""
    await db.drivers.insert_one(dict(doc))
    await log_audit("driver.create", current, {"name": payload.name})
    doc.pop("_id", None)
    return doc


@router.patch("/drivers/{driver_id}")
async def team_update_driver(driver_id: str, payload: DriverUpdate,
                             current=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Chauffeur introuvable")
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if k in DRIVER_FIELDS}
    if "email" in updates and updates["email"]:
        updates["email"] = updates["email"].lower()
    if not updates:
        raise HTTPException(400, "Aucun champ à mettre à jour")
    await db.drivers.update_one({"id": driver_id}, {"$set": updates})
    await log_audit("driver.update", current, {"name": driver.get("name"), "fields": list(updates)})
    return await db.drivers.find_one({"id": driver_id}, {"_id": 0})


class GrantAccessIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/drivers/{driver_id}/grant-access")
async def grant_driver_access(driver_id: str, payload: GrantAccessIn,
                              current=Depends(require_roles("admin"))):
    """Crée un compte utilisateur (rôle chauffeur) lié à ce chauffeur — accès PWA."""
    tid = _tenant_or_400()
    db = get_db()
    raw = get_raw_db()
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Chauffeur introuvable")
    if driver.get("user_id"):
        raise HTTPException(400, "Ce chauffeur a déjà un compte lié")
    email = payload.email.lower()
    if await raw.users.find_one({"email": email}):
        raise HTTPException(400, "Email déjà utilisé — utilisez « Lier un compte existant »")
    user = {
        "id": str(uuid.uuid4()), "email": email, "name": driver.get("name") or email,
        "role": "driver", "tenant_id": tid, "driver_id": driver_id,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await raw.users.insert_one(dict(user))
    await db.drivers.update_one({"id": driver_id}, {"$set": {"user_id": user["id"], "email": driver.get("email") or email}})
    await log_audit("driver.grant_access", current, {"driver": driver.get("name"), "email": email})
    return {"driver_id": driver_id, "user_id": user["id"], "email": email}


class LinkUserIn(BaseModel):
    user_id: str


@router.post("/drivers/{driver_id}/link-user")
async def link_driver_user(driver_id: str, payload: LinkUserIn,
                           current=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    db = get_db()
    raw = get_raw_db()
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Chauffeur introuvable")
    target = await raw.users.find_one({"id": payload.user_id, "tenant_id": tid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "Utilisateur introuvable dans votre entreprise")
    await db.drivers.update_one({"id": driver_id}, {"$set": {"user_id": target["id"]}})
    await raw.users.update_one({"id": target["id"]}, {"$set": {"driver_id": driver_id}})
    await log_audit("driver.link_user", current, {"driver": driver.get("name"), "email": target["email"]})
    return {"linked": True}


@router.post("/drivers/{driver_id}/unlink-user")
async def unlink_driver_user(driver_id: str, current=Depends(require_roles("admin"))):
    tid = _tenant_or_400()
    db = get_db()
    raw = get_raw_db()
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Chauffeur introuvable")
    if driver.get("user_id"):
        await raw.users.update_one({"id": driver["user_id"], "tenant_id": tid}, {"$unset": {"driver_id": ""}})
    await db.drivers.update_one({"id": driver_id}, {"$unset": {"user_id": ""}})
    await log_audit("driver.unlink_user", current, {"driver": driver.get("name")})
    return {"unlinked": True}
