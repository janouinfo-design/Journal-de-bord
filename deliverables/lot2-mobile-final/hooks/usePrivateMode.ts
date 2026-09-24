import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import {
  getPrivateMode,
  setPrivateMode,
  PrivateModeStatus,
} from '@/api/privateMode';

/**
 * Phase 2 — Machine à états Privé/Professionnel côté app (backend = source de vérité).
 *
 * Règles (validées terrain, cf. Patch 0009) :
 * - JAMAIS de changement optimiste : l'état affiché vient du backend (autoritaire).
 * - Un `success=true` à l'envoi n'est JAMAIS une confirmation de mode.
 * - PENDING (attente confirmation télémétrique) : NON bloquant. L'app reste navigable,
 *   le polling continue en arrière-plan, MAIS on interdit une nouvelle commande.
 * - L'état PENDING ne dépend PAS de l'état React local : au remount/relaunch, on relit
 *   le backend (qui conserve PENDING_CONFIRMATION jusqu'à preuve ou timeout serveur).
 * - Confirmation UNIQUEMENT sur preuve télémétrique -> BUSINESS / PRIVATE.
 * - Pas de preuve : UNKNOWN/UNCONFIRMED (transition_result=TIMEOUT). JAMAIS « actif ».
 * - Repères UX (affichage seulement, seuils indépendants du timeout serveur) :
 *     90 s  -> avertissement « confirmation plus longue, faites rouler le véhicule ».
 *     180 s -> message renforcé + proposer « Actualiser l'état » (jamais de renvoi commande).
 * - Le bouton « Actualiser l'état » relit le backend ; il NE renvoie AUCUNE commande device.
 */

/** Repères UX (ms). Indépendants du PENDING_TIMEOUT_S serveur (résolution d'état réelle). */
export const PENDING_WARN_MS = 90_000;   // 90 s : confirmation plus longue que prévu
export const PENDING_LONG_MS = 180_000;  // 180 s : message renforcé + Actualiser

export type PendingPhase = 'none' | 'normal' | 'long' | 'verylong';

/** Cadence de polling : rapide pendant une transition, sobre au repos. */
const POLL_ACTIVE_MS = 5_000;   // transition en cours -> relire vite
const POLL_IDLE_MS_DEFAULT = 15_000;

function isTransientState(s: PrivateModeStatus['state']): boolean {
  return s === 'PENDING_CONFIRMATION' || s === 'PRIVATE_REQUESTED' || s === 'BUSINESS_REQUESTED';
}

export function usePrivateMode(pollMs = POLL_IDLE_MS_DEFAULT) {
  const [status, setStatus] = useState<PrivateModeStatus>({
    state: 'UNKNOWN',
    allowed: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentMessage, setSentMessage] = useState<string | null>(null);
  const [lastDistanceKm, setLastDistanceKm] = useState<number | null>(null);
  // `nowTs` : horloge légère pour recalculer les phases UX pendant PENDING (granularité poll).
  const [nowTs, setNowTs] = useState<number>(() => Date.now());
  const inFlight = useRef(false);
  const lastVehicleId = useRef<string | null | undefined>(undefined);
  // Horodatage LOCAL de la dernière commande envoyée (repère UX de secours si le backend
  // ne renvoie pas encore command_sent_at). Le backend reste prioritaire.
  const localCommandSentAt = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await getPrivateMode();
      const newVid = s.vehicle_id ?? null;
      // Changement de véhicule -> reset des données volatiles (pas de contamination).
      if (lastVehicleId.current !== undefined && lastVehicleId.current !== newVid) {
        setLastDistanceKm(null);
        localCommandSentAt.current = null;
      }
      lastVehicleId.current = newVid;
      // Confirmation atteinte OU timeout serveur -> plus de repère de commande local.
      if (!isTransientState(s.state)) {
        localCommandSentAt.current = null;
      }
      setStatus(s);
      setNowTs(Date.now());
    } catch {
      // pas d'écrasement optimiste : si on ne peut pas lire -> UNKNOWN (jamais BUSINESS supposé)
      setStatus((prev) => ({ ...prev, state: 'UNKNOWN' }));
    }
  }, []);

  /** Alias explicite pour l'UI (« Actualiser l'état ») : relit le backend, ZÉRO commande device. */
  const refreshState = refresh;

  const requestMode = useCallback(
    async (mode: 'PRIVATE' | 'BUSINESS') => {
      if (inFlight.current) return;               // anti double-tap / concurrence
      if (isTransientState(status.state)) return; // transition en cours -> aucune nouvelle commande
      if (!status.allowed) {
        setError(reasonToMessage(status.reason));
        return;
      }
      inFlight.current = true;
      setBusy(true);
      setError(null);
      setSentMessage(null);
      localCommandSentAt.current = Date.now();
      // état transitoire local (informatif, PAS un succès)
      setStatus((prev) => ({
        ...prev,
        state: mode === 'PRIVATE' ? 'PRIVATE_REQUESTED' : 'BUSINESS_REQUESTED',
      }));
      setNowTs(Date.now());
      try {
        const res = await setPrivateMode(mode);
        if (res.ok && res.state === 'PENDING_CONFIRMATION') {
          // Commande envoyée, confirmation device en cours (télémétrie async).
          // PAS un succès « actif » : on reste PENDING et on continue à relire le backend.
          setStatus((prev) => ({ ...prev, state: 'PENDING_CONFIRMATION' }));
          setSentMessage(res.message ?? `Commande ${mode === 'PRIVATE' ? 'Privé' : 'Professionnel'} envoyée`);
        } else if (res.ok) {
          setStatus((prev) => ({ ...prev, state: res.state }));
          setSentMessage(res.message ?? `Commande ${mode === 'PRIVATE' ? 'Privé' : 'Professionnel'} envoyée`);
          if (typeof res.private_distance_km === 'number') {
            setLastDistanceKm(res.private_distance_km);
          }
        } else {
          // non confirmé / refusé -> message honnête (code HTTP prioritaire, sinon reason)
          setError(reasonToMessage(res.reason, res.http_status));
          localCommandSentAt.current = null;
          // Retour Pro non confirmé : on NE bascule PAS optimiste vers Professionnel.
        }
        await refresh(); // resynchronise avec la vérité backend (résout aussi le PENDING)
      } catch {
        // réseau/timeout/5xx inattendu : état incertain -> UNKNOWN, jamais de fausse confirmation.
        setStatus((prev) => ({ ...prev, state: 'UNKNOWN' }));
        setError('Impossible de confirmer le changement. Vérifiez votre connexion et réessayez.');
        localCommandSentAt.current = null;
      } finally {
        setBusy(false);
        inFlight.current = false;
      }
    },
    [refresh, status.allowed, status.reason, status.state],
  );

  // Montage + polling ADAPTATIF : rapide pendant une transition, sobre au repos.
  // Le polling continue en arrière-plan même si l'écran n'est pas au premier plan
  // (l'app doit pouvoir naviguer pendant PENDING sans perdre la confirmation).
  const pending = isTransientState(status.state);
  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    const interval = pending ? POLL_ACTIVE_MS : pollMs;
    const id = setInterval(() => {
      refresh();
    }, interval);
    return () => clearInterval(id);
  }, [refresh, pollMs, pending]);

  // Retour au premier plan (app entière) -> re-lecture immédiate de l'état serveur réel.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') {
        refresh();
      }
    });
    return () => sub.remove();
  }, [refresh]);

  // Repère de temps écoulé depuis l'envoi de la commande (backend prioritaire).
  // `nowTs` est inclus volontairement : il force la relecture de la ref locale
  // `localCommandSentAt` à chaque tick de poll (la ref seule ne déclenche pas de recompute).
  const commandSentMs = useMemo(() => {
    const fromBackend = status.command_sent_at ? Date.parse(status.command_sent_at) : NaN;
    if (!Number.isNaN(fromBackend)) return fromBackend;
    return localCommandSentAt.current;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.command_sent_at, nowTs]);

  const pendingElapsedMs = useMemo(() => {
    if (!pending || !commandSentMs) return 0;
    return Math.max(0, nowTs - commandSentMs);
  }, [pending, commandSentMs, nowTs]);

  const pendingPhase: PendingPhase = useMemo(() => {
    if (!pending) return 'none';
    if (pendingElapsedMs >= PENDING_LONG_MS) return 'verylong';
    if (pendingElapsedMs >= PENDING_WARN_MS) return 'long';
    return 'normal';
  }, [pending, pendingElapsedMs]);

  const target: 'PRIVATE' | 'BUSINESS' | null = useMemo(() => {
    if (status.requested_target === 'PRIVATE' || status.requested_target === 'BUSINESS') {
      return status.requested_target;
    }
    if (status.state === 'PRIVATE_REQUESTED') return 'PRIVATE';
    if (status.state === 'BUSINESS_REQUESTED') return 'BUSINESS';
    return null;
  }, [status.requested_target, status.state]);

  // Message d'attente CLAIR et non alarmant (aucun jargon technique).
  const pendingMessage: string | null = useMemo(() => {
    if (!pending) return null;
    const cible = target === 'PRIVATE' ? 'Privé' : target === 'BUSINESS' ? 'Professionnel' : null;
    const base = cible
      ? `Confirmation du mode ${cible} en cours…`
      : 'Confirmation du mode en cours…';
    if (pendingPhase === 'verylong') {
      return `${base} Le véhicule doit rouler pour transmettre une nouvelle position. Vous pouvez actualiser l'état.`;
    }
    if (pendingPhase === 'long') {
      return `${base} Confirmation plus longue que prévu — assurez-vous que le véhicule roule.`;
    }
    return `${base} Le véhicule doit transmettre une nouvelle télémétrie.`;
  }, [pending, target, pendingPhase]);

  return {
    status,
    busy,
    error,
    sentMessage,
    lastDistanceKm,
    pending,
    // Cible demandée pendant la transition (pour messages contextuels côté UI).
    pendingTarget: target,
    // Repères UX d'attente (ne changent PAS la source de vérité backend).
    pendingElapsedMs,
    pendingPhase,
    pendingMessage,
    // Timeout serveur : commande envoyée mais état device NON prouvé (transition_result=TIMEOUT).
    // L'UI réactive les boutons et affiche un message honnête (jamais un faux PRO/PRIVÉ).
    timedOut: status.transition_result === 'TIMEOUT',
    privateOdometerSupported: !!status.private_odometer_supported,
    requestMode,
    refresh,
    refreshState,
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
