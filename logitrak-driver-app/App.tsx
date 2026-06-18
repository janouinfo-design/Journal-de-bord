import React, { useEffect } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { RootNavigator } from '@/navigation/RootNavigator';
import { useAuthStore } from '@/store/authStore';
import { registerBackgroundTask } from '@/ble/background';
import { registerForPushNotifications } from '@/utils/notifications';
import { logger } from '@/utils/logger';

export default function App() {
  const bootstrap = useAuthStore((s) => s.bootstrap);

  useEffect(() => {
    bootstrap();
    registerBackgroundTask().catch((e) => logger.warn('app', 'background task registration', e));
    registerForPushNotifications().catch((e) =>
      logger.warn('app', 'push notification registration', e),
    );
  }, [bootstrap]);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <RootNavigator />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
