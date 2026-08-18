import { useEffect, useRef, useState } from 'react';
import { getAccessToken, getApiUrl } from '@/api/client';
import { logger } from '@/utils/logger';

export type RealtimeEvent =
  | { type: 'ble.conflict'; session_id: string; vehicle_id?: string; drivers?: string[] }
  | { type: 'ble.resolved'; session_id: string }
  | { type: 'session.update'; payload: Record<string, unknown> }
  | { type: 'kill_switch'; reason?: string };

const WS_SCHEME = process.env.EXPO_PUBLIC_WS_SCHEME || 'wss';

/**
 * Subscribe to the backend WebSocket /api/livre/realtime
 * Auto-reconnects with exponential backoff (1s → 30s).
 */
export function useRealtime(onEvent: (e: RealtimeEvent) => void, role: 'driver' | 'admin' = 'driver') {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1000);
  const stoppedRef = useRef(false);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    stoppedRef.current = false;

    const connect = async () => {
      if (stoppedRef.current) return;
      try {
        const token = await getAccessToken();
        if (!token) {
          // Retry once authenticated.
          setTimeout(connect, 2000);
          return;
        }
        const apiUrl = getApiUrl();
        const host = apiUrl.replace(/^https?:\/\//, '');
        const path = role === 'admin' ? '/api/livre/ws/admin' : '/api/livre/realtime';
        const url = `${WS_SCHEME}://${host}${path}?token=${encodeURIComponent(token)}`;
        logger.debug('realtime', `connecting ${url.replace(token, '***')}`);

        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          backoffRef.current = 1000;
          setConnected(true);
          logger.info('realtime', 'WebSocket connected');
        };
        ws.onmessage = (msg) => {
          try {
            const data = JSON.parse(msg.data) as RealtimeEvent;
            handlerRef.current(data);
          } catch (e) {
            logger.warn('realtime', 'invalid WS payload', e);
          }
        };
        ws.onerror = (e) => {
          logger.warn('realtime', 'WS error', e);
        };
        ws.onclose = () => {
          setConnected(false);
          wsRef.current = null;
          if (stoppedRef.current) return;
          const delay = backoffRef.current;
          backoffRef.current = Math.min(delay * 2, 30_000);
          logger.info('realtime', `WS closed; reconnecting in ${delay}ms`);
          setTimeout(connect, delay);
        };
      } catch (e) {
        logger.error('realtime', 'connect threw', e);
        setTimeout(connect, 5000);
      }
    };

    connect();
    return () => {
      stoppedRef.current = true;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [role]);

  return { connected };
}
