"""Thin re-export of the auth router (kept in `app.auth` for utility helpers).

The router itself is defined in `app/auth.py` because it is co-located with
`hash_password`, `verify_password`, `create_access_token`, `get_current_user`,
`require_roles`, … which are imported by virtually every sub-router. Moving
the router file would create circular import risks for no gain.

This shim exists so the new `app/routes/` package exposes a uniform layout.
"""
from app.auth import router  # noqa: F401

__all__ = ["router"]
