import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { bleService } from '../services/ble';
import {
  getCurrentSession,
  getFleetTags,
  postBleDetection,
  setManualMode as apiSetManualMode,
  ApiError,
} from '../services/api';
import {
  indexFleetTags,
  matchDetectionToTag,
  computeDetection,
  tagLabel,
  DETECTION_WINDOW_MS,
} from '../services/detection';

const MAX_BUFFER = 300;

/**
 * Hook central de la console chauffeur.
 * - Charge la session courante + tags flotte (données réelles).
 * - Gère le scan BLE réel et l'agrégation des détections.
 * - Pousse les détections réelles vers le backend (throttlé).
 */
export function useDriverConsole() {
  const { token, signOut } = useAuth();

  const [session, setSession] = useState(null);
  const [fleetTags, setFleetTags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const [scanning, setScanning] = useState(false);
  const [bleError, setBleError] = useState(null);
  const [detections, setDetections] = useState([]); // tampon roulant
  const [tick, setTick] = useState(0); // force recomputation

  const [mode, setMode] = useState(null); // 'pro' | 'prive' | null
  const [modeSubmitting, setModeSubmitting] = useState(false);
  const [testingTagKey, setTestingTagKey] = useState(null);

  const detectionsRef = useRef([]);
  const lastPostRef = useRef({}); // throttle par tag
  const fleetIndexRef = useRef(new Map());

  const bleAvailable = bleService.isSupported();
  const unavailableReason = bleService.unavailableReason();

  // ---- Chargement des données réelles ----
  const load = useCallback(async () => {
    setError(null);
    try {
      const [sess, tags] = await Promise.allSettled([
        getCurrentSession(token),
        getFleetTags(token),
      ]);

      if (sess.status === 'fulfilled') {
        setSession(sess.value);
        const m = sess.value?.mode || sess.value?.manual_mode || sess.value?.current_mode || null;
        if (m) setMode(String(m).toLowerCase());
      } else if (sess.reason instanceof ApiError && sess.reason.status === 401) {
        throw sess.reason;
      }

      if (tags.status === 'fulfilled') {
        const list = Array.isArray(tags.value)
          ? tags.value
          : tags.value?.tags || tags.value?.data || tags.value?.items || [];
        setFleetTags(list);
        fleetIndexRef.current = indexFleetTags(list);
      } else if (tags.reason instanceof ApiError && tags.reason.status === 401) {
        throw tags.reason;
      }

      // Si les deux ont échoué (hors 401), remonter une erreur.
      if (sess.status === 'rejected' && tags.status === 'rejected') {
        const e = sess.reason || tags.reason;
        setError(e instanceof ApiError ? e.message : 'Chargement impossible.');
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        await signOut();
        return;
      }
      setError(e instanceof ApiError ? e.message : 'Chargement impossible.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, signOut]);

  useEffect(() => { load(); }, [load]);

  const refresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  // ---- Recalcul périodique de la fenêtre de détection ----
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 2000);
    return () => clearInterval(id);
  }, []);

  // ---- Réception d'une détection BLE réelle ----
  const ingestDetection = useCallback(
    (raw, { fromTest = false, forcedTag = null } = {}) => {
      const tag = forcedTag || matchDetectionToTag(raw, fleetIndexRef.current);
      if (!tag) return; // on ne conserve que les balises de la flotte
      const tagKey =
        tag.mac || tag.uuid || tag.ble_id || tag.bleId || tag.id || tagLabel(tag);
      const entry = {
        tagKey: String(tagKey),
        tag,
        rssi: typeof raw.rssi === 'number' ? raw.rssi : null,
        timestamp: raw.timestamp || Date.now(),
      };
      const next = [...detectionsRef.current, entry].slice(-MAX_BUFFER);
      detectionsRef.current = next;
      setDetections(next);

      // Envoi au backend (throttlé à 1/3s par tag), donnée réelle uniquement.
      const now = Date.now();
      const last = lastPostRef.current[entry.tagKey] || 0;
      if (fromTest || now - last > 3000) {
        lastPostRef.current[entry.tagKey] = now;
        const payload = {
          tag: tagKey,
          rssi: entry.rssi,
          name: tagLabel(tag),
          detected_at: new Date(entry.timestamp).toISOString(),
          source: fromTest ? 'manual_test' : 'ble_scan',
        };
        postBleDetection(payload, token).catch(() => {});
      }
    },
    [token]
  );

  // ---- Démarrer / arrêter le scan ----
  const startScan = useCallback(async () => {
    setBleError(null);
    if (!bleAvailable) {
      setBleError(unavailableReason);
      return;
    }
    const unsub = bleService.subscribe((evt) => {
      if (evt.type === 'scanning') setScanning(evt.scanning);
      else if (evt.type === 'error') setBleError(evt.reason);
      else if (evt.type === 'device') ingestDetection(evt.device);
    });
    bleService._unsub = unsub;
    await bleService.startScan((d) => ingestDetection(d));
  }, [bleAvailable, unavailableReason, ingestDetection]);

  const stopScan = useCallback(() => {
    bleService.stopScan();
    if (bleService._unsub) bleService._unsub();
    setScanning(false);
  }, []);

  useEffect(() => () => { stopScan(); }, [stopScan]);

  // ---- Test manuel d'un tag ----
  // NOTE (données réelles) : sur natif, le "test" vérifie la présence réelle du tag.
  // Ici, le bouton envoie une détection de test explicitement marquée source='manual_test'
  // au backend, pour valider la chaîne de bout en bout. Aucun RSSI fictif n'est fabriqué.
  const testTag = useCallback(
    async (tag) => {
      const tagKey = String(
        tag.mac || tag.uuid || tag.ble_id || tag.bleId || tag.id || tagLabel(tag)
      );
      setTestingTagKey(tagKey);
      try {
        await postBleDetection(
          {
            tag: tagKey,
            rssi: null, // test manuel : pas de mesure réelle de signal
            name: tagLabel(tag),
            detected_at: new Date().toISOString(),
            source: 'manual_test',
          },
          token
        );
        return { ok: true };
      } catch (e) {
        return { ok: false, message: e instanceof ApiError ? e.message : 'Test échoué.' };
      } finally {
        setTestingTagKey(null);
      }
    },
    [token]
  );

  // ---- Basculer PRO / PRIVÉ ----
  const changeMode = useCallback(
    async (nextMode) => {
      const prev = mode;
      setMode(nextMode);
      setModeSubmitting(true);
      try {
        await apiSetManualMode(nextMode, token);
        return { ok: true };
      } catch (e) {
        setMode(prev); // rollback si échec
        return { ok: false, message: e instanceof ApiError ? e.message : 'Bascule impossible.' };
      } finally {
        setModeSubmitting(false);
      }
    },
    [mode, token]
  );

  // ---- Calculs dérivés (mémorisés sur tick) ----
  const { candidate, liveByTag } = useMemo(() => {
    const now = Date.now();
    const { best, byTag } = computeDetection(detectionsRef.current, now);
    const map = new Map();
    byTag.forEach((b) => map.set(b.key, b));
    return { candidate: best, liveByTag: map };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, detections]);

  return {
    // données
    session,
    fleetTags,
    mode,
    candidate,
    liveByTag,
    // états
    loading,
    error,
    refreshing,
    scanning,
    bleAvailable,
    unavailableReason,
    bleError,
    modeSubmitting,
    testingTagKey,
    windowMs: DETECTION_WINDOW_MS,
    // actions
    refresh,
    startScan,
    stopScan,
    testTag,
    changeMode,
  };
}
