# Livre de Bord — BLE Phase A (Identification chauffeur PWA)

> **Statut** : ✅ Stable · Backend 32/32 pytest · Frontend e2e validé
> **Version** : `livre-ble-phase-a-stable`
> **Date** : Février 2026

---

## 🎯 Objectif

Identifier automatiquement quel chauffeur conduit quel véhicule grâce à des
tags Bluetooth BLE installés à bord, et permettre au chauffeur de **forcer**
la classification du trajet en **PROFESSIONNEL** ou **PRIVÉ** depuis une
console mobile (PWA web pour la Phase A).

---

## 🧩 Architecture Phase A

```
┌────────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│ PWA Chauffeur      │     │ FastAPI Backend   │     │ MongoDB         │
│ /driver            │────▶│ /api/livre/ble/*  │────▶│ ble_tags        │
│ (mobile browser)   │     │ /api/livre/driver/│     │ ble_detections  │
│                    │     │     *             │     │ driver_sessions │
│ - vehicle card     │     │                   │     │ audit_log       │
│ - 2 boutons        │◀────│ cascade rules :   │     │ trips.mobile_   │
│   PRO / PRIVÉ      │     │  mobile > vehicle │     │   override      │
│ - simulateur BLE   │     │  > geofence > sch │     └─────────────────┘
└────────────────────┘     └───────────────────┘
        ▲                          ▲
        │                          │
        │ poll /current-session    │
        │ POST /detections         │
        │ POST /manual-mode        │
        │                          │
   ┌────┴───────┐             ┌────┴──────────────────────┐
   │ Chauffeur  │             │ Admin Logitrak            │
   │ Jean Dupont│             │ /livre/identification     │
   └────────────┘             │  - 8 KPI cards            │
                              │  - Tableau sessions       │
                              │  - Actions inline         │
                              │  - Dialog modification    │
                              └───────────────────────────┘
```

---

## 📡 Endpoints REST créés

> Préfixe : `/api/livre` · Auth : cookie session JWT

### CRUD Tags BLE (admin)

| Méthode | URL | Rôle | Description |
|---|---|---|---|
| `GET`    | `/ble/tags`                      | admin/manager | Liste des tags du tenant |
| `POST`   | `/ble/tags`                      | admin         | Upsert `{id?, vehicle_id, identifier, label}` |
| `DELETE` | `/ble/tags/{tag_id}`             | admin         | Supprime un tag |

### Ingestion & simulation

| Méthode | URL | Rôle | Description |
|---|---|---|---|
| `POST` | `/ble/detections` | driver/admin/manager | Ingest 1 ou N détections `{identifier, rssi, ts?, platform?, battery?}`. Mapping chauffeur ↔ user par email pour rôle driver. |
| `POST` | `/ble/simulate`   | admin | Injecte une détection synthétique pour tester sans tag physique |

### Sessions chauffeur (admin/manager)

| Méthode | URL | Rôle | Description |
|---|---|---|---|
| `GET`    | `/ble/sessions?status=&start=&end=&limit=200` | admin/manager | Liste enrichie (driver_name, vehicle_plate, vehicle_model) |
| `PUT`    | `/ble/sessions/{id}` | admin/manager | Amend `{driver_id?, vehicle_id?, status?, mobile_override?}` + audit log |
| `GET`    | `/ble/dashboard?start=&end=` | admin/manager | KPIs agrégés |
| `GET/PUT` | `/ble/settings` | admin/manager (GET) · admin (PUT) | 5 clés : `ble_enabled`, `ble_min_duration_s`, `ble_min_rssi`, `ble_min_confidence`, `allow_driver_override` |

### Chauffeur PWA

| Méthode | URL | Rôle | Description |
|---|---|---|---|
| `GET`  | `/driver/current-session` | driver (ou admin/manager pour debug) | Session active du chauffeur authentifié, enrichie avec véhicule |
| `POST` | `/driver/manual-mode` | driver | `{mode: 'professional' \| 'personal'}` — stamp session + propage `mobile_override` à tous les trips à venir + audit |

---

## ⚖️ Cascade de priorités (rules.classify_trip)

Ordre absolu, du plus prioritaire au moins prioritaire :

```
1. trip.mobile_override         (choix manuel du chauffeur depuis l'app)
2. vehicle.mode                 (always_pro / always_perso)
3. trip.geofence_classification (positionné par moteur de géofence — à implémenter)
4. schedule (driver ou défaut)  (plages horaires par jour de la semaine)
```

**Garantie testée unitairement** : si un chauffeur clique PRIVÉ à 10 h, même
si le véhicule est `always_pro` et l'horaire est « travail 08-17 », le trajet
est classé `personal`. Voir
[`backend/tests/test_iteration8_ble.py`](../backend/tests/test_iteration8_ble.py).

---

## 🧠 Score de confiance (`_compute_confidence`)

Échelle 0..100 calculée sur fenêtre glissante de **30 minutes** :

| Facteur | Poids | Calcul |
|---|---|---|
| **Stabilité du signal**  | 35 % | `(1 - min(stdev_RSSI, 20) / 20) × 35` |
| **Force du signal**       | 25 % | RSSI médian normalisé entre –95 et –40 dBm × 25 |
| **Durée de présence**     | 20 % | `min(minutes / 5, 1) × 20` (plein à 5 min) |
| **Historique de pairing** | 20 % | Ratio passé `(driver,vehicle)` / total sessions closes du driver × 20 |

Promotion de statut :
- `< ble_min_duration_s` (défaut 120 s) → `open`
- `>= ble_min_confidence` (défaut 60) → `automatic`
- sinon → `pending` (validation manuelle requise)
- Override mobile → `manual`

---

## 📱 PWA Chauffeur (`/driver`)

- **Route protégée** hors du AppLayout (design dédié plein écran sombre)
- **Polling** `/driver/current-session` toutes les 10 s
- **Composants** :
  - Vehicle card avec pulse vert, plaque, modèle, RSSI, détections, barre de confiance
  - 2 gros boutons `PRO` (bleu) / `PRIVÉ` (gris clair) avec badge `ACTIF`
  - Banner override jaune si `mobile_override` actif
  - Simulateur BLE intégré (input `BUS35` + bouton ping → 3 détections rapides)
- **data-testids** : `driver-console-page`, `driver-vehicle-card`,
  `driver-mode-pro`, `driver-mode-perso`, `driver-override-banner`,
  `driver-sim-input`, `driver-sim-ping`, `driver-refresh`, `driver-logout`

---

## 🧪 Procédure de test

### Pré-requis
- Backend FastAPI actif (supervisor)
- MongoDB seedé avec mock data
- 1 véhicule réel Navixy synchronisé (ex. LOGITRAK AUDI)
- Comptes : `admin@logitrak.ch / admin123`, `manager@logitrak.ch / manager123`,
  `chauffeur@logitrak.ch / chauffeur123`

### Test rapide (5 minutes)

```bash
API_URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)

# 1. Admin crée un tag BLE
curl -s -c /tmp/adm.txt -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@logitrak.ch","password":"admin123"}' > /dev/null

VEH_ID=$(curl -s -b /tmp/adm.txt "$API_URL/api/livre/vehicles" \
  | python3 -c "import sys,json;print([v['id'] for v in json.load(sys.stdin) if 'LOGITRAK' in (v.get('plate') or '')][0])")

curl -s -b /tmp/adm.txt -X POST "$API_URL/api/livre/ble/tags" \
  -H "Content-Type: application/json" \
  -d "{\"vehicle_id\":\"$VEH_ID\",\"identifier\":\"BUS35\"}"

# 2. Chauffeur envoie 5 détections
curl -s -c /tmp/drv.txt -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"chauffeur@logitrak.ch","password":"chauffeur123"}' > /dev/null

for i in 1 2 3 4 5; do
  curl -s -b /tmp/drv.txt -X POST "$API_URL/api/livre/ble/detections" \
    -H "Content-Type: application/json" \
    -d '{"identifier":"BUS35","rssi":-60,"platform":"pwa"}' > /dev/null
  sleep 0.3
done

# 3. Vérifier la session
curl -s -b /tmp/drv.txt "$API_URL/api/livre/driver/current-session" | python3 -m json.tool

# 4. Forçage PRIVÉ par le chauffeur
curl -s -b /tmp/drv.txt -X POST "$API_URL/api/livre/driver/manual-mode" \
  -H "Content-Type: application/json" -d '{"mode":"personal"}' | python3 -m json.tool

# 5. Admin voit la session
curl -s -b /tmp/adm.txt "$API_URL/api/livre/ble/sessions?limit=3" | python3 -m json.tool
```

### Test interactif PWA

1. Ouvrir https://&lt;backend-url&gt;/driver dans un mobile (ou Chrome DevTools mode mobile)
2. Login `chauffeur@logitrak.ch` / `chauffeur123`
3. Taper `BUS35` dans le simulateur BLE et cliquer l'icône Bluetooth
4. La carte véhicule s'affiche avec pulse vert
5. Cliquer **PRIVÉ** → badge ACTIF apparaît
6. Toast `Mode PRIVÉ activé · N trajet(s) impacté(s)`

### Tests automatisés
- `pytest backend/tests/test_iteration8_ble.py` → 32 tests cascade, RBAC, confidence, ignore rssi/tag inconnu
- Rapport agent : `/app/test_reports/iteration_8.json`

---

## ⚠️ Limites de la PWA Phase A

| Limite | Conséquence | Mitigation Phase B |
|---|---|---|
| **Pas de scan BLE en arrière-plan** | Le téléphone doit avoir la page `/driver` ouverte en avant-plan pour ingérer les détections | App native React Native avec service Foreground (Android) / Core Bluetooth (iOS) |
| **Pas de notifications push** | Conflits BLE non remontés en temps réel | Expo Push Notifications + token enregistré côté backend |
| **Simulateur BLE manuel** | Test sans hardware mais pas de scan réel | Bibliothèque `react-native-ble-plx` |
| **Une seule détection à la fois** | Pas de comparaison RSSI cross-device temps réel | WebSocket + batch ingestion natif |
| **Auth via cookie session web** | Sécurisé mais nécessite renouvellement périodique | JWT avec refresh token pour app native |
| **Pas de chiffrement bout-en-bout des positions** | Acceptable pour MVP RGPD | Si requis : envelope encryption sur les détections sensibles |

---

## 🚧 Points reportés en Phase B (app native)

1. **App Expo / React Native** dédiée (repo séparé)
2. **Scan BLE en arrière-plan** (iOS Core Bluetooth State Restoration, Android Foreground Service)
3. **Notifications push** via Expo Push Notifications
4. **Détection multi-chauffeurs** (cas n° 7 de la spec) — sessions `status=conflict` quand 2 téléphones reçoivent le même tag avec scores équivalents
5. **Détection cross-device** par comparaison RSSI agrégée côté serveur
6. **Auto-clôture de session** par géofence d'arrivée (extinction moteur Navixy)
7. **Mode hors ligne** : queue locale des détections + replay quand le réseau revient
8. **Bouton physique BLE** alternative (button widget pour les flottes sans smartphone)

---

## 🚧 Points reportés en Phase C (déploiement)

1. Compte Apple Developer + Google Play Console
2. EAS Build (Expo) + TestFlight + Play Internal Testing
3. Politique de confidentialité dédiée (mention BLE, géolocalisation)
4. Soumission Apple : justification de l'usage du Bluetooth en arrière-plan
5. Builds CI/CD via GitHub Actions

---

## 📂 Fichiers livrés

### Backend
- `backend/app/ble_engine.py` (NOUVEAU)
- `backend/app/rules.py` (cascade modifiée)
- `backend/app/routes.py` (11 endpoints ajoutés)
- `backend/tests/test_iteration8_ble.py` (32 tests pytest)

### Frontend
- `frontend/src/pages/IdentificationPage.jsx` (NOUVEAU)
- `frontend/src/pages/DriverConsolePage.jsx` (NOUVEAU)
- `frontend/src/pages/SettingsPage.jsx` (colonne « Tag BLE »)
- `frontend/src/App.js` (routes `/livre/identification`, `/driver`)
- `frontend/src/components/layout/AppLayout.jsx` (section nav « Identification BLE »)

### Documentation
- `docs/ble_phase_a.md` (ce fichier)
- `memory/PRD.md` (entrée Iteration 8)
- `memory/test_credentials.md` (à jour)

---

## ✅ Critères de validation Phase A — atteints

- [x] Backend MongoDB pour tags, détections, sessions, audit
- [x] Endpoint ingestion fiable (idempotent, ignore rssi faible / tag inconnu)
- [x] Score de confiance avec 4 facteurs
- [x] PWA chauffeur avec 2 boutons PRO/PRIVÉ
- [x] Cascade `mobile > vehicle > geofence > schedule` testée
- [x] Page admin avec KPIs + actions
- [x] RBAC strict (driver/manager/admin)
- [x] Invariant Personnel Masqué non régressé
- [x] Simulateur BLE pour tester sans hardware
- [x] Tests automatisés 32/32 PASS
- [x] Documentation complète

---

**Prochaine étape recommandée** : carte MapLibre sur l'historique
(visualisation des trajets pro/perso) AVANT de démarrer la Phase B native.
Cela permet de valider la couche backend complète avant d'engager les coûts
de développement mobile et de stores.
