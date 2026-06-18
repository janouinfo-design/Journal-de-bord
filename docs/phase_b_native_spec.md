# Phase B — App native Expo (cahier des charges)

> **Statut** : 📋 Cahier des charges · Pas encore démarrée
> **Pré-requis** : Phase A `livre-ble-phase-a-stable` ✅

---

## 🎯 Objectif

Remplacer la PWA web `/driver` par une **vraie app mobile native** capable
de scanner les balises BLE **en arrière-plan**, recevoir des **notifications
push**, et fonctionner **hors-ligne** avec replay quand le réseau revient.

---

## 🧱 Stack technique recommandée

| Couche | Choix | Justification |
|---|---|---|
| Framework | **Expo SDK 51+** (React Native 0.74+) | Build managé, OTA updates, EAS Build |
| BLE | **`react-native-ble-plx`** | Maintenu, supporte iOS + Android, API stable |
| Background | **`expo-background-task`** + Foreground Service Android | Scan BLE périodique même app fermée |
| Notifications | **`expo-notifications`** + Expo Push Service | Gratuit, sans Firebase à provisionner |
| Storage | **`@react-native-async-storage/async-storage`** | Queue détections + token JWT |
| HTTP | **`axios`** (déjà familier côté web) | Cohérence avec le frontend |
| Auth | **JWT avec refresh token** | Sessions longues sans re-login |
| Maps (optionnel) | **`react-native-maplibre-gl`** | Cohérence avec frontend web |
| Tests | **Jest + Detox** | Tests E2E mobile |

---

## 🗂️ Structure du repo `logitrak-driver-app` (séparé)

```
logitrak-driver-app/
├── app.json                    # Expo config + permissions iOS/Android
├── App.tsx                     # Root, navigation, providers
├── src/
│   ├── api/
│   │   ├── client.ts           # axios + intercepteur refresh-token
│   │   └── ble.ts              # POST /ble/detections, manual-mode
│   ├── ble/
│   │   ├── scanner.ts          # react-native-ble-plx wrapper
│   │   ├── background.ts       # expo-background-task task
│   │   └── queue.ts            # offline buffer + replay
│   ├── screens/
│   │   ├── LoginScreen.tsx
│   │   ├── DriverScreen.tsx    # vehicle card + PRO/PRIVÉ buttons
│   │   └── SettingsScreen.tsx
│   ├── hooks/
│   │   ├── useCurrentSession.ts
│   │   └── useRealtime.ts      # WebSocket (Phase B WebSocket)
│   └── store/                  # Zustand (auth, session, queue)
├── eas.json                    # EAS Build profiles (dev / preview / prod)
└── README.md
```

---

## 🔐 Permissions

### iOS (`Info.plist` via `app.json` `expo.ios.infoPlist`)
```json
"NSBluetoothAlwaysUsageDescription": "Logitrak utilise le Bluetooth pour identifier automatiquement le véhicule conduit.",
"NSBluetoothPeripheralUsageDescription": "Détection des tags BLE installés à bord.",
"UIBackgroundModes": ["bluetooth-central", "fetch", "remote-notification"]
```

### Android (`AndroidManifest.xml` via `app.json` `expo.android.permissions`)
```
- BLUETOOTH_SCAN              (API 31+)
- BLUETOOTH_CONNECT           (API 31+)
- ACCESS_FINE_LOCATION        (required by BLE scan)
- FOREGROUND_SERVICE
- FOREGROUND_SERVICE_LOCATION (API 34+)
- POST_NOTIFICATIONS          (API 33+)
```

⚠️ Justification Apple obligatoire en review : « Background BLE scan to
automatically identify the vehicle being driven — privacy-by-design, no
location data leaves the device unless the driver explicitly classifies a
trip as professional. »

---

## 🌊 Architecture offline-first

```
┌────────────────────────────────────────────────────────────────┐
│  Tracker BLE émet → ble-plx → detectionsQueue (AsyncStorage)   │
│                                       │                        │
│                                       ▼                        │
│              chaque 30s OR network online :                    │
│                  POST /ble/detections (batch)                  │
│                                       │                        │
│                                       ▼                        │
│                       backend → driver_sessions                │
└────────────────────────────────────────────────────────────────┘
```

- Queue locale tamponnée ≤ 24h
- Backoff exponentiel si erreur réseau (1s, 2s, 4s, 8s, 16s, 30s, 60s max)
- Sync forcée au passage en avant-plan + au retour de réseau

---

## 📡 Endpoints réutilisés (Phase A → compatibles)

Aucun nouvel endpoint backend requis pour la Phase B — l'app consomme :

| Méthode | URL | Usage |
|---|---|---|
| POST `/api/auth/login` | login + JWT |
| POST `/api/auth/refresh` | refresh token (à ajouter Phase A.5 si nécessaire) |
| GET `/api/livre/driver/current-session` | poll OU push via WebSocket |
| POST `/api/livre/ble/detections` | ingestion batch |
| POST `/api/livre/driver/manual-mode` | toggle PRO/PRIVÉ |
| WS `/api/livre/realtime` | push temps réel (conflits, kill switch) |

---

## ✅ Critères d'acceptation Phase B

1. App installable depuis TestFlight (iOS) + Play Internal (Android)
2. Scan BLE actif **app fermée** sur les 2 plateformes (test 24h)
3. Queue offline : retrait du réseau pendant 1h, retour → toutes les détections sont remontées
4. Notification push reçue quand l'admin déclare un conflit non résolu
5. PRO/PRIVÉ fonctionne hors-ligne (action enqueue + replay)
6. Battery drain < 5 % par 24h en usage normal (mesure Apple Energy / Android Battery)
7. Latence détection → backend < 15 s en conditions réseau normales
8. Crash-free rate ≥ 99,5 % sur 100 sessions

---

## 💰 Coûts annexes

- Apple Developer Program : **99 USD / an**
- Google Play Console : **25 USD une fois**
- EAS Build (Expo) : gratuit jusqu'à 30 builds/mois, sinon ~99 USD/mois
- (optionnel) Sentry mobile : gratuit ≤ 5k events/mois

---

## 🗓️ Planning prévisionnel

| Sprint | Durée | Livrable |
|---|---|---|
| S1 | 1 semaine | Scaffold Expo, login, navigation, écran chauffeur |
| S2 | 1 semaine | BLE scanner + queue offline + intégration backend |
| S3 | 1 semaine | Background task iOS/Android + notifications push |
| S4 | 1 semaine | Polishing, tests Detox, builds EAS preview |
| Review | 2 semaines | TestFlight + Play Internal + soumission stores |

**Total : ~6-7 semaines** entre kickoff et publication.

---

## 🚧 Points d'attention

1. **iOS Background BLE State Restoration** — implémentation pointue, prévoir 2-3 jours
2. **Android Battery Optimization** — demander l'exemption via `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`
3. **Review Apple** — anticiper 2-3 cycles de review (justification BLE background)
4. **GDPR / nLPD** — politique de confidentialité dédiée + bouton « Supprimer mon compte » dans l'app

---

## 🔗 Liens vers Phase A

- Documentation backend : [`/app/docs/ble_phase_a.md`](./ble_phase_a.md)
- Cascade de priorités : `mobile_override > vehicle.mode > geofence > schedule`
- Score de confiance : 35 % stabilité + 25 % force + 20 % durée + 20 % historique
