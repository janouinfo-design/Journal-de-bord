/**
 * Lot 5 — politique d'accès de l'app chauffeur : onglets visibles selon modules / permissions,
 * et traduction des erreurs d'accès structurées renvoyées par le backend.
 */
import { visibleTabs, can, hasModule, EMPTY_ACCESS } from '@/navigation/tabsPolicy';
import { describeApiError, isAccessDenied, errorCode } from '@/utils/apiError';

const DRIVER_ACCESS = {
  modules: ['journal', 'trip_classification', 'private_mode', 'drivers', 'energy', 'fuel', 'fines', 'reports', 'notifications'],
  permissions: ['journal.view_self', 'trips.classify_self', 'identification.self', 'fuel.view_self', 'fines.view_self',
    'notifications.manage_self', 'work_schedule.view'],
  mode: 'enforce',
  loaded: true,
};
const LOADED_EMPTY = { ...EMPTY_ACCESS, loaded: true };

const err = (status: number, detail: unknown) => ({ response: { status, data: { detail } } });

describe('tabsPolicy', () => {
  it('chauffeur complet : 4 onglets', () => {
    expect(visibleTabs(DRIVER_ACCESS, 'driver')).toEqual(['Conduite', 'Trajets', 'Profil', 'Reglages']);
  });

  it('module drivers coupé : plus de Conduite', () => {
    const access = { ...DRIVER_ACCESS, modules: DRIVER_ACCESS.modules.filter((m) => m !== 'drivers') };
    expect(visibleTabs(access, 'driver')).toEqual(['Trajets', 'Profil', 'Reglages']);
  });

  it('permission journal.view_self retirée : plus de Trajets', () => {
    const access = { ...DRIVER_ACCESS, permissions: DRIVER_ACCESS.permissions.filter((p) => p !== 'journal.view_self') };
    expect(visibleTabs(access, 'driver')).toEqual(['Conduite', 'Profil', 'Reglages']);
  });

  it('accès non chargé (/auth/me indisponible ou ancien backend) : rien n\'est masqué, le serveur tranche', () => {
    expect(visibleTabs(EMPTY_ACCESS, 'driver')).toEqual(['Conduite', 'Trajets', 'Profil', 'Reglages']);
    expect(hasModule(EMPTY_ACCESS, 'private_mode')).toBe(true);
    expect(can(EMPTY_ACCESS, 'driver', 'trips.classify_self')).toBe(true);
  });

  it('accès chargé mais vide : seuls Profil et Réglages restent', () => {
    expect(visibleTabs(LOADED_EMPTY, 'driver')).toEqual(['Profil', 'Reglages']);
  });

  it('superadmin : toujours autorisé par can(), modules respectés', () => {
    expect(can(LOADED_EMPTY, 'superadmin', 'identification.self')).toBe(true);
    expect(hasModule(LOADED_EMPTY, 'drivers')).toBe(false);
    expect(hasModule(LOADED_EMPTY, undefined)).toBe(true);
  });
});

describe('apiError', () => {
  it('traduit les codes structurés', () => {
    expect(describeApiError(err(403, { code: 'module_disabled', module: 'fines' }), 'x'))
      .toMatch(/pas activée pour votre entreprise/);
    expect(describeApiError(err(403, { code: 'permission_denied', permission: 'positions.view' }), 'x'))
      .toMatch(/autorisation/);
    expect(describeApiError(err(401, { code: 'account_disabled' }), 'x')).toMatch(/désactivé/);
    expect(describeApiError(err(403, { code: 'tenant_suspended', msg: 'Client suspendu' }), 'x')).toMatch(/suspendu/);
  });

  it('conserve les refus legacy texte et le repli', () => {
    expect(describeApiError(err(403, 'Accès refusé'), 'x')).toBe('Accès refusé');
    expect(describeApiError(err(500, null), 'Repli')).toBe('Repli');
    expect(describeApiError(new Error('network'), 'Repli')).toBe('Repli');
    expect(describeApiError(err(400, { msg: 'Message serveur' }), 'x')).toBe('Message serveur');
  });

  it('isAccessDenied / errorCode', () => {
    expect(isAccessDenied(err(403, { code: 'permission_denied' }))).toBe(true);
    expect(isAccessDenied(err(403, 'Accès refusé'))).toBe(false);
    expect(errorCode(err(401, { code: 'account_disabled' }))).toBe('account_disabled');
    expect(errorCode(err(403, 'x'))).toBeNull();
  });
});
