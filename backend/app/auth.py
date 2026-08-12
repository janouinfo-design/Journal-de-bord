"""JWT auth: register, login, me, refresh, logout. Role-based access."""
import os
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from pydantic import BaseModel, EmailStr

JWT_ALGORITHM = "HS256"
ACCESS_TTL_MIN = 60 * 24  # 1 day for convenience
REFRESH_TTL_DAYS = 7
IMP_ACCESS_TTL_MIN = 60  # durée max d'une session d'aperçu « Se connecter comme… »


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str, role: str, extra_claims: dict | None = None,
                        ttl_minutes: int | None = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes or ACCESS_TTL_MIN),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def _set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie(
        "access_token", access, httponly=True, secure=True,
        samesite="none", max_age=ACCESS_TTL_MIN * 60, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh, httponly=True, secure=True,
        samesite="none", max_age=REFRESH_TTL_DAYS * 86400, path="/",
    )


async def get_current_user(request: Request):
    from app.db import get_db
    db = get_db()
    # Bearer (session d'aperçu par onglet) prioritaire sur le cookie
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Type de token invalide")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            raise HTTPException(status_code=401, detail="Utilisateur introuvable")
        # Rôle « Lecture seule » : blocage serveur de toute action d'écriture
        if user.get("role") == "lecture_seule" and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            _p = request.url.path
            if not any(_p.endswith(s) for s in ("/auth/logout", "/auth/refresh", "/auth/impersonate/end")):
                raise HTTPException(status_code=403, detail="Compte en lecture seule — action non autorisée")
        if payload.get("imp"):
            user["impersonated_by"] = {
                "user_id": payload.get("imp_actor_id"),
                "email": payload.get("imp_actor_email"),
                "session_id": payload.get("imp_session_id"),
                "auth_source": payload.get("auth_source"),
            }
        from app.tenant_context import set_current_tenant, NO_TENANT
        if user.get("role") == "superadmin":
            set_current_tenant(request.headers.get("X-Tenant-Id") or NO_TENANT)
        else:
            set_current_tenant(user.get("tenant_id") or "default")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expiré")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide")


async def get_user_from_request(req) -> dict | None:
    """Cookie-based auth helper that also works for FastAPI `WebSocket`
    (which exposes `.cookies` and `.headers` like Request). Returns the
    user dict (without password_hash) or None if unauthenticated."""
    from app.db import get_db
    db = get_db()
    token = req.cookies.get("access_token")
    if not token:
        auth_header = req.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        return None
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return await db.users.find_one(
            {"id": payload["sub"]}, {"_id": 0, "password_hash": 0},
        )
    except Exception:
        return None



def require_roles(*roles):
    async def _dep(user=Depends(get_current_user)):
        if user.get("role") == "superadmin":
            return user
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Accès refusé")
        return user
    return _dep


# ===== Router =====
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "driver"  # admin | manager | driver


@router.post("/login")
async def login(payload: LoginIn, response: Response):
    from app.db import get_db
    db = get_db()
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        from app.audit import log_audit
        await log_audit("auth.login_failed", None, {"email": email})
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    access = create_access_token(user["id"], user["email"], user["role"])
    refresh = create_refresh_token(user["id"])
    _set_auth_cookies(response, access, refresh)
    user.pop("_id", None)
    user.pop("password_hash", None)
    from app.audit import log_audit
    await log_audit("auth.login", user)
    return {"user": user, "access_token": access, "refresh_token": refresh}


class NavixySsoIn(BaseModel):
    session_key: str


SSO_FAIL_CATEGORIES = ("invalid_format", "navixy_rejected", "navixy_timeout",
                       "tenant_unmapped", "tenant_suspended", "internal_error")
_sso_fail_log_buckets: dict = {}


async def _audit_sso_failure(request: Request, category: str, tenant_id: str | None = None):
    """Audit catégorisé des échecs SSO — jamais la clé, catégorie contrôlée,
    tenant seulement s'il a été identifié serveur, max 5 entrées / IP / 10 min."""
    if category not in SSO_FAIL_CATEGORIES:
        category = "internal_error"
    # IP réelle posée par le proxy de confiance (nginx/ingress), sinon IP de connexion
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() if request else ""
    ip = (fwd or (request.client.host if request and request.client else "unknown"))[:64]
    now_ts = datetime.now(timezone.utc).timestamp()
    bucket = _sso_fail_log_buckets.setdefault(ip, [])
    bucket[:] = [t for t in bucket if now_ts - t < 600]
    if len(bucket) >= 5:
        return
    bucket.append(now_ts)
    from app.audit import log_audit
    await log_audit("auth.sso_failed", None, {"category": category}, tenant_id=tenant_id)


@router.post("/navixy-sso")
async def navixy_sso(payload: NavixySsoIn, request: Request, response: Response):
    """SSO iframe Navixy: valide la session_key auprès de l'API Navixy,
    trouve ou crée l'utilisateur local (moindre privilège), puis pose les cookies JWT."""
    import os
    import uuid
    import httpx
    from app.db import get_db

    session_key = payload.session_key.strip()
    if not session_key or len(session_key) < 16:
        await _audit_sso_failure(request, "invalid_format")
        raise HTTPException(status_code=400, detail="Clé de session Navixy manquante ou invalide")

    base_url = os.environ.get("NAVIXY_API_URL", "https://api.navixy.com/v2").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{base_url}/user/get_info", json={"hash": session_key})
    except httpx.TimeoutException:
        await _audit_sso_failure(request, "navixy_timeout")
        raise HTTPException(status_code=502, detail="API Navixy injoignable (délai dépassé)")
    except Exception:
        await _audit_sso_failure(request, "internal_error")
        raise HTTPException(status_code=502, detail="Impossible de contacter l'API Navixy")
    if r.status_code >= 500:
        await _audit_sso_failure(request, "navixy_rejected")
        raise HTTPException(status_code=502, detail="API Navixy indisponible")
    try:
        data = r.json()
    except Exception:
        await _audit_sso_failure(request, "navixy_rejected")
        raise HTTPException(status_code=401, detail="Session Navixy invalide ou expirée")

    if not data.get("success"):
        await _audit_sso_failure(request, "navixy_rejected")
        raise HTTPException(status_code=401, detail="Session Navixy invalide ou expirée")

    info = data.get("user_info", {}) or {}
    email = (info.get("login") or "").strip().lower()
    if not email:
        await _audit_sso_failure(request, "navixy_rejected")
        raise HTTPException(status_code=422, detail="L'utilisateur Navixy n'a pas d'email exploitable")
    name = (info.get("title")
            or " ".join(filter(None, [info.get("first_name"), info.get("last_name")]))
            or email.split("@")[0])

    # Rattachement au client (tenant) via le compte maître Navixy — jamais depuis le navigateur
    master = data.get("master") or {}
    navixy_owner_id = master.get("id") or info.get("id")

    db = get_db()
    tenant = await db.tenants.find_one(
        {"navixy_master_user_id": navixy_owner_id}, {"_id": 0})

    user = await db.users.find_one({"email": email})
    if user:
        ut = await db.tenants.find_one({"id": user.get("tenant_id")}, {"_id": 0, "status": 1})
        if ut and ut.get("status") != "active":
            await _audit_sso_failure(request, "tenant_suspended", tenant_id=user.get("tenant_id"))
            raise HTTPException(status_code=403,
                                detail="Votre entreprise est suspendue. Contactez Logitrak.")
    else:
        if tenant and tenant.get("status") != "active":
            await _audit_sso_failure(request, "tenant_suspended", tenant_id=tenant["id"])
            raise HTTPException(status_code=403,
                                detail="Votre entreprise est suspendue. Contactez Logitrak.")
        if not tenant:
            await _audit_sso_failure(request, "tenant_unmapped")
            raise HTTPException(
                status_code=403,
                detail="Votre entreprise n'est pas encore activée sur le Journal de bord. Contactez Logitrak.")
        # Compte principal Navixy → admin de son entreprise ;
        # nouveau sous-utilisateur → lecture_seule (moindre privilège, promotion par un admin autorisé)
        is_master_account = not master.get("id") or master.get("id") == info.get("id")
        role = "admin" if is_master_account else "lecture_seule"
        user = {
            "id": str(uuid.uuid4()),
            "email": email,
            "name": name,
            "role": role,
            "tenant_id": tenant["id"],
            "password_hash": None,
            "auth_origin": "navixy",
            "navixy_user_id": info.get("id"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(dict(user))
    if not user.get("navixy_user_id") and info.get("id"):
        await db.users.update_one({"id": user["id"]}, {"$set": {"navixy_user_id": info.get("id")}})

    access = create_access_token(user["id"], user["email"], user["role"])
    refresh = create_refresh_token(user["id"])
    _set_auth_cookies(response, access, refresh)
    user.pop("_id", None)
    user.pop("password_hash", None)
    # Dernier accès SSO réussi du client (jamais modifié par le bouton de test superadmin)
    await db.tenants.update_one(
        {"id": user["tenant_id"]},
        {"$set": {"last_sso_at": datetime.now(timezone.utc).isoformat()}})
    from app.audit import log_audit
    await log_audit("auth.sso", user, {"navixy_user_id": info.get("id")},
                    tenant_id=user.get("tenant_id"))
    return {"user": user, "access_token": access, "refresh_token": refresh}


class ImpersonateExchangeIn(BaseModel):
    token: str


@router.post("/impersonate")
async def impersonate_exchange(payload: ImpersonateExchangeIn, request: Request):
    """Échange un token d'aperçu à usage unique contre une session Bearer (par onglet).
    Aucun cookie n'est posé : la session de l'administrateur reste intacte."""
    import hashlib
    from app.db import get_raw_db
    db = get_raw_db()

    th = hashlib.sha256(payload.token.encode()).hexdigest()
    rec = await db.impersonation_tokens.find_one({"token_hash": th})
    now = datetime.now(timezone.utc)
    if not rec:
        raise HTTPException(status_code=401, detail="Lien d'aperçu invalide ou expiré")
    if rec.get("used"):
        await db.impersonation_tokens.update_one({"id": rec["id"]}, {"$inc": {"replay_attempts": 1}})
        raise HTTPException(status_code=401, detail="Lien d'aperçu invalide ou expiré")
    if datetime.fromisoformat(rec["expires_at"]) < now:
        await db.impersonation_tokens.update_one({"id": rec["id"]}, {"$set": {"denied_at": now.isoformat()}})
        raise HTTPException(status_code=401, detail="Lien d'aperçu invalide ou expiré")
    await db.impersonation_tokens.update_one(
        {"id": rec["id"]}, {"$set": {"used": True, "used_at": now.isoformat()}})

    target = await db.users.find_one({"id": rec["target_user_id"]}, {"_id": 0, "password_hash": 0})
    if not target or target.get("role") == "superadmin":
        raise HTTPException(status_code=404, detail="Utilisateur cible introuvable")

    access = create_access_token(
        target["id"], target["email"], target["role"],
        extra_claims={
            "imp": True,
            "imp_actor_id": rec["actor_user_id"],
            "imp_actor_email": rec["actor_email"],
            "imp_session_id": rec["id"],
            "auth_source": rec["auth_source"],
        },
        ttl_minutes=IMP_ACCESS_TTL_MIN)
    from app.audit import log_audit
    await log_audit("user.impersonate_open",
                    {"id": rec["actor_user_id"], "email": rec["actor_email"],
                     "tenant_id": rec.get("tenant_id")},
                    {"target": target["email"], "target_role": target["role"],
                     "ip": request.client.host if request.client else None,
                     "session_id": rec["id"]},
                    tenant_id=rec.get("tenant_id"))
    return {
        "user": target,
        "access_token": access,
        "impersonation": {
            "actor_email": rec["actor_email"],
            "session_id": rec["id"],
            "started_at": now.isoformat(),
        },
    }


@router.post("/impersonate/end")
async def impersonate_end(request: Request, user=Depends(get_current_user)):
    imp = user.get("impersonated_by")
    if imp:
        from app.audit import log_audit
        from app.db import get_raw_db
        await log_audit("user.impersonate_end", user,
                        {"actor": imp.get("email"), "session_id": imp.get("session_id"),
                         "ip": request.client.host if request.client else None})
        if imp.get("session_id"):
            await get_raw_db().impersonation_tokens.update_one(
                {"id": imp["session_id"]},
                {"$set": {"ended_at": datetime.now(timezone.utc).isoformat()}})
    return {"ended": True}


# ===== Invitations chauffeur — liens publics de création de mot de passe =====
@router.get("/invitation/{token}")
async def invitation_info(token: str):
    import hashlib
    from app.db import get_raw_db
    db = get_raw_db()
    th = hashlib.sha256(token.encode()).hexdigest()
    rec = await db.invitations.find_one({"token_hash": th}, {"_id": 0})
    now = datetime.now(timezone.utc)
    if (not rec or rec.get("used")
            or datetime.fromisoformat(rec["expires_at"]) < now):
        raise HTTPException(status_code=404, detail="Invitation invalide ou expirée")
    tenant = await db.tenants.find_one({"id": rec["tenant_id"]}, {"_id": 0, "name": 1})
    return {"driver_name": rec.get("driver_name"), "email": rec["email"],
            "company": (tenant or {}).get("name") or "Logitrak"}


class InvitationAcceptIn(BaseModel):
    password: str


@router.post("/invitation/{token}/accept")
async def invitation_accept(token: str, payload: InvitationAcceptIn, response: Response):
    import hashlib
    import uuid
    from app.db import get_raw_db
    db = get_raw_db()
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caractères")
    th = hashlib.sha256(token.encode()).hexdigest()
    rec = await db.invitations.find_one({"token_hash": th}, {"_id": 0})
    now = datetime.now(timezone.utc)
    if (not rec or rec.get("used")
            or datetime.fromisoformat(rec["expires_at"]) < now):
        raise HTTPException(status_code=404, detail="Invitation invalide ou expirée")
    driver = await db.drivers.find_one({"id": rec["driver_id"], "tenant_id": rec["tenant_id"]}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Chauffeur introuvable")
    if driver.get("user_id"):
        raise HTTPException(status_code=400, detail="Ce chauffeur a déjà un compte actif")
    email = rec["email"].lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400,
                            detail="Un compte existe déjà avec cet email — contactez votre administrateur")
    user = {
        "id": str(uuid.uuid4()), "email": email,
        "name": driver.get("name") or rec.get("driver_name") or email,
        "role": "driver", "tenant_id": rec["tenant_id"], "driver_id": rec["driver_id"],
        "password_hash": hash_password(payload.password),
        "auth_origin": "invitation",
        "created_at": now.isoformat(),
    }
    await db.users.insert_one(dict(user))
    await db.drivers.update_one({"id": rec["driver_id"], "tenant_id": rec["tenant_id"]},
                                {"$set": {"user_id": user["id"], "email": driver.get("email") or email}})
    await db.invitations.update_one({"id": rec["id"]}, {"$set": {"used": True, "used_at": now.isoformat()}})
    user.pop("password_hash", None)
    from app.audit import log_audit
    await log_audit("driver.invite_accepted", user,
                    {"driver": driver.get("name"), "invited_by": rec.get("invited_by")},
                    tenant_id=rec["tenant_id"])
    access = create_access_token(user["id"], user["email"], user["role"])
    refresh = create_refresh_token(user["id"])
    _set_auth_cookies(response, access, refresh)
    return {"user": user, "access_token": access}


@router.post("/register")
async def register(payload: RegisterIn, response: Response, current=Depends(require_roles("admin"))):
    from app.db import get_db
    from app.tenant_context import get_effective_tenant_id
    import uuid
    db = get_db()
    tenant_id = get_effective_tenant_id()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Sélectionnez d'abord un client")
    if payload.role not in ("admin", "manager", "driver", "lecture_seule"):
        raise HTTPException(status_code=400, detail="Rôle invalide (admin, manager, driver, lecture_seule)")
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": payload.name,
        "role": payload.role,
        "tenant_id": tenant_id,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    user.pop("_id", None)
    user.pop("password_hash", None)
    from app.audit import log_audit
    await log_audit("user.create", current, {"email": email, "role": payload.role})
    return {"user": user}


@router.post("/logout")
async def logout(response: Response, request: Request):
    """Logout: clear cookies and best-effort revoke the current push token."""
    # Best-effort: deactivate any push token bound to this access token's user
    from app.db import get_db
    try:
        token = request.cookies.get("access_token") or ""
        if not token:
            ah = request.headers.get("Authorization", "")
            if ah.startswith("Bearer "):
                token = ah[7:]
        if token:
            payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM],
                                 options={"verify_exp": False})
            uid = payload.get("sub")
            if uid:
                db = get_db()
                await db.push_tokens.update_many(
                    {"user_id": uid},
                    {"$set": {"active": False,
                              "deactivated_at": datetime.now(timezone.utc).isoformat()}},
                )
    except Exception:
        pass
    response.delete_cookie("access_token", path="/", samesite="none", secure=True)
    response.delete_cookie("refresh_token", path="/", samesite="none", secure=True)
    return {"ok": True}


class RefreshIn(BaseModel):
    refresh_token: str | None = None


@router.post("/refresh")
async def refresh(payload: RefreshIn, request: Request, response: Response):
    """Issue a new access token (and rotate the refresh token).

    Accepts the refresh token from either:
    - cookie `refresh_token` (web PWA)
    - JSON body `{refresh_token}` (native Expo app)

    Returns JSON `{access_token, refresh_token, user}` and refreshes cookies.
    """
    from app.db import get_db
    db = get_db()

    token = (payload.refresh_token if payload else None) or request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token manquant")
    try:
        decoded = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expiré")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Refresh token invalide")

    if decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Type de token invalide")

    user = await db.users.find_one({"id": decoded["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    new_access = create_access_token(user["id"], user["email"], user["role"])
    new_refresh = create_refresh_token(user["id"])
    _set_auth_cookies(response, new_access, new_refresh)
    return {"user": user, "access_token": new_access, "refresh_token": new_refresh}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {"user": user}


@router.get("/users")
async def list_users(current=Depends(require_roles("admin"))):
    """List all registered users (admin only).

    Used by the notification preferences panel to target a specific user
    when sending a test notification, and by any future admin user-management UI.
    Excludes the password hash from the response.
    """
    from app.db import get_db
    from app.tenant_context import get_effective_tenant_id
    db = get_db()
    q = {}
    tid = get_effective_tenant_id() if current.get("role") == "superadmin" else (current.get("tenant_id") or "default")
    if tid:
        q["tenant_id"] = tid
    rows = await db.users.find(
        q, {"_id": 0, "password_hash": 0},
    ).to_list(1000)
    return rows


async def seed_admin():
    from app.db import get_db
    import uuid
    db = get_db()

    accounts = [
        (os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"], "Administrateur", "admin"),
        (os.environ["MANAGER_EMAIL"], os.environ["MANAGER_PASSWORD"], "Gestionnaire Flotte", "manager"),
        (os.environ["DRIVER_EMAIL"], os.environ["DRIVER_PASSWORD"], "Jean Dupont", "driver"),
    ]
    for email, password, name, role in accounts:
        email = email.lower()
        existing = await db.users.find_one({"email": email})
        if existing is None:
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "email": email,
                "name": name,
                "role": role,
                "tenant_id": "default",
                "password_hash": hash_password(password),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        elif not verify_password(password, existing["password_hash"]):
            await db.users.update_one(
                {"email": email},
                {"$set": {"password_hash": hash_password(password)}},
            )
