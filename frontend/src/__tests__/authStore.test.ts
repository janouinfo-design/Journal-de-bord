/**
 * Tests unitaires du store d'authentification.
 * Vérifie : mapping name -> full_name, flux must_change_password, message d'erreur générique.
 */
import { useAuthStore } from '@/store/authStore';

jest.mock('@/api/client', () => ({
  fetchMe: jest.fn(),
  login: jest.fn(),
  logout: jest.fn(),
  getAccessToken: jest.fn(),
}));
jest.mock('@/api/ble', () => ({
  getMyProfile: jest.fn(),
}));
jest.mock('@/utils/logger', () => ({ logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn() } }));

import * as client from '@/api/client';
import * as ble from '@/api/ble';

const reset = () =>
  useAuthStore.setState({ user: null, loading: true, error: null, mustChangePassword: false });

describe('authStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    reset();
  });

  it('mappe name -> full_name à la connexion', async () => {
    (client.login as jest.Mock).mockResolvedValue({
      user: { id: '1', email: 'c@x.ch', role: 'driver', name: 'Jean Dupont' },
      access_token: 'a',
      refresh_token: 'r',
    });
    (ble.getMyProfile as jest.Mock).mockResolvedValue({ must_change_password: false });

    const ok = await useAuthStore.getState().signIn('c@x.ch', 'pw');
    expect(ok).toBe(true);
    expect(useAuthStore.getState().user?.full_name).toBe('Jean Dupont');
  });

  it('active mustChangePassword quand le profil le demande', async () => {
    (client.login as jest.Mock).mockResolvedValue({
      user: { id: '1', email: 'c@x.ch', role: 'driver', name: 'X' },
      access_token: 'a',
    });
    (ble.getMyProfile as jest.Mock).mockResolvedValue({ must_change_password: true });

    await useAuthStore.getState().signIn('c@x.ch', 'pw');
    expect(useAuthStore.getState().mustChangePassword).toBe(true);
  });

  it('clearMustChangePassword remet le drapeau à false', () => {
    useAuthStore.setState({ mustChangePassword: true });
    useAuthStore.getState().clearMustChangePassword();
    expect(useAuthStore.getState().mustChangePassword).toBe(false);
  });

  it('affiche le message serveur générique sur échec de login', async () => {
    (client.login as jest.Mock).mockRejectedValue({
      response: { data: { detail: 'Identifiants incorrects ou accès temporairement bloqué' } },
    });
    const ok = await useAuthStore.getState().signIn('c@x.ch', 'bad');
    expect(ok).toBe(false);
    expect(useAuthStore.getState().error).toMatch(/Identifiants incorrects/);
  });
});
