import { colors } from '../theme/theme';

/**
 * Association détections BLE réelles <-> tags de la flotte, et calcul du score de confiance.
 *
 * TRAÇABILITÉ DU SCORE (aucune valeur inventée) :
 *  - Entrées : détections BLE réelles (rssi mesuré, nombre d'occurrences récentes).
 *  - Fenêtre : seules les détections des DETECTION_WINDOW_MS dernières ms comptent.
 *  - Score = 55% force du signal (rssi normalisé) + 45% récurrence (nb détections plafonné).
 *  - Le score reflète la proximité/stabilité mesurée ; il n'est PAS fourni par le serveur.
 *    Si le serveur renvoie un score autoritatif, il doit primer sur ce calcul local.
 */

export const DETECTION_WINDOW_MS = 15000; // fenêtre de récence
const RSSI_MIN = -100; // très faible
const RSSI_MAX = -45;  // très proche
const COUNT_SATURATION = 8; // au-delà, la récurrence n'augmente plus le score

/** Normalise un RSSI (dBm) en 0..1. */
export function rssiToUnit(rssi) {
  if (rssi == null || Number.isNaN(rssi)) return 0;
  const clamped = Math.max(RSSI_MIN, Math.min(RSSI_MAX, rssi));
  return (clamped - RSSI_MIN) / (RSSI_MAX - RSSI_MIN);
}

/** Qualité lisible du signal + couleur. */
export function signalQuality(rssi) {
  if (rssi == null) return { label: 'N/A', color: colors.textFaint };
  if (rssi >= -60) return { label: 'Excellent', color: colors.signalStrong };
  if (rssi >= -75) return { label: 'Bon', color: colors.signalMedium };
  return { label: 'Faible', color: colors.signalWeak };
}

/** Normalise l'identifiant d'un tag pour comparaison. */
function norm(v) {
  return (v == null ? '' : String(v)).trim().toLowerCase();
}

/**
 * Construit un index des tags de la flotte par identifiants BLE possibles.
 * Un tag peut exposer : id, mac, uuid, address, name...
 */
export function indexFleetTags(fleetTags = []) {
  const byKey = new Map();
  fleetTags.forEach((tag) => {
    const keys = [tag?.mac, tag?.address, tag?.uuid, tag?.ble_id, tag?.bleId, tag?.id, tag?.name];
    keys.forEach((k) => {
      const nk = norm(k);
      if (nk) byKey.set(nk, tag);
    });
  });
  return byKey;
}

/**
 * Fait correspondre une détection BLE brute à un tag connu.
 * Retourne le tag ou null.
 */
export function matchDetectionToTag(detection, fleetIndex) {
  if (!detection || !fleetIndex) return null;
  const candidates = [detection.id, detection.name, detection.mac, detection.uuid];
  for (const c of candidates) {
    const nk = norm(c);
    if (nk && fleetIndex.has(nk)) return fleetIndex.get(nk);
  }
  return null;
}

/**
 * Agrège des détections récentes par tag et calcule un candidat "véhicule détecté".
 * @param {Array} detections  [{ tagKey, tag, rssi, timestamp }]
 * @param {number} now
 * @returns { best, byTag }  best = meilleur candidat (ou null)
 */
export function computeDetection(detections, now = Date.now()) {
  const recent = detections.filter((d) => now - d.timestamp <= DETECTION_WINDOW_MS);
  const byTag = new Map();

  recent.forEach((d) => {
    const key = d.tagKey;
    if (!byTag.has(key)) {
      byTag.set(key, { tag: d.tag, key, count: 0, rssis: [], lastSeen: 0 });
    }
    const entry = byTag.get(key);
    entry.count += 1;
    if (typeof d.rssi === 'number') entry.rssis.push(d.rssi);
    entry.lastSeen = Math.max(entry.lastSeen, d.timestamp);
  });

  const results = [];
  byTag.forEach((entry) => {
    const avgRssi =
      entry.rssis.length > 0
        ? Math.round(entry.rssis.reduce((a, b) => a + b, 0) / entry.rssis.length)
        : null;
    const signalUnit = rssiToUnit(avgRssi);
    const countUnit = Math.min(1, entry.count / COUNT_SATURATION);
    const confidence = Math.round((0.55 * signalUnit + 0.45 * countUnit) * 100);
    results.push({
      tag: entry.tag,
      key: entry.key,
      count: entry.count,
      avgRssi,
      confidence,
      lastSeen: entry.lastSeen,
    });
  });

  results.sort((a, b) => b.confidence - a.confidence || (b.avgRssi ?? -999) - (a.avgRssi ?? -999));
  return { best: results[0] || null, byTag: results };
}

/** Libellé d'affichage d'un tag / véhicule. */
export function tagLabel(tag) {
  if (!tag) return 'Inconnu';
  return (
    tag.vehicle_name ||
    tag.vehicleName ||
    tag.vehicle ||
    tag.plate ||
    tag.immatriculation ||
    tag.name ||
    tag.label ||
    tag.mac ||
    tag.id ||
    'Tag'
  );
}
