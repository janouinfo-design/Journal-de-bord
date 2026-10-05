/**
 * Feature flags côté app chauffeur.
 *
 * PHASE 1 BLE — l'écran technique de lecture BLE Private/Business est strictement
 * réservé au DEV. Il n'est JAMAIS activé globalement ni exposé en production.
 *
 * Activation (dev uniquement), par variable d'environnement Expo publique :
 *   EXPO_PUBLIC_PRIVATE_MODE_BLE_DEV=1
 * Combinée à __DEV__ (build de développement). En build production, même si la
 * variable était présente, on exige __DEV__ -> OFF par défaut (fail-closed).
 */

/** true uniquement en build DEV ET si le flag d'env est explicitement activé. */
export const PRIVATE_MODE_BLE_DEV: boolean =
  typeof __DEV__ !== 'undefined' &&
  __DEV__ === true &&
  process.env.EXPO_PUBLIC_PRIVATE_MODE_BLE_DEV === '1';
