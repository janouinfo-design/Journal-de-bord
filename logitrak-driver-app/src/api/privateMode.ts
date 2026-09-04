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
}

export async function getPrivateMode(): Promise<PrivateModeStatus> {
  const { data } = await apiClient.get('/api/livre/driver/private-mode');
  return data as PrivateModeStatus;
}

export async function setPrivateMode(mode: 'PRIVATE' | 'BUSINESS'): Promise<PrivateModeResult> {
  const { data } = await apiClient.post('/api/livre/driver/private-mode', { mode });
  return data as PrivateModeResult;
}
