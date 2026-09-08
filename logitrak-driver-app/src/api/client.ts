import axios, { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import Constants from 'expo-constants';
import { logger } from '@/utils/logger';
import * as storage from '@/utils/storage';

const API_URL =
  process.env.EXPO_PUBLIC_API_URL ||
  (Constants.expoConfig?.extra as Record<string, string> | undefined)?.apiUrl ||
  'http://localhost:8001';

const ACCESS_KEY = 'logitrak.access_token';
const REFRESH_KEY = 'logitrak.refresh_token';

export async function setTokens(access: string | null, refresh: string | null) {
  if (access) {
    await storage.setItemAsync(ACCESS_KEY, access);
  } else {
    await storage.deleteItemAsync(ACCESS_KEY);
  }
  if (refresh) {
    await storage.setItemAsync(REFRESH_KEY, refresh);
  } else {
    await storage.deleteItemAsync(REFRESH_KEY);
  }
}

export async function getAccessToken(): Promise<string | null> {
  return storage.getItemAsync(ACCESS_KEY);
}

export async function getRefreshToken(): Promise<string | null> {
  return storage.getItemAsync(REFRESH_KEY);
}

export function getApiUrl(): string {
  return API_URL;
}

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const refresh = await getRefreshToken();
      if (!refresh) return null;
      const { data } = await axios.post(
        `${API_URL}/api/auth/refresh`,
        { refresh_token: refresh },
        { timeout: 10_000 },
      );
      const access = data?.access_token as string | undefined;
      const newRefresh = (data?.refresh_token as string | undefined) ?? refresh;
      if (access) {
        await setTokens(access, newRefresh);
        return access;
      }
      return null;
    } catch (e) {
      logger.warn('api', 'Refresh token failed; logging out', e);
      await setTokens(null, null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

apiClient.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  const token = await getAccessToken();
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes('/auth/')
    ) {
      original._retry = true;
      const newAccess = await refreshAccessToken();
      if (newAccess) {
        original.headers!.Authorization = `Bearer ${newAccess}`;
        return apiClient.request(original);
      }
    }
    return Promise.reject(error);
  },
);

export type LoginResponse = {
  access_token: string;
  refresh_token?: string;
  user: { id: string; email: string; role: string; name?: string; full_name?: string };
};

export async function login(email: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>('/api/auth/login', { email, password });
  await setTokens(data.access_token, data.refresh_token ?? null);
  return data;
}

export async function logout() {
  try {
    await apiClient.post('/api/auth/logout');
  } catch {
    /* ignore */
  }
  await setTokens(null, null);
}

// /api/auth/me renvoie {user{...}} — on dé-emballe pour renvoyer l'objet user.
export async function fetchMe() {
  const { data } = await apiClient.get('/api/auth/me');
  return data?.user ?? data;
}

// Changement de mot de passe (utilisé par le flux must_change_password et le profil).
export async function changePassword(currentPassword: string, newPassword: string) {
  const { data } = await apiClient.post('/api/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
  return data;
}
