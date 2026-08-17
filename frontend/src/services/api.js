import { API_URL, ENDPOINTS } from './config';
import { getToken } from './storage';

/**
 * Client API Logitrak.
 * - Utilise fetch (compatible web + natif).
 * - Ajoute automatiquement le Bearer JWT.
 * - Normalise les erreurs en messages français exploitables par l'UI.
 * - Ne fabrique JAMAIS de données : en cas d'échec, l'erreur remonte telle quelle.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'error', payload = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

function messageFromStatus(status, detail) {
  if (detail && typeof detail === 'string') return detail;
  switch (status) {
    case 0:
      return 'Impossible de joindre le serveur. Vérifiez votre connexion internet.';
    case 400:
      return 'Requête invalide.';
    case 401:
      return 'Session expirée ou identifiants invalides.';
    case 403:
      return "Accès refusé : vous n'avez pas les droits nécessaires.";
    case 404:
      return 'Ressource introuvable.';
    case 405:
      return 'Méthode non autorisée.';
    case 422:
      return 'Données invalides.';
    case 429:
      return 'Trop de requêtes. Réessayez dans un instant.';
    case 500:
    case 502:
    case 503:
      return 'Le serveur Logitrak est momentanément indisponible.';
    default:
      return 'Une erreur est survenue.';
  }
}

async function request(path, { method = 'GET', body, token, timeout = 15000, auth = true } = {}) {
  const url = `${API_URL}${path}`;
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let authToken = token;
  if (auth && !authToken) authToken = await getToken();
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  let resp;
  try {
    resp = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    const aborted = e?.name === 'AbortError';
    throw new ApiError(
      aborted ? 'Délai d’attente dépassé. Le serveur ne répond pas.' : messageFromStatus(0),
      { status: 0, code: aborted ? 'timeout' : 'network' }
    );
  }
  clearTimeout(timer);

  let data = null;
  const text = await resp.text();
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = text; }
  }

  if (!resp.ok) {
    const detail =
      (data && typeof data === 'object' && (data.detail || data.message || data.error)) ||
      (typeof data === 'string' ? data : null);
    const detailStr = Array.isArray(detail)
      ? detail.map((d) => d?.msg || d).join(', ')
      : detail;
    throw new ApiError(messageFromStatus(resp.status, detailStr), {
      status: resp.status,
      code: resp.status === 401 ? 'unauthorized' : 'http_error',
      payload: data,
    });
  }

  return data;
}

// --- Auth ---
export async function login(email, password) {
  const data = await request(ENDPOINTS.login, {
    method: 'POST',
    auth: false,
    body: { email, password },
  });
  // Le backend renvoie un JWT ; le nom du champ peut varier.
  const token =
    data?.access_token || data?.token || data?.jwt || data?.accessToken || null;
  if (!token) {
    throw new ApiError('Réponse de connexion inattendue (aucun jeton reçu).', {
      status: 200,
      code: 'no_token',
      payload: data,
    });
  }
  return { token, raw: data };
}

// --- Session courante du chauffeur ---
export async function getCurrentSession(token) {
  return request(ENDPOINTS.currentSession, { token });
}

// --- Tags BLE de la flotte ---
export async function getFleetTags(token) {
  return request(ENDPOINTS.fleetTags, { token });
}

// --- Envoi d'une détection BLE réelle ---
export async function postBleDetection(detection, token) {
  return request(ENDPOINTS.bleDetections, { method: 'POST', body: detection, token });
}

// --- Bascule manuelle PRO / PRIVÉ ---
export async function setManualMode(mode, token) {
  return request(ENDPOINTS.manualMode, { method: 'POST', body: { mode }, token });
}

// --- Enregistrement du jeton push Expo ---
export async function registerPushToken(expoPushToken, token) {
  return request(ENDPOINTS.pushToken, {
    method: 'POST',
    body: { expo_push_token: expoPushToken, platform: 'expo' },
    token,
  });
}

/** Décode (sans vérifier) le payload d'un JWT pour affichage. */
export function decodeJwt(token) {
  try {
    const part = token.split('.')[1];
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const pad = b64.length % 4 ? '='.repeat(4 - (b64.length % 4)) : '';
    const json = decodeURIComponent(
      atob(b64 + pad)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(json);
  } catch (e) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Diagnostic de connexion (aide au dépannage — n'affiche que des données réelles).
// ---------------------------------------------------------------------------

/** Vérifie la joignabilité de l'API (racine). */
export async function pingApi() {
  const started = Date.now();
  try {
    const resp = await fetch(`${API_URL}/`, { method: 'GET' });
    const ms = Date.now() - started;
    return { reachable: true, status: resp.status, ms, url: `${API_URL}/` };
  } catch (e) {
    return {
      reachable: false,
      status: 0,
      ms: Date.now() - started,
      url: `${API_URL}/`,
      error: e?.message || 'inconnue',
    };
  }
}

/**
 * Teste l'endpoint de login et renvoie la réponse BRUTE réelle du serveur,
 * sans interprétation ni masquage. Sert à diagnostiquer un refus d'identifiants.
 */
export async function diagnoseLogin(email, password) {
  const url = `${API_URL}${ENDPOINTS.login}`;
  const started = Date.now();
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const ms = Date.now() - started;
    const text = await resp.text();
    let detail = text;
    try {
      const j = JSON.parse(text);
      detail = typeof j?.detail === 'string' ? j.detail : JSON.stringify(j).slice(0, 300);
    } catch (e) {}
    return { status: resp.status, ok: resp.ok, detail, ms, url };
  } catch (e) {
    return { status: 0, ok: false, detail: e?.message || 'réseau', ms: Date.now() - started, url };
  }
}

