import { Trip } from '@/api/trips';

/** Nombre de trajets NON classifiés (classification null/absente). Données réelles. */
export function countUnclassified(trips: Trip[]): number {
  if (!Array.isArray(trips)) return 0;
  return trips.filter((t) => t && (t.classification === null || t.classification === undefined)).length;
}

/**
 * Dernier trajet = celui avec l'horodatage de FIN (sinon début) le plus récent.
 * Retourne null si aucun trajet. Aucune donnée inventée.
 */
export function deriveLastTrip(trips: Trip[]): Trip | null {
  if (!Array.isArray(trips) || trips.length === 0) return null;
  const ts = (t: Trip) => {
    const v = t.end_time || t.start_time;
    const n = v ? Date.parse(v) : NaN;
    return Number.isNaN(n) ? -Infinity : n;
  };
  return trips.reduce((best, cur) => (ts(cur) > ts(best) ? cur : best), trips[0]);
}
