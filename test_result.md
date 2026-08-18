#====================================================================================================
# Phase 4.1 — Finalisation App Chauffeur Expo (Mes trajets, Profil, Réglages)
#====================================================================================================

user_problem_statement: |
  Phase 4.1 : terminer UNIQUEMENT les écrans manquants de l'app chauffeur Expo — Mes trajets,
  détail trajet, classification PRO/PRIVÉ, Profil, Réglages, navigation par onglets — sans
  toucher au cœur validé (login, claim, current-session, stop, PRO/PRIVÉ, BLE, conflits, push).
  Données réelles uniquement, N/A si champ absent.

frontend:
  - task: "Mes trajets (liste)"
    implemented: true
    working: true
    file: "frontend/src/screens/TripsScreen.tsx, src/store/tripsStore.ts, src/api/trips.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "64 trajets réels affichés (date, badge PRO/PRIVÉ/À classer, plaque, distance, durée). Loading/empty/error/pull-to-refresh gérés."
  - task: "Détail trajet + tracé + reclassification"
    implemented: true
    working: true
    file: "frontend/src/screens/TripDetailScreen.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Itinéraire (adresses réelles), Détails (distance/durée/vitesses/carburant), Tracé (points GPS réels, source affichée), reclassify PRO/PRIVÉ après confirmation serveur — sans crash."
  - task: "Profil chauffeur (read-only)"
    implemented: true
    working: true
    file: "frontend/src/screens/ProfileScreen.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "my-profile réel : nom, email, statut compte, accès mobile, tag BLE (Non), dernière détection. Boutons changer mdp + logout. Read-only (aucun endpoint d'édition driver)."
  - task: "Réglages (compte, notifications réelles, application)"
    implemented: true
    working: true
    file: "frontend/src/screens/SettingsScreen.tsx, src/api/notifications.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Compte (changer mdp, logout), Bluetooth toggle, Notifications = préférences RÉELLES (2 toggles push), Application (version + env dev). Aucune URL/secret affichée."
  - task: "Navigation par onglets (Conduite/Trajets/Profil/Réglages)"
    implemented: true
    working: true
    file: "frontend/src/navigation/RootNavigator.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Bottom tabs OK. Gate must_change_password conservé. TripDetail + ChangePassword en stack. Gear Settings retiré de Conduite (anti-duplication)."
  - task: "RÉGRESSION cœur (login/claim/PRO-PRIVÉ/stop)"
    implemented: true
    working: true
    file: "frontend/src/screens/DriverScreen.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "E2E post-Phase4.1 : CLAIM PASS, PRIVÉ PASS, STOP PASS, bouton stop masqué après. Aucune régression."

metadata:
  created_by: "main_agent"
  version: "3.0"
  test_sequence: 3
  run_ui: true

test_plan:
  current_focus: []
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Phase 4.1 terminée. Qualité: typecheck PASS, lint 0 err (2 warnings pré-existants),
      jest 23/23, expo-doctor 17/17. Backend régression 60 pass / 4 skip (2e tenant non provisionné).
      Cœur intact. PARTIEL inchangés : BLE device, push device, Navixy, SMTP.
