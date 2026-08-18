import { apiClient } from './client';

/**
 * Contrats API RÉELS (audités sur le backend Phase 3 — routes /api/livre/driver/*).
 * Aucune donnée inventée : les champs correspondent exactement aux réponses serveur.
 */

export type BleDetection = {
  identifier: string;
  rssi: number;
  ts?: string; // ISO
  platform?: 'ios' | 'android' | 'pwa' | 'native';
  local_name?: string | null;
  device_id?: string | null;
  manufacturer_data?: string | null;
  service_uuids?: string[] | null;
};

// Objet véhicule imbriqué renvoyé par le serveur (my-vehicle / current-session).
export type SessionVehicle = {
  id?: string;
  plate?: string | null;
  model?: string | null;
};

// Session telle que renvoyée réellement par le backend.
export type CurrentSession = {
  id: string | null;
  status:
    | 'open'
    | 'pending'
    | 'automatic'
    | 'confirmed'
    | 'manual'
    | 'conflict'
    | 'closed'
    | null;
  driver_id?: string;
  vehicle_id?: string;
  vehicle?: SessionVehicle | null;
  identification_source?: 'APP' | 'BLE' | 'APP+BLE' | 'MANUEL' | null;
  active_driver?: boolean;
  mobile_override?: 'professional' | 'personal' | null;
  confidence?: number | null;
  detection_count?: number;
  last_rssi?: number | null;
  started_at?: string;
  ended_at?: string | null;
};

export type MyVehicleResponse = {
  vehicle: SessionVehicle | null;
  current: boolean;
  session: CurrentSession | null;
};

export type MyProfile = {
  name: string | null;
  email: string | null;
  account_active: boolean;
  must_change_password: boolean;
  driver_active: boolean | null;
  ble_tag_associated: boolean;
  last_ble_detection: string | null;
};

export type FleetTag = {
  id: string;
  identifier: string;
  identifier_raw: string;
  label: string | null;
  vehicle_plate: string | null;
  vehicle_model: string | null;
};

export type ClaimResult = {
  status: 'confirmed' | 'conflict';
  session: CurrentSession | null;
  conflict_with_driver_id?: string;
};

export type StopResult =
  | { stopped: true; vehicle_plate: string | null; session: CurrentSession }
  | { stopped: false; message: string };

// --- BLE : le backend accepte {detections:[...]} OU une détection unique.
// Le contrat officiel (EXPO_APP_PROMPT) est {detections:[...]}.
export async function postDetections(detections: BleDetection[]) {
  if (!detections.length) return { count: 0 };
  const { data } = await apiClient.post('/api/livre/ble/detections', { detections });
  return data;
}

// --- Session courante : le serveur renvoie {session|null}. On dé-emballe.
export async function getCurrentSession(): Promise<CurrentSession | null> {
  const { data } = await apiClient.get('/api/livre/driver/current-session');
  return (data?.session ?? null) as CurrentSession | null;
}

export async function getMyVehicle(): Promise<MyVehicleResponse> {
  const { data } = await apiClient.get('/api/livre/driver/my-vehicle');
  return data as MyVehicleResponse;
}

export async function getMyProfile(): Promise<MyProfile> {
  const { data } = await apiClient.get('/api/livre/driver/my-profile');
  return data as MyProfile;
}

export type Vehicle = {
  id: string;
  plate: string | null;
  model: string | null;
  mode?: string;
};

// Liste des véhicules de la flotte (source des vehicle_id réels pour « Je conduis »).
export async function getVehicles(): Promise<Vehicle[]> {
  const { data } = await apiClient.get('/api/livre/vehicles');
  return (Array.isArray(data) ? data : []) as Vehicle[];
}

export async function getFleetTags(): Promise<FleetTag[]> {
  const { data } = await apiClient.get('/api/livre/driver/fleet-tags');
  return (Array.isArray(data) ? data : []) as FleetTag[];
}

// --- « Je conduis » (claim). Ne recrée aucune logique côté client.
export async function claimVehicle(vehicleId: string): Promise<ClaimResult> {
  const { data } = await apiClient.post('/api/livre/driver/claim', { vehicle_id: vehicleId });
  return data as ClaimResult;
}

// --- « Je m'arrête » (stop). Idempotent côté serveur.
export async function stopDriving(): Promise<StopResult> {
  const { data } = await apiClient.post('/api/livre/driver/stop');
  return data as StopResult;
}

export async function setManualMode(mode: 'professional' | 'personal') {
  const { data } = await apiClient.post('/api/livre/driver/manual-mode', { mode });
  return data;
}

export async function registerPushToken(token: string, platform?: string) {
  const { data } = await apiClient.post('/api/livre/driver/push-token', { token, platform });
  return data;
}

// DELETE push-token : le backend attend le token en query param.
export async function deletePushToken(token: string) {
  const { data } = await apiClient.delete('/api/livre/driver/push-token', {
    params: { token },
  });
  return data;
}
