import { apiClient } from './client';

// Phase 2 — Mode Privé/Professionnel (masquage GPS device + km privés via AVL16).
// Backend autoritaire : l'app envoie une INTENTION, jamais de commande device brute.

export type PrivateModeState =
  | 'BUSINESS'
  | 'PRIVATE_REQUESTED'
  | 'PRIVATE'
  | 'BUSINESS_REQUESTED'
  | 'FAILED'
  | 'UNKNOWN';

export interface PrivateModeStatus {
  state: PrivateModeState;
  allowed: boolean;
  reason?: string | null;
  vehicle_id?: string | null;
  tracker_id?: number | null;
  vehicle_plate?: string | null;
  private_odometer_supported?: boolean;
  last_transition_at?: string | null;
}

export interface PrivateModeResult {
  ok: boolean;
  allowed?: boolean;
  state: PrivateModeState;
  reason?: string | null;
  idempotent?: boolean;
  private_distance_km?: number | null;
  distance_status?: string | null;
  confirmation_source?: string | null;
  http_status?: number | null; // renseigné côté client en cas d'erreur HTTP
}

export async function getPrivateMode(): Promise<PrivateModeStatus> {
  const { data } = await apiClient.get('/api/livre/driver/private-mode');
  return data as PrivateModeStatus;
}

export async function setPrivateMode(mode: 'PRIVATE' | 'BUSINESS'): Promise<PrivateModeResult> {
  try {
    const { data } = await apiClient.post('/api/livre/driver/private-mode', { mode });
    return data as PrivateModeResult;
  } catch (e: any) {
    // Refus d'autorisation backend (403/409/503) -> résultat métier explicite,
    // jamais une exception opaque. Aucun secret n'est présent dans le detail.
    const status = e?.response?.status ?? null;
    const detail = e?.response?.data?.detail ?? null;
    if (status && [400, 403, 409, 422, 503].includes(status)) {
      return {
        ok: false,
        allowed: status !== 400 && status !== 422,
        state: 'UNKNOWN',
        reason: typeof detail === 'string' ? detail : null,
        http_status: status,
      };
    }
    throw e; // 401/timeout/offline/5xx inattendu -> géré par le hook (relecture serveur)
  }
}
