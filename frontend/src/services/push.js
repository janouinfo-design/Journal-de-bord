import { Platform } from 'react-native';
import Constants from 'expo-constants';

/**
 * Notifications push Expo.
 * - Chargement paresseux des modules natifs pour éviter les erreurs sur web.
 * - Ne fabrique aucun état : si indisponible, renvoie null + raison.
 */

let Notifications = null;
let Device = null;
let moduleError = null;

try {
  // eslint-disable-next-line global-require
  Notifications = require('expo-notifications');
  // eslint-disable-next-line global-require
  Device = require('expo-device');
} catch (e) {
  moduleError = e;
}

export function isPushSupported() {
  return Platform.OS !== 'web' && !!Notifications && !moduleError;
}

export function configureNotificationHandler() {
  if (!isPushSupported()) return;
  try {
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowBanner: true,
        shouldShowList: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      }),
    });
  } catch (e) {}
}

/**
 * Demande la permission et récupère le jeton push Expo.
 * @returns {Promise<{token: string|null, reason: string|null}>}
 */
export async function getExpoPushToken() {
  if (!isPushSupported()) {
    return {
      token: null,
      reason:
        Platform.OS === 'web'
          ? "Les notifications push ne sont pas disponibles sur le web."
          : "Module de notifications indisponible (build natif requis).",
    };
  }
  try {
    if (Device && !Device.isDevice) {
      return { token: null, reason: 'Les notifications push requièrent un appareil physique.' };
    }
    const { status: existing } = await Notifications.getPermissionsAsync();
    let status = existing;
    if (existing !== 'granted') {
      const req = await Notifications.requestPermissionsAsync();
      status = req.status;
    }
    if (status !== 'granted') {
      return { token: null, reason: 'Autorisation de notifications refusée.' };
    }

    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Logitrak',
        importance: Notifications.AndroidImportance.DEFAULT,
        lightColor: '#1FB6A8',
      });
    }

    const projectId =
      Constants?.expoConfig?.extra?.eas?.projectId ||
      Constants?.easConfig?.projectId;
    const tokenResp = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined
    );
    return { token: tokenResp?.data || null, reason: null };
  } catch (e) {
    return { token: null, reason: e?.message || 'Erreur lors de l’obtention du jeton push.' };
  }
}
