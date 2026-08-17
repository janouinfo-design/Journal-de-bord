# Logitrak Chauffeur — App mobile Expo

Application mobile **Expo (React Native)** pour les chauffeurs de tous les clients Logitrak.
Elle consomme l'**API existante** `https://journal.logitrak.ch/api` (aucun backend métier n'est créé).
Thème **sombre**, langue **française**, reproduisant la console chauffeur web.

## Fonctionnalités (MVP livré)

- **Connexion** : `POST /api/auth/login {email, password}` → JWT Bearer. L'entreprise (tenant) est reconnue côté serveur via le JWT. Le jeton est stocké (AsyncStorage).
- **Console chauffeur** :
  - **Véhicule détecté** par scan BLE : signal (dBm), nombre de détections, **score de confiance** (calcul local tracé, voir `src/services/detection.js`).
  - **Boutons PRO / PRIVÉ** → `POST /api/livre/driver/manual-mode {mode}`.
  - **Liste des balises BLE de la flotte** (`GET /api/livre/driver/fleet-tags`) avec bouton **Tester** (`POST /api/livre/ble/detections`).
  - **Session courante** : `GET /api/livre/driver/current-session`.
- **États clairs** : chargement, aucune donnée, erreur réseau/API, BLE indisponible — **aucune donnée fictive** n'est jamais affichée.

## Règle « données réelles uniquement »

- Le scan BLE natif (`react-native-ble-plx`) **ne fonctionne que dans un build natif** (development build EAS), **pas dans Expo Go ni sur le web**.
- Sur **web** (preview), l'app affiche clairement « Scan Bluetooth indisponible » et **ne fabrique aucune détection**.
- Le **score de confiance** est calculé à partir de mesures BLE réelles (RSSI + récurrence) et est documenté ; si le serveur fournit un score autoritatif, il doit primer.

## Architecture réseau (important)

- **Natif (iOS/Android)** : l'app appelle **directement** `https://journal.logitrak.ch/api` (le fetch natif n'est pas soumis au CORS).
- **Web (preview de dev)** : le navigateur bloque le cross-origin (CORS). L'app passe donc par un **reverse-proxy transparent** exposé par l'environnement (`REACT_APP_BACKEND_URL` → `/app/backend/server.py`) qui **relaie tel quel** vers l'API réelle. Ce proxy n'ajoute **aucune logique métier** et ne fabrique **aucune donnée**. Il ne relaie que les namespaces `auth/` et `livre/`.

## Lancer en développement (web preview)

Le service `frontend` (supervisor) lance `expo start --web --port 3000`. Ouvrir l'URL de preview.

## Build natif EAS (BLE + notifications push réels)

Le BLE et les notifications push **nécessitent un development build** (pas Expo Go) :

```bash
cd /app/frontend
npm i -g eas-cli          # ou: npx eas-cli
eas login
# 1) Renseigner votre projectId EAS dans app.config.js (extra.eas.projectId)
eas build --profile development --platform android   # APK dev-client
# puis lancer le serveur dev et ouvrir le dev-client :
npx expo start --dev-client
```

- Permissions Bluetooth/Localisation (Android) et descriptions (iOS) sont déjà déclarées dans `app.config.js`.
- Notifications push : renseigner `extra.eas.projectId` puis l'app récupère un **jeton Expo** et l'envoie à `POST /api/livre/driver/push-token` (chemin ajustable dans `src/services/config.js`).

## Structure

```
src/
  context/AuthContext.js       # état JWT + user, signIn/signOut
  navigation/RootNavigator.js  # Login <-> Console selon l'auth
  screens/LoginScreen.js       # connexion JWT
  screens/ConsoleScreen.js     # console chauffeur (écran principal)
  hooks/useDriverConsole.js    # logique métier (session, tags, scan, modes)
  services/api.js              # client API (fetch + JWT + erreurs FR)
  services/config.js           # résolution URL par plateforme
  services/ble.js              # scan BLE natif (abstraction plateforme)
  services/detection.js        # matching tags + score de confiance (tracé)
  services/push.js             # jeton push Expo
  services/storage.js          # persistance JWT/user
  components/                  # UI réutilisable (thème sombre)
  theme/theme.js               # palette sombre Logitrak
```

## Points restants / bonus

- Scan BLE **en arrière-plan** (détection auto) : structure prête (`app.config.js` background modes) — à finaliser dans un build natif.
- Endpoint push exact à confirmer côté backend.
