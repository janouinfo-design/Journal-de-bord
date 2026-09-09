/**
 * Tests de la logique de pré-sélection véhicule — parité Console web (T1–T10).
 * Invariants : jamais le 1er véhicule arbitraire ; défaut uniquement si autorisé ;
 * SINGLE = verrouillé ; révocation signalée.
 */
import { resolveVehicleSelection } from '@/utils/driverVehicleSelection';

const V = (id: string) => ({ id });

describe('resolveVehicleSelection', () => {
  it('T1 — ALL multiple sans défaut : AUCUNE sélection (jamais le 1er arbitraire)', () => {
    const r = resolveVehicleSelection({
      accessMode: 'ALL', vehicles: [V('a'), V('b'), V('c')],
    });
    expect(r.selectedId).toBeNull();
    expect(r.locked).toBe(false);
  });

  it('T2 — défaut AUTORISÉ : pré-sélectionné', () => {
    const r = resolveVehicleSelection({
      accessMode: 'ALL', vehicles: [V('a'), V('b')], defaultVehicleId: 'b',
    });
    expect(r.selectedId).toBe('b');
  });

  it('T3 — défaut HORS périmètre : ignoré, aucune sélection', () => {
    const r = resolveVehicleSelection({
      accessMode: 'SELECTED', vehicles: [V('a'), V('b')], defaultVehicleId: 'z',
    });
    expect(r.selectedId).toBeNull();
  });

  it('T4 — SINGLE : auto-sélection du véhicule unique + verrouillé', () => {
    const r = resolveVehicleSelection({ accessMode: 'SINGLE', vehicles: [V('x')] });
    expect(r.selectedId).toBe('x');
    expect(r.locked).toBe(true);
  });

  it('T5 — liste à 1 (hors SINGLE) : auto-sélection non verrouillée', () => {
    const r = resolveVehicleSelection({ accessMode: 'SELECTED', vehicles: [V('x')] });
    expect(r.selectedId).toBe('x');
    expect(r.locked).toBe(false);
  });

  it('T6 — sélection active encore autorisée : conservée (priorité sur le défaut)', () => {
    const r = resolveVehicleSelection({
      accessMode: 'ALL', vehicles: [V('a'), V('b')],
      defaultVehicleId: 'b', currentSelectedId: 'a',
    });
    expect(r.selectedId).toBe('a');
    expect(r.revoked).toBe(false);
  });

  it('T7 — sélection active RÉVOQUÉE : désélection + revoked=true', () => {
    const r = resolveVehicleSelection({
      accessMode: 'SELECTED', vehicles: [V('a'), V('b')], currentSelectedId: 'z',
    });
    expect(r.selectedId).toBeNull();
    expect(r.revoked).toBe(true);
  });

  it('T8 — sélection mémorisée autorisée : réutilisée', () => {
    const r = resolveVehicleSelection({
      accessMode: 'ALL', vehicles: [V('a'), V('b')], storedId: 'b',
    });
    expect(r.selectedId).toBe('b');
  });

  it('T9 — sélection mémorisée révoquée : repli sur le défaut autorisé', () => {
    const r = resolveVehicleSelection({
      accessMode: 'ALL', vehicles: [V('a'), V('b')], storedId: 'z', defaultVehicleId: 'a',
    });
    expect(r.selectedId).toBe('a');
  });

  it('T10 — liste vide : aucune sélection, jamais de crash', () => {
    const r = resolveVehicleSelection({ accessMode: 'SELECTED', vehicles: [] });
    expect(r.selectedId).toBeNull();
  });

  it('T7bis — révocation avec défaut autorisé : bascule sur le défaut, revoked signalé', () => {
    const r = resolveVehicleSelection({
      accessMode: 'SELECTED', vehicles: [V('a'), V('b')],
      currentSelectedId: 'z', defaultVehicleId: 'b',
    });
    expect(r.selectedId).toBe('b');
    expect(r.revoked).toBe(true);
  });
});
