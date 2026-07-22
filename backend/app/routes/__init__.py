"""Routes package — aggregates all sub-routers into a single `livre_router`.

Public surface:
- `livre_router`  — APIRouter(prefix="/livre"), aggregates BLE, dashboard,
                    identification, notifications, realtime, reports, settings,
                    misc (bootstrap/navixy/master-data/trips/audit-log).
- `auth_router`   — APIRouter(prefix="/auth"), re-exported from `app.routes.auth`.

Both are mounted under `/api` by `server.py`, preserving exactly the same
public URLs as before the refactoring (no breaking change).
"""
from fastapi import APIRouter

from app.routes import (
    auth as _auth,
    ble as _ble,
    dashboard as _dashboard,
    fines as _fines,
    identification as _identification,
    misc as _misc,
    notifications as _notifications,
    realtime as _realtime,
    reports as _reports,
    settings as _settings,
    team as _team,
)

# Re-export the auth router (kept under /auth — sibling of /livre)
auth_router = _auth.router

# Single livre router that aggregates everything else under /livre
livre_router = APIRouter(prefix="/livre", tags=["livre-de-bord"])
livre_router.include_router(_misc.router)
livre_router.include_router(_settings.router)
livre_router.include_router(_dashboard.router)
livre_router.include_router(_reports.router)
livre_router.include_router(_ble.router)
livre_router.include_router(_realtime.router)
livre_router.include_router(_identification.router)
livre_router.include_router(_notifications.router)
livre_router.include_router(_fines.router)
livre_router.include_router(_team.router)

__all__ = ["auth_router", "livre_router"]
