import * as BackgroundFetch from 'expo-background-fetch';
import * as TaskManager from 'expo-task-manager';
import { logger } from '@/utils/logger';
import { flushQueue } from './queue';

export const BACKGROUND_BLE_TASK = 'logitrak-background-ble-task';

/**
 * Background task: flush the offline detections queue to the backend.
 *
 * NOTE: Truly continuous BLE scanning while the app is closed requires native
 * modules (iOS Core Bluetooth state restoration, Android Foreground Service).
 * Phase B (this scaffold) ships a best-effort background flush that runs
 * every ~15 minutes while the app is suspended or backgrounded.
 */
TaskManager.defineTask(BACKGROUND_BLE_TASK, async () => {
  try {
    const sent = await flushQueue();
    logger.info('background', `background flush sent ${sent} detections`);
    return sent > 0
      ? BackgroundFetch.BackgroundFetchResult.NewData
      : BackgroundFetch.BackgroundFetchResult.NoData;
  } catch (e) {
    logger.error('background', 'background task failed', e);
    return BackgroundFetch.BackgroundFetchResult.Failed;
  }
});

export async function registerBackgroundTask() {
  const isRegistered = await TaskManager.isTaskRegisteredAsync(BACKGROUND_BLE_TASK);
  if (isRegistered) {
    logger.debug('background', 'task already registered');
    return;
  }
  try {
    await BackgroundFetch.registerTaskAsync(BACKGROUND_BLE_TASK, {
      minimumInterval: 15 * 60, // 15 min (iOS may stretch this)
      stopOnTerminate: false,
      startOnBoot: true,
    });
    logger.info('background', 'background fetch task registered');
  } catch (e) {
    logger.warn('background', 'registerTaskAsync failed', e);
  }
}

export async function unregisterBackgroundTask() {
  try {
    await BackgroundFetch.unregisterTaskAsync(BACKGROUND_BLE_TASK);
  } catch (e) {
    logger.warn('background', 'unregisterTaskAsync failed', e);
  }
}
