import { create } from 'zustand';
import {
  CurrentSession,
  ClaimResult,
  StopResult,
  getCurrentSession,
  setManualMode,
  claimVehicle,
  stopDriving,
} from '@/api/ble';
import { logger } from '@/utils/logger';

type SessionState = {
  session: CurrentSession | null;
  loading: boolean;
  lastFetch: number | null;
  bleEnabled: boolean;
  blePermissionDenied: boolean;
  conflict: boolean;
  submitting: boolean; // garde anti-double-clic pour claim/stop
  refresh: () => Promise<void>;
  setMode: (mode: 'professional' | 'personal') => Promise<boolean>;
  claim: (vehicleId: string) => Promise<ClaimResult | { error: string }>;
  stop: () => Promise<StopResult | { error: string }>;
  setBleEnabled: (v: boolean) => void;
  setBlePermissionDenied: (v: boolean) => void;
};

export const useSessionStore = create<SessionState>((set, get) => ({
  session: null,
  loading: false,
  lastFetch: null,
  bleEnabled: true,
  blePermissionDenied: false,
  conflict: false,
  submitting: false,

  refresh: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const s = await getCurrentSession();
      set({
        session: s,
        loading: false,
        lastFetch: Date.now(),
        conflict: s?.status === 'conflict',
      });
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

  // « Je conduis » — ouvre une session via le backend (source APP). Anti-double-clic.
  claim: async (vehicleId) => {
    if (get().submitting) return { error: 'En cours…' };
    set({ submitting: true });
    try {
      const res = await claimVehicle(vehicleId);
      // On rafraîchit d'abord (source de vérité serveur)...
      await get().refresh();
      // ...puis on applique l'état issu du claim en dernier, pour ne pas écraser
      // un conflit signalé que le refresh (session null) effacerait à tort.
      set({
        session: res.session ?? get().session,
        conflict: res.status === 'conflict' || get().conflict,
        submitting: false,
      });
      return res;
    } catch (e: any) {
      set({ submitting: false });
      const msg = e?.response?.data?.detail || 'Impossible de démarrer la conduite.';
      logger.error('session', 'claim failed', e);
      return { error: msg };
    }
  },

  // « Je m'arrête » — clôture volontaire. Idempotent côté serveur. Anti-double-clic.
  stop: async () => {
    if (get().submitting) return { error: 'En cours…' };
    set({ submitting: true });
    try {
      const res = await stopDriving();
      // Après un stop, la session courante est close/absente : on rafraîchit.
      await get().refresh();
      set({ submitting: false });
      return res;
    } catch (e: any) {
      set({ submitting: false });
      const msg = e?.response?.data?.detail || 'La clôture a échoué. Réessayez.';
      logger.error('session', 'stop failed', e);
      return { error: msg };
    }
  },

  setBleEnabled: (v) => set({ bleEnabled: v }),
  setBlePermissionDenied: (v) => set({ blePermissionDenied: v }),
}));
