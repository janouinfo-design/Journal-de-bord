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
 * Construit l'URL + options de connexion WS. Le token n'apparaît JAMAIS dans l'URL
 * (logs proxy/serveur) : il est transmis via le header Authorization, supporté
 * nativement par le WebSocket React Native (3e argument non standard web).
 */
export function buildRealtimeConnection(
  apiUrl: string,
  role: 'driver' | 'admin',
  token: string,
): { url: string; options: { headers: { Authorization: string } } } {
  const host = apiUrl.replace(/^https?:\/\//, '');
  const path = role === 'admin' ? '/api/livre/ws/admin' : '/api/livre/realtime';
  return {
    url: `${WS_SCHEME}://${host}${path}`,
    options: { headers: { Authorization: `Bearer ${token}` } },
  };
}

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
        const { url, options } = buildRealtimeConnection(apiUrl, role, token);
        logger.debug('realtime', `connecting ${url}`);

        // React Native accepte (url, protocols, { headers }) — natif iOS/Android.
        const ws = new (WebSocket as any)(url, null, options) as WebSocket;
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
        ws.onclose = (e: any) => {
          setConnected(false);
          wsRef.current = null;
          if (stoppedRef.current) return;
          // 4401 = non autorisé : pas de boucle agressive, on attend directement le plafond.
          const delay = e?.code === 4401 ? 30_000 : backoffRef.current;
          backoffRef.current = Math.min(backoffRef.current * 2, 30_000);
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
