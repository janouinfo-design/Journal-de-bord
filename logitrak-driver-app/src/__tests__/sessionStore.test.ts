/**
 * Tests unitaires du store de session.
 * Vérifie : garde anti-double-clic (submitting), idempotence de « Je m'arrête »,
 * mise à jour de session sur claim confirmé, et détection de conflit.
 */
import { useSessionStore } from '@/store/sessionStore';

jest.mock('@/api/ble', () => ({
  getCurrentSession: jest.fn(),
  setManualMode: jest.fn(),
  claimVehicle: jest.fn(),
  stopDriving: jest.fn(),
}));
jest.mock('@/utils/logger', () => ({ logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn() } }));

import * as ble from '@/api/ble';

const reset = () =>
  useSessionStore.setState({
    session: null,
    loading: false,
    lastFetch: null,
    conflict: false,
    submitting: false,
  });

describe('sessionStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    reset();
  });

  it('claim confirmé met à jour la session et rafraîchit', async () => {
    const session = { id: 's1', status: 'confirmed', active_driver: true, vehicle: { plate: 'GE 1' } };
    (ble.claimVehicle as jest.Mock).mockResolvedValue({ status: 'confirmed', session });
    (ble.getCurrentSession as jest.Mock).mockResolvedValue(session);

    const res = await useSessionStore.getState().claim('veh-1');
    expect('status' in res && res.status).toBe('confirmed');
    expect(ble.claimVehicle).toHaveBeenCalledWith('veh-1');
    expect(useSessionStore.getState().submitting).toBe(false);
  });

  it('claim en conflit active le drapeau conflict', async () => {
    (ble.claimVehicle as jest.Mock).mockResolvedValue({ status: 'conflict', session: null });
    (ble.getCurrentSession as jest.Mock).mockResolvedValue(null);
    await useSessionStore.getState().claim('veh-1');
    expect(useSessionStore.getState().conflict).toBe(true);
  });

  it('stop avec session active renvoie stopped:true', async () => {
    (ble.stopDriving as jest.Mock).mockResolvedValue({
      stopped: true,
      vehicle_plate: 'GE 123456',
      session: { id: 's1', status: 'closed' },
    });
    (ble.getCurrentSession as jest.Mock).mockResolvedValue(null);
    const res = await useSessionStore.getState().stop();
    expect('stopped' in res && res.stopped).toBe(true);
  });

  it('stop idempotent renvoie stopped:false sans erreur', async () => {
    (ble.stopDriving as jest.Mock).mockResolvedValue({
      stopped: false,
      message: 'Aucune session active',
    });
    (ble.getCurrentSession as jest.Mock).mockResolvedValue(null);
    const res = await useSessionStore.getState().stop();
    expect('stopped' in res && res.stopped).toBe(false);
  });

  it('anti-double-clic : un second stop pendant submitting est ignoré', async () => {
    useSessionStore.setState({ submitting: true });
    const res = await useSessionStore.getState().stop();
    expect('error' in res).toBe(true);
    expect(ble.stopDriving).not.toHaveBeenCalled();
  });

  it('détecte le conflit lors du refresh', async () => {
    (ble.getCurrentSession as jest.Mock).mockResolvedValue({ id: 's', status: 'conflict' });
    await useSessionStore.getState().refresh();
    expect(useSessionStore.getState().conflict).toBe(true);
  });
});
