#====================================================================================================
# Testing Protocol - Logitrak Journal de bord — App Chauffeur (Expo) + Backend Phase 3
#====================================================================================================

user_problem_statement: |
  Sync depuis le repo GitHub janouinfo-design/Journal-de-bord (main, Phase 3, 442/442).
  Auditer les contrats API du backend ACTUEL. Corriger l'app Expo déjà développée
  (logitrak-driver-app) SANS repartir de zéro : implémenter « Je m'arrête » (POST /driver/stop),
  le flux must_change_password, conserver les corrections précédentes. Tests obligatoires :
  typecheck, lint, jest, expo-doctor + régression backend pertinente.

backend:
  - task: "Backend Phase 3 (repo) déployé comme backend de travail"
    implemented: true
    working: true
    file: "backend/server.py (repo)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Remplacé l'ancien backend v1 par le backend Phase 3 du repo. Endpoints driver/stop, change-password, must_change_password, ble/detections {detections:[...]}, claim, manual-mode, fleet-tags confirmés. Login {user,access_token,refresh_token}."
  - task: "Régression backend (suites pertinentes)"
    implemented: true
    working: true
    file: "backend/tests/*"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Sur HTTPS preview: test_phase3_admin_driver 23 pass/4 skip (stop, idempotence, conflit, historique, unicité tag), test_iteration8_ble 32/32, test_iteration22_ble_normalize 5/5, test_livre_de_bord majoritaire pass. Skips/échecs restants = 2e tenant (admin-b) + seed fuel/fines non provisionnés (environnemental). Cookies auth Secure => tests DOIVENT tourner via URL HTTPS, pas http://localhost."

frontend:
  - task: "« Je m'arrête » (POST /driver/stop) — bouton, confirmation, anti-double-clic, idempotence"
    implemented: true
    working: true
    file: "frontend/src/screens/DriverScreen.tsx, src/store/sessionStore.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "E2E web 10/10 PASS : stop clôture la session, bouton masqué sans session active, garde submitting. Idempotence gérée (stopped:false)."
  - task: "Flux must_change_password (écran forcé)"
    implemented: true
    working: true
    file: "frontend/src/screens/ChangePasswordScreen.tsx, src/store/authStore.ts, src/navigation/RootNavigator.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Gate implémenté : si must_change_password, seul l'écran de changement est accessible. Compte test = false, donc pas déclenché (comportement correct)."
  - task: "« Je conduis » (claim) + sélecteur véhicule + PRO/PRIVÉ + mapping session.vehicle.plate/model"
    implemented: true
    working: true
    file: "frontend/src/screens/DriverScreen.tsx, src/api/ble.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "E2E: claim GE 123456 -> SESSION ACTIVE, PRO/PRIVÉ bannières OK, plaque/modèle corrects."
  - task: "Adaptateurs plateforme (storage web/native, alert web/native)"
    implemented: true
    working: true
    file: "frontend/src/utils/storage.ts, src/utils/alert.ts"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "expo-secure-store (natif) / localStorage (web) ; Alert.alert (natif) / window.confirm (web). Nécessaire pour le preview web ; natif inchangé."

metadata:
  created_by: "main_agent"
  version: "2.0"
  test_sequence: 2
  run_ui: true

test_plan:
  current_focus: []
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Qualité app: typecheck PASS, lint 0 erreurs (2 warnings pré-existants), jest 10/10, expo-doctor 17/17.
      E2E web 10/10. Backend régression driver/BLE PASS. Reste PARTIEL = 2e tenant + seed fuel/fines + BLE terrain + push device.
