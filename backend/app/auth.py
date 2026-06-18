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


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TTL_MIN),
        "type": "access",
    }
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
        "access_token", access, httponly=True, secure=False,
        samesite="lax", max_age=ACCESS_TTL_MIN * 60, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh, httponly=True, secure=False,
        samesite="lax", max_age=REFRESH_TTL_DAYS * 86400, path="/",
    )


async def get_current_user(request: Request):
    from app.db import get_db
    db = get_db()
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Type de token invalide")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            raise HTTPException(status_code=401, detail="Utilisateur introuvable")
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
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    access = create_access_token(user["id"], user["email"], user["role"])
    refresh = create_refresh_token(user["id"])
    _set_auth_cookies(response, access, refresh)
    user.pop("_id", None)
    user.pop("password_hash", None)
    return {"user": user, "access_token": access, "refresh_token": refresh}


@router.post("/register")
async def register(payload: RegisterIn, response: Response, current=Depends(require_roles("admin"))):
    from app.db import get_db
    import uuid
    db = get_db()
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": payload.name,
        "role": payload.role,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    user.pop("_id", None)
    user.pop("password_hash", None)
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
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
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
                "password_hash": hash_password(password),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        elif not verify_password(password, existing["password_hash"]):
            await db.users.update_one(
                {"email": email},
                {"$set": {"password_hash": hash_password(password)}},
            )
