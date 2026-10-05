/**
 * Feature flags côté app chauffeur.
 *
 * PHASE 1 BLE — l'écran technique de lecture BLE Private/Business est strictement
 * réservé au développement, jamais exposé en production.
 *
 * Activation DÉTERMINISTE par variable d'environnement Expo publique, injectée
 * au build EAS (uniquement dans le profil `pilot-dev-ble`) :
 *   EXPO_PUBLIC_PRIVATE_MODE_BLE_DEV=1
 *
 * On NE dépend PLUS de `__DEV__` : son état n'est pas garanti sur un APK
 * dev-client lancé sans Metro. Le garde-fou « jamais en production » est assuré
 * par l'ABSENCE de cette variable dans les profils production / pilot-production.
 * Fail-closed : variable absente ou != '1' -> OFF (seule la valeur exacte "1" active).
 *
 * NOTE TEST : `babel-preset-expo` INLINE les EXPO_PUBLIC_* à la compilation. La
 * LOGIQUE est donc isolée dans des fonctions PURES (paramétrées) — testables de
 * façon déterministe — et les constantes exportées ne sont que des applications
 * de ces fonctions à la valeur d'environnement réelle du build.
 */

// ---------------------------------------------------------------------------
// LOGIQUE PURE (testable, indépendante de l'inlining EXPO_PUBLIC_*)
// ---------------------------------------------------------------------------

/** Seule la valeur exacte "1" active la fonction (fail-closed). */
export function computeBleDevEnabled(raw: string | undefined | null): boolean {
  return raw === '1';
}

/** Parse une allowlist CSV en liste normalisée (vide si absente). */
export function parseAllowedTrackers(csv: string | undefined | null): string[] {
  return (csv || '').split(',').map((s) => s.trim()).filter(Boolean);
}

/** Correspondance EXACTE (jamais sous-chaîne) d'un id contre une allowlist. */
export function isTrackerAllowed(
  trackerId: string | null | undefined,
  allowlist: string[],
): boolean {
  if (!trackerId) return false;
  if (!allowlist || allowlist.length === 0) return false; // fail-closed
  const normalized = String(trackerId).trim();
  return allowlist.some((allowed) => normalized === allowed.trim());
}

/**
 * Extraction DÉTERMINISTE de candidats-identifiants depuis un nom BLE, par
 * découpage sur séparateurs NON alphanumériques (jamais par sous-chaîne).
 * Ex : "FMC-781479-x" -> ["FMC","781479","x"] ; "17814790" -> ["17814790"].
 *
 * ⚠️ Le format réel du nom BLE annoncé par le FMC130 781479 n'est PAS supposé :
 * il doit être CONFIRMÉ au premier scan terrain (l'écran DEV journalise le nom
 * détecté). Si l'exact match échoue, ajuster EXPO_PUBLIC_BLE_DEV_ALLOWED_TRACKERS
 * avec la valeur réelle. On ne suppose jamais un format non vérifié.
 */
export function extractCandidateTrackerIds(bleName: string | null | undefined): string[] {
  if (!bleName) return [];
  return String(bleName).split(/[^A-Za-z0-9]+/).map((s) => s.trim()).filter(Boolean);
}

/**
 * Un périphérique BLE est-il autorisé vis-à-vis d'une allowlist donnée ? Vérifie,
 * en EXACT match : les identifiants bruts (name/localName/id) ET les tokens
 * extraits de name/localName. Fail-closed : rien ne matche -> false.
 */
export function isBleDeviceAllowed(
  d: { name?: string | null; localName?: string | null; id?: string | null },
  allowlist: string[],
): boolean {
  if (!allowlist || allowlist.length === 0) return false;
  const rawCandidates = [d.name, d.localName, d.id].filter(Boolean) as string[];
  const tokenCandidates = [
    ...extractCandidateTrackerIds(d.name),
    ...extractCandidateTrackerIds(d.localName),
  ];
  const all = [...rawCandidates.map((s) => s.trim()), ...tokenCandidates];
  return all.some((c) => isTrackerAllowed(c, allowlist));
}

// ---------------------------------------------------------------------------
// APPLICATION aux variables d'environnement réelles du build (inlinées par EAS)
// ---------------------------------------------------------------------------

/** true UNIQUEMENT si EXPO_PUBLIC_PRIVATE_MODE_BLE_DEV vaut exactement '1'. */
export const PRIVATE_MODE_BLE_DEV: boolean =
  computeBleDevEnabled(process.env.EXPO_PUBLIC_PRIVATE_MODE_BLE_DEV);

/** Allowlist effective (garde-fou pilote). Vide -> fail-closed. */
export const BLE_DEV_ALLOWED_TRACKERS: string[] =
  parseAllowedTrackers(process.env.EXPO_PUBLIC_BLE_DEV_ALLOWED_TRACKERS);

/** Exact match d'un id tracker contre l'allowlist effective. */
export function isTrackerAllowedForBleDev(trackerId: string | null | undefined): boolean {
  return isTrackerAllowed(trackerId, BLE_DEV_ALLOWED_TRACKERS);
}

/** Le périphérique réellement détecté est-il autorisé (allowlist effective) ? */
export function isBleDeviceAllowedForDev(d: {
  name?: string | null; localName?: string | null; id?: string | null;
}): boolean {
  return isBleDeviceAllowed(d, BLE_DEV_ALLOWED_TRACKERS);
}
