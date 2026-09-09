/**
 * Tests unitaires du store véhicules AUTORISÉS (source d'autorité /driver/vehicles).
 */
import { useVehiclesStore } from '@/store/vehiclesStore';

jest.mock('@/api/ble', () => ({
  getDriverVehicles: jest.fn(),
}));
jest.mock('@/utils/logger', () => ({ logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn() } }));

import * as ble from '@/api/ble';

const ACCESS_ALL = {
  access_mode: 'ALL',
  default_vehicle_id: null,
  vehicles: [
    { id: 'v3', plate: 'VD 999000', model: 'Renault Trafic' },
    { id: 'v1', plate: 'GE 123456', model: 'Mercedes Sprinter' },
    { id: 'v2', plate: 'GE 234567', model: 'VW Crafter' },
  ],
};

const reset = () =>
  useVehiclesStore.setState({
    vehicles: [], accessMode: null, defaultVehicleId: null,
    loading: false, error: null, loaded: false,
  });

describe('vehiclesStore (périmètre autorisé chauffeur)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    reset();
  });

  it('charge le périmètre autorisé (trié par plaque) + mode + défaut', async () => {
    (ble.getDriverVehicles as jest.Mock).mockResolvedValue({
      ...ACCESS_ALL,
      default_vehicle_id: 'v2',
    });
    await useVehiclesStore.getState().load();
    const st = useVehiclesStore.getState();
    expect(st.vehicles.map((v) => v.plate)).toEqual(['GE 123456', 'GE 234567', 'VD 999000']);
    expect(st.accessMode).toBe('ALL');
    expect(st.defaultVehicleId).toBe('v2');
    expect(st.loaded).toBe(true);
    expect(st.error).toBeNull();
  });

  it('ne recharge pas si déjà chargé (cache), sauf force=true', async () => {
    (ble.getDriverVehicles as jest.Mock).mockResolvedValue(ACCESS_ALL);
    await useVehiclesStore.getState().load();
    await useVehiclesStore.getState().load();
    expect(ble.getDriverVehicles).toHaveBeenCalledTimes(1);
    await useVehiclesStore.getState().load(true);
    expect(ble.getDriverVehicles).toHaveBeenCalledTimes(2);
  });

  it('SELECTED : expose uniquement la liste autorisée retournée par le backend', async () => {
    (ble.getDriverVehicles as jest.Mock).mockResolvedValue({
      access_mode: 'SELECTED',
      default_vehicle_id: null,
      vehicles: [{ id: 'v1', plate: 'GE 123456', model: null }],
    });
    await useVehiclesStore.getState().load();
    const st = useVehiclesStore.getState();
    expect(st.accessMode).toBe('SELECTED');
    expect(st.vehicles).toHaveLength(1);
  });

  it('FAIL-CLOSED : erreur API => liste vidée + erreur explicite + loaded=false', async () => {
    (ble.getDriverVehicles as jest.Mock).mockResolvedValue(ACCESS_ALL);
    await useVehiclesStore.getState().load();
    expect(useVehiclesStore.getState().vehicles).toHaveLength(3);

    (ble.getDriverVehicles as jest.Mock).mockRejectedValue(new Error('network'));
    await useVehiclesStore.getState().load(true);
    const st = useVehiclesStore.getState();
    expect(st.vehicles).toEqual([]);          // aucune liste résiduelle
    expect(st.error).toBeTruthy();
    expect(st.loaded).toBe(false);            // un retry refetchera
  });

  it('liste vide réelle : pas une erreur (empty state distinct)', async () => {
    (ble.getDriverVehicles as jest.Mock).mockResolvedValue({
      access_mode: 'SELECTED', default_vehicle_id: null, vehicles: [],
    });
    await useVehiclesStore.getState().load();
    const st = useVehiclesStore.getState();
    expect(st.vehicles).toEqual([]);
    expect(st.error).toBeNull();
    expect(st.loaded).toBe(true);
  });

  it('recherche locale : plaque, modèle, insensible casse/espaces', async () => {
    (ble.getDriverVehicles as jest.Mock).mockResolvedValue(ACCESS_ALL);
    await useVehiclesStore.getState().load();
    const { search } = useVehiclesStore.getState();
    expect(search('').length).toBe(3);
    expect(search('ge 123').map((v) => v.id)).toEqual(['v1']);
    expect(search('GE123').map((v) => v.id)).toEqual(['v1']);
    expect(search('trafic').map((v) => v.id)).toEqual(['v3']);
    expect(search('zzz')).toEqual([]);
  });
});
