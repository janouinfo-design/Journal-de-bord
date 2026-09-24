import { create } from 'zustand';
import {
  VehicleAssignment,
  getActiveAssignment,
  takeVehicle,
  changeVehicle,
  endAssignment,
  AssignmentActionResult,
} from '@/api/vehicleAssignment';
import { cacheActiveAssignment, readCachedAssignment, clearCachedAssignment } from '@/utils/assignmentCache';
import { logger } from '@/utils/logger';
import type { PrivateModeStatus } from '@/api/privateMode';

/**
 * Store d'affectation véhicule (Lot 2). Backend = source de vérité.
 * États UX explicites (jamais de gris muet). Cache local = affichage dégradé hors ligne SEULEMENT.
 */

export type AssignmentUXState =
  | 'loading'        // Chargement du véhicule…
  | 'active'         // Véhicule actif
  | 'none'           // Aucun véhicule
  | 'acting'         // Action en cours…
  | 'offline'        // Mode hors ligne (cache affiché)
  | 'error';         // Erreur de synchronisation (Réessayer)

type AssignmentState = {
  uxState: AssignmentUXState;
  assignment: VehicleAssignment | null;
  offline: boolean;              // true = affichage dégradé (backend injoignable)
  actionError: string | null;    // message métier d'une action (TAKE/CHANGE/END)
  syncError: boolean;            // true = GET active a échoué (≠ aucune affectation)
  inFlight: boolean;             // anti double-clic
  refresh: () => Promise<void>;
  take: (vehicleId: string) => Promise<AssignmentActionResult | null>;
  change: (vehicleId: string) => Promise<AssignmentActionResult | null>;
  end: () => Promise<AssignmentActionResult | null>;
  clearActionError: () => void;
};

/** request_id stable pour une action (idempotence backend tenant+request_id). */
function newRequestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Détecte une erreur réseau (backend injoignable) vs une erreur applicative (4xx/5xx). */
function isNetworkError(e: any): boolean {
  // axios : pas de réponse => réseau/timeout. Sinon on a e.response.status.
  return !!e && !e.response;
}

export const useAssignmentStore = create<AssignmentState>((set, get) => ({
  uxState: 'loading',
  assignment: null,
  offline: false,
  actionError: null,
  syncError: false,
  inFlight: false,

  /**
   * Recharge l'affectation ACTIVE depuis le backend (source de vérité).
   * - Succès : met à jour + cache.
   * - Erreur RÉSEAU : mode hors ligne dégradé avec cache (JAMAIS "aucun véhicule").
   * - Erreur APPLICATIVE : état 'error' (Réessayer), sans conclure "aucun véhicule".
   */
  refresh: async () => {
    if (get().uxState !== 'acting') set({ uxState: 'loading' });
    try {
      const { assignment } = await getActiveAssignment();
      await cacheActiveAssignment(assignment);
      set({
        assignment,
        offline: false,
        syncError: false,
        uxState: assignment ? 'active' : 'none',
      });
    } catch (e: any) {
      if (isNetworkError(e)) {
        // Backend injoignable -> affichage dégradé depuis le cache (informatif).
        const { assignment } = await readCachedAssignment();
        logger.warn('assignment', 'refresh network error -> offline degraded');
        set({
          assignment,
          offline: true,
          syncError: false,
          uxState: assignment ? 'offline' : 'error', // pas de cache -> erreur (jamais "none")
        });
      } else {
        // Erreur applicative : NE PAS conclure "aucun véhicule".
        logger.warn('assignment', 'refresh app error', e);
        set({ offline: false, syncError: true, uxState: 'error' });
      }
    }
  },

  take: async (vehicleId: string) => {
    if (get().inFlight || get().offline) {
      if (get().offline) set({ actionError: 'Connexion requise pour effectuer cette action.' });
      return null;
    }
    set({ inFlight: true, uxState: 'acting', actionError: null });
    const requestId = newRequestId('take');
    try {
      const res = await takeVehicle(vehicleId, requestId);
      if (res.result === 'conflict') {
        set({ actionError: reasonToMessage(res.reason) });
      }
      await get().refresh();
      return res;
    } catch (e: any) {
      if (isNetworkError(e)) {
        set({ actionError: 'Connexion requise pour effectuer cette action.', uxState: 'offline' });
      } else {
        set({ actionError: 'Action impossible pour le moment.', uxState: 'error' });
      }
      return null;
    } finally {
      set({ inFlight: false });
    }
  },

  change: async (vehicleId: string) => {
    if (get().inFlight || get().offline) {
      if (get().offline) set({ actionError: 'Connexion requise pour effectuer cette action.' });
      return null;
    }
    set({ inFlight: true, uxState: 'acting', actionError: null });
    const requestId = newRequestId('change');
    try {
      const res = await changeVehicle(vehicleId, requestId);
      if (res.result === 'conflict') {
        // A reste ACTIVE côté backend : le refresh réaffichera A (jamais "aucun véhicule").
        set({ actionError: reasonToMessage(res.reason) });
      }
      await get().refresh();
      return res;
    } catch (e: any) {
      if (isNetworkError(e)) {
        set({ actionError: 'Connexion requise pour effectuer cette action.', uxState: 'offline' });
      } else {
        set({ actionError: 'Action impossible pour le moment.', uxState: 'error' });
      }
      return null;
    } finally {
      set({ inFlight: false });
    }
  },

  end: async () => {
    if (get().inFlight || get().offline) {
      if (get().offline) set({ actionError: 'Connexion requise pour effectuer cette action.' });
      return null;
    }
    set({ inFlight: true, uxState: 'acting', actionError: null });
    const requestId = newRequestId('end');
    try {
      const res = await endAssignment(requestId);
      await get().refresh();
      return res;
    } catch (e: any) {
      if (isNetworkError(e)) {
        set({ actionError: 'Connexion requise pour effectuer cette action.', uxState: 'offline' });
      } else {
        set({ actionError: 'Action impossible pour le moment.', uxState: 'error' });
      }
      return null;
    } finally {
      set({ inFlight: false });
    }
  },

  clearActionError: () => set({ actionError: null }),
}));

/** Message chauffeur pour les conflits d'affectation (aucun jargon technique). */
export function reasonToMessage(reason?: string | null): string {
  switch (reason) {
    case 'VEHICLE_OCCUPIED':
      return "Ce véhicule vient d'être pris par un autre conducteur.";
    case 'DRIVER_ALREADY_ACTIVE':
      return 'Vous avez déjà un véhicule en cours.';
    case 'STATE_CHANGED':
      return "L'état a changé. Réessayez.";
    default:
      return 'Action impossible pour le moment.';
  }
}

// ---------------------------------------------------------------------------
// RÈGLE MÉTIER : « Fin de service » autorisée UNIQUEMENT si Mode Privé = BUSINESS CONFIRMÉ.
// Cohérent avec 0009 : commande envoyée / success=true / PENDING != confirmé.
// SEUL BUSINESS confirmé (state=BUSINESS) autorise END. Tout le reste bloque.
// L'app LIT l'état existant (GET /driver/private-mode) — aucune modif moteur.
// ---------------------------------------------------------------------------
export interface EndGate {
  allowed: boolean;
  message: string | null;   // message à afficher si bloqué
}

export function endServiceGate(pm: PrivateModeStatus | null | undefined, pmError?: boolean): EndGate {
  // Erreur de lecture du mode -> BLOQUÉ (impossible de vérifier, fail-closed).
  if (pmError || !pm) {
    return { allowed: false, message: 'Impossible de vérifier le mode du véhicule. Réessayez avant de terminer votre service.' };
  }
  const state = pm.state;
  const target = pm.requested_target;

  if (state === 'BUSINESS') {
    return { allowed: true, message: null };                     // ✅ SEUL cas autorisé
  }
  if (state === 'PRIVATE') {
    return { allowed: false, message: 'Repassez en Professionnel avant de terminer votre service.' };
  }
  // Transitions PENDING : bloquées jusqu'à confirmation télémétrique (jamais sur success=true).
  if (state === 'PENDING_CONFIRMATION' || state === 'PRIVATE_REQUESTED' || state === 'BUSINESS_REQUESTED') {
    if (target === 'BUSINESS' || state === 'BUSINESS_REQUESTED') {
      return { allowed: false, message: 'Passage en Professionnel en cours de confirmation. Attendez la confirmation avant de terminer votre service.' };
    }
    return { allowed: false, message: 'Changement de mode en cours. Attendez la confirmation avant de terminer votre service.' };
  }
  // Timeout serveur : commande envoyée mais mode NON confirmé (transition_result=TIMEOUT).
  // On ne conclut jamais BUSINESS -> END bloquée + message d'action clair.
  if (pm.transition_result === 'TIMEOUT') {
    return { allowed: false, message: 'Le mode n\'a pas été confirmé. Repassez en Professionnel (faites rouler le véhicule) avant de terminer votre service.' };
  }
  // UNKNOWN / FAILED / autre -> BLOQUÉ (fail-closed).
  return { allowed: false, message: 'Impossible de vérifier le mode du véhicule. Réessayez avant de terminer votre service.' };
}
