import { apiClient } from './client';

/**
 * Documents VÉHICULE — API réelle liée au Journal de bord (aucune donnée inventée).
 * Backend : /api/livre/driver/vehicle-documents (tenant/chauffeur/véhicule contrôlés serveur).
 */

export type VehicleDocumentType =
  | 'carte_grise' | 'assurance' | 'leasing' | 'controle_technique' | 'autre';

export type VehicleDocumentStatus = 'a_traiter' | 'valide' | 'expire';

export interface VehicleDocument {
  id: string;
  tenant_id?: string;
  vehicle_id: string;
  driver_id?: string | null;
  type: VehicleDocumentType;
  filename: string;
  content_type?: string | null;
  size_bytes?: number | null;
  status: VehicleDocumentStatus;
  document_date?: string | null;
  expiry_date?: string | null;
  ocr_extracted?: Record<string, unknown> | null;
  created_at?: string | null;
  created_by?: string | null;
}

export interface VehicleDocumentsResponse {
  vehicle_id: string;
  documents: VehicleDocument[];
}

export const DOCUMENT_TYPE_LABEL: Record<VehicleDocumentType, string> = {
  carte_grise: 'Carte grise',
  assurance: 'Assurance',
  leasing: 'Leasing',
  controle_technique: 'Contrôle technique',
  autre: 'Autre',
};

export const STATUS_LABEL: Record<VehicleDocumentStatus, string> = {
  a_traiter: 'À traiter',
  valide: 'Validé',
  expire: 'Expiré',
};

// Liste réelle des documents du véhicule (défaut : véhicule de session côté serveur).
export async function listVehicleDocuments(vehicleId?: string): Promise<VehicleDocumentsResponse> {
  const { data } = await apiClient.get('/api/livre/driver/vehicle-documents', {
    params: vehicleId ? { vehicle_id: vehicleId } : undefined,
  });
  return {
    vehicle_id: data?.vehicle_id ?? vehicleId ?? '',
    documents: Array.isArray(data?.documents) ? data.documents : [],
  };
}

export interface UploadInput {
  uri: string;
  name: string;
  mimeType: string;
  type: VehicleDocumentType;
  vehicleId?: string;
  documentDate?: string;
  expiryDate?: string;
}

// Upload multipart -> backend Journal (stockage + OCR restent côté serveur).
export async function uploadVehicleDocument(input: UploadInput): Promise<VehicleDocument> {
  const form = new FormData();
  // React Native FormData file part.
  form.append('file', {
    uri: input.uri,
    name: input.name,
    type: input.mimeType,
  } as any);
  form.append('type', input.type);
  if (input.vehicleId) form.append('vehicle_id', input.vehicleId);
  if (input.documentDate) form.append('document_date', input.documentDate);
  if (input.expiryDate) form.append('expiry_date', input.expiryDate);
  const { data } = await apiClient.post('/api/livre/driver/vehicle-documents', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data as VehicleDocument;
}

export async function validateVehicleDocument(docId: string): Promise<VehicleDocument> {
  const { data } = await apiClient.post(`/api/livre/driver/vehicle-documents/${docId}/validate`);
  return data as VehicleDocument;
}

export async function archiveVehicleDocument(docId: string): Promise<{ archived: boolean; id: string }> {
  const { data } = await apiClient.delete(`/api/livre/driver/vehicle-documents/${docId}`);
  return data;
}
