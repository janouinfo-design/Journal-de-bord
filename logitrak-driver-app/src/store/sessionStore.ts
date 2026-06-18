import { create } from 'zustand';
import { CurrentSession, getCurrentSession, setManualMode } from '@/api/ble';
import { logger } from '@/utils/logger';

type SessionState = {
  session: CurrentSession | null;
  loading: boolean;
  lastFetch: number | null;
  bleEnabled: boolean;
  blePermissionDenied: boolean;
  refresh: () => Promise<void>;
  setMode: (mode: 'professional' | 'personal') => Promise<boolean>;
  setBleEnabled: (v: boolean) => void;
  setBlePermissionDenied: (v: boolean) => void;
};

export const useSessionStore = create<SessionState>((set, get) => ({
  session: null,
  loading: false,
  lastFetch: null,
  bleEnabled: true,
  blePermissionDenied: false,

  refresh: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const s = await getCurrentSession();
      set({ session: s, loading: false, lastFetch: Date.now() });
    } catch (e) {
      logger.warn('session', 'refresh failed', e);
      set({ loading: false });
    }
  },

  setMode: async (mode) => {
    try {
      await setManualMode(mode);
      await get().refresh();
      return true;
    } catch (e) {
      logger.error('session', 'setMode failed', e);
      return false;
    }
  },

  setBleEnabled: (v) => set({ bleEnabled: v }),
  setBlePermissionDenied: (v) => set({ blePermissionDenied: v }),
}));
