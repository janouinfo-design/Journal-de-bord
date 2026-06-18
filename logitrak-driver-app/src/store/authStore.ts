import { create } from 'zustand';
import { fetchMe, login as apiLogin, logout as apiLogout, getAccessToken } from '@/api/client';
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
  signIn: (email: string, password: string) => Promise<boolean>;
  signOut: () => Promise<void>;
  bootstrap: () => Promise<void>;
};

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,
  error: null,

  bootstrap: async () => {
    try {
      const token = await getAccessToken();
      if (!token) {
        set({ user: null, loading: false });
        return;
      }
      const me = await fetchMe();
      set({ user: me, loading: false });
    } catch (e) {
      logger.warn('auth', 'bootstrap failed; clearing session', e);
      set({ user: null, loading: false });
    }
  },

  signIn: async (email: string, password: string) => {
    set({ loading: true, error: null });
    try {
      const data = await apiLogin(email, password);
      set({ user: data.user, loading: false });
      return true;
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Identifiants invalides';
      set({ loading: false, error: msg });
      return false;
    }
  },

  signOut: async () => {
    await apiLogout();
    set({ user: null });
  },
}));
