import { apiClient } from './client';

/**
 * Contrats API RÉELS pour les trajets (audités sur le backend Phase 3) :
 * - GET  /api/livre/trips           -> { trips: Trip[], settings_mode }
 * - PUT  /api/livre/trips/{id}/classify { classification } -> { ok: true }
 * - GET  /api/livre/trips/{id}/track -> { trip_id, points: [[lng,lat]], source, count }
 * Le serveur ne renvoie QUE les trajets du chauffeur connecté (rôle driver).
 */

export type TripClassification = 'professional' | 'personal' | null;

export type Trip = {
  id: string;
  driver_id?: string;
  driver_name?: string;
  vehicle_id?: string;
  vehicle_plate?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  start_address?: string | null;
  end_address?: string | null;
  start_lat?: number | null;
  start_lng?: number | null;
  end_lat?: number | null;
  end_lng?: number | null;
  distance_km?: number | null;
  duration_min?: number | null;
  avg_speed?: number | null;
  max_speed?: number | null;
  fuel_l?: number | null;
  classification?: TripClassification;
  auto_classified?: boolean;
  mobile_override?: 'professional' | 'personal' | null;
  navixy_track_id?: number | null;
};

export type TripsResponse = {
  trips: Trip[];
  settings_mode?: string;
};

export type TrackResponse = {
  trip_id: string;
  points: [number, number][]; // [lng, lat]
  source: string;
  count: number;
};

export type TripsQuery = {
  classification?: 'professional' | 'personal';
  start?: string;
  end?: string;
  vehicle_id?: string;
  limit?: number;
};

export async function getTrips(query: TripsQuery = {}): Promise<TripsResponse> {
  const { data } = await apiClient.get('/api/livre/trips', { params: query });
  const trips = Array.isArray(data?.trips) ? data.trips : [];
  return { trips, settings_mode: data?.settings_mode };
}

// Classification PRO/PRIVÉ d'un trajet. Le backend renvoie {ok:true} après confirmation.
export async function classifyTrip(
  tripId: string,
  classification: 'professional' | 'personal',
): Promise<{ ok: boolean }> {
  const { data } = await apiClient.put(`/api/livre/trips/${tripId}/classify`, {
    classification,
  });
  return data;
}

// Tracé GPS d'un trajet. Peut renvoyer 403 si trajet personnel masqué.
export async function getTrack(tripId: string): Promise<TrackResponse> {
  const { data } = await apiClient.get(`/api/livre/trips/${tripId}/track`);
  return data as TrackResponse;
}
