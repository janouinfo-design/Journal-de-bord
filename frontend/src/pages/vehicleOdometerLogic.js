/**
 * Logique FAIL-CLOSED de la calibration odomètre (UI).
 * Extrait en fonctions pures pour être testable sans navigateur.
 *
 * RÈGLE ABSOLUE : le bouton de calibration n'est actif QUE si can_calibrate === true.
 * Aucun fallback sur device_write_enabled. Tout autre cas (false / null / undefined /
 * propriété absente / état null suite à une erreur GET) => bouton désactivé, aucun POST.
 */

/** true UNIQUEMENT si le backend renvoie explicitement can_calibrate === true. */
export function canCalibrate(state) {
  return state?.can_calibrate === true;
}

/**
 * Le bouton « Synchroniser » est-il désactivé ?
 * Désactivé si : gate backend non autorisée, soumission en cours, ou saisie vide.
 */
export function syncDisabled({ state, submitting, dashKm } = {}) {
  if (!canCalibrate(state)) return true;   // fail-closed
  if (submitting) return true;
  if (!dashKm) return true;                 // pas de valeur saisie
  return false;
}

/** Peut-on ouvrir la confirmation / lancer un POST ? (garde fail-closed) */
export function canAttemptCalibration(state) {
  return canCalibrate(state);
}
