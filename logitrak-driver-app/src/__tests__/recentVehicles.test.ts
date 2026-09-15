/**
 * Tests de la dérivation des véhicules récents (à partir des trajets réels).
 */
import { deriveRecentVehicles } from '@/utils/recentVehicles';

const FLEET = [
  { id: 'v1', plate: 'GE 123456', model: 'Mercedes Sprinter' },
  { id: 'v2', plate: 'GE 234567', model: 'VW Crafter' },
  { id: 'v3', plate: 'VD 999000', model: 'Renault Trafic' },
];

const trip = (over: any) => ({ id: 'x', ...over });

describe('deriveRecentVehicles', () => {
  it('renvoie [] si pas de trajets', () => {
    expect(deriveRecentVehicles([], FLEET)).toEqual([]);
  });

  it('dérive les véhicules récents distincts, récents d\'abord', () => {
    const trips = [
      trip({ vehicle_id: 'v2' }),
      trip({ vehicle_id: 'v1' }),
      trip({ vehicle_id: 'v2' }), // doublon ignoré
      trip({ vehicle_id: 'v3' }),
    ];
    const r = deriveRecentVehicles(trips, FLEET, 5);
    expect(r.map((v) => v.id)).toEqual(['v2', 'v1', 'v3']);
  });

  it('repli sur la plaque si vehicle_id absent', () => {
    const trips = [trip({ vehicle_plate: 'GE 123456' })];
    const r = deriveRecentVehicles(trips, FLEET);
    expect(r[0].id).toBe('v1');
  });

  it('ignore un véhicule hors flotte (jamais de donnée fabriquée)', () => {
    const trips = [trip({ vehicle_id: 'inconnu' }), trip({ vehicle_id: 'v1' })];
    const r = deriveRecentVehicles(trips, FLEET);
    expect(r.map((v) => v.id)).toEqual(['v1']);
  });

  it('respecte la limite max', () => {
    const trips = [
      trip({ vehicle_id: 'v1' }),
      trip({ vehicle_id: 'v2' }),
      trip({ vehicle_id: 'v3' }),
    ];
    const r = deriveRecentVehicles(trips, FLEET, 2);
    expect(r).toHaveLength(2);
  });
});
