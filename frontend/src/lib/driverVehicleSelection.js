// Sélection de véhicule côté Console Chauffeur — logique pure, fail-closed.
// Priorité : sélection active valide → localStorage valide → default backend → unique → aucune.

export const STORAGE_PREFIX = "logitrak.driver.vehicle.";

export function storageKey(userKey) {
  return `${STORAGE_PREFIX}${userKey || "anon"}`;
}

export function resolveVehicleSelection({ vehicles, defaultVehicleId, storedId, currentId }) {
  const list = Array.isArray(vehicles) ? vehicles : [];
  const ids = new Set(list.map((v) => v.id));
  const out = { selectedId: null, purgeStored: false, revoked: false };

  if (storedId && !ids.has(storedId)) out.purgeStored = true;
  if (currentId && !ids.has(currentId)) out.revoked = true;

  if (currentId && ids.has(currentId)) {
    out.selectedId = currentId;
    return out;
  }
  if (storedId && ids.has(storedId)) {
    out.selectedId = storedId;
    return out;
  }
  if (defaultVehicleId && ids.has(defaultVehicleId)) {
    out.selectedId = defaultVehicleId;
    return out;
  }
  if (list.length === 1) {
    out.selectedId = list[0].id;
    return out;
  }
  return out;
}
