/**
 * Tests — dérivations de trajets pour l'écran Conduite (données réelles uniquement).
 * countUnclassified + deriveLastTrip. Aucune donnée inventée, purement déterministe.
 */
import { countUnclassified, deriveLastTrip } from '@/utils/tripDerivations';
import type { Trip } from '@/api/trips';

const T = (over: Partial<Trip>): Trip => ({ id: over.id || 'x', ...over } as Trip);

describe('countUnclassified', () => {
  it('compte les trajets sans classification (null/undefined)', () => {
    const trips = [
      T({ id: '1', classification: 'professional' }),
      T({ id: '2', classification: null }),
      T({ id: '3' }), // undefined
      T({ id: '4', classification: 'personal' }),
    ];
    expect(countUnclassified(trips)).toBe(2);
  });

  it('retourne 0 si tout est classé', () => {
    expect(countUnclassified([
      T({ id: '1', classification: 'professional' }),
      T({ id: '2', classification: 'personal' }),
    ])).toBe(0);
  });

  it('gère une liste vide ou invalide', () => {
    expect(countUnclassified([])).toBe(0);
    // @ts-expect-error test robustesse entrée non-tableau
    expect(countUnclassified(null)).toBe(0);
  });
});

describe('deriveLastTrip', () => {
  it('retourne null si aucun trajet', () => {
    expect(deriveLastTrip([])).toBeNull();
  });

  it('choisit le trajet avec la fin la plus récente', () => {
    const trips = [
      T({ id: 'old', end_time: '2026-09-14T08:00:00Z' }),
      T({ id: 'new', end_time: '2026-09-15T09:00:00Z' }),
      T({ id: 'mid', end_time: '2026-09-14T20:00:00Z' }),
    ];
    expect(deriveLastTrip(trips)?.id).toBe('new');
  });

  it('utilise start_time si end_time absent', () => {
    const trips = [
      T({ id: 'a', start_time: '2026-09-15T07:00:00Z' }),
      T({ id: 'b', start_time: '2026-09-15T10:00:00Z' }),
    ];
    expect(deriveLastTrip(trips)?.id).toBe('b');
  });
});
