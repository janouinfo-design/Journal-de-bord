import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getPrivateMode,
  setPrivateMode,
  PrivateModeState,
  PrivateModeStatus,
} from '@/api/privateMode';

/**
 * Phase 2 — Machine à états Privé/Professionnel côté app.
 *
 * Règles :
 * - JAMAIS de changement optimiste : l'état affiché vient du backend (autoritaire).
 * - Pendant une transition (REQUESTED), les boutons doivent être désactivés (`busy`).
 * - Au montage / focus / après réseau : on récupère l'état RÉEL (jamais BUSINESS par défaut).
 * - En cas d'échec/non-confirmation : état FAILED/UNKNOWN + message honnête, possibilité de réessayer.
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

  const refresh = useCallback(async () => {
    try {
      const s = await getPrivateMode();
      setStatus(s);
    } catch {
      // pas d'écrasement optimiste : si on ne peut pas lire -> UNKNOWN
      setStatus((prev) => ({ ...prev, state: 'UNKNOWN' }));
    }
  }, []);

  const requestMode = useCallback(
    async (mode: 'PRIVATE' | 'BUSINESS') => {
      if (inFlight.current) return; // anti double-clic / concurrence
      inFlight.current = true;
      setBusy(true);
      setError(null);
      // état transitoire local (REQUESTED) — informatif, pas un succès
      setStatus((prev) => ({
        ...prev,
        state: mode === 'PRIVATE' ? 'PRIVATE_REQUESTED' : 'BUSINESS_REQUESTED',
      }));
      try {
        const res = await setPrivateMode(mode);
        if (res.ok) {
          setStatus((prev) => ({ ...prev, state: res.state }));
          if (typeof res.private_distance_km === 'number') {
            setLastDistanceKm(res.private_distance_km);
          }
        } else {
          // non confirmé / refusé -> état honnête renvoyé par le backend
          setStatus((prev) => ({ ...prev, state: res.state }));
          setError(_reasonToMessage(res.reason));
        }
        // resynchronise avec la vérité backend
        await refresh();
      } catch {
        setStatus((prev) => ({ ...prev, state: 'UNKNOWN' }));
        setError("Impossible de confirmer le changement. Vérifiez votre connexion et réessayez.");
      } finally {
        setBusy(false);
        inFlight.current = false;
      }
    },
    [refresh],
  );

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [refresh, pollMs]);

  return { status, busy, error, lastDistanceKm, requestMode, refresh };
}

function _reasonToMessage(reason?: string | null): string {
  switch (reason) {
    case 'not_confirmed':
      return "Le changement n'a pas pu être confirmé par le véhicule. Réessayez.";
    case 'transition_in_progress':
      return 'Un changement de mode est déjà en cours…';
    case 'capability_not_field_validated':
      return "Ce véhicule n'est pas encore activé pour le mode Privé.";
    case 'no_tracker':
      return 'Aucun traceur associé à ce véhicule.';
    case 'no_active_vehicle':
      return 'Aucun véhicule actif.';
    default:
      return "Action impossible pour le moment.";
  }
}
