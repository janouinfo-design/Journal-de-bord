/**
 * Tests unitaires du store flotte (recherche locale scalable).
 */
import { useVehiclesStore } from '@/store/vehiclesStore';

jest.mock('@/api/ble', () => ({
  getVehicles: jest.fn(),
}));
jest.mock('@/utils/logger', () => ({ logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn() } }));

import * as ble from '@/api/ble';

const FLEET = [
  { id: 'v1', plate: 'GE 123456', model: 'Mercedes Sprinter' },
  { id: 'v2', plate: 'GE 234567', model: 'VW Crafter' },
  { id: 'v3', plate: 'VD 999000', model: 'Renault Trafic' },
];

const reset = () =>
  useVehiclesStore.setState({ vehicles: [], loading: false, error: null, loaded: false });

describe('vehiclesStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    reset();
  });

  it('charge la flotte (triée par plaque) et met loaded=true', async () => {
    (ble.getVehicles as jest.Mock).mockResolvedValue([...FLEET].reverse());
    await useVehiclesStore.getState().load();
    const v = useVehiclesStore.getState().vehicles;
    expect(v).toHaveLength(3);
    expect(v[0].plate).toBe('GE 123456'); // trié
    expect(useVehiclesStore.getState().loaded).toBe(true);
  });

  it('ne recharge pas si déjà chargé (cache)', async () => {
    (ble.getVehicles as jest.Mock).mockResolvedValue(FLEET);
    await useVehiclesStore.getState().load();
    await useVehiclesStore.getState().load(); // 2e appel ignoré
    expect(ble.getVehicles).toHaveBeenCalledTimes(1);
  });

  it('recherche vide -> toute la flotte', () => {
    useVehiclesStore.setState({ vehicles: FLEET, loaded: true });
    expect(useVehiclesStore.getState().search('')).toHaveLength(3);
  });

  it('recherche par plaque partielle (insensible casse)', () => {
    useVehiclesStore.setState({ vehicles: FLEET, loaded: true });
    const r = useVehiclesStore.getState().search('ge 123');
    expect(r).toHaveLength(1);
    expect(r[0].plate).toBe('GE 123456');
  });

  it('recherche tolérante aux espaces : "GE123" trouve "GE 123456"', () => {
    useVehiclesStore.setState({ vehicles: FLEET, loaded: true });
    const r = useVehiclesStore.getState().search('GE123');
    expect(r.map((x) => x.plate)).toContain('GE 123456');
  });

  it('recherche par modèle', () => {
    useVehiclesStore.setState({ vehicles: FLEET, loaded: true });
    const r = useVehiclesStore.getState().search('sprinter');
    expect(r).toHaveLength(1);
    expect(r[0].model).toBe('Mercedes Sprinter');
  });

  it('aucun résultat', () => {
    useVehiclesStore.setState({ vehicles: FLEET, loaded: true });
    expect(useVehiclesStore.getState().search('zzzzz')).toHaveLength(0);
  });
});
