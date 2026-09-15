import { apiClient } from './client';

/**
 * Inspection VÉHICULE — API réelle liée au Journal de bord (aucune donnée inventée).
 * Backend : /api/livre/driver/inspections (tenant/chauffeur/véhicule contrôlés serveur).
 */

export type ItemState = 'OK' | 'ANOMALIE' | 'N/A';
export type InspectionStatus = 'in_progress' | 'validated';

export interface InspectionPhoto {
  id: string;
  filename: string;
  content_type?: string | null;
  size_bytes?: number | null;
  uploaded_at?: string | null;
}

export interface ChecklistEntry {
  item: string;
  state: ItemState | null;
  comment: string | null;
  photos: InspectionPhoto[];
}

export interface Inspection {
  id: string;
  tenant_id?: string;
  vehicle_id: string;
  driver_id?: string | null;
  created_by?: string | null;
  status: InspectionStatus;
  started_at?: string | null;
  validated_at?: string | null;
  general_comment?: string | null;
  vehicle_snapshot?: { plate?: string | null; model?: string | null } | null;
  driver_snapshot?: { name?: string | null } | null;
  checklist: ChecklistEntry[];
  created_at?: string | null;
}

export const CHECKLIST_LABEL: Record<string, string> = {
  pneus: 'Pneus',
  eclairage: 'Éclairage',
  pare_brise: 'Pare-brise / vitres',
  carrosserie: 'Carrosserie',
  retroviseurs: 'Rétroviseurs',
  freins_temoins: 'Freins / témoins',
  niveaux_liquides: 'Niveaux / liquides',
  proprete: 'Propreté',
  equipements_obligatoires: 'Équipements obligatoires',
  documents_vehicule: 'Documents véhicule',
  autre: 'Autre',
};

export async function createInspection(vehicleId?: string): Promise<Inspection> {
  const { data } = await apiClient.post('/api/livre/driver/inspections',
    vehicleId ? { vehicle_id: vehicleId } : {});
  return data as Inspection;
}

export async function getCurrentInspection(vehicleId?: string): Promise<Inspection | null> {
  const { data } = await apiClient.get('/api/livre/driver/inspections/current', {
    params: vehicleId ? { vehicle_id: vehicleId } : undefined,
  });
  return (data?.inspection ?? null) as Inspection | null;
}

export async function listInspections(vehicleId?: string): Promise<Inspection[]> {
  const { data } = await apiClient.get('/api/livre/driver/inspections', {
    params: vehicleId ? { vehicle_id: vehicleId } : undefined,
  });
  return Array.isArray(data?.inspections) ? data.inspections : [];
}

export async function getInspection(id: string): Promise<Inspection> {
  const { data } = await apiClient.get(`/api/livre/driver/inspections/${id}`);
  return data as Inspection;
}

export async function saveChecklist(
  id: string,
  items: { item: string; state: ItemState; comment?: string }[],
  generalComment?: string,
): Promise<Inspection> {
  const { data } = await apiClient.put(`/api/livre/driver/inspections/${id}/checklist`, {
    items, general_comment: generalComment ?? null,
  });
  return data as Inspection;
}

export async function addInspectionPhoto(
  id: string, item: string, photo: { uri: string; name: string; mimeType: string },
): Promise<InspectionPhoto> {
  const form = new FormData();
  form.append('item', item);
  form.append('file', { uri: photo.uri, name: photo.name, type: photo.mimeType } as any);
  const { data } = await apiClient.post(`/api/livre/driver/inspections/${id}/photos`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data as InspectionPhoto;
}

export async function deleteInspectionPhoto(id: string, photoId: string): Promise<void> {
  await apiClient.delete(`/api/livre/driver/inspections/${id}/photos/${photoId}`);
}

export async function validateInspection(id: string): Promise<Inspection> {
  const { data } = await apiClient.post(`/api/livre/driver/inspections/${id}/validate`);
  return data as Inspection;
}
