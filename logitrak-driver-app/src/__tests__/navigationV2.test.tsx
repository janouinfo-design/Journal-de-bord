/**
 * APP DRIVER V2 — Phase 1 : navigation + shells Documents/Inspection.
 * Tests LÉGERS (react-test-renderer, comme l'existant) : rendu des nouveaux écrans
 * avec CONTEXTE RÉEL mocké + absence de données fictives + config de navigation.
 */
import { act, create } from 'react-test-renderer';
import React from 'react';

jest.mock('@/api/ble', () => ({
  getMyVehicle: jest.fn(),
  getMyProfile: jest.fn(),
}));
jest.mock('@/api/documents', () => ({
  listVehicleDocuments: jest.fn(),
  DOCUMENT_TYPE_LABEL: { carte_grise: 'Carte grise', assurance: 'Assurance', leasing: 'Leasing', controle_technique: 'Contrôle technique', autre: 'Autre' },
  STATUS_LABEL: { a_traiter: 'À traiter', valide: 'Validé', expire: 'Expiré' },
}));
jest.mock('@/api/inspections', () => ({
  listInspections: jest.fn(),
  createInspection: jest.fn(),
  getCurrentInspection: jest.fn(),
  saveChecklist: jest.fn(),
  addInspectionPhoto: jest.fn(),
  deleteInspectionPhoto: jest.fn(),
  validateInspection: jest.fn(),
  CHECKLIST_LABEL: { pneus: 'Pneus', autre: 'Autre' },
}));
jest.mock('expo-image-picker', () => ({
  requestCameraPermissionsAsync: jest.fn(),
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));
jest.mock('react-native-safe-area-context', () => {
  const RN = require('react');
  return { SafeAreaView: ({ children }: any) => RN.createElement(RN.Fragment, null, children) };
});

import * as ble from '@/api/ble';
import * as docsApi from '@/api/documents';
import * as inspApi from '@/api/inspections';
import { DocumentsScreen } from '@/screens/DocumentsScreen';
import { InspectionScreen } from '@/screens/InspectionScreen';

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });
function byId(tree: any, id: string) { return tree.root.findByProps({ testID: id }); }
function textOf(node: any): string {
  const c = node.props.children;
  return Array.isArray(c) ? c.join('') : String(c);
}

const VEHICLE = { vehicle: { id: 'v1', plate: 'FR 275924', model: 'VW Tiguan' }, current: true, session: null };
const PROFILE = {
  name: 'Orhan', email: 'orhan@logitrak.ch', account_active: true,
  must_change_password: false, driver_active: true, ble_tag_associated: false, last_ble_detection: null,
};

describe('DocumentsScreen (réel Phase 2)', () => {
  beforeEach(() => jest.clearAllMocks());

  it('affiche le véhicule sélectionné + liste réelle des documents (0 mock inventé)', async () => {
    (ble.getMyVehicle as jest.Mock).mockResolvedValue(VEHICLE);
    (docsApi.listVehicleDocuments as jest.Mock).mockResolvedValue({
      vehicle_id: 'v1',
      documents: [
        { id: 'd1', vehicle_id: 'v1', type: 'assurance', filename: 'assurance.pdf',
          status: 'valide', expiry_date: '2027-01-01' },
      ],
    });
    let tree: any;
    await act(async () => { tree = create(<DocumentsScreen />); });
    await flush();
    expect(textOf(byId(tree, 'documents-vehicle'))).toBe('FR 275924');
    expect(byId(tree, 'document-item-d1')).toBeTruthy();
    tree.unmount();
  });

  it('aucun document -> empty state propre (jamais de faux document)', async () => {
    (ble.getMyVehicle as jest.Mock).mockResolvedValue(VEHICLE);
    (docsApi.listVehicleDocuments as jest.Mock).mockResolvedValue({ vehicle_id: 'v1', documents: [] });
    let tree: any;
    await act(async () => { tree = create(<DocumentsScreen />); });
    await flush();
    expect(byId(tree, 'documents-empty')).toBeTruthy();
    tree.unmount();
  });

  it('erreur -> message honnête + retry, jamais de faux document', async () => {
    (ble.getMyVehicle as jest.Mock).mockRejectedValue(new Error('net'));
    let tree: any;
    await act(async () => { tree = create(<DocumentsScreen />); });
    await flush();
    expect(byId(tree, 'documents-error')).toBeTruthy();
    tree.unmount();
  });
});

describe('InspectionScreen (réel Phase 3)', () => {
  beforeEach(() => jest.clearAllMocks());

  it('affiche véhicule/plaque + chauffeur + historique réel (0 mock inventé)', async () => {
    (ble.getMyVehicle as jest.Mock).mockResolvedValue(VEHICLE);
    (ble.getMyProfile as jest.Mock).mockResolvedValue(PROFILE);
    (inspApi.listInspections as jest.Mock).mockResolvedValue([
      { id: 'i1', vehicle_id: 'v1', status: 'validated', validated_at: '2026-09-10T10:00:00',
        checklist: [{ item: 'pneus', state: 'ANOMALIE', comment: 'usure', photos: [] }] },
    ]);
    let tree: any;
    await act(async () => { tree = create(<InspectionScreen />); });
    await flush();
    expect(textOf(byId(tree, 'inspection-vehicle-plate'))).toBe('FR 275924');
    expect(textOf(byId(tree, 'inspection-driver'))).toBe('Orhan');
    expect(byId(tree, 'inspection-hist-i1')).toBeTruthy();
    tree.unmount();
  });

  it('aucune inspection -> empty state honnête', async () => {
    (ble.getMyVehicle as jest.Mock).mockResolvedValue(VEHICLE);
    (ble.getMyProfile as jest.Mock).mockResolvedValue(PROFILE);
    (inspApi.listInspections as jest.Mock).mockResolvedValue([]);
    let tree: any;
    await act(async () => { tree = create(<InspectionScreen />); });
    await flush();
    expect(byId(tree, 'inspection-history-empty')).toBeTruthy();
    tree.unmount();
  });
});

describe('Navigation V2 config', () => {
  it('barre = 5 onglets (Conduite|Trajets|Documents|Inspection|Profil), Reglages retiré, Settings dans le Stack', () => {
    const fs = require('fs');
    const path = require('path');
    const src = fs.readFileSync(path.join(__dirname, '..', 'navigation', 'RootNavigator.tsx'), 'utf8');
    for (const tab of ['"Conduite"', '"Trajets"', '"Documents"', '"Inspection"', '"Profil"']) {
      expect(src.includes('name=' + tab)).toBe(true);
    }
    expect(src.includes('name="Reglages"')).toBe(false);
    expect(src.includes('name="Settings"')).toBe(true);
  });
});
