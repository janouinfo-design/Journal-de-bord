/* useRealtime — connects to /api/livre/realtime WebSocket with exponential
 * back-off reconnection. Subscribers receive every message in the tenant
 * room as `{type, data, ts}`.
 */
import { useEffect, useRef, useState } from "react";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

function wsUrl() {
  const base = BACKEND.replace(/^http/i, "ws");
  return `${base.replace(/\/$/, "")}/api/livre/realtime`;
}

export function useRealtime(onMessage) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const cbRef = useRef(onMessage);
  cbRef.current = onMessage;

  useEffect(() => {
    let cancelled = false;
    let pingInterval = null;

    const connect = () => {
      if (cancelled) return;
      try {
        const ws = new WebSocket(wsUrl());
        wsRef.current = ws;

        ws.onopen = () => {
          attemptRef.current = 0;
          setConnected(true);
          pingInterval = setInterval(() => {
            try { ws.send("ping"); } catch (e) {
              console.debug("[useRealtime] ping send failed:", e);
            }
          }, 25000);
        };
        ws.onmessage = (e) => {
          try {
            const payload = JSON.parse(e.data);
            if (payload?.type && payload.type !== "pong" && payload.type !== "hello") {
              cbRef.current?.(payload);
            }
          } catch (err) {
            console.debug("[useRealtime] malformed payload ignored:", err);
          }
        };
        ws.onerror = (e) => {
          console.debug("[useRealtime] socket error; reconnecting via onclose:", e);
        };
        ws.onclose = () => {
          setConnected(false);
          if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
          if (cancelled) return;
          const attempt = ++attemptRef.current;
          const delay = Math.min(30000, 500 * Math.pow(2, Math.min(attempt, 6))); // cap 30s
          setTimeout(connect, delay);
        };
      } catch (e) {
        console.warn("[useRealtime] WebSocket constructor failed:", e);
        const attempt = ++attemptRef.current;
        const delay = Math.min(30000, 500 * Math.pow(2, Math.min(attempt, 6)));
        setTimeout(connect, delay);
      }
    };

    connect();
    return () => {
      cancelled = true;
      if (pingInterval) clearInterval(pingInterval);
      try { wsRef.current?.close(); } catch (e) {
        console.debug("[useRealtime] close on unmount failed:", e);
      }
    };
  }, []);

  return { connected };
}
