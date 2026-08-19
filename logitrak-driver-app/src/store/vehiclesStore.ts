import { create } from 'zustand';
import { Vehicle, getVehicles } from '@/api/ble';
import { logger } from '@/utils/logger';

/**
 * Store de la flotte de véhicules (source : GET /api/livre/vehicles, tenant-scopé côté serveur).
 * - Chargé une seule fois (liste mutualisée, pas d'appel par véhicule).
 * - Recherche LOCALE : insensible à la casse, tolérante aux espaces (plaque/marque/modèle).
 * - Prêt pour 6 / 50 / 100 / 200 véhicules (la virtualisation est gérée par FlatList côté écran).
 */

type VehiclesState = {
  vehicles: Vehicle[];
  loading: boolean;
  error: string | null;
  loaded: boolean;
  load: (force?: boolean) => Promise<void>;
  search: (query: string) => Vehicle[];
};

/** Normalise une chaîne pour la recherche : minuscules + espaces compressés. */
function norm(s: string | null | undefined): string {
  return (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

export const useVehiclesStore = create<VehiclesState>((set, get) => ({
  vehicles: [],
  loading: false,
  error: null,
  loaded: false,

  load: async (force = false) => {
    if (get().loading) return;
    if (get().loaded && !force) return; // cache : on ne recharge pas inutilement
    set({ loading: true, error: null });
    try {
      const list = await getVehicles();
      // Tri par plaque pour une liste lisible.
      list.sort((a, b) => (a.plate || '').localeCompare(b.plate || ''));
      set({ vehicles: list, loading: false, loaded: true });
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Impossible de charger la liste des véhicules.';
      logger.warn('vehicles', 'load failed', e);
      set({ loading: false, error: msg });
    }
  },

  // Recherche locale multi-champs. Une requête vide renvoie toute la flotte.
  search: (query: string) => {
    const q = norm(query);
    const all = get().vehicles;
    if (!q) return all;
    // On compare aussi une version "sans espaces" pour tolérer "GE123" ~ "GE 123456".
    const qNoSpace = q.replace(/\s/g, '');
    return all.filter((v) => {
      const plate = norm(v.plate);
      const model = norm(v.model);
      const plateNoSpace = plate.replace(/\s/g, '');
      return (
        plate.includes(q) ||
        model.includes(q) ||
        plateNoSpace.includes(qNoSpace)
      );
    });
  },
}));
