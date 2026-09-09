export type AccessMode = 'ALL' | 'SELECTED' | 'SINGLE';

export type SelectionInput = {
  accessMode: AccessMode;
  vehicles: Array<{ id: string }>;
  defaultVehicleId?: string | null;
  currentSelectedId?: string | null;
  storedId?: string | null;
};

export type SelectionResult = {
  selectedId: string | null;
  locked: boolean;
  revoked: boolean;
};

/**
 * Résolution de la sélection véhicule côté chauffeur — parité Console web (T1–T10).
 *
 * Priorité :
 *   1. sélection active encore AUTORISÉE (jamais écrasée) ;
 *   2. sélection mémorisée si encore autorisée ;
 *   3. véhicule par défaut UNIQUEMENT s'il appartient au périmètre autorisé ;
 *   4. véhicule unique (mode SINGLE ou liste à un seul élément).
 *
 * JAMAIS le premier véhicule d'une liste multiple sans défaut (pas de choix arbitraire).
 * `revoked` = la sélection active a perdu son autorisation (à signaler à l'utilisateur).
 * `locked`  = mode SINGLE : le choix n'est pas modifiable.
 */
export function resolveVehicleSelection(input: SelectionInput): SelectionResult {
  const ids = new Set((input.vehicles || []).map((v) => v.id));
  const locked = input.accessMode === 'SINGLE';

  const current = input.currentSelectedId ?? null;
  if (current && ids.has(current)) {
    return { selectedId: current, locked, revoked: false };
  }
  const revoked = current !== null;

  const stored = input.storedId ?? null;
  if (stored && ids.has(stored)) {
    return { selectedId: stored, locked, revoked };
  }

  const def = input.defaultVehicleId ?? null;
  if (def && ids.has(def)) {
    return { selectedId: def, locked, revoked };
  }

  if (ids.size === 1) {
    return { selectedId: input.vehicles[0].id, locked, revoked };
  }

  return { selectedId: null, locked, revoked };
}
