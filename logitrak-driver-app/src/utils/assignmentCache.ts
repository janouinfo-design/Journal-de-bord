import { getItemAsync, setItemAsync, deleteItemAsync } from './storage';
import { VehicleAssignment } from '@/api/vehicleAssignment';

/**
 * Cache local de l'affectation — UNIQUEMENT pour l'affichage dégradé hors ligne.
 * JAMAIS source de vérité : au retour réseau, le backend gagne toujours.
 */

const KEY_ASSIGNMENT = 'last_known_active_vehicle';
const KEY_SYNC_AT = 'assignment_last_sync_at';

export async function cacheActiveAssignment(a: VehicleAssignment | null): Promise<void> {
  try {
    if (a) {
      await setItemAsync(KEY_ASSIGNMENT, JSON.stringify(a));
      await setItemAsync(KEY_SYNC_AT, new Date().toISOString());
    } else {
      await deleteItemAsync(KEY_ASSIGNMENT);
    }
  } catch {
    // cache best-effort — jamais bloquant
  }
}

export async function readCachedAssignment(): Promise<{ assignment: VehicleAssignment | null; syncedAt: string | null }> {
  try {
    const raw = await getItemAsync(KEY_ASSIGNMENT);
    const syncedAt = await getItemAsync(KEY_SYNC_AT);
    return { assignment: raw ? (JSON.parse(raw) as VehicleAssignment) : null, syncedAt };
  } catch {
    return { assignment: null, syncedAt: null };
  }
}

export async function clearCachedAssignment(): Promise<void> {
  try {
    await deleteItemAsync(KEY_ASSIGNMENT);
    await deleteItemAsync(KEY_SYNC_AT);
  } catch {
    // no-op
  }
}
