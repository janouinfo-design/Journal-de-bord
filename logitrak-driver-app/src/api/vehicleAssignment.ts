import { apiClient } from './client';

/**
 * Lot 2 — Affectation conducteur <-> véhicule PERSISTANTE (backend = source de vérité).
 *
 * Le backend (Lot 1) garantit : une seule affectation ACTIVE par chauffeur, concurrence
 * gérée en DB (index uniques partiels), idempotence via request_id, historique immuable.
 * L'app ne fait qu'appeler ces endpoints et refléter l'état renvoyé — jamais d'autorité locale.
 */

export interface VehicleAssignment {
  id: string;
  vehicle_id: string;
  status: 'ACTIVE' | 'ENDED';
  assignment_started_at?: string | null;
  segment_started_at?: string | null;
  previous_vehicle_id?: string | null;
  source?: string | null;
  // enrichissement backend (données réelles véhicule)
  vehicle_plate?: string | null;
  vehicle_model?: string | null;
  vehicle_label?: string | null;
}

export interface AssignmentActiveResponse {
  assignment: VehicleAssignment | null;
}

export interface AssignmentActionResult {
  ok: boolean;
  result: 'ok' | 'conflict' | 'noop';
  reason?: string | null;         // VEHICLE_OCCUPIED | DRIVER_ALREADY_ACTIVE | STATE_CHANGED ...
  idempotent?: boolean;
  assignment?: VehicleAssignment | null;
  http_status?: number;
}

/** Affectation ACTIVE du chauffeur (ou null). Source de vérité serveur. */
export async function getActiveAssignment(): Promise<AssignmentActiveResponse> {
  const { data } = await apiClient.get('/api/livre/driver/vehicle-assignment/active');
  return data;
}

/** « Prendre ce véhicule » — crée une affectation ACTIVE. request_id = idempotence. */
export async function takeVehicle(vehicleId: string, requestId: string): Promise<AssignmentActionResult> {
  const { data } = await apiClient.post('/api/livre/driver/vehicle-assignment/take', {
    vehicle_id: vehicleId,
    request_id: requestId,
  });
  return data;
}

/** « Changer de véhicule » — mutation atomique A->B côté backend (jamais deux ACTIVE). */
export async function changeVehicle(vehicleId: string, requestId: string): Promise<AssignmentActionResult> {
  const { data } = await apiClient.post('/api/livre/driver/vehicle-assignment/change', {
    vehicle_id: vehicleId,
    request_id: requestId,
  });
  return data;
}

/** « Fin de service » — libère le véhicule (idempotent). */
export async function endAssignment(requestId: string): Promise<AssignmentActionResult> {
  const { data } = await apiClient.post('/api/livre/driver/vehicle-assignment/end', {
    request_id: requestId,
  });
  return data;
}
