"""Expo Push Notifications — async HTTP client.

Sends batches of Expo push messages to https://exp.host/--/api/v2/push/send,
parses the per-message tickets, and auto-deactivates dead tokens
(`DeviceNotRegistered`, `InvalidCredentials`, `MessageTooBig`, …).

Public surface (used by `notifications_service.py`):
- `send_to_tokens(tokens, title, body, data?, category?, sound?)` → summary dict
- `cleanup_token(token, reason)` → marks `push_tokens.active=False`

The Expo Push endpoint requires NO API key. It is rate-limited to ~600 msg/s.
Receipts ("ok" / errors) come back synchronously in `data[i].status`.

Reference: https://docs.expo.dev/push-notifications/sending-notifications/
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
MAX_BATCH = 100  # Expo accepts up to 100 messages per HTTP call
DEAD_ERRORS = {
    "DeviceNotRegistered",
    "InvalidCredentials",
    "MismatchSenderId",
}

# Optional access token for protected projects (not required by default)
_EXPO_ACCESS_TOKEN = os.environ.get("EXPO_ACCESS_TOKEN")


def _is_expo_token(t: str) -> bool:
    return isinstance(t, str) and (
        t.startswith("ExponentPushToken[") or t.startswith("ExpoPushToken[")
    )


async def cleanup_token(token: str, reason: str = "expo_error") -> None:
    """Soft-deactivate an Expo token; used when Expo reports it as dead."""
    from app.db import get_db
    try:
        db = get_db()
        await db.push_tokens.update_many(
            {"token": token},
            {"$set": {
                "active": False,
                "deactivated_at": datetime.now(timezone.utc).isoformat(),
                "deactivated_reason": reason,
            }},
        )
        logger.info("Push token deactivated (%s): %s", reason, token[-12:])
    except Exception as e:
        logger.warning("cleanup_token failed: %s", e)


async def _send_batch(
    client: httpx.AsyncClient, messages: list[dict],
) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
    }
    if _EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {_EXPO_ACCESS_TOKEN}"

    try:
        resp = await client.post(EXPO_PUSH_URL, json=messages, headers=headers, timeout=20.0)
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as e:
        logger.warning("Expo push HTTP error: %s", e)
        return [{"status": "error", "message": str(e)} for _ in messages]
    except Exception as e:
        logger.warning("Expo push send failed: %s", e)
        return [{"status": "error", "message": str(e)} for _ in messages]

    data = body.get("data")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        # Top-level errors (e.g. malformed payload)
        return [{"status": "error", "message": str(body)} for _ in messages]
    return data


async def send_to_tokens(
    tokens: list[str],
    title: str,
    body: str,
    *,
    data: dict[str, Any] | None = None,
    category: str | None = None,
    sound: str | None = "default",
    priority: str = "high",
    channel_id: str = "default",
) -> dict[str, Any]:
    """Send a single notification to many Expo push tokens.

    Returns `{ok, sent, failed, dead_tokens, results}`.
    Dead tokens are deactivated in the DB before returning.
    """
    valid = [t for t in (tokens or []) if _is_expo_token(t)]
    if not valid:
        return {"ok": True, "sent": 0, "failed": 0, "dead_tokens": [], "results": []}

    base_payload = {
        "title": title,
        "body": body,
        "data": data or {},
        "priority": priority,
        "channelId": channel_id,
    }
    if sound:
        base_payload["sound"] = sound
    if category:
        base_payload["categoryId"] = category  # iOS interactive notifications

    # Build per-token messages
    messages = [{**base_payload, "to": t} for t in valid]

    sent = 0
    failed = 0
    dead: list[str] = []
    all_results: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        # Chunk into batches of MAX_BATCH
        for i in range(0, len(messages), MAX_BATCH):
            chunk = messages[i:i + MAX_BATCH]
            chunk_tokens = valid[i:i + MAX_BATCH]
            tickets = await _send_batch(client, chunk)

            for token, ticket in zip(chunk_tokens, tickets):
                status = ticket.get("status")
                all_results.append({"token": token[-12:], **ticket})
                if status == "ok":
                    sent += 1
                else:
                    failed += 1
                    err = (ticket.get("details") or {}).get("error") or ticket.get("message")
                    if err in DEAD_ERRORS or err == "DeviceNotRegistered":
                        dead.append(token)

    # Deactivate dead tokens (best-effort, concurrent)
    if dead:
        await asyncio.gather(
            *(cleanup_token(t, reason="expo_dead") for t in dead),
            return_exceptions=True,
        )

    return {
        "ok": failed == 0,
        "sent": sent,
        "failed": failed,
        "dead_tokens": [t[-12:] for t in dead],
        "results": all_results,
    }
