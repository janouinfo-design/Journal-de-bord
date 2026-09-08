/**
 * Tests unitaires du store des trajets (Mes trajets + classification).
 * Vérifie : chargement, liste vide, erreur API, classify PRO/PRIVÉ (confirmation-first),
 * erreur backend, accès refusé (403), garde anti-double-clic.
 */
import { useTripsStore } from '@/store/tripsStore';

jest.mock('@/api/trips', () => ({
  getTrips: jest.fn(),
  classifyTrip: jest.fn(),
}));
jest.mock('@/utils/logger', () => ({ logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn() } }));

import * as trips from '@/api/trips';

const reset = () =>
  useTripsStore.setState({
    trips: [],
    settingsMode: undefined,
    loading: false,
    error: null,
    classifyingId: null,
  });

const T = (over: any = {}) => ({
  id: 't1',
  vehicle_plate: 'GE 123456',
  start_time: '2026-08-18T17:05:00+00:00',
  end_time: '2026-08-18T17:13:00+00:00',
  distance_km: 7.8,
  duration_min: 8,
  classification: 'professional',
  ...over,
});

describe('tripsStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    reset();
  });

  it('charge la liste des trajets', async () => {
    (trips.getTrips as jest.Mock).mockResolvedValue({ trips: [T(), T({ id: 't2' })], settings_mode: 'mixte' });
    await useTripsStore.getState().load();
    expect(useTripsStore.getState().trips).toHaveLength(2);
    expect(useTripsStore.getState().settingsMode).toBe('mixte');
    expect(useTripsStore.getState().error).toBeNull();
  });

  it('gère une liste vide', async () => {
    (trips.getTrips as jest.Mock).mockResolvedValue({ trips: [], settings_mode: 'mixte' });
    await useTripsStore.getState().load();
    expect(useTripsStore.getState().trips).toHaveLength(0);
    expect(useTripsStore.getState().error).toBeNull();
  });

  it('gère une erreur API au chargement', async () => {
    (trips.getTrips as jest.Mock).mockRejectedValue({ response: { data: { detail: 'boom' } } });
    await useTripsStore.getState().load();
    expect(useTripsStore.getState().error).toBe('boom');
  });

  it('classe un trajet PRIVÉ après confirmation serveur', async () => {
    useTripsStore.setState({ trips: [T({ classification: 'professional' })] });
    (trips.classifyTrip as jest.Mock).mockResolvedValue({ ok: true });
    const res = await useTripsStore.getState().classify('t1', 'personal');
    expect(res.ok).toBe(true);
    expect(useTripsStore.getState().trips[0].classification).toBe('personal');
  });

  it('classe un trajet PRO après confirmation serveur', async () => {
    useTripsStore.setState({ trips: [T({ classification: 'personal' })] });
    (trips.classifyTrip as jest.Mock).mockResolvedValue({ ok: true });
    const res = await useTripsStore.getState().classify('t1', 'professional');
    expect(res.ok).toBe(true);
    expect(useTripsStore.getState().trips[0].classification).toBe('professional');
  });

  it("n'applique PAS le changement si le backend échoue", async () => {
    useTripsStore.setState({ trips: [T({ classification: 'professional' })] });
    (trips.classifyTrip as jest.Mock).mockRejectedValue({ response: { status: 500 } });
    const res = await useTripsStore.getState().classify('t1', 'personal');
    expect(res.ok).toBe(false);
    expect(useTripsStore.getState().trips[0].classification).toBe('professional'); // inchangé
  });

  it('renvoie un message clair sur accès refusé (403)', async () => {
    useTripsStore.setState({ trips: [T()] });
    (trips.classifyTrip as jest.Mock).mockRejectedValue({ response: { status: 403 } });
    const res = await useTripsStore.getState().classify('t1', 'personal');
    expect(res.ok).toBe(false);
    expect(res.message).toMatch(/vos propres trajets/i);
  });

  it('anti-double-clic : une 2e classification pendant traitement est ignorée', async () => {
    useTripsStore.setState({ trips: [T()], classifyingId: 't1' });
    const res = await useTripsStore.getState().classify('t1', 'personal');
    expect(res.ok).toBe(false);
    expect(trips.classifyTrip).not.toHaveBeenCalled();
  });
});
