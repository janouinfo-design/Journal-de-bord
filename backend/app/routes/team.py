"""Administration client (tenant admin) — gestion des utilisateurs et des chauffeurs.

Réservé au rôle `admin` (de l'entreprise) — le superadmin y accède via impersonation.
Toutes les données sont automatiquement scopées au tenant courant (proxy DB).
"""
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.audit import log_audit
from app.auth import get_current_user, require_roles, hash_password, IMP_ACCESS_TTL_MIN
from app.db import get_db, get_raw_db
from app.emailer import is_smtp_configured, send_invitation_email
from app.tenant_context import get_effective_tenant_id

router = APIRouter(prefix="/team", tags=["team"])

TEAM_ROLES = ("admin", "manager", "driver", "lecture_seule")


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
    active: Optional[bool] = None


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
    if payload.active is not None:
        if target["id"] == current["id"] and payload.active is False:
            raise HTTPException(400, "Vous ne pouvez pas désactiver votre propre compte")
        updates["active"] = payload.active
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


class ImpersonateIn(BaseModel):
    reason: Optional[str] = None


@router.post("/users/{user_id}/impersonate")
async def team_impersonate_user(user_id: str, request: Request,
                                payload: Optional[ImpersonateIn] = None,
                                current=Depends(require_roles("admin"))):
    """Génère un token d'aperçu à usage unique (60 s) pour « Se connecter comme… »."""
    tid = _tenant_or_400()
    if current.get("impersonated_by"):
        raise HTTPException(403, "Impossible d'imbriquer les sessions d'aperçu")
    raw = get_raw_db()
    tenant = await raw.tenants.find_one({"id": tid}, {"_id": 0, "status": 1})
    if tenant and tenant.get("status") != "active":
        raise HTTPException(403, "Client suspendu — aperçu indisponible")
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
    reason = (payload.reason or "").strip() if payload else ""
    rec = {
        "id": str(uuid.uuid4()),
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "actor_user_id": current["id"], "actor_email": current["email"],
        "actor_name": current.get("name"),
        "target_user_id": target["id"], "target_email": target["email"],
        "target_name": target.get("name"), "target_role": target.get("role"),
        "tenant_id": tid, "auth_source": auth_source,
        "reason": reason or None,
        "used": False,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=60)).isoformat(),
        "ip": request.client.host if request.client else None,
    }
    await raw.impersonation_tokens.insert_one(dict(rec))
    await log_audit("user.impersonate_start", current,
                    {"target": target["email"], "target_role": target["role"],
                     "session_id": rec["id"], "auth_source": auth_source,
                     "reason": reason or None, "ip": rec["ip"]})
    return {"token": token, "expires_in": 60,
            "target": {"name": target.get("name"), "email": target["email"], "role": target["role"]}}


def _imp_status(rec: dict, now: datetime) -> str:
    if rec.get("denied_at"):
        return "denied"
    if not rec.get("used"):
        return "expired" if datetime.fromisoformat(rec["expires_at"]) < now else "pending"
    if rec.get("ended_at"):
        return "ended"
    used_at = datetime.fromisoformat(rec["used_at"])
    return "active" if used_at + timedelta(minutes=IMP_ACCESS_TTL_MIN) > now else "ended"


@router.get("/impersonation-sessions")
async def list_impersonation_sessions(tenant_id: Optional[str] = None,
                                      current=Depends(require_roles("admin"))):
    """Historique des sessions « Se connecter comme… » — lecture seule, non modifiable."""
    raw = get_raw_db()
    if current.get("role") == "superadmin":
        if tenant_id == "all":
            q = {}
        elif tenant_id:
            q = {"tenant_id": tenant_id}
        else:
            tid = get_effective_tenant_id()
            q = {"tenant_id": tid} if tid else {}
    else:
        q = {"tenant_id": current.get("tenant_id") or "default"}
    rows = await raw.impersonation_tokens.find(
        q, {"_id": 0, "token_hash": 0}).sort("created_at", -1).to_list(500)
    now = datetime.now(timezone.utc)
    for r in rows:
        r["status"] = _imp_status(r, now)
        if r.get("used_at") and r.get("ended_at"):
            delta = datetime.fromisoformat(r["ended_at"]) - datetime.fromisoformat(r["used_at"])
            r["duration_seconds"] = max(0, int(delta.total_seconds()))
        elif r["status"] == "active":
            delta = now - datetime.fromisoformat(r["used_at"])
            r["duration_seconds"] = max(0, int(delta.total_seconds()))
        else:
            r["duration_seconds"] = None
    return rows


# ====================== CHAUFFEURS (personnes qui conduisent) ======================
class DriverIn(BaseModel):
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
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


DRIVER_FIELDS = ("name", "first_name", "last_name", "internal_number", "phone",
                 "email", "active", "ibutton_id", "rfid_id", "ble_id", "group",
                 "start_date", "end_date")


@router.get("/drivers")
async def team_list_drivers(user=Depends(require_roles("admin", "manager"))):
    tid = _tenant_or_400()
    db = get_db()
    drivers = await db.drivers.find({}, {"_id": 0}).sort("name", 1).to_list(1000)
    raw = get_raw_db()
    users = await raw.users.find(
        {"tenant_id": tid},
        {"_id": 0, "id": 1, "email": 1, "active": 1, "last_login_at": 1,
         "driver_id": 1, "role": 1}).to_list(2000)
    by_id = {u["id"]: u for u in users}
    by_driver = {u["driver_id"]: u for u in users if u.get("driver_id")}
    by_email = {u["email"]: u for u in users if u.get("role") == "driver"}
    open_sessions = await db.driver_sessions.find(
        {"status": {"$in": ["open", "automatic", "pending", "manual", "confirmed", "conflict", "ending"]},
         "$or": [{"ended_at": None}, {"ended_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "driver_id": 1, "vehicle_id": 1, "status": 1, "started_at": 1,
         "identification_source": 1, "last_seen": 1}).to_list(2000)
    veh_ids = list({s["vehicle_id"] for s in open_sessions})
    veh_rows = await db.vehicles.find(
        {"id": {"$in": veh_ids}}, {"_id": 0, "id": 1, "plate": 1, "model": 1}).to_list(2000) if veh_ids else []
    vby = {v["id"]: v for v in veh_rows}
    sess_by_driver: dict = {}
    for s in sorted(open_sessions, key=lambda x: x.get("started_at") or "", reverse=True):
        sess_by_driver.setdefault(s["driver_id"], s)
    now = datetime.now(timezone.utc).isoformat()
    invitations = await raw.invitations.find(
        {"tenant_id": tid, "used": False, "expires_at": {"$gt": now}},
        {"_id": 0, "driver_id": 1, "email": 1, "expires_at": 1, "created_at": 1}).to_list(1000)
    inv_by_driver = {i["driver_id"]: i for i in invitations}
    for d in drivers:
        acc = by_id.get(d.get("user_id")) or by_driver.get(d["id"]) \
            or (by_email.get(d.get("email")) if d.get("email") else None)
        d["account"] = ({"user_id": acc["id"], "email": acc["email"],
                         "active": acc.get("active", True) is not False,
                         "last_login_at": acc.get("last_login_at")} if acc else None)
        inv = inv_by_driver.get(d["id"]) if not acc else None
        d["pending_invitation"] = ({"email": inv["email"], "expires_at": inv["expires_at"],
                                    "created_at": inv["created_at"]} if inv else None)
        s = sess_by_driver.get(d["id"])
        d["current_session"] = ({**s, "vehicle_plate": vby.get(s["vehicle_id"], {}).get("plate"),
                                 "vehicle_model": vby.get(s["vehicle_id"], {}).get("model")}
                                if s else None)
        acts = []
        if acc and acc.get("last_login_at"):
            acts.append((acc["last_login_at"], "Connexion"))
        if s:
            acts.append((s.get("last_seen") or s.get("started_at") or "", "Session"))
        d["last_activity"] = ({"ts": max(acts)[0], "kind": max(acts)[1]} if acts else None)
    return drivers


@router.post("/drivers")
async def team_create_driver(payload: DriverIn, current=Depends(require_roles("admin"))):
    _tenant_or_400()
    db = get_db()
    doc = {"id": str(uuid.uuid4()),
           "created_at": datetime.now(timezone.utc).isoformat(),
           **{k: getattr(payload, k) for k in DRIVER_FIELDS}}
    full = (doc.get("name") or "").strip() or " ".join(
        p for p in [(doc.get("first_name") or "").strip(),
                    (doc.get("last_name") or "").strip()] if p)
    if not full:
        raise HTTPException(400, "Nom du chauffeur requis (nom complet ou prénom + nom)")
    doc["name"] = full
    doc["email"] = (doc.get("email") or "").lower() or ""
    doc["internal_number"] = (doc.get("internal_number") or "").strip() or None
    if doc["email"]:
        dup = await db.drivers.find_one({"email": doc["email"]}, {"_id": 1})
        if dup:
            raise HTTPException(409, "Un chauffeur avec cet e-mail existe déjà")
    if doc["internal_number"]:
        dup = await db.drivers.find_one({"internal_number": doc["internal_number"]}, {"_id": 1})
        if dup:
            raise HTTPException(409, "Ce matricule est déjà attribué à un autre chauffeur")
    if doc.get("ble_id"):
        from app.ble_engine import normalize_identifier
        norm = normalize_identifier(doc["ble_id"])
        dup = await db.drivers.find_one(
            {"ble_id_norm": norm, "active": {"$ne": False}}, {"_id": 1})
        if dup:
            raise HTTPException(409, "Ce tag BLE est déjà attribué à un autre chauffeur")
        doc["ble_id_norm"] = norm
    await db.drivers.insert_one(dict(doc))
    await log_audit("driver.create", current, {"name": doc["name"]})
    if doc.get("ble_id"):
        await log_audit("driver.ble_tag_assigned", current,
                        {"driver": doc["name"], "tag": doc["ble_id"]})
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
    if "email" in updates:
        updates["email"] = (updates.get("email") or "").lower() or ""
        if updates["email"]:
            dup = await db.drivers.find_one(
                {"email": updates["email"], "id": {"$ne": driver_id}}, {"_id": 1})
            if dup:
                raise HTTPException(409, "Un chauffeur avec cet e-mail existe déjà")
    if "internal_number" in updates:
        updates["internal_number"] = (updates.get("internal_number") or "").strip() or None
        if updates["internal_number"]:
            dup = await db.drivers.find_one(
                {"internal_number": updates["internal_number"], "id": {"$ne": driver_id}}, {"_id": 1})
            if dup:
                raise HTTPException(409, "Ce matricule est déjà attribué à un autre chauffeur")
    if "ble_id" in updates:
        from app.ble_engine import normalize_identifier
        norm = normalize_identifier(updates["ble_id"]) if updates.get("ble_id") else None
        if norm:
            dup = await db.drivers.find_one(
                {"ble_id_norm": norm, "id": {"$ne": driver_id}, "active": {"$ne": False}},
                {"_id": 1})
            if dup:
                raise HTTPException(409, "Ce tag BLE est déjà attribué à un autre chauffeur")
        updates["ble_id_norm"] = norm
    if ("first_name" in updates or "last_name" in updates) and "name" not in updates:
        fn = (updates.get("first_name") if "first_name" in updates else driver.get("first_name")) or ""
        ln = (updates.get("last_name") if "last_name" in updates else driver.get("last_name")) or ""
        combined = f"{fn} {ln}".strip()
        if combined:
            updates["name"] = combined
    await db.drivers.update_one({"id": driver_id}, {"$set": updates})
    await log_audit("driver.update", current, {"name": driver.get("name"), "fields": list(updates)})
    if "ble_id" in updates:
        await log_audit(
            "driver.ble_tag_assigned" if updates.get("ble_id") else "driver.ble_tag_removed",
            current, {"driver": driver.get("name"),
                      "tag": updates.get("ble_id") or driver.get("ble_id")})
    if "active" in updates and updates["active"] != driver.get("active", True):
        await log_audit("driver.disabled" if updates["active"] is False else "driver.enabled",
                        current, {"driver": driver.get("name")})
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


async def _find_driver_account(raw, tid: str, driver: dict) -> Optional[dict]:
    """Résout le compte lié : drivers.user_id, sinon users.driver_id, sinon email (rôle driver)."""
    proj = {"_id": 0, "password_hash": 0}
    if driver.get("user_id"):
        u = await raw.users.find_one({"id": driver["user_id"], "tenant_id": tid}, proj)
        if u:
            return u
    u = await raw.users.find_one({"driver_id": driver["id"], "tenant_id": tid}, proj)
    if u:
        return u
    if driver.get("email"):
        return await raw.users.find_one(
            {"email": driver["email"], "tenant_id": tid, "role": "driver"}, proj)
    return None


@router.post("/drivers/{driver_id}/reset-password")
async def reset_driver_password(driver_id: str, current=Depends(require_roles("admin"))):
    """Génère un mot de passe temporaire (affiché UNE SEULE FOIS, jamais loggé,
    jamais relisible) et force le changement à la prochaine connexion."""
    tid = _tenant_or_400()
    db = get_db()
    raw = get_raw_db()
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Chauffeur introuvable")
    target = await _find_driver_account(raw, tid, driver)
    if not target:
        raise HTTPException(400, "Ce chauffeur n'a pas de compte lié")
    temp = secrets.token_urlsafe(9)
    await raw.users.update_one(
        {"id": target["id"]},
        {"$set": {"password_hash": hash_password(temp), "must_change_password": True}})
    await raw.login_attempts.delete_many({"identifier": target["email"]})
    await log_audit("driver.password_reset", current,
                    {"driver": driver.get("name"), "email": target["email"]})
    return {"temp_password": temp, "email": target["email"], "must_change_password": True}


OPEN_SESSION_STATUSES = ["open", "automatic", "pending", "manual", "confirmed", "ending"]
AUDIT_EVENT_ACTIONS = [
    "driver_claim", "driver_change", "driver_session_closed", "amend_session",
    "resolve_conflict", "driver.create", "driver.update", "driver.grant_access",
    "driver.password_reset", "driver.ble_tag_assigned", "driver.ble_tag_removed",
    "driver.disabled", "driver.enabled", "auth.login",
]


@router.get("/drivers/{driver_id}/overview")
async def driver_overview(driver_id: str, current=Depends(require_roles("admin", "manager"))):
    """Fiche admin chauffeur : identité, compte, méthodes d'identification,
    session actuelle, historique sessions + événements. Aucune donnée inventée."""
    tid = _tenant_or_400()
    db = get_db()
    raw = get_raw_db()
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(404, "Chauffeur introuvable")

    account = None
    u = await _find_driver_account(raw, tid, driver)
    if u:
        account = {"user_id": u["id"], "email": u["email"],
                   "active": u.get("active", True) is not False,
                   "last_login_at": u.get("last_login_at"),
                   "must_change_password": bool(u.get("must_change_password")),
                   "created_at": u.get("created_at")}

    sessions = await db.driver_sessions.find(
        {"driver_id": driver_id}, {"_id": 0}).sort("started_at", -1).to_list(20)
    veh_ids = list({s["vehicle_id"] for s in sessions})
    veh_rows = await db.vehicles.find(
        {"id": {"$in": veh_ids}}, {"_id": 0, "id": 1, "plate": 1, "model": 1}).to_list(500) if veh_ids else []
    vby = {v["id"]: v for v in veh_rows}
    for s in sessions:
        s["vehicle_plate"] = vby.get(s["vehicle_id"], {}).get("plate")
        s["vehicle_model"] = vby.get(s["vehicle_id"], {}).get("model")
    current_session = next(
        (s for s in sessions
         if s.get("status") in OPEN_SESSION_STATUSES and not s.get("ended_at")), None)

    last_claim = await db.driver_sessions.find_one(
        {"driver_id": driver_id, "confirmed_at": {"$ne": None}},
        {"_id": 0, "confirmed_at": 1}, sort=[("confirmed_at", -1)])
    last_det = await db.ble_detections.find_one(
        {"driver_id": driver_id, "ignored": False},
        {"_id": 0, "ts": 1}, sort=[("ts", -1)])
    proof = await raw.app_state.find_one({"id": f"ble_field_proof_{tid}"}, {"_id": 0})

    ors = [{"driver_id": driver_id}, {"from_driver_id": driver_id},
           {"to_driver_id": driver_id}, {"details.driver": driver.get("name")}]
    if account:
        ors.append({"user_email": account["email"]})
    events = await db.audit_log.find(
        {"$or": ors, "action": {"$in": AUDIT_EVENT_ACTIONS}}, {"_id": 0}).to_list(200)
    for e in events:
        e["event_ts"] = e.get("ts") or e.get("at")
    events.sort(key=lambda e: e.get("event_ts") or "", reverse=True)
    events = events[:15]

    candidates = []
    if account and account.get("last_login_at"):
        candidates.append((account["last_login_at"], "Connexion APP"))
    if last_claim and last_claim.get("confirmed_at"):
        candidates.append((last_claim["confirmed_at"], "Confirmation APP"))
    if last_det and last_det.get("ts"):
        candidates.append((last_det["ts"], "Détection BLE"))
    if sessions:
        candidates.append((sessions[0].get("last_seen") or sessions[0].get("started_at") or "", "Session"))
    last_activity = None
    if candidates:
        ts, kind = max(candidates)
        last_activity = {"ts": ts, "kind": kind}

    return {
        "driver": driver,
        "account": account,
        "identification": {
            "app": {"enabled": bool(account),
                    "account_active": account["active"] if account else None,
                    "last_login_at": account.get("last_login_at") if account else None,
                    "last_claim_at": (last_claim or {}).get("confirmed_at")},
            "ble": {"tag": driver.get("ble_id"),
                    "last_detection_at": (last_det or {}).get("ts"),
                    "field_validated": bool((proof or {}).get("validated")),
                    "field_validation_note": None if (proof or {}).get("validated")
                    else "Validation terrain BLE en attente"},
        },
        "current_session": current_session,
        "sessions": sessions,
        "events": events,
        "last_activity": last_activity,
    }


class InviteIn(BaseModel):
    email: EmailStr


@router.post("/drivers/{driver_id}/invite")
async def invite_driver(driver_id: str, payload: InviteIn, request: Request,
                        background_tasks: BackgroundTasks,
                        current=Depends(require_roles("admin"))):
    """Envoie une invitation par email (lien de création de mot de passe, valable 7 jours).
    Si le SMTP n'est pas configuré, retourne le lien à copier manuellement."""
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

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await raw.invitations.delete_many({"driver_id": driver_id, "used": False})
    rec = {
        "id": str(uuid.uuid4()),
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "driver_id": driver_id, "driver_name": driver.get("name"),
        "tenant_id": tid, "email": email,
        "invited_by": current["email"],
        "used": False,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
    }
    await raw.invitations.insert_one(dict(rec))

    base = (os.environ.get("APP_URL") or request.headers.get("origin") or "").rstrip("/")
    invite_url = f"{base}/invitation?token={token}"
    email_sent = False
    if is_smtp_configured():
        tenant = await raw.tenants.find_one({"id": tid}, {"_id": 0, "name": 1})
        background_tasks.add_task(send_invitation_email, email, driver.get("name") or email,
                                  invite_url, (tenant or {}).get("name") or "Logitrak")
        email_sent = True
    await log_audit("driver.invite_sent", current,
                    {"driver": driver.get("name"), "email": email, "email_sent": email_sent})
    return {"invite_url": invite_url, "email_sent": email_sent, "email": email, "expires_days": 7}


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
