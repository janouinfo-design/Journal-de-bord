import { apiClient } from './client';

export type BleDetection = {
  identifier: string;
  rssi: number;
  ts?: string; // ISO
  platform?: 'ios' | 'android' | 'pwa' | 'native';
  battery?: number;
  // Rich metadata — sent when react-native-ble-plx provides it (native app),
  // empty/undefined for the simulated PWA pings.
  local_name?: string | null;
  device_id?: string | null;
  manufacturer_data?: string | null;
  service_uuids?: string[] | null;
};

export type CurrentSession = {
  id: string | null;
  status: 'open' | 'pending' | 'automatic' | 'manual' | 'conflict' | 'closed' | null;
  driver_id?: string;
  driver_name?: string;
  vehicle_id?: string;
  vehicle_plate?: string;
  vehicle_model?: string;
  confidence_score?: number;
  rssi_median?: number;
  detections_count?: number;
  mobile_override?: 'professional' | 'personal' | null;
  start_time?: string;
};

export async function postDetections(detections: BleDetection[]) {
  if (!detections.length) return { accepted: 0 };
  const { data } = await apiClient.post('/api/livre/ble/detections', detections);
  return data;
}

export async function getCurrentSession(): Promise<CurrentSession> {
  const { data } = await apiClient.get('/api/livre/driver/current-session');
  return data;
}

export async function setManualMode(mode: 'professional' | 'personal') {
  const { data } = await apiClient.post('/api/livre/driver/manual-mode', { mode });
  return data;
}

export async function registerPushToken(token: string) {
  try {
    const { data } = await apiClient.post('/api/livre/driver/push-token', { token });
    return data;
  } catch {
    // Backend endpoint optional in Phase A; ignore 404.
    return null;
  }
}
