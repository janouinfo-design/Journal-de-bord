import { create } from 'zustand';
import { Vehicle, DriverVehicleAccess, getDriverVehicles } from '@/api/ble';
import { logger } from '@/utils/logger';

/**
 * Store des véhicules AUTORISÉS du chauffeur (source : GET /api/livre/driver/vehicles).
 * - Source d'autorité EXCLUSIVE côté chauffeur : jamais la flotte globale du tenant.
 * - Fail-closed : en cas d'erreur, liste vide + erreur explicite (aucun repli global).
 * - Recherche LOCALE : insensible à la casse, tolérante aux espaces (plaque/modèle).
 */

type VehiclesState = {
  vehicles: Vehicle[];
  accessMode: DriverVehicleAccess['access_mode'] | null;
  defaultVehicleId: string | null;
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
  accessMode: null,
  defaultVehicleId: null,
  loading: false,
  error: null,
  loaded: false,

  load: async (force = false) => {
    if (get().loading) return;
    if (get().loaded && !force) return; // cache : on ne recharge pas inutilement
    set({ loading: true, error: null });
    try {
      const access = await getDriverVehicles();
      const list = [...access.vehicles];
      list.sort((a, b) => (a.plate || '').localeCompare(b.plate || ''));
      set({
        vehicles: list,
        accessMode: access.access_mode,
        defaultVehicleId: access.default_vehicle_id,
        loading: false,
        loaded: true,
      });
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Impossible de charger les véhicules.';
      logger.warn('vehicles', 'load failed', e);
      // Fail-closed : aucune liste résiduelle en cas d'erreur.
      set({
        vehicles: [],
        accessMode: null,
        defaultVehicleId: null,
        loading: false,
        loaded: false,
        error: msg,
      });
    }
  },

  // Recherche locale multi-champs. Une requête vide renvoie tout le périmètre autorisé.
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
