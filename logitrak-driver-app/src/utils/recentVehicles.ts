import { Trip } from '@/api/trips';
import { Vehicle } from '@/api/ble';

/**
 * Dérive les véhicules RÉCEMMENT utilisés par le chauffeur à partir de ses trajets réels
 * (source : GET /api/livre/trips, déjà triés récents d'abord côté serveur).
 * Aucune donnée fabriquée : on ne renvoie que des véhicules réellement présents dans la flotte.
 *
 * @param trips     trajets du chauffeur (récents d'abord)
 * @param fleet     flotte complète (pour retrouver id/model fiables)
 * @param max       nombre max de véhicules récents (3 à 5)
 */
export function deriveRecentVehicles(
  trips: Trip[],
  fleet: Vehicle[],
  max = 5,
): Vehicle[] {
  if (!trips?.length || !fleet?.length) return [];
  const byId = new Map(fleet.map((v) => [v.id, v]));
  const byPlate = new Map(fleet.map((v) => [(v.plate || '').toLowerCase(), v]));

  const seen = new Set<string>();
  const recents: Vehicle[] = [];
  for (const t of trips) {
    // Priorité à l'id véhicule ; repli sur la plaque si l'id n'est pas résolvable.
    let vehicle: Vehicle | undefined;
    if (t.vehicle_id && byId.has(t.vehicle_id)) vehicle = byId.get(t.vehicle_id);
    else if (t.vehicle_plate) vehicle = byPlate.get(t.vehicle_plate.toLowerCase());
    if (!vehicle || !vehicle.id || seen.has(vehicle.id)) continue;
    seen.add(vehicle.id);
    recents.push(vehicle);
    if (recents.length >= max) break;
  }
  return recents;
}
