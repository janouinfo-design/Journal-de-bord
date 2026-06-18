"""WebSocket /realtime channel for live identification events."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime import get_broadcaster

router = APIRouter(tags=["realtime"])


@router.websocket("/realtime")
async def realtime_ws(ws: WebSocket):
    """In-memory pub/sub of identification events for the current tenant.

    Auth is done by reading the same `session` cookie used by REST. We accept
    any authenticated user (admin/manager/driver); messages are JSON
    `{type, data, ts}`. The frontend hook handles reconnection.
    """
    from app.auth import get_user_from_request  # local import keeps the cycle out
    try:
        user = await get_user_from_request(ws)
    except Exception:
        user = None
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    broadcaster = get_broadcaster()
    await broadcaster.join(ws, tenant_id="default")
    try:
        await ws.send_text('{"type":"hello","data":{"ok":true},"ts":""}')
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong","data":{},"ts":""}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await broadcaster.leave(ws, tenant_id="default")
