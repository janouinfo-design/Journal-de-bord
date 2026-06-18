import { Platform, PermissionsAndroid } from 'react-native';
import * as Device from 'expo-device';
import { logger } from './logger';

export type BlePermissionResult =
  | { granted: true }
  | { granted: false; reason: 'denied' | 'unsupported' | 'unknown' };

/**
 * Request BLE-related runtime permissions.
 * iOS handles BLE permission through Info.plist + system prompt (handled by ble-plx on first scan).
 * Android requires explicit runtime permissions (location + scan + connect).
 */
export async function requestBlePermissions(): Promise<BlePermissionResult> {
  if (Platform.OS === 'ios') {
    // Permission is asked on the first ble-plx call.
    return { granted: true };
  }

  if (Platform.OS !== 'android') {
    return { granted: false, reason: 'unsupported' };
  }

  try {
    const apiLevel = Platform.Version as number;
    const perms: string[] = [];

    if (apiLevel >= 31) {
      perms.push(
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
      );
    } else {
      perms.push(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);
    }

    if (apiLevel >= 33) {
      perms.push(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
    }

    perms.push(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);

    const results = await PermissionsAndroid.requestMultiple(perms as never[]);
    const allGranted = Object.values(results).every(
      (v) => v === PermissionsAndroid.RESULTS.GRANTED,
    );

    logger.debug('permissions', 'BLE permissions result', results);
    return allGranted ? { granted: true } : { granted: false, reason: 'denied' };
  } catch (e) {
    logger.error('permissions', 'BLE permission request failed', e);
    return { granted: false, reason: 'unknown' };
  }
}

export async function isPhysicalDevice(): Promise<boolean> {
  return Boolean(Device.isDevice);
}
