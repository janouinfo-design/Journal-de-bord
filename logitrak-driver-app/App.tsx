import React, { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { RootNavigator } from '@/navigation/RootNavigator';
import { useAuthStore } from '@/store/authStore';
import { registerBackgroundTask } from '@/ble/background';
import { registerForPushNotifications } from '@/utils/notifications';
import {
  registerNotificationCategories,
  attachNotificationActionHandler,
  replayPendingActions,
} from '@/utils/notificationActions';
import { registerPushToken } from '@/api/ble';
import { logger } from '@/utils/logger';

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    bootstrap();
    registerBackgroundTask().catch((e) => logger.warn('app', 'background task registration', e));
    registerNotificationCategories().catch((e) =>
      logger.warn('app', 'notification categories', e),
    );
    const detach = attachNotificationActionHandler();
    return () => {
      detach?.();
    };
  }, [bootstrap]);

  // Once the user is logged in, register the push token + replay pending actions.
  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const token = await registerForPushNotifications();
        if (token) {
          await registerPushToken(token);
        }
      } catch (e) {
        logger.warn('app', 'push registration failed', e);
      }
      await replayPendingActions();
    })();
  }, [user]);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <RootNavigator />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

