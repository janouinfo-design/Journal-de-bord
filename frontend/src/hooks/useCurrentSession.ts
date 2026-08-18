import { useEffect } from 'react';
import { AppState } from 'react-native';
import { useSessionStore } from '@/store/sessionStore';

const POLL_INTERVAL_MS = 10_000;

/**
 * Foreground-poll the current driver session and refresh on app focus.
 */
export function useCurrentSessionPoll() {
  const refresh = useSessionStore((s) => s.refresh);

  useEffect(() => {
    let active = true;
    let interval: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (interval) return;
      refresh();
      interval = setInterval(() => {
        if (active) refresh();
      }, POLL_INTERVAL_MS);
    };
    const stop = () => {
      if (interval) clearInterval(interval);
      interval = null;
    };

    start();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') start();
      else stop();
    });

    return () => {
      active = false;
      stop();
      sub.remove();
    };
  }, [refresh]);
}
