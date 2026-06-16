"""Thin async client for Navixy User API (api.navixy.com/v2).

Authentication uses session `hash` (32-char hex). Configure via env:
- NAVIXY_API_URL (default https://api.navixy.com/v2)
- NAVIXY_HASH

All methods raise NavixyError on non-success responses.
"""
import os
from typing import Any
import httpx


class NavixyError(Exception):
    pass


def _base_url() -> str:
    return os.environ.get("NAVIXY_API_URL", "https://api.navixy.com/v2").rstrip("/")


def _hash() -> str:
    h = os.environ.get("NAVIXY_HASH", "").strip()
    if not h:
        raise NavixyError("NAVIXY_HASH non configuré dans .env")
    return h


def is_configured() -> bool:
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
