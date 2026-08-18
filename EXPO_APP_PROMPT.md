# CAHIER DES CHARGES — APPLICATION MOBILE CHAUFFEUR « LOGITRAK Journal de bord »
### Projet Expo séparé — à copier comme prompt initial du nouveau projet

> **Contexte** : le backend existe déjà et est en production d'aperçu (FastAPI + MongoDB, multi-tenant).
> L'app mobile NE contient AUCUNE logique métier serveur : elle consomme exclusivement les
> 18 endpoints listés ci-dessous. Ne jamais inventer un endpoint ou un champ non listé.

---

## 1. OBJECTIF

Application mobile pour les **chauffeurs** d'une flotte de véhicules :
1. Se connecter avec e-mail + mot de passe (comptes créés par l'admin dans le Journal de bord).
2. Confirmer **« Je conduis »** sur un véhicule → ouvre une session conducteur.
3. Terminer volontairement avec **« Je m'arrête »**.
4. Basculer le mode de trajet **PROFESSIONNEL / PRIVÉ** (distinct de l'identité chauffeur).
5. Consulter **Mes trajets** et classifier les trajets non classés (PRO/PRIVÉ).
6. Voir son profil et son véhicule/session en cours.
7. (Optionnel, build natif) Scanner les tags BLE des véhicules pour l'identification automatique.

Langue de l'interface : **français uniquement**.

## 2. STACK IMPOSÉE

- **Expo** (dernière SDK stable), React Native, TypeScript recommandé.
- Navigation : expo-router ou React Navigation — 4 onglets : **Conduite · Mes trajets · Profil · Réglages**.
- Stockage sécurisé des tokens : `expo-secure-store`.
- Push : `expo-notifications` (le backend accepte déjà les tokens Expo).
- BLE (optionnel, phase 2 mobile) : `react-native-ble-plx` — nécessite un **development build**
  (pas Expo Go). Ne pas bloquer la v1 là-dessus.

## 3. CONFIGURATION

- `API_BASE_URL` dans un fichier d'env (`EXPO_PUBLIC_API_URL`). Tous les appels préfixés `/api`.
- Aucun secret dans le code. Aucun tenant_id envoyé par le client : il est déduit du token côté serveur.

## 4. AUTHENTIFICATION (déjà implémentée côté serveur — ne rien réinventer)

| Méthode | URL | Body | Réponse | Erreurs |
|---|---|---|---|---|
| POST | `/api/auth/login` | `{email, password}` | `{user, access_token, refresh_token}` | 401 message générique unique (« Identifiants incorrects ou accès temporairement bloqué ») — NE PAS distinguer mauvais mdp / compte inconnu / verrou ; 422 |
| POST | `/api/auth/refresh` | `{refresh_token}` | `{user, access_token, refresh_token}` (rotation → stocker le NOUVEAU) | 401 → retour au login |
| POST | `/api/auth/logout` | — (Bearer) | `{ok}` | 401 |
| GET | `/api/auth/me` | — (Bearer) | `{user{id,email,name,role,tenant_id,driver_id}}` | 401 |
| POST | `/api/auth/change-password` | `{current_password, new_password}` (≥ 8 car.) | 200 | 401 mdp actuel faux, 400 trop court |

Règles :
- `access_token` en mémoire + SecureStore ; `refresh_token` en SecureStore uniquement.
- Intercepteur HTTP : sur 401 → tenter UN refresh → rejouer la requête → sinon déconnecter.
- **Brute force serveur** : 5 échecs = verrou 15 min. Afficher le message générique du serveur tel quel.
- **`must_change_password`** : si `GET /api/livre/driver/my-profile` renvoie `must_change_password: true`,
  forcer un écran « Nouveau mot de passe » (appelle `/api/auth/change-password`) avant tout accès.

## 5. ENDPOINTS CHAUFFEUR (rôle `driver`, Bearer)

| Méthode | URL | Body / Params | Réponse (succès) | Erreurs |
|---|---|---|---|---|
| GET | `/api/livre/driver/my-profile` | — | `{name, email, account_active, must_change_password, driver_active, ble_tag_associated, last_ble_detection}` — jamais de mot de passe | 401 |
| GET | `/api/livre/driver/my-vehicle` | — | `{vehicle{id,plate,model}, current(bool), session{id,status,started_at,identification_source,active_driver,mobile_override,confidence}}` — peut être `vehicle:null` | 401 · 400 non lié |
| GET | `/api/livre/driver/current-session` | — | `{session|null}` | 401 · 400 non lié |
| POST | `/api/livre/driver/claim` | `{vehicle_id}` | `{status:"confirmed"|"conflict", session, conflict_with_driver_id?}` | 401 · 400 non lié · 404 véhicule · 422 |
| POST | `/api/livre/driver/stop` | — | `{stopped:true, vehicle_plate, session}` ou `{stopped:false, message:"Aucune session active"}` (idempotent, jamais 500) | 401 · 400 non lié |
| POST | `/api/livre/driver/manual-mode` | `{mode:"professional"|"personal"}` | session mise à jour | 400 · 401 · 403 · 404 |
| POST | `/api/livre/driver/push-token` | `{token, platform?, device_id?}` | 200 | 401 |
| DELETE | `/api/livre/driver/push-token` | — | 200 | 401 |
| GET | `/api/livre/driver/fleet-tags` | — | tags BLE des véhicules de la flotte (pour le scan téléphone) | 401 |
| POST | `/api/livre/ble/detections` | `{identifier, rssi}` | détection ingérée (identification BLE / fusion APP+BLE) | 401 |

## 6. TRAJETS

| Méthode | URL | Params/Body | Réponse | Erreurs |
|---|---|---|---|---|
| GET | `/api/livre/trips` | query `classification, start, end, vehicle_id, limit` | `{trips[], settings_mode}` — le serveur ne renvoie QUE les trajets du chauffeur connecté | 401 |
| PUT | `/api/livre/trips/{id}/classify` | `{classification:"professional"|"personal"}` | trajet mis à jour | 401 · 403 trajet d'autrui · 404 |
| GET | `/api/livre/trips/{id}/track` | — | `[[lng,lat],…]` | 403 trajet privé masqué · 404 |

« Trajets à compléter » = éléments de la liste avec `classification: null` (filtrer côté client).
Il n'existe PAS d'endpoint « détail trajet » dédié : utiliser l'objet de la liste + `/track` pour le tracé.

## 7. ÉCRANS V1

1. **Login** : email + mdp, message d'erreur = celui du serveur, loader, logo Logitrak.
2. **Changement de mot de passe forcé** (si `must_change_password`).
3. **Conduite** (accueil) :
   - carte « Véhicule actuel » (`my-vehicle`) : plaque, modèle, session (source APP/BLE/APP+BLE, début, durée) ;
   - sélecteur de véhicule (liste depuis `fleet-tags` ou saisie de la plaque via la flotte) + gros bouton **« Je conduis »** ;
   - si `status:"conflict"` en réponse au claim : bandeau orange « Conflit signalé — un gestionnaire doit confirmer le conducteur » (ne PAS masquer) ;
   - bouton rouge **« Je m'arrête »** visible seulement si session active ; `stopped:false` → toast informatif ;
   - toggle **PRO / PRIVÉ** (`manual-mode`) avec l'état courant (`session.mobile_override`).
4. **Mes trajets** : liste paginée, badge PRO/PRIVÉ/À classer, filtre par période ; action classer (PUT classify) ; détail avec tracé (polyline sur carte) si non privé.
5. **Profil** : `my-profile` (nom, e-mail, statut compte, tag BLE associé, dernière détection BLE) + changement de mot de passe + déconnexion.
6. **Réglages** : activation notifications push (enregistre le token), à propos.

## 8. RÈGLES MÉTIER À RESPECTER (déjà appliquées côté serveur)

- **Identité chauffeur (APP/BLE/APP+BLE/MANUEL) ≠ type de trajet (PRO/PRIVÉ)** : deux notions séparées dans l'UI.
- Ne JAMAIS afficher de donnée inventée (pas de niveau de carburant/batterie fictif, pas de "100 %" de confiance par défaut). Si `confidence` est null et statut confirmé → afficher « Confirmé ».
- « Je m'arrête » n'est PAS obligatoire : les sessions se ferment aussi automatiquement (fin de trajet, timeout, changement de chauffeur). L'UI doit tolérer une session déjà fermée côté serveur.
- Un conflit ne se résout PAS dans l'app chauffeur (v1) : c'est le gestionnaire qui tranche.
- BLE chauffeur via traceurs Teltonika/Navixy : fonctionnalité serveur en cours de validation terrain — ne rien promettre dans l'UI à ce sujet.

## 9. QUALITÉ

- `testID` sur chaque élément interactif (`login-submit`, `claim-button`, `stop-button`, `mode-toggle`, `trip-classify-pro`, …).
- Gestion hors-ligne minimale : cache du dernier profil/session, bannière « hors ligne », retry.
- Polling léger de `current-session` (30–60 s) quand l'écran Conduite est actif.
- Aucun log du mot de passe ni des tokens.

## 10. COMPTES DE TEST (environnement d'aperçu)

- Chauffeur : `chauffeur@logitrak.ch` / `chauffeur123`
- Chauffeur 2 : `paul.test@client.ch` / `paul1234`
(Ne pas coder ces valeurs en dur — écran de login normal.)
