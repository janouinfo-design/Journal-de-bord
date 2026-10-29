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
  useAuthStore.setState({
    user: null, loading: true, error: null, mustChangePassword: false,
    access: { modules: [], permissions: [], mode: 'legacy', loaded: false },
  });

describe('authStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    reset();
    (client.fetchMe as jest.Mock).mockResolvedValue({
      user: { id: '1', email: 'c@x.ch', role: 'driver', name: 'Jean Dupont' },
      access_control_mode: 'enforce',
      modules_enabled: ['journal', 'drivers'],
      permissions_effective: ['journal.view_self', 'identification.self'],
    });
  });

  it('mappe name -> full_name à la connexion et charge modules / permissions', async () => {
    (client.login as jest.Mock).mockResolvedValue({
      user: { id: '1', email: 'c@x.ch', role: 'driver', name: 'Jean Dupont' },
      access_token: 'a',
      refresh_token: 'r',
    });
    (ble.getMyProfile as jest.Mock).mockResolvedValue({ must_change_password: false });

    const ok = await useAuthStore.getState().signIn('c@x.ch', 'pw');
    expect(ok).toBe(true);
    expect(useAuthStore.getState().user?.full_name).toBe('Jean Dupont');
    expect(useAuthStore.getState().access).toEqual({
      modules: ['journal', 'drivers'], permissions: ['journal.view_self', 'identification.self'], mode: 'enforce',
      loaded: true,
    });
    expect(useAuthStore.getState().hasModule('drivers')).toBe(true);
    expect(useAuthStore.getState().hasModule('fines')).toBe(false);
    expect(useAuthStore.getState().can('identification.self')).toBe(true);
    expect(useAuthStore.getState().can('trips.classify_self')).toBe(false);
  });

  it('connexion réussie même si /auth/me enrichi échoue (accès vide)', async () => {
    (client.login as jest.Mock).mockResolvedValue({
      user: { id: '1', email: 'c@x.ch', role: 'driver', name: 'X' }, access_token: 'a',
    });
    (client.fetchMe as jest.Mock).mockRejectedValue(new Error('offline'));
    (ble.getMyProfile as jest.Mock).mockResolvedValue({ must_change_password: false });
    expect(await useAuthStore.getState().signIn('c@x.ch', 'pw')).toBe(true);
    expect(useAuthStore.getState().access.modules).toEqual([]);
    expect(useAuthStore.getState().access.loaded).toBe(false);
    // accès inconnu ⇒ rien n'est masqué côté UI
    expect(useAuthStore.getState().hasModule('private_mode')).toBe(true);
    expect(useAuthStore.getState().can('trips.classify_self')).toBe(true);
  });

  it('bootstrap : compte désactivé → session purgée avec message lisible', async () => {
    (client.getAccessToken as jest.Mock).mockResolvedValue('tok');
    (client.fetchMe as jest.Mock).mockRejectedValue({ response: { status: 401, data: { detail: { code: 'account_disabled' } } } });
    await useAuthStore.getState().bootstrap();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().error).toMatch(/désactivé/);
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
