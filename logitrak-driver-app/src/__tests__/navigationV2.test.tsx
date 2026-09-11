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
jest.mock('react-native-safe-area-context', () => {
  const RN = require('react');
  return { SafeAreaView: ({ children }: any) => RN.createElement(RN.Fragment, null, children) };
});

import * as ble from '@/api/ble';
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

describe('DocumentsScreen (shell Phase 1)', () => {
  beforeEach(() => jest.clearAllMocks());

  it('affiche le CONTEXTE RÉEL (chauffeur + véhicule) et un état vide honnête (0 mock)', async () => {
    (ble.getMyVehicle as jest.Mock).mockResolvedValue(VEHICLE);
    (ble.getMyProfile as jest.Mock).mockResolvedValue(PROFILE);
    let tree: any;
    await act(async () => { tree = create(<DocumentsScreen />); });
    await flush();
    expect(textOf(byId(tree, 'documents-driver'))).toBe('Orhan');
    expect(textOf(byId(tree, 'documents-vehicle'))).toBe('FR 275924');
    expect(byId(tree, 'documents-empty')).toBeTruthy(); // état vide honnête, aucune donnée fictive
    tree.unmount();
  });

  it('erreur contexte -> message honnête, jamais de faux document', async () => {
    (ble.getMyVehicle as jest.Mock).mockRejectedValue(new Error('net'));
    (ble.getMyProfile as jest.Mock).mockRejectedValue(new Error('net'));
    let tree: any;
    await act(async () => { tree = create(<DocumentsScreen />); });
    await flush();
    expect(byId(tree, 'documents-error')).toBeTruthy();
    tree.unmount();
  });
});

describe('InspectionScreen (shell Phase 1)', () => {
  beforeEach(() => jest.clearAllMocks());

  it('rattache au véhicule sélectionné + chauffeur, historique vide honnête (0 mock)', async () => {
    (ble.getMyVehicle as jest.Mock).mockResolvedValue(VEHICLE);
    (ble.getMyProfile as jest.Mock).mockResolvedValue(PROFILE);
    let tree: any;
    await act(async () => { tree = create(<InspectionScreen />); });
    await flush();
    expect(textOf(byId(tree, 'inspection-vehicle-plate'))).toBe('FR 275924');
    expect(textOf(byId(tree, 'inspection-driver'))).toBe('Orhan');
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
