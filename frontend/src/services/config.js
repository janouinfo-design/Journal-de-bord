import Constants from 'expo-constants';
import { Platform } from 'react-native';

// URL de l'API Logitrak « Livre de Bord ».
//
// STRATÉGIE PAR PLATEFORME :
// - NATIF (iOS/Android) : l'app appelle DIRECTEMENT l'API réelle. Le fetch natif
//   n'est pas soumis au CORS -> aucune dépendance à un proxy.
// - WEB (preview de développement) : le navigateur bloque les requêtes cross-origin
//   vers journal.logitrak.ch (CORS). On passe donc par le reverse-proxy transparent
//   de l'environnement (webApiBase injecté depuis REACT_APP_BACKEND_URL via
//   app.config.js) qui relaie tel quel vers l'API réelle. Ce proxy n'ajoute aucune
//   logique métier et ne fabrique aucune donnée.
//
// Priorité : override explicite EXPO_PUBLIC_API_URL -> logique par plateforme.

const PRODUCTION_API = 'https://journal.logitrak.ch';

// Détection robuste du web : Platform.OS peut renvoyer 'unknown' selon le bundle
// react-native-web, on vérifie donc aussi la présence du DOM.
const IS_WEB =
  Platform.OS === 'web' ||
  (typeof document !== 'undefined' && typeof window !== 'undefined');

const EXPLICIT_URL =
  process.env.EXPO_PUBLIC_API_URL ||
  (Constants?.expoConfig?.extra?.apiUrl) ||
  null;

// Base du proxy web, injectée au bundling par app.config.js.
const WEB_PROXY_BASE =
  Constants?.expoConfig?.extra?.webApiBase ||
  process.env.EXPO_PUBLIC_BACKEND_URL ||
  process.env.REACT_APP_BACKEND_URL ||
  null;

function resolveBase() {
  if (EXPLICIT_URL) return EXPLICIT_URL;
  if (IS_WEB && WEB_PROXY_BASE) return WEB_PROXY_BASE;
  return PRODUCTION_API;
}

export const API_BASE = resolveBase().replace(/\/$/, '');
export const API_URL = `${API_BASE}/api`;
export const IS_WEB_PLATFORM = IS_WEB;

// UUID de service BLE à cibler pour le scan (surtout requis par iOS en arrière-plan).
// Vide par défaut : on scanne toutes les balises puis on filtre via /fleet-tags.
// Renseignable via app.config.js -> extra.bleServiceUuids (tableau) ou
// EXPO_PUBLIC_BLE_SERVICE_UUIDS (liste séparée par des virgules).
const rawUuids =
  Constants?.expoConfig?.extra?.bleServiceUuids ||
  (process.env.EXPO_PUBLIC_BLE_SERVICE_UUIDS
    ? process.env.EXPO_PUBLIC_BLE_SERVICE_UUIDS.split(',')
    : null);
export const BLE_SERVICE_UUIDS =
  Array.isArray(rawUuids) && rawUuids.length
    ? rawUuids.map((u) => String(u).trim()).filter(Boolean)
    : null;

// Endpoints connus de l'API Logitrak (Livre de Bord).
export const ENDPOINTS = {
  login: '/auth/login',
  currentSession: '/livre/driver/current-session',
  fleetTags: '/livre/driver/fleet-tags',
  bleDetections: '/livre/ble/detections',
  manualMode: '/livre/driver/manual-mode',
  // Endpoint jeton push (côté backend existant). Ajustable si le chemin réel diffère.
  pushToken: '/livre/driver/push-token',
};

export const PLATFORM = Platform.OS; // 'ios' | 'android' | 'web'
