/**
 * Registers iOS/Android interactive notification categories so the user can
 * resolve a BLE conflict directly from the notification (lock screen).
 *
 * Two actions are exposed:
 *  - confirm_driver  ("Je conduisais")
 *  - deny_driver     ("Ce n'était pas moi")
 *
 * The action is handled by `notificationActionHandler` in this file:
 * on receipt, we deep-link to the Driver screen AND post the corresponding
 * `/api/livre/driver/manual-mode` call so the backend acts even if the user
 * never opens the app foreground.
 */
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { logger } from './logger';
import { setManualMode } from '@/api/ble';

const BLE_CONFLICT_CATEGORY = 'BLE_CONFLICT';
const PENDING_ACTIONS_KEY = 'logitrak.pending_actions.v1';

type PendingAction = {
  type: 'driver_confirm' | 'driver_deny';
  ts: number;
  sessionId?: string;
};

export async function registerNotificationCategories() {
  try {
    await Notifications.setNotificationCategoryAsync(BLE_CONFLICT_CATEGORY, [
      {
        identifier: 'confirm_driver',
        buttonTitle: 'Je conduisais',
        options: { opensAppToForeground: false },
      },
      {
        identifier: 'deny_driver',
        buttonTitle: "Ce n'était pas moi",
        options: { opensAppToForeground: false, isDestructive: true },
      },
    ]);
    logger.info('notifications', `category ${BLE_CONFLICT_CATEGORY} registered`);
  } catch (e) {
    logger.warn('notifications', 'setNotificationCategoryAsync failed', e);
  }
}

/**
 * Persist a pending action when the network call fails so we can replay it.
 */
async function enqueuePending(action: PendingAction) {
  try {
    const raw = await AsyncStorage.getItem(PENDING_ACTIONS_KEY);
    const list: PendingAction[] = raw ? JSON.parse(raw) : [];
    list.push(action);
    await AsyncStorage.setItem(PENDING_ACTIONS_KEY, JSON.stringify(list));
    logger.info('notifications', 'enqueued pending action', action);
  } catch (e) {
    logger.warn('notifications', 'enqueuePending failed', e);
  }
}

export async function replayPendingActions(): Promise<number> {
  try {
    const raw = await AsyncStorage.getItem(PENDING_ACTIONS_KEY);
    if (!raw) return 0;
    const list: PendingAction[] = JSON.parse(raw);
    if (!list.length) return 0;
    let replayed = 0;
    const remaining: PendingAction[] = [];
    for (const a of list) {
      try {
        await setManualMode(a.type === 'driver_confirm' ? 'professional' : 'personal');
        replayed += 1;
      } catch (e) {
        remaining.push(a);
      }
    }
    await AsyncStorage.setItem(PENDING_ACTIONS_KEY, JSON.stringify(remaining));
    if (replayed) logger.info('notifications', `replayed ${replayed} pending action(s)`);
    return replayed;
  } catch (e) {
    logger.warn('notifications', 'replayPendingActions failed', e);
    return 0;
  }
}

/**
 * Listener: when the user taps an action button on a BLE notification,
 * fire the corresponding manual-mode call (or enqueue if offline).
 */
export function attachNotificationActionHandler() {
  const sub = Notifications.addNotificationResponseReceivedListener(async (response) => {
    try {
      const actionId = response.actionIdentifier;
      const data = (response.notification.request.content.data ?? {}) as Record<string, unknown>;
      const type = (data.type as string) || (data.event as string) || '';
      if (!type.startsWith('ble.')) return;

      let mode: 'professional' | 'personal' | null = null;
      let kind: PendingAction['type'] | null = null;

      if (actionId === 'confirm_driver') {
        mode = 'professional';
        kind = 'driver_confirm';
      } else if (actionId === 'deny_driver') {
        mode = 'personal';
        kind = 'driver_deny';
      }
      if (!mode || !kind) return;

      try {
        await setManualMode(mode);
        logger.info('notifications', `inline action ${actionId} → ${mode} OK`);
      } catch (e) {
        logger.warn('notifications', `inline action ${actionId} failed; queueing`, e);
        await enqueuePending({
          type: kind,
          ts: Date.now(),
          sessionId: data.session_id as string | undefined,
        });
      }
    } catch (e) {
      logger.warn('notifications', 'response handler error', e);
    }
  });
  return () => sub.remove();
}

export { BLE_CONFLICT_CATEGORY };
