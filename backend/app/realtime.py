"""Tiny in-memory WebSocket broadcaster for the Logitrak realtime channel.

Rooms are keyed by `tenant_id` (mono-tenant for now, but ready for multi).
Messages are JSON objects with shape `{type, data, ts}`. The frontend hook
`useRealtime()` reconnects automatically with exponential backoff.

Message types currently emitted:
- `session_opened`     — new BLE session (driver↔vehicle)
- `session_updated`    — confidence/mode changed
- `conflict_detected`  — 2+ drivers on the same vehicle
- `conflict_resolved`  — admin resolved a conflict
- `kill_switch`        — privacy kill switch fired (echo)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class _Broadcaster:
    def __init__(self):
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def join(self, ws: WebSocket, tenant_id: str = "default") -> None:
        async with self._lock:
            self._rooms.setdefault(tenant_id, set()).add(ws)

    async def leave(self, ws: WebSocket, tenant_id: str = "default") -> None:
        async with self._lock:
            self._rooms.get(tenant_id, set()).discard(ws)

    async def publish(self, msg_type: str, data: dict, tenant_id: str | None = None) -> None:
        if tenant_id is None:
            from app.tenant_context import get_tenant_id
            tenant_id = get_tenant_id() or "default"
        payload = json.dumps({
            "type": msg_type,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, default=str)
        async with self._lock:
            sockets = list(self._rooms.get(tenant_id, set()))
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.debug("broadcast send failed, marking socket dead: %s", e)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._rooms.get(tenant_id, set()).discard(ws)


_broadcaster: Optional[_Broadcaster] = None


def get_broadcaster() -> _Broadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = _Broadcaster()
    return _broadcaster
