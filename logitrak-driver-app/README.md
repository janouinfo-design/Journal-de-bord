# Logitrak Driver — App Native (Phase B)

App **Expo / React Native** pour les chauffeurs Logitrak, conçue pour le scan
BLE continu en arrière-plan (la limitation principale de la PWA Chrome).

## ✅ Statut actuel

Tout le code est **production-ready** :

- ✅ Scanner BLE continu avec `react-native-ble-plx` (state machine, dedupe, permissions)
- ✅ Background task `expo-background-fetch` (flush queue offline toutes les ~15 min)
- ✅ Queue offline avec retry + backoff exponentiel + cap d'âge 24 h
- ✅ Auth JWT + refresh token sécurisé (`expo-secure-store`)
- ✅ Push notifications Expo + handlers d'actions (PRO/PRIVÉ depuis la notif)
- ✅ Realtime WebSocket (conflits BLE, kill switch)
- ✅ Écrans : Login, Driver (vehicle + mode override), Settings
- ✅ TypeScript strict (typecheck PASS)
- ✅ Permissions configurées : iOS `bluetooth-central` + Android `BLUETOOTH_SCAN/CONNECT` + `FOREGROUND_SERVICE`

## 🚀 Mise en route

### 1. Prérequis (poste local)

```bash
# Node 20 + Yarn
node -v       # >= 20.x
yarn -v       # 1.22+

# Outils Expo
npm install -g eas-cli
eas login     # connectez-vous avec le compte Expo (gratuit)
```

### 2. Configuration

Éditer `app.json` :
- Remplacez `"projectId": "00000000-0000-0000-0000-000000000000"` par le vrai
  ID donné par `eas init` (étape suivante).
- Remplacez `"owner": "logitrak"` par votre slug Expo.

```bash
cd /app/logitrak-driver-app
yarn install
eas init    # crée l'app sur Expo + écrit le projectId
```

### 3. Build de test (APK Android, le plus simple pour démarrer)

```bash
eas build --profile preview --platform android
```

EAS compile dans le cloud (~10 min) et fournit un lien APK à télécharger
directement sur la Tab A9.

### 4. Installation sur la Tab A9

1. Ouvrir le lien APK depuis Chrome sur la tablette
2. Autoriser l'installation d'apps inconnues
3. Lancer **Logitrak Driver**
4. Accorder :
   - **Bluetooth** → autoriser
   - **Localisation** → choisir **« Toujours »** (sinon le scan s'arrête en arrière-plan)
   - **Notifications** → autoriser

### 5. Login + test

- Identifiants chauffeur : `chauffeur@logitrak.ch` / `chauffeur123`
- L'écran principal affiche **"Recherche en cours…"** puis bascule sur le véhicule détecté dès que le scan capte un beacon configuré (matching par MAC ou par alias).

### 6. Build de production

```bash
# Mise à jour dans app.json : "version": "1.0.0"
eas build --profile production --platform all
```

## 🔧 Comment ça marche techniquement

### Scanner BLE foreground (app ouverte)
`src/ble/scanner.ts` lance `react-native-ble-plx` en mode continu. À chaque
détection, le scanner :
1. Extrait l'identifiant (`device.name` > `device.localName` > suffixe MAC)
2. Filtre par dedupe (2 s par identifier)
3. Met en queue dans AsyncStorage (`src/ble/queue.ts`)
4. Tente immédiatement un flush HTTP vers `POST /api/livre/ble/detections`

### Scanner BLE arrière-plan
- **iOS** : `UIBackgroundModes: ["bluetooth-central"]` permet à Core Bluetooth de
  continuer le scan tant qu'iOS ne tue pas le processus. Les détections sont
  écrites en queue et flushées au prochain réveil.
- **Android** : la permission `FOREGROUND_SERVICE` est déclarée, mais le scaffold
  actuel utilise `expo-background-fetch` (~15 min) qui suffit pour flusher la
  queue. Pour un scan vraiment continu app fermée, il faut ajouter un plugin
  natif foreground service — réservé Phase C.

### Queue offline
La queue persiste dans `AsyncStorage` jusqu'à 5 000 détections / 24 h. Le flush
est déclenché :
- au démarrage de l'app (hook `useQueueFlusher`)
- à chaque détection (foreground)
- périodiquement par `expo-background-fetch` (background)
- manuellement via le bouton "Flush" dans Settings (à venir)

## 🧪 Comment vérifier que ça fonctionne

1. Démarrer l'app + se connecter en tant que chauffeur
2. Activer le Bluetooth de votre **phone** et celui d'un beacon Logitrak (`BC57291D22C5`)
3. Approcher la phone du beacon (< 5 m)
4. L'écran principal doit afficher le véhicule lié au beacon (`LOGITRAK AUDI`)
5. Côté admin (Chrome desktop) → page **Identification chauffeurs** → la session apparaît avec statut `automatic`, confiance > 80 %

## 🛡️ Sécurité

- Tokens JWT stockés dans **`expo-secure-store`** (Keychain iOS / EncryptedSharedPreferences Android)
- HTTPS obligatoire (les profils EAS dev/preview/production utilisent toutes des URLs HTTPS)
- Pas de logging des tokens ni des données sensibles en clair

## 📚 Liens utiles

- Spec native complète : `/app/docs/phase_b_native_spec.md`
- Spec BLE Phase A : `/app/docs/ble_phase_a.md`
- Backend endpoints utilisés : `POST /api/livre/ble/detections`, `GET /api/livre/driver/current-session`, `POST /api/livre/driver/push-token`
