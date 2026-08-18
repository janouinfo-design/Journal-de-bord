import { create } from 'zustand';
import { Trip, TripsResponse, getTrips, classifyTrip } from '@/api/trips';
import { logger } from '@/utils/logger';

type TripsState = {
  trips: Trip[];
  settingsMode?: string;
  loading: boolean;
  error: string | null;
  classifyingId: string | null; // anti-double-clic par trajet
  load: () => Promise<void>;
  refresh: () => Promise<void>;
  classify: (
    tripId: string,
    classification: 'professional' | 'personal',
  ) => Promise<{ ok: boolean; message?: string }>;
};

export const useTripsStore = create<TripsState>((set, get) => ({
  trips: [],
  settingsMode: undefined,
  loading: false,
  error: null,
  classifyingId: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const res: TripsResponse = await getTrips({ limit: 200 });
      set({ trips: res.trips, settingsMode: res.settings_mode, loading: false });
    } catch (e: any) {
      const msg =
        e?.response?.data?.detail ||
        'Impossible de charger vos trajets. Vérifiez votre connexion.';
      logger.warn('trips', 'load failed', e);
      set({ loading: false, error: msg });
    }
  },

  refresh: async () => {
    // Rechargement sans écran de chargement plein (pull-to-refresh gère l'indicateur).
    try {
      const res: TripsResponse = await getTrips({ limit: 200 });
      set({ trips: res.trips, settingsMode: res.settings_mode, error: null });
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Actualisation impossible.';
      set({ error: msg });
    }
  },

  // Classification : on n'affiche JAMAIS un succès avant confirmation serveur.
  classify: async (tripId, classification) => {
    if (get().classifyingId) return { ok: false, message: 'En cours…' };
    set({ classifyingId: tripId });
    try {
      const res = await classifyTrip(tripId, classification);
      if (res?.ok) {
        // Mise à jour locale APRÈS confirmation serveur uniquement.
        set((s) => ({
          classifyingId: null,
          trips: s.trips.map((t) =>
            t.id === tripId ? { ...t, classification, auto_classified: false } : t,
          ),
        }));
        return { ok: true };
      }
      set({ classifyingId: null });
      return { ok: false, message: 'Réponse serveur inattendue.' };
    } catch (e: any) {
      set({ classifyingId: null });
      const status = e?.response?.status;
      const msg =
        status === 403
          ? "Vous ne pouvez classer que vos propres trajets."
          : status === 404
          ? 'Trajet introuvable.'
          : e?.response?.data?.detail || 'La classification a échoué. Réessayez.';
      logger.warn('trips', 'classify failed', e);
      return { ok: false, message: msg };
    }
  },
}));
