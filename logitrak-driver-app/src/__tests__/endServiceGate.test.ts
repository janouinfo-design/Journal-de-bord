import { endServiceGate, reasonToMessage } from '@/store/assignmentStore';
import type { PrivateModeStatus } from '@/api/privateMode';

/**
 * Tests de la RÈGLE MÉTIER critique : « Fin de service » autorisée UNIQUEMENT
 * si le Mode Privé est BUSINESS CONFIRMÉ. Cohérent avec 0009 (commande envoyée /
 * PENDING / success=true != confirmé). Le mobile LIT l'état, ne modifie pas le moteur.
 */

function pm(partial: Partial<PrivateModeStatus>): PrivateModeStatus {
  return { state: 'UNKNOWN', allowed: true, ...partial } as PrivateModeStatus;
}

describe('endServiceGate — Fin de service ↔ Mode Privé', () => {
  test('BUSINESS confirmé → END AUTORISÉE', () => {
    const g = endServiceGate(pm({ state: 'BUSINESS' }));
    expect(g.allowed).toBe(true);
    expect(g.message).toBeNull();
  });

  test('PRIVATE confirmé → END BLOQUÉE (repasser PRO)', () => {
    const g = endServiceGate(pm({ state: 'PRIVATE' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Repassez en Professionnel/i);
  });

  test('PENDING vers PRIVATE → END BLOQUÉE', () => {
    const g = endServiceGate(pm({ state: 'PENDING_CONFIRMATION', requested_target: 'PRIVATE' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Changement de mode en cours/i);
  });

  test('PENDING vers BUSINESS → END BLOQUÉE jusqu’à confirmation', () => {
    const g = endServiceGate(pm({ state: 'PENDING_CONFIRMATION', requested_target: 'BUSINESS' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/en cours de confirmation/i);
  });

  test('BUSINESS_REQUESTED (transition) → END BLOQUÉE', () => {
    const g = endServiceGate(pm({ state: 'BUSINESS_REQUESTED' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/en cours de confirmation/i);
  });

  test('PRIVATE_REQUESTED (transition) → END BLOQUÉE', () => {
    const g = endServiceGate(pm({ state: 'PRIVATE_REQUESTED' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Changement de mode en cours/i);
  });

  test('UNKNOWN → END BLOQUÉE (fail-closed)', () => {
    const g = endServiceGate(pm({ state: 'UNKNOWN' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Impossible de vérifier/i);
  });

  test('erreur lecture private-mode (pmError) → END BLOQUÉE', () => {
    const g = endServiceGate(null, true);
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Impossible de vérifier/i);
  });

  test('status null sans erreur → END BLOQUÉE (fail-closed)', () => {
    const g = endServiceGate(null);
    expect(g.allowed).toBe(false);
  });

  test('séquence PRIVATE → PRO(pending) → BUSINESS confirmé : END devient dispo', () => {
    // 1. PRIVATE confirmé -> bloqué
    expect(endServiceGate(pm({ state: 'PRIVATE' })).allowed).toBe(false);
    // 2. Chauffeur appuie PRO -> PENDING vers BUSINESS -> toujours bloqué
    expect(endServiceGate(pm({ state: 'PENDING_CONFIRMATION', requested_target: 'BUSINESS' })).allowed).toBe(false);
    // 3. TELEMETRY_CONFIRMED -> BUSINESS -> END autorisée
    expect(endServiceGate(pm({ state: 'BUSINESS' })).allowed).toBe(true);
  });

  test('timeout serveur (UNKNOWN + transition_result=TIMEOUT) → END BLOQUÉE + message d\'action', () => {
    const g = endServiceGate(pm({ state: 'UNKNOWN', transition_result: 'TIMEOUT', requested_target: 'BUSINESS' }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/n'a pas été confirmé/i);
    expect(g.message).toMatch(/rouler/i);
  });

  test('success=true à l\'envoi ne débloque PAS END (état PENDING reste bloquant)', () => {
    // Simule le retour d'un POST « ok » mais état device NON prouvé (PENDING).
    const g = endServiceGate(pm({ state: 'PENDING_CONFIRMATION', requested_target: 'PRIVATE' }));
    expect(g.allowed).toBe(false);
  });

  test('FAILED → END BLOQUÉE (fail-closed)', () => {
    const g = endServiceGate(pm({ state: 'FAILED' as any }));
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Impossible de vérifier/i);
  });

  test('BUSINESS confirmé APRÈS timeout (promotion tardive) → END AUTORISÉE', () => {
    // Le backend a fini par confirmer BUSINESS (télémétrie tardive). state=BUSINESS prime.
    const g = endServiceGate(pm({ state: 'BUSINESS', transition_result: 'TIMEOUT' as any }));
    expect(g.allowed).toBe(true);
  });

  // -------------------------------------------------------------------------
  // AUTORITÉ BACKEND (end_service_allowed / private_mode_applicable).
  // Bug Ivan/S564 : compte sans Mode Privé + véhicule sans capability.
  // -------------------------------------------------------------------------
  test('backend: end_service_allowed=true (non applicable) → END AUTORISÉE même si state≠BUSINESS', () => {
    const g = endServiceGate(
      pm({ state: 'UNKNOWN', private_mode_applicable: false, end_service_allowed: true }),
    );
    expect(g.allowed).toBe(true);
    expect(g.message).toBeNull();
  });

  test('cas Ivan/S564 : private_mode_applicable=false + end_service_allowed=true → END AUTORISÉE', () => {
    const g = endServiceGate(
      pm({ state: 'UNKNOWN', allowed: false, private_mode_applicable: false, end_service_allowed: true }),
    );
    expect(g.allowed).toBe(true);
  });

  test('backend: end_service_allowed=false + PRIVATE → END BLOQUÉE (repasser PRO)', () => {
    const g = endServiceGate(
      pm({ state: 'PRIVATE', private_mode_applicable: true, end_service_allowed: false }),
    );
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Repassez en Professionnel/i);
  });

  test('backend: end_service_allowed=false + PENDING → END BLOQUÉE', () => {
    const g = endServiceGate(
      pm({ state: 'PENDING_CONFIRMATION', private_mode_applicable: true, end_service_allowed: false }),
    );
    expect(g.allowed).toBe(false);
    expect(g.message).toMatch(/Changement de mode en cours/i);
  });

  test('backend: end_service_allowed=true + BUSINESS → END AUTORISÉE', () => {
    const g = endServiceGate(
      pm({ state: 'BUSINESS', private_mode_applicable: true, end_service_allowed: true }),
    );
    expect(g.allowed).toBe(true);
  });

  test('repli rétro-compat : private_mode_applicable=false SANS end_service_allowed → END AUTORISÉE', () => {
    // Backend ancien sans end_service_allowed, mais expose private_mode_applicable=false.
    const g = endServiceGate(pm({ state: 'UNKNOWN', private_mode_applicable: false }));
    expect(g.allowed).toBe(true);
  });
});

describe('reasonToMessage — conflits affectation', () => {
  test('VEHICLE_OCCUPIED', () => {
    expect(reasonToMessage('VEHICLE_OCCUPIED')).toMatch(/autre conducteur/i);
  });
  test('DRIVER_ALREADY_ACTIVE', () => {
    expect(reasonToMessage('DRIVER_ALREADY_ACTIVE')).toMatch(/déjà un véhicule/i);
  });
  test('STATE_CHANGED', () => {
    expect(reasonToMessage('STATE_CHANGED')).toMatch(/état a changé/i);
  });
  test('inconnu → message générique', () => {
    expect(reasonToMessage('WHATEVER')).toMatch(/impossible/i);
  });
});
