import { create } from 'zustand';
import { fetchMe, login as apiLogin, logout as apiLogout, getAccessToken } from '@/api/client';
import { getMyProfile } from '@/api/ble';
import { logger } from '@/utils/logger';

export type AuthUser = {
  id: string;
  email: string;
  role: string;
  full_name?: string;
};

type AuthState = {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  mustChangePassword: boolean;
  signIn: (email: string, password: string) => Promise<boolean>;
  signOut: () => Promise<void>;
  bootstrap: () => Promise<void>;
  refreshMustChangePassword: () => Promise<void>;
  clearMustChangePassword: () => void;
};

// Normalise l'utilisateur serveur : le backend renvoie `name`, l'app utilise `full_name`.
function normalizeUser(raw: any): AuthUser | null {
  if (!raw) return null;
  return {
    id: raw.id,
    email: raw.email,
    role: raw.role,
    full_name: raw.full_name || raw.name || undefined,
  };
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  loading: true,
  error: null,
  mustChangePassword: false,

  bootstrap: async () => {
    try {
      const token = await getAccessToken();
      if (!token) {
        set({ user: null, loading: false });
        return;
      }
      const me = await fetchMe();
      set({ user: normalizeUser(me), loading: false });
      // Vérifie must_change_password via le profil chauffeur.
      await get().refreshMustChangePassword();
    } catch (e) {
      logger.warn('auth', 'bootstrap failed; clearing session', e);
      set({ user: null, loading: false });
    }
  },

  signIn: async (email: string, password: string) => {
    set({ loading: true, error: null });
    try {
      const data = await apiLogin(email, password);
      set({ user: normalizeUser(data.user), loading: false });
      await get().refreshMustChangePassword();
      return true;
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Identifiants incorrects ou accès temporairement bloqué';
      set({ loading: false, error: msg });
      return false;
    }
  },

  refreshMustChangePassword: async () => {
    try {
      const profile = await getMyProfile();
      set({ mustChangePassword: Boolean(profile.must_change_password) });
    } catch (e) {
      // Ne bloque pas la session si le profil échoue ; on considère false par prudence.
      logger.warn('auth', 'my-profile check failed', e);
    }
  },

  clearMustChangePassword: () => set({ mustChangePassword: false }),

  signOut: async () => {
    await apiLogout();
    set({ user: null, mustChangePassword: false });
  },
}));
