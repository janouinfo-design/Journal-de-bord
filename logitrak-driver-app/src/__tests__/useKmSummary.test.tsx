/**
 * Tests — useKmSummary (Km Pro/Privé, source backend, reset au changement de véhicule).
 * L'API km-summary est MOCKÉE (aucun appel réseau). Aucun calcul GPS local.
 */
import { act, create } from 'react-test-renderer';
import React from 'react';
import { Text } from 'react-native';

jest.mock('@/api/ble', () => ({ getKmSummary: jest.fn() }));

import * as api from '@/api/ble';
import { useKmSummary } from '@/hooks/useKmSummary';

function makeHarness(vehicleId?: string | null) {
  const ref: { current: ReturnType<typeof useKmSummary> | null } = { current: null };
  function Probe({ vid }: { vid?: string | null }) {
    ref.current = useKmSummary(vid, 'today');
    return <Text>probe</Text>;
  }
  return { ref, Probe };
}

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe('useKmSummary', () => {
  beforeEach(() => jest.clearAllMocks());

  it('affiche les km backend (pro/privé) pour le véhicule actif', async () => {
    (api.getKmSummary as jest.Mock).mockResolvedValue({
      period: 'today', vehicle_id: 'vA', pro_km: 42.8, private_km: 8.3, available: true,
    });
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe vid="vA" />); });
    await flush();
    expect(ref.current?.proKm).toBe(42.8);
    expect(ref.current?.privateKm).toBe(8.3);
    expect(ref.current?.available).toBe(true);
    tree.unmount();
  });

  it('km indisponibles -> valeurs null (jamais inventées)', async () => {
    (api.getKmSummary as jest.Mock).mockResolvedValue({
      period: 'today', vehicle_id: null, pro_km: null, private_km: null, available: false,
    });
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe vid={null} />); });
    await flush();
    expect(ref.current?.proKm).toBeNull();
    expect(ref.current?.privateKm).toBeNull();
    expect(ref.current?.available).toBe(false);
    tree.unmount();
  });

  it('erreur backend -> pas de valeur inventée', async () => {
    (api.getKmSummary as jest.Mock).mockRejectedValue(new Error('net'));
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe vid="vA" />); });
    await flush();
    expect(ref.current?.proKm).toBeNull();
    expect(ref.current?.privateKm).toBeNull();
    tree.unmount();
  });

  it('changement de véhicule -> refetch + pas de contamination', async () => {
    (api.getKmSummary as jest.Mock).mockResolvedValue({
      period: 'today', vehicle_id: 'vA', pro_km: 10, private_km: 1, available: true,
    });
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe vid="vA" />); });
    await flush();
    expect(ref.current?.proKm).toBe(10);
    // véhicule B renvoie d'autres km
    (api.getKmSummary as jest.Mock).mockResolvedValue({
      period: 'today', vehicle_id: 'vB', pro_km: 55, private_km: 4, available: true,
    });
    await act(async () => { tree.update(<Probe vid="vB" />); });
    await flush();
    expect(ref.current?.proKm).toBe(55);   // km du véhicule B, pas de A
    expect(api.getKmSummary).toHaveBeenCalledTimes(2);
    tree.unmount();
  });

  it('changement de période (semaine) -> refetch avec la bonne période + label', async () => {
    const refObj: { current: ReturnType<typeof useKmSummary> | null } = { current: null };
    function Probe({ period }: { period: 'today' | 'week' | 'month' }) {
      refObj.current = useKmSummary('vA', period);
      return <Text>p</Text>;
    }
    (api.getKmSummary as jest.Mock).mockResolvedValue({
      period: 'today', period_label: "Aujourd'hui", vehicle_id: 'vA',
      pro_km: 12, private_km: 2, available: true,
    });
    let tree: any;
    await act(async () => { tree = create(<Probe period="today" />); });
    await flush();
    expect(api.getKmSummary).toHaveBeenLastCalledWith('today');

    (api.getKmSummary as jest.Mock).mockResolvedValue({
      period: 'week', period_label: '14 – 20 septembre', vehicle_id: 'vA',
      pro_km: 88, private_km: 9, available: true,
    });
    await act(async () => { tree.update(<Probe period="week" />); });
    await flush();
    expect(api.getKmSummary).toHaveBeenLastCalledWith('week');
    expect(refObj.current?.proKm).toBe(88);
    expect(refObj.current?.periodLabel).toBe('14 – 20 septembre');
    tree.unmount();
  });
});
