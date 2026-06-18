# Logitrak Driver — App native (Phase B scaffold)

> **Statut** : 📦 Scaffold complet · prêt à builder localement
> **Stack** : Expo SDK 51 · TypeScript · React Native 0.74 · `react-native-ble-plx` 3.x
> **Backend** : consomme l'API FastAPI existante du Livre de Bord Logitrak (Phase A)

---

## 🎯 À quoi sert cette app

App mobile native pour les **chauffeurs** de la flotte Logitrak. Elle :

1. **Scanne le Bluetooth en continu** pour identifier le véhicule conduit via un tag BLE embarqué
2. Envoie les détections au backend pour résolution automatique de la session
3. Affiche le véhicule détecté + 2 gros boutons **PRO** / **PRIVÉ**
4. **File hors-ligne** : continue à enregistrer les détections sans réseau, puis les renvoie en batch
5. **Notifications push** : alertes en cas de conflit BLE ou de clôture forcée par l'admin
6. **WebSocket** temps réel pour la mise à jour instantanée de la session

---

## 📁 Structure

```
logitrak-driver-app/
├── App.tsx                      # Root + providers (auth bootstrap, BG task, push)
├── index.js                     # Expo entry
├── app.json                     # Permissions iOS/Android, plugins
├── eas.json                     # Profils EAS Build (dev / preview / production)
├── .env.example                 # Variables EXPO_PUBLIC_*
└── src/
    ├── api/
    │   ├── client.ts            # axios + JWT access/refresh + intercepteur 401
    │   └── ble.ts               # POST détections, GET current-session, manual-mode
    ├── ble/
    │   ├── scanner.ts           # react-native-ble-plx + dedupe + enqueue
    │   ├── queue.ts             # AsyncStorage queue + flush exponentiel
    │   └── background.ts        # expo-background-fetch (flush périodique)
    ├── hooks/
    │   ├── useCurrentSession.ts # poll 10 s en avant-plan
    │   ├── useQueueFlusher.ts   # flush 30 s + NetInfo reconnect
    │   └── useRealtime.ts       # WebSocket avec backoff exponentiel
    ├── navigation/
    │   └── RootNavigator.tsx    # React Navigation stack
    ├── screens/
    │   ├── LoginScreen.tsx      # email + password → JWT
    │   ├── DriverScreen.tsx     # carte véhicule + boutons PRO/PRIVÉ
    │   └── SettingsScreen.tsx   # toggle BLE, file, déconnexion
    ├── store/                   # Zustand (auth, session, queue)
    ├── utils/
    │   ├── logger.ts            # logs scopés (BLE / api / queue / realtime)
    │   ├── permissions.ts       # demande runtime Android (BT_SCAN/CONNECT/LOCATION)
    │   └── notifications.ts     # Expo Notifications + canal Android
    └── theme/colors.ts          # palette LOGITRAK (dark + accent bleu)
```

---

## 🚀 Démarrage local (sur votre machine)

### Pré-requis

| Outil | Version recommandée |
|---|---|
| Node.js | ≥ 20 LTS |
| Yarn | 1.22+ |
| Xcode | 15+ (build iOS) |
| Android Studio | Hedgehog+ avec SDK 34 et un AVD API 33/34 |
| Expo CLI | inutile, on utilise `npx expo` |
| EAS CLI (build cloud) | `npm i -g eas-cli` |

### 1. Installer les dépendances

```bash
cd /app/logitrak-driver-app
yarn install
```

> ⚠️ `react-native-ble-plx` est un module natif → **vous DEVEZ utiliser un dev client**
> (pas Expo Go) pour tester le BLE réel.

### 2. Configurer l'environnement

```bash
cp .env.example .env
```

Éditez `.env` :

```env
EXPO_PUBLIC_API_URL=https://<votre-preview>.preview.emergentagent.com
EXPO_PUBLIC_WS_SCHEME=wss
EXPO_PUBLIC_DEBUG=1
```

> Pour pointer sur le backend Emergent : récupérez `REACT_APP_BACKEND_URL` dans `/app/frontend/.env`.
> Pour un backend local sur le même réseau Wi-Fi : `http://192.168.x.y:8001` (jamais `localhost` depuis un téléphone réel).

### 3. Premier build (dev client)

#### Android

```bash
npx expo prebuild --clean
npx expo run:android
```

#### iOS (macOS uniquement)

```bash
npx expo prebuild --clean
cd ios && pod install && cd ..
npx expo run:ios --device   # branchez un iPhone via USB
```

> Sur le simulateur iOS, le BLE est désactivé. Utilisez un appareil physique.

### 4. Lancer le serveur de dev

```bash
npx expo start --dev-client
```

Scannez le QR avec votre dev client installé → reload à chaud.

### 5. Tester sans hardware BLE

L'app **n'a pas de simulateur BLE intégré côté natif** (contrairement à la PWA `/driver`).
Pour tester sans tag physique, **gardez la PWA `/driver`** ouverte sur un mobile,
ou utilisez l'endpoint admin :

```bash
curl -X POST "$API_URL/api/livre/ble/simulate" \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"identifier":"BUS35","rssi":-55,"driver_email":"chauffeur@logitrak.ch"}'
```

L'app affichera la session injectée via le polling (10 s) + le WebSocket.

---

## 📦 Builds EAS (cloud)

```bash
eas login
eas build:configure                  # une seule fois (ID projet généré)
eas build --profile preview --platform android
eas build --profile preview --platform ios
```

Profils dans `eas.json` :

| Profil       | Distribution      | API par défaut                  |
|--------------|-------------------|---------------------------------|
| development  | internal + dev    | `https://dev.logitrak.ch`       |
| preview      | internal (TF/IT)  | `https://preview.logitrak.ch`   |
| production   | stores            | `https://app.logitrak.ch`       |

Pour soumettre :

```bash
eas submit --profile production --platform ios
eas submit --profile production --platform android
```

---

## 🔐 Permissions demandées

### iOS

- `NSBluetoothAlwaysUsageDescription` — scan BLE arrière-plan
- `NSBluetoothPeripheralUsageDescription`
- `NSLocationWhenInUseUsageDescription` — requis par CoreBluetooth
- `UIBackgroundModes`: `bluetooth-central`, `fetch`, `remote-notification`, `processing`

### Android

- `BLUETOOTH_SCAN` + `BLUETOOTH_CONNECT` (API 31+)
- `ACCESS_FINE_LOCATION`
- `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_LOCATION` (API 34+)
- `POST_NOTIFICATIONS` (API 33+)
- `WAKE_LOCK` + `RECEIVE_BOOT_COMPLETED`

---

## 🔄 Endpoints consommés

| Méthode | URL                                            | Usage                                   |
|---------|------------------------------------------------|-----------------------------------------|
| POST    | `/api/auth/login`                              | login → JWT                             |
| POST    | `/api/auth/refresh`                            | refresh token                           |
| GET     | `/api/auth/me`                                 | profil utilisateur                      |
| POST    | `/api/auth/logout`                             | logout                                  |
| GET     | `/api/livre/driver/current-session`            | poll session active                     |
| POST    | `/api/livre/ble/detections`                    | ingestion batch                         |
| POST    | `/api/livre/driver/manual-mode`                | forçage PRO/PRIVÉ                       |
| POST    | `/api/livre/driver/push-token` *(optionnel)*   | enregistrement token Expo Push          |
| WS      | `/api/livre/realtime`                          | événements temps réel (conflits, kill)  |

> Le backend FastAPI reste **inchangé**. Tous les endpoints sont compatibles Phase A.
> Le seul ajout suggéré côté backend (optionnel) : `/api/auth/refresh` et
> `/api/livre/driver/push-token` (à ajouter en Phase A.5 selon les besoins).

---

## 🧪 Logs & debug

Les logs sont préfixés par scope dans la console Metro :

```
[10:42:13.012] [INFO] [scanner] BLE scan started
[10:42:14.301] [DEBUG] [queue] enqueued detection { size: 1, id: 'BUS35' }
[10:42:44.105] [INFO] [queue] flushed 7 detections
[10:42:45.880] [INFO] [realtime] WebSocket connected
```

Pour augmenter la verbosité : `EXPO_PUBLIC_DEBUG=1` dans `.env`.

---

## ⚠️ Fallbacks intégrés

| Cas                              | Comportement                                                       |
|----------------------------------|--------------------------------------------------------------------|
| Bluetooth désactivé              | Bannière "Activez le Bluetooth", scanner en attente d'allumage     |
| Permission refusée               | Bannière `⚠ Permission refusée`, boutons PRO/PRIVÉ toujours actifs |
| Réseau coupé                     | File AsyncStorage tamponne 24h max (5 000 détections), backoff exp |
| Token expiré                     | Refresh automatique sur 401, retry de la requête originale         |
| WebSocket fermé                  | Reconnexion auto (backoff 1 s → 30 s), pas de perte de données     |
| Backend indisponible             | Le polling /current-session échoue silencieusement, la file grossit|
| Émulateur iOS / device virtuel   | Scanner reste `idle` ; saisie manuelle PRO/PRIVÉ toujours possible |

---

## 🚧 Limitations connues du scaffold

1. **iOS Background BLE State Restoration** non encore activé — à implémenter dans
   `BleManager` constructor avec `restoreStateIdentifier`. Voir [docs ble-plx](https://github.com/dotintent/react-native-ble-plx#background-mode).
2. **Android Foreground Service BLE** non activé — pour un scan robuste en arrière-plan
   prolongé, ajouter un Foreground Service via `react-native-background-actions`.
3. **Pas de Detox** ni de tests E2E dans ce scaffold.
4. **Pas d'écran de gestion fine des tags** (admin uniquement, déjà sur le web).
5. **Endpoint `/api/auth/refresh`** : le client est prêt à l'utiliser, mais le backend
   FastAPI ne l'expose pas encore. Tant qu'il n'est pas ajouté, un 401 entraîne un logout.

---

## 📚 Documents associés

- [`/app/docs/ble_phase_a.md`](../docs/ble_phase_a.md) — architecture Phase A (PWA + backend)
- [`/app/docs/phase_b_native_spec.md`](../docs/phase_b_native_spec.md) — cahier des charges Phase B
- [`/app/memory/test_credentials.md`](../memory/test_credentials.md) — comptes de test

---

## ❓ Soutien

Pour tout blocage sur le build natif, vérifiez :

1. `npx expo doctor` → résout les versions incompatibles
2. Pour iOS : Xcode → Settings → Locations → Command Line Tools sélectionné
3. Pour Android : `ANDROID_HOME` exporté, AVD avec API 33 ou 34, Bluetooth activé sur le device physique (les AVDs n'émettent pas de BLE)

---

**Phase B livrée — prête à builder.** 🚚
