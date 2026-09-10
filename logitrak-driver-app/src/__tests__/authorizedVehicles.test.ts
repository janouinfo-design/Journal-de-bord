/**
 * P0/P1 — Périmètre véhicules AUTORISÉS (source d'autorité backend /driver/vehicles).
 * Vérifie que l'app consomme le bon endpoint et n'invente aucun véhicule.
 */
import { apiClient } from '@/api/client';
import { getAuthorizedVehicles, getMyVehicles, getVehicles } from '@/api/ble';

jest.mock('@/api/client', () => ({
  apiClient: { get: jest.fn() },
}));

const mockGet = apiClient.get as jest.Mock;

describe('getAuthorizedVehicles — /driver/vehicles', () => {
  beforeEach(() => jest.clearAllMocks());

  it('appelle /api/livre/driver/vehicles (périmètre autorisé, jamais /livre/vehicles)', async () => {
    mockGet.mockResolvedValue({
      data: { access_mode: 'SELECTED', default_vehicle_id: 'v2', vehicles: [
        { id: 'v1', plate: 'FR 275924', model: 'VW Tiguan' },
        { id: 'v2', plate: 'GE 100000', model: 'VW Crafter' },
      ] },
    });
    const r = await getAuthorizedVehicles();
    expect(mockGet).toHaveBeenCalledWith('/api/livre/driver/vehicles');
    expect(r.access_mode).toBe('SELECTED');
    expect(r.default_vehicle_id).toBe('v2');
    expect(r.vehicles).toHaveLength(2);
  });

  it('liste vide autorisée -> vehicles=[] (jamais de fallback arbitraire)', async () => {
    mockGet.mockResolvedValue({ data: { access_mode: 'SELECTED', default_vehicle_id: null, vehicles: [] } });
    const r = await getAuthorizedVehicles();
    expect(r.vehicles).toEqual([]);
    expect(r.default_vehicle_id).toBeNull();
  });

  it('payload malformé -> défauts sûrs (access_mode ALL, vehicles [])', async () => {
    mockGet.mockResolvedValue({ data: {} });
    const r = await getAuthorizedVehicles();
    expect(r.access_mode).toBe('ALL');
    expect(r.vehicles).toEqual([]);
  });

  it('erreur réseau -> rejette (l’UI doit afficher ERROR, jamais EMPTY)', async () => {
    mockGet.mockRejectedValue(new Error('network'));
    await expect(getAuthorizedVehicles()).rejects.toThrow();
  });

  it('getMyVehicles et getVehicles dérivent du périmètre autorisé', async () => {
    mockGet.mockResolvedValue({ data: { access_mode: 'ALL', default_vehicle_id: null, vehicles: [
      { id: 'v1', plate: 'FR 275924', model: 'VW Tiguan' },
    ] } });
    expect(await getMyVehicles()).toHaveLength(1);
    expect(await getVehicles()).toHaveLength(1);
    // Aucun appel à l'ancien endpoint flotte complète.
    expect(mockGet).not.toHaveBeenCalledWith('/api/livre/vehicles');
    expect(mockGet).not.toHaveBeenCalledWith('/api/livre/driver/my-vehicles');
  });
});
