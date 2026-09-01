#====================================================================================================
# Phase 4.1 — Finalisation App Chauffeur Expo (Mes trajets, Profil, Réglages)
#====================================================================================================

user_problem_statement: |
  Phase 4.1 : terminer UNIQUEMENT les écrans manquants de l'app chauffeur Expo — Mes trajets,
  détail trajet, classification PRO/PRIVÉ, Profil, Réglages, navigation par onglets — sans
  toucher au cœur validé (login, claim, current-session, stop, PRO/PRIVÉ, BLE, conflits, push).
  Données réelles uniquement, N/A si champ absent.

backend:
  - task: "Navixy credential refactor regression - multi-tenant isolation"
    implemented: true
    working: true
    file: "backend/app/integrations.py, app/navixy_client.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Suite 1 (test_navixy_multitenant.py + test_navixy_credential.py + test_odometer_audit.py): 14 PASSED. Multi-tenant credential isolation, priority resolution, odometer UNAVAILABLE (not zero), anti-IDOR all verified."
  - task: "Navixy refactor regression - BLE + auto-assignment unaffected"
    implemented: true
    working: true
    file: "backend/app/ble_engine.py, app/assignments.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Suite 2 (test_iteration8_ble.py + test_phase42_autoassign.py): 38 PASSED. BLE detection and auto-assignment logic unaffected by credential refactor."
  - task: "Navixy refactor regression - Phase 3 admin/driver flows"
    implemented: true
    working: true
    file: "backend/app/routes/"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Suite 3 (test_phase3_admin_driver.py): 23 PASSED, 4 SKIPPED (2nd tenant admin-b not provisioned - expected). No new failures introduced by refactor."
  - task: "Odometer endpoint security + UNAVAILABLE behavior"
    implemented: true
    working: true
    file: "backend/app/routes/livre.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Curl verification: GET /api/livre/driver/vehicle/odometer without auth → 401 ✓. With auth (chauffeur@logitrak.ch) → 200 with status='UNAVAILABLE', odometer_km=null, reason='no_active_vehicle' ✓. NEVER returns 0. Correct expected behavior (Navixy not configured in env)."

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
  - task: "Login screen - password eye toggle, remember checkbox, trim"
    implemented: true
    working: true
    file: "logitrak-driver-app/src/screens/LoginScreen.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "All 5 tests PASS: (1) Login screen renders with all elements (LOGITRAK, email, password, eye toggle testID=login-toggle-password, Rester connecté checkbox testID=login-remember, Se connecter button). (2) Password eye toggle works - icon changes 👁️↔🙈, secureTextEntry toggles correctly. (3) Remember checkbox toggles checkmark ✓ on/off. (4) KEY TEST: Login with spaces '  chauffeur@logitrak.ch  ' succeeds - trim() works, navigates to Driver screen showing Jean Dupont + bottom tabs (Conduite/Mes trajets/Profil/Réglages). (5) No console errors (BLE/notifications warnings filtered). Screenshots confirm all features working."

metadata:
  created_by: "main_agent"
  version: "3.1"
  test_sequence: 4
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
  - agent: "testing"
    message: |
      Login screen verification complete (Phase 4.1 review). All new features tested and working:
      ✅ Password show/hide eye toggle (testID: login-toggle-password) - icon changes, secureTextEntry toggles
      ✅ "Rester connecté" checkbox (testID: login-remember) - toggles checkmark correctly
      ✅ Trim on email+password - KEY TEST PASS: login with '  chauffeur@logitrak.ch  ' (spaces) succeeds, navigates to Driver screen
      ✅ All UI elements render correctly with proper testIDs
      ✅ No console errors (filtered BLE/notifications/web-unavailable warnings)
      Real credentials tested: chauffeur@logitrak.ch / chauffeur123. Screenshots captured. No issues found.
  - agent: "testing"
    message: |
      BACKEND REGRESSION TEST COMPLETE - Navixy credential refactor to centralized multi-tenant module (app/integrations.py).
      
      TEST RESULTS (all against HTTPS preview URL):
      ✅ Suite 1 (Navixy multi-tenant + credential + odometer audit): 14 PASSED
      ✅ Suite 2 (BLE + auto-assignment): 38 PASSED  
      ✅ Suite 3 (Phase 3 admin/driver): 23 PASSED, 4 SKIPPED (expected - 2nd tenant not provisioned)
      ✅ Curl verification: 401 without auth ✓, UNAVAILABLE (not 0) with auth ✓
      
      TOTAL: 75 PASSED, 4 SKIPPED, 0 FAILED
      
      NO REGRESSION DETECTED. The centralized credential resolver (fail-closed, per-tenant, Fernet encryption, global fallback gated) is working correctly. Navixy-dependent reads correctly return UNAVAILABLE (never 0) when Navixy is not configured. All security checks (401, anti-IDOR, multi-tenant isolation) passing.
