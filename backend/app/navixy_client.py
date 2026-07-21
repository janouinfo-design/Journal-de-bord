"""Thin async client for Navixy User API (api.navixy.com/v2).

Authentication uses session `hash` (32-char hex). Configure via env:
- NAVIXY_API_URL (default https://api.navixy.com/v2)
- NAVIXY_HASH

All methods raise NavixyError on non-success responses.
"""
import os
from typing import Any, Optional
import httpx


class NavixyError(Exception):
    pass


def _base_url() -> str:
    from app.tenant_context import get_tenant_doc
    t = get_tenant_doc()
    if t and t.get("navixy_api_url"):
        return t["navixy_api_url"].rstrip("/")
    return os.environ.get("NAVIXY_API_URL", "https://api.navixy.com/v2").rstrip("/")


def _hash() -> str:
    from app.tenant_context import get_tenant_doc
    t = get_tenant_doc()
    if t and t.get("navixy_hash"):
        return t["navixy_hash"]
    h = os.environ.get("NAVIXY_HASH", "").strip()
    if not h:
        raise NavixyError("Clé d'intégration LOGITRAK non configurée")
    return h


def is_configured() -> bool:
    from app.tenant_context import get_tenant_doc, get_tenant_id
    if get_tenant_id():
        t = get_tenant_doc()
        return bool(t and t.get("navixy_hash"))
    return bool(os.environ.get("NAVIXY_HASH", "").strip())


async def _post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    payload = {"hash": _hash(), **payload}
    r = await client.post(f"{_base_url()}/{path.lstrip('/')}",
                          json=payload, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise NavixyError(f"Navixy {path}: {data.get('status', {}).get('description', data)}")
    return data


async def get_user_info() -> dict:
    async with httpx.AsyncClient() as c:
        return await _post(c, "user/get_info", {})


async def list_trackers() -> list[dict]:
    async with httpx.AsyncClient() as c:
        data = await _post(c, "tracker/list", {})
    return data.get("list", [])


async def list_employees() -> list[dict]:
    async with httpx.AsyncClient() as c:
        data = await _post(c, "employee/list", {})
    return data.get("list", [])


async def list_zones() -> list[dict]:
    async with httpx.AsyncClient() as c:
        data = await _post(c, "zone/list", {})
    return data.get("list", [])


async def list_tracks(tracker_id: int, date_from: str, date_to: str) -> dict:
    """`from` / `to` format: 'YYYY-MM-DD HH:MM:SS' (server timezone)."""
    async with httpx.AsyncClient() as c:
        return await _post(c, "track/list", {
            "tracker_id": tracker_id, "from": date_from, "to": date_to,
        })


async def read_track_points(tracker_id: int, date_from: str, date_to: str,
                            track_id: Optional[int] = None,
                            simplify: bool = True, point_limit: int = 500) -> list[dict]:
    """Fetch raw GPS points (`track/read`) for a tracker over a time range.

    `date_from` / `date_to` format: 'YYYY-MM-DD HH:MM:SS' (server timezone).
    Optionally restrict to a specific Navixy track_id. Returns the raw list
    of point dicts (`lat`, `lng`, `get_time`, `speed`, `heading`, ...).
    """
    body: dict = {
        "tracker_id": int(tracker_id),
        "from": date_from,
        "to": date_to,
        "simplify": simplify,
        "point_limit": int(point_limit),
    }
    if track_id is not None:
        body["track_id"] = int(track_id)
    async with httpx.AsyncClient() as c:
        data = await _post(c, "track/read", body)
    return data.get("list") or []


async def list_commands(tracker_id: int) -> list[dict]:
    """List available commands for a given tracker (depends on its model/firmware).

    Each item typically contains: id, name, command_type, description, params...
    See https://navixy.com/docs/navixy-api/user-api/backend-api/resources/tracker/command
    """
    async with httpx.AsyncClient() as c:
        data = await _post(c, "tracker/command/list", {"tracker_id": tracker_id})
    return data.get("list", [])


async def send_raw_command(tracker_id: int, command: str, reliable: bool = True) -> dict:
    """Send a raw protocol command to a tracker via Navixy (Phase 2 — write op).

    Endpoint: `tracker/raw_command/send`. Returns `{success, command_id, ...}`.
    `reliable=True` makes Navixy queue and retry the command until ACK/timeout.

    Caller is responsible for ensuring the device supports this command. The
    enforcer module restricts the call to vehicles classified as 'full'
    compatibility (see `privacy_scan.classify_model`).
    """
    async with httpx.AsyncClient() as c:
        return await _post(c, "tracker/raw_command/send", {
            "tracker_id": int(tracker_id),
            "command": command,
            "reliable": reliable,
        })
