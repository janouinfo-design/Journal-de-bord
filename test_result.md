#====================================================================================================
# Testing Protocol - Logitrak Chauffeur (Expo mobile app)
#====================================================================================================

user_problem_statement: |
  App mobile Expo « Logitrak Chauffeur » multi-entreprises consommant l'API existante
  https://journal.logitrak.ch/api. Login JWT, console chauffeur (véhicule détecté par BLE,
  signal dBm, nb détections, score confiance, boutons PRO/PRIVÉ, liste tags BLE flotte + test).
  Endpoints: POST /auth/login, GET /livre/driver/current-session, GET /livre/driver/fleet-tags,
  POST /livre/ble/detections, POST /livre/driver/manual-mode. Français, thème sombre.
  BLE natif via react-native-ble-plx (nécessite development build EAS). Bonus: scan BLE
  background + notifications push Expo.

backend:
  - task: "Reverse-proxy transparent vers l'API Logitrak (web preview only)"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "8/8 tests passés. Forward réel auth/ et livre/, JWT passé, 401 réels relayés (Email ou mot de passe incorrect, Token invalide), 404 hors namespace, routes locales non régressées."

frontend:
  - task: "Écran de connexion JWT"
    implemented: true
    working: true
    file: "frontend/src/screens/LoginScreen.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Rendu OK (thème sombre FR), toggle mot de passe OK, validation OK, erreur réelle serveur affichée (Email ou mot de passe incorrect) via proxy same-origin."

  - task: "Console chauffeur (session, tags flotte, PRO/PRIVÉ, scan BLE)"
    implemented: true
    working: "NA"
    file: "frontend/src/screens/ConsoleScreen.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Implémenté. Non testable au-delà du login sans identifiants chauffeur valides. BLE natif non testable sur web (état 'indisponible' affiché, aucune donnée fictive)."

  - task: "Service BLE (react-native-ble-plx) + score de confiance tracé"
    implemented: true
    working: "NA"
    file: "frontend/src/services/ble.js, frontend/src/services/detection.js"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Nécessite un development build EAS (téléphone réel). Sur web: indisponible par design."

  - task: "Scan BLE arrière-plan + auto-détection + notif locale (bonus)"
    implemented: true
    working: "NA"
    file: "frontend/src/services/backgroundScan.js"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Implémenté: toggle auto-détection persisté, notif locale au seuil de confiance, restoreState iOS. Testable uniquement en build natif EAS. Android background persistant nécessite un Foreground Service (non inclus, documenté)."

  - task: "Enregistrement jeton push Expo (POST /livre/driver/push-token)"
    implemented: true
    working: "NA"
    file: "frontend/src/services/push.js, frontend/src/hooks/useDriverConsole.js"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Câblé au montage de la console (natif). Endpoint confirmé par l'utilisateur. Non testable sur web."

metadata:
  created_by: "main_agent"
  version: "1.0"
  test_sequence: 1
  run_ui: false

test_plan:
  current_focus:
    - "Console chauffeur avec identifiants réels (en attente de credentials)"
    - "Scan BLE réel via build EAS natif"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      MVP livré et vérifié: login JWT via API réelle (proxy web pour contourner CORS,
      natif appelle l'API directement). Console chauffeur implémentée mais flux authentifié
      non testé (aucun identifiant chauffeur fourni). BLE/push nécessitent un build EAS natif.
      Aucune donnée fictive: états N/A / erreur / indisponible clairs partout.
