import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import {
  getPrivateMode,
  setPrivateMode,
  PrivateModeStatus,
} from '@/api/privateMode';

/**
 * Phase 2 — Machine à états Privé/Professionnel côté app (backend = source de vérité).
 *
 * Règles :
 * - JAMAIS de changement optimiste : l'état affiché vient du backend (autoritaire).
 * - Pendant une transition (SWITCHING_*), le contrôle est verrouillé (`busy`), un seul appel.
 * - Au montage / retour foreground / après réseau : on récupère l'état RÉEL (jamais supposé).
 * - Retour Professionnel jamais anticipé : si incertain, on reste "confidentialité active".
 * - En cas d'échec : message honnête (sans jargon), possibilité de réessayer.
 * - Changement de véhicule : l'état est ré-évalué (aucune contamination inter-véhicule).
 */
export function usePrivateMode(pollMs = 15000) {
  const [status, setStatus] = useState<PrivateModeStatus>({
    state: 'UNKNOWN',
    allowed: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastDistanceKm, setLastDistanceKm] = useState<number | null>(null);
  const inFlight = useRef(false);
  const lastVehicleId = useRef<string | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const s = await getPrivateMode();
      const newVid = s.vehicle_id ?? null;
      // Changement de véhicule -> reset des données volatiles (pas de contamination).
      // (comparaison normalisée : évite un faux positif null/undefined)
      if (lastVehicleId.current !== undefined && lastVehicleId.current !== newVid) {
        setLastDistanceKm(null);
      }
      lastVehicleId.current = newVid;
      setStatus(s);
    } catch {
      // pas d'écrasement optimiste : si on ne peut pas lire -> UNKNOWN (jamais BUSINESS supposé)
      setStatus((prev) => ({ ...prev, state: 'UNKNOWN' }));
    }
  }, []);

  const requestMode = useCallback(
    async (mode: 'PRIVATE' | 'BUSINESS') => {
      if (inFlight.current) return; // anti double-tap / concurrence
      if (!status.allowed) {
        setError(reasonToMessage(status.reason));
        return;
      }
      inFlight.current = true;
      setBusy(true);
      setError(null);
      // état transitoire local (SWITCHING_*) — informatif, PAS un succès
      setStatus((prev) => ({
        ...prev,
        state: mode === 'PRIVATE' ? 'PRIVATE_REQUESTED' : 'BUSINESS_REQUESTED',
      }));
      try {
        const res = await setPrivateMode(mode);
        if (res.ok && res.state === 'PENDING_CONFIRMATION') {
          // Commande envoyée, confirmation device en cours (télémétrie async).
          // PAS un succès affiché : état "en cours de confirmation", on continue à relire.
          setStatus((prev) => ({ ...prev, state: 'PENDING_CONFIRMATION' }));
        } else if (res.ok) {
          setStatus((prev) => ({ ...prev, state: res.state }));
          if (typeof res.private_distance_km === 'number') {
            setLastDistanceKm(res.private_distance_km);
          }
        } else {
          // non confirmé / refusé -> message honnête (code HTTP prioritaire, sinon reason)
          setError(reasonToMessage(res.reason, res.http_status));
          // Retour Pro non confirmé : on NE bascule PAS optimiste vers Professionnel.
        }
        await refresh(); // resynchronise avec la vérité backend (résout aussi le PENDING)
      } catch {
        // réseau/timeout/5xx inattendu : état incertain -> UNKNOWN, jamais de fausse confirmation.
        setStatus((prev) => ({ ...prev, state: 'UNKNOWN' }));
        setError('Impossible de confirmer le changement. Vérifiez votre connexion et réessayez.');
      } finally {
        setBusy(false);
        inFlight.current = false;
      }
    },
    [refresh, status.allowed, status.reason],
  );

  // Montage + polling léger.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [refresh, pollMs]);

  // Retour au premier plan -> re-lecture de l'état serveur réel (jamais d'état obsolète).
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') {
        refresh();
      }
    });
    return () => sub.remove();
  }, [refresh]);

  return {
    status,
    busy,
    error,
    lastDistanceKm,
    pending: status.state === 'PENDING_CONFIRMATION',
    privateOdometerSupported: !!status.private_odometer_supported,
    requestMode,
    refresh,
  };
}

/**
 * Traduit une raison métier / code HTTP en message chauffeur simple (aucun jargon
 * technique : ni AVL, ni Navixy, ni Teltonika, ni privatemode). Le code HTTP prime.
 */
export function reasonToMessage(reason?: string | null, httpStatus?: number | null): string {
  // 1) Raisons normalisées de la gate centrale (backend).
  switch (reason) {
    case 'PRIVATE_MODE_FEATURE_DISABLED':
    case 'PRIVATE_MODE_TENANT_NOT_ALLOWED':
    case 'PRIVATE_MODE_VEHICLE_NOT_PILOT':
      return "Le mode Privé n'est pas disponible pour le moment.";
    case 'PRIVATE_MODE_KILL_SWITCH_ACTIVE':
    case 'PRIVATE_MODE_INTEGRATION_UNAVAILABLE':
      return 'Mode Privé temporairement indisponible. Réessayez plus tard.';
    case 'PRIVATE_MODE_NOT_SUPPORTED':
      return "Le mode Privé n'est pas disponible pour ce véhicule.";
    case 'PRIVATE_MODE_NO_TRACKER':
    case 'PRIVATE_MODE_NO_VEHICLE':
      return 'Aucun véhicule actif.';
    // Anciennes raisons métier (rétro-compat) :
    case 'not_confirmed':
      return "Le changement n'a pas pu être confirmé par le véhicule. Réessayez.";
    case 'transition_in_progress':
      return 'Un changement de mode est déjà en cours…';
    case 'no_active_vehicle':
      return 'Aucun véhicule actif.';
  }
  // 2) Sinon, message selon le code HTTP.
  switch (httpStatus) {
    case 401:
    case 403:
      return "Votre session n'est plus valide ou le mode Privé n'est pas autorisé.";
    case 409:
      return "Le changement n'a pas pu être effectué car l'état du véhicule a changé.";
    case 503:
      return 'Mode Privé temporairement indisponible. Réessayez plus tard.';
    default:
      return 'Action impossible pour le moment.';
  }
}
