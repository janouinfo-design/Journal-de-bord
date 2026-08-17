import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import { bleService } from './ble';
import { showLocalNotification } from './push';
import { BLE_SERVICE_UUIDS } from './config';
import {
  indexFleetTags,
  matchDetectionToTag,
  computeDetection,
  tagLabel,
} from './detection';

/**
 * Gestionnaire de DÉTECTION AUTOMATIQUE du véhicule via scan BLE (bonus).
 *
 * Objectif : lorsque l'app tourne (premier plan ou, selon l'OS, en arrière-plan),
 * repérer automatiquement la balise de la flotte la plus proche et notifier le
 * chauffeur (+ pousser la détection réelle au backend).
 *
 * LIMITES HONNÊTES PAR OS (aucune sur-promesse) :
 * - iOS : le scan en arrière-plan n'est fiable QUE si des `serviceUUIDs` sont fournis
 *   (voir BLE_SERVICE_UUIDS). La restauration d'état est activée (restoreStateIdentifier).
 * - Android : un scan pleinement persistant en arrière-plan requiert un Foreground
 *   Service (notification persistante) — non inclus ici (nécessite un module natif
 *   dédié). Le scan fonctionne app au premier plan et un temps limité en arrière-plan.
 *
 * RÈGLE DONNÉES RÉELLES : aucune détection fabriquée. On n'agit que sur des mesures
 * BLE réelles corrélées aux balises renvoyées par /fleet-tags.
 */

const PREF_KEY = 'logitrak.autoDetect';
const NOTIFY_COOLDOWN_MS = 60000; // 1 notif / véhicule / minute max
const CONFIDENCE_THRESHOLD = 60; // seuil de déclenchement (voir detection.js)

class BackgroundScanManager {
  constructor() {
    this.enabled = false;
    this.running = false;
    this.fleetIndex = new Map();
    this.detections = [];
    this.lastNotify = {}; // par tagKey
    this.unsub = null;
    this.onDetection = null; // callback (detection) fourni par l'app
    this.lastAnnouncedKey = null;
  }

  isSupported() {
    return bleService.isSupported();
  }

  async loadPreference() {
    try {
      const v = await AsyncStorage.getItem(PREF_KEY);
      this.enabled = v === '1';
    } catch (e) {
      this.enabled = false;
    }
    return this.enabled;
  }

  async setPreference(on) {
    this.enabled = !!on;
    try {
      await AsyncStorage.setItem(PREF_KEY, on ? '1' : '0');
    } catch (e) {}
  }

  setFleetTags(tags) {
    this.fleetIndex = indexFleetTags(tags || []);
  }

  /**
   * Démarre le scan d'auto-détection.
   * @param {Object} opts { onDetection: fn(detection), onCandidate: fn(candidate) }
   */
  async start(opts = {}) {
    if (!this.isSupported()) {
      return { ok: false, reason: bleService.unavailableReason() };
    }
    if (this.running) return { ok: true };

    this.onDetection = opts.onDetection || null;
    this.onCandidate = opts.onCandidate || null;

    this.unsub = bleService.subscribe((evt) => {
      if (evt.type === 'device') this._ingest(evt.device);
      else if (evt.type === 'restored') {
        // iOS a restauré une session de scan en arrière-plan.
      }
    });

    const ok = await bleService.startScan(null, {
      serviceUUIDs: BLE_SERVICE_UUIDS || null,
    });
    this.running = !!ok;
    return ok ? { ok: true } : { ok: false, reason: bleService.unavailableReason() };
  }

  stop() {
    if (this.unsub) {
      this.unsub();
      this.unsub = null;
    }
    bleService.stopScan();
    this.running = false;
  }

  _ingest(raw) {
    const tag = matchDetectionToTag(raw, this.fleetIndex);
    if (!tag) return; // balise hors flotte -> ignorée

    const tagKey = String(
      tag.mac || tag.uuid || tag.ble_id || tag.bleId || tag.id || tagLabel(tag)
    );
    this.detections.push({
      tagKey,
      tag,
      rssi: typeof raw.rssi === 'number' ? raw.rssi : null,
      timestamp: raw.timestamp || Date.now(),
    });
    if (this.detections.length > 300) this.detections = this.detections.slice(-300);

    // Remonter la détection brute (pour envoi backend throttlé côté hook).
    if (this.onDetection) this.onDetection({ tagKey, tag, rssi: raw.rssi, timestamp: Date.now() });

    // Évaluer le meilleur candidat.
    const { best } = computeDetection(this.detections, Date.now());
    if (this.onCandidate) this.onCandidate(best);
    if (best && best.confidence >= CONFIDENCE_THRESHOLD) {
      this._maybeNotify(best);
    }
  }

  _maybeNotify(candidate) {
    const key = candidate.key;
    const now = Date.now();
    const last = this.lastNotify[key] || 0;
    // Notifie uniquement à un nouveau véhicule ou après le cooldown.
    if (key !== this.lastAnnouncedKey || now - last > NOTIFY_COOLDOWN_MS) {
      this.lastNotify[key] = now;
      this.lastAnnouncedKey = key;
      showLocalNotification(
        'Véhicule détecté',
        `${tagLabel(candidate.tag)} · signal ${candidate.avgRssi ?? 'N/A'} dBm · confiance ${candidate.confidence}%`,
        { tagKey: key, confidence: candidate.confidence }
      );
    }
  }
}

export const backgroundScan = new BackgroundScanManager();
