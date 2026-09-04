/**
 * Tests unitaires — hook usePrivateMode (Phase 2, mode Privé/Professionnel).
 *
 * Valide la LOGIQUE UI sans device réel :
 * - récupération de l'état réel au montage (jamais BUSINESS par défaut),
 * - non-optimiste : état transitoire REQUESTED puis état backend seulement après réponse,
 * - échec/non-confirmation -> message honnête, pas de succès affiché,
 * - erreur réseau -> UNKNOWN + message, jamais PRIVATE confirmé,
 * - double-tap : une seule intention envoyée (anti-concurrence),
 * - messages sans jargon technique (AVL16/Navixy/Teltonika/privatemode).
 *
 * L'API privateMode est MOCKÉE (aucun appel réseau réel).
 */
import { act, create } from 'react-test-renderer';
import React from 'react';
import { Text } from 'react-native';

jest.mock('@/api/privateMode', () => ({
  getPrivateMode: jest.fn(),
  setPrivateMode: jest.fn(),
}));

import * as api from '@/api/privateMode';
import { usePrivateMode } from '@/hooks/usePrivateMode';

// Petit harnais : expose les valeurs du hook via une ref.
function makeHarness() {
  const ref: { current: ReturnType<typeof usePrivateMode> | null } = { current: null };
  function Probe() {
    ref.current = usePrivateMode(999999); // poll long, on pilote manuellement
    return <Text>probe</Text>;
  }
  return { ref, Probe };
}

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe('usePrivateMode', () => {
  beforeEach(() => jest.clearAllMocks());
  afterEach(() => { jest.clearAllTimers(); });

  it('récupère l\'état réel au montage (jamais BUSINESS par défaut)', async () => {
    (api.getPrivateMode as jest.Mock).mockResolvedValue({ state: 'PRIVATE', allowed: true });
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe />); });
    await flush();
    expect(ref.current?.status.state).toBe('PRIVATE');
    expect(api.getPrivateMode).toHaveBeenCalled();
    tree.unmount();
  });

  it('bascule non-optimiste : REQUESTED puis PRIVATE seulement après réponse ok', async () => {
    (api.getPrivateMode as jest.Mock).mockResolvedValue({ state: 'BUSINESS', allowed: true });
    (api.setPrivateMode as jest.Mock).mockResolvedValue({ ok: true, state: 'PRIVATE' });
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe />); });
    await flush();
    expect(ref.current?.status.state).toBe('BUSINESS');
    // le backend reflète le nouvel état lors du refresh post-bascule (réaliste)
    (api.getPrivateMode as jest.Mock).mockResolvedValue({ state: 'PRIVATE', allowed: true });
    await act(async () => { await ref.current!.requestMode('PRIVATE'); });
    await flush();
    expect(ref.current?.status.state).toBe('PRIVATE');
    expect(api.setPrivateMode).toHaveBeenCalledWith('PRIVATE');
    tree.unmount();
  });

  it('non-confirmation backend -> pas de PRIVATE + message honnête sans jargon', async () => {
    (api.getPrivateMode as jest.Mock).mockResolvedValue({ state: 'BUSINESS', allowed: true });
    (api.setPrivateMode as jest.Mock).mockResolvedValue({
      ok: false, state: 'PRIVATE_REQUESTED', reason: 'not_confirmed',
    });
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe />); });
    await flush();
    await act(async () => { await ref.current!.requestMode('PRIVATE'); });
    await flush();
    expect(ref.current?.status.state).not.toBe('PRIVATE'); // jamais optimiste
    const err = ref.current?.error ?? '';
    expect(err.length).toBeGreaterThan(0);
    // aucun jargon technique exposé
    for (const bad of ['AVL', 'Navixy', 'Teltonika', 'privatemode', 'raw_command', '11813', '11000']) {
      expect(err.toLowerCase()).not.toContain(bad.toLowerCase());
    }
    tree.unmount();
  });

  it('erreur réseau -> UNKNOWN + message, jamais PRIVATE confirmé', async () => {
    (api.getPrivateMode as jest.Mock).mockResolvedValue({ state: 'BUSINESS', allowed: true });
    (api.setPrivateMode as jest.Mock).mockRejectedValue(new Error('network'));
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe />); });
    await flush();
    await act(async () => { await ref.current!.requestMode('PRIVATE'); });
    await flush();
    expect(ref.current?.status.state).toBe('UNKNOWN');
    expect(ref.current?.error).toBeTruthy();
    tree.unmount();
  });

  it('double-tap : une seule intention envoyée (anti-concurrence)', async () => {
    (api.getPrivateMode as jest.Mock).mockResolvedValue({ state: 'BUSINESS', allowed: true });
    let resolveSet: (v: any) => void = () => {};
    (api.setPrivateMode as jest.Mock).mockImplementation(
      () => new Promise((res) => { resolveSet = res; }));
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe />); });
    await flush();
    // deux taps quasi simultanés
    await act(async () => {
      ref.current!.requestMode('PRIVATE');
      ref.current!.requestMode('PRIVATE');
    });
    // résout la 1re promesse
    await act(async () => { resolveSet({ ok: true, state: 'PRIVATE' }); await Promise.resolve(); });
    await flush();
    expect(api.setPrivateMode).toHaveBeenCalledTimes(1); // une seule commande
    tree.unmount();
  });

  it('lecture impossible au montage -> UNKNOWN (jamais BUSINESS supposé)', async () => {
    (api.getPrivateMode as jest.Mock).mockRejectedValue(new Error('offline'));
    const { ref, Probe } = makeHarness();
    let tree: any;
    await act(async () => { tree = create(<Probe />); });
    await flush();
    expect(ref.current?.status.state).toBe('UNKNOWN');
    tree.unmount();
  });
});
