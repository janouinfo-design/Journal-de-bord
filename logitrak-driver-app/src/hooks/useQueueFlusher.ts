import { useEffect } from 'react';
import { AppState } from 'react-native';
import NetInfo from '@react-native-community/netinfo';
import { useQueueStore } from '@/store/queueStore';

const FLUSH_INTERVAL_MS =
  Number(process.env.EXPO_PUBLIC_BLE_BATCH_FLUSH_INTERVAL || 30) * 1000;

/**
 * Periodically flush the BLE detection queue while the app is foregrounded.
 * Also flushes on network reconnect and app resume.
 */
export function useQueueFlusher() {
  const triggerFlush = useQueueStore((s) => s.triggerFlush);
  const refreshSize = useQueueStore((s) => s.refreshSize);

  useEffect(() => {
    refreshSize();

    const interval = setInterval(() => {
      triggerFlush();
    }, FLUSH_INTERVAL_MS);

    const appSub = AppState.addEventListener('change', (state) => {
      if (state === 'active') triggerFlush();
    });

    const netSub = NetInfo.addEventListener((net) => {
      if (net.isConnected && net.isInternetReachable) {
        triggerFlush();
      }
    });

    return () => {
      clearInterval(interval);
      appSub.remove();
      netSub();
    };
  }, [triggerFlush, refreshSize]);
}
