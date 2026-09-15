/* Détection front d'un trajet en mode Privé (device), miroir du backend
 * `private_mode_engine.trip_is_private`. Source autoritaire = marqueur métier
 * renvoyé par le backend (jamais déduit de coordonnées).
 *
 * Le backend REDACTE déjà toute localisation d'un trajet privé (lat/lng/adresse
 * = null) et ajoute `private_redacted: true`. Côté web on n'affiche donc jamais
 * de position pour ces trajets — on montre explicitement « Position masquée ».
 */
export function isPrivateTrip(t) {
  if (!t || typeof t !== "object") return false;
  if (t.private_redacted === true) return true;
  if (t.private_mode === true) return true;
  if (typeof t.mode_status === "string" && t.mode_status.toUpperCase() === "PRIVATE") return true;
  if (t.privacy === "private") return true;
  return false;
}
