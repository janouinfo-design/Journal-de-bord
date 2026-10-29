/**
 * Politique d'affichage des onglets de l'app chauffeur (Lot 5).
 * Pure : testable sans React. Le backend reste l'autorité (403 en mode Appliqué) ;
 * ici on évite seulement de montrer des écrans que le client n'a pas souscrits
 * ou que l'utilisateur n'a pas le droit d'utiliser.
 * Tant que l'accès n'est pas chargé (`loaded=false` : /auth/me indisponible ou ancien backend),
 * rien n'est masqué — le serveur tranche et l'app affiche un message lisible.
 */
export type Access = { modules: string[]; permissions: string[]; mode: string; loaded: boolean };

export type TabName = 'Conduite' | 'Trajets' | 'Profil' | 'Reglages';

export const TAB_POLICY: Record<TabName, { module?: string; perms?: string[] }> = {
  Conduite: { module: 'drivers', perms: ['identification.self', 'identification.edit'] },
  Trajets: { module: 'journal', perms: ['journal.view_self', 'journal.view'] },
  Profil: {},
  Reglages: {},
};

export const ALL_TABS = Object.keys(TAB_POLICY) as TabName[];

export const EMPTY_ACCESS: Access = { modules: [], permissions: [], mode: 'legacy', loaded: false };

export function hasModule(access: Access, code?: string): boolean {
  return !code || !access.loaded || access.modules.includes(code);
}

export function can(access: Access, role: string | undefined, ...perms: string[]): boolean {
  if (role === 'superadmin' || perms.length === 0 || !access.loaded) return true;
  return perms.some((p) => access.permissions.includes(p));
}

export function visibleTabs(access: Access, role: string | undefined): TabName[] {
  if (!access.loaded) return ALL_TABS;
  return ALL_TABS.filter((name) => {
    const p = TAB_POLICY[name];
    return hasModule(access, p.module) && can(access, role, ...(p.perms ?? []));
  });
}
