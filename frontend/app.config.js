// Configuration Expo dynamique.
// app.config.js s'exécute côté Node au moment du bundling : process.env y est
// disponible. On y injecte l'URL du proxy web (REACT_APP_BACKEND_URL) dans
// `extra.webApiBase`, ce qui la rend accessible dans l'app via
// Constants.expoConfig.extra — y compris sur le bundle web où process.env
// n'est pas fiable.

const WEB_API_BASE =
  process.env.REACT_APP_BACKEND_URL ||
  process.env.EXPO_PUBLIC_BACKEND_URL ||
  null;

export default ({ config }) => ({
  ...config,
  name: 'Logitrak Chauffeur',
  slug: 'logitrak-chauffeur',
  version: '1.0.0',
  orientation: 'portrait',
  scheme: 'logitrak',
  userInterfaceStyle: 'dark',
  newArchEnabled: true,
  splash: {
    backgroundColor: '#0B0F14',
  },
  assetBundlePatterns: ['**/*'],
  ios: {
    supportsTablet: true,
    bundleIdentifier: 'ch.logitrak.chauffeur',
    infoPlist: {
      NSBluetoothAlwaysUsageDescription:
        'Logitrak utilise le Bluetooth pour détecter automatiquement le véhicule associé à votre trajet via les balises BLE de la flotte.',
      NSBluetoothPeripheralUsageDescription:
        'Logitrak utilise le Bluetooth pour détecter les balises BLE des véhicules.',
      UIBackgroundModes: ['bluetooth-central', 'fetch', 'remote-notification'],
    },
  },
  android: {
    package: 'ch.logitrak.chauffeur',
    adaptiveIcon: {
      backgroundColor: '#0B0F14',
    },
    permissions: [
      'android.permission.BLUETOOTH',
      'android.permission.BLUETOOTH_ADMIN',
      'android.permission.BLUETOOTH_SCAN',
      'android.permission.BLUETOOTH_CONNECT',
      'android.permission.ACCESS_COARSE_LOCATION',
      'android.permission.ACCESS_FINE_LOCATION',
      'android.permission.FOREGROUND_SERVICE',
      'android.permission.POST_NOTIFICATIONS',
    ],
  },
  web: {
    bundler: 'metro',
    favicon: './assets/favicon.png',
  },
  plugins: [
    [
      'react-native-ble-plx',
      {
        isBackgroundEnabled: true,
        modes: ['peripheral', 'central'],
        bluetoothAlwaysPermission:
          'Logitrak utilise le Bluetooth pour détecter automatiquement le véhicule via les balises BLE.',
      },
    ],
    [
      'expo-notifications',
      {
        color: '#1FB6A8',
      },
    ],
  ],
  extra: {
    // URL du reverse-proxy pour le preview web (source : REACT_APP_BACKEND_URL).
    webApiBase: WEB_API_BASE,
    // UUID de service BLE à cibler (recommandé pour le scan iOS en arrière-plan).
    // Vide par défaut : scan de toutes les balises puis filtrage via /fleet-tags.
    // Ex: ['0000feaa-0000-1000-8000-00805f9b34fb']
    bleServiceUuids: process.env.EXPO_PUBLIC_BLE_SERVICE_UUIDS
      ? process.env.EXPO_PUBLIC_BLE_SERVICE_UUIDS.split(',').map((u) => u.trim())
      : [],
    eas: {
      projectId: 'REPLACE_WITH_YOUR_EAS_PROJECT_ID',
    },
  },
});
