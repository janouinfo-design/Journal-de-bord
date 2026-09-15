# DRIVER_ODOMETER_NAVIXY_AUDIT.md
## Audit odomètre Teltonika → Navixy → LOGITRAK (READ-ONLY)

> **Portée** : audit du code et de l'environnement LOGITRAK (READ-ONLY).
> **Environnement d'audit** : `NAVIXY_HASH` **NON configuré** → aucun appel Navixy
> runtime possible. Aucun accès Teltonika Configurator ni appareil terrain.
> **Conséquence** : tout ce qui dépend d'un runtime Navixy/device réel est marqué
> `NOT VERIFIED`. Aucune donnée n'a été inventée, aucune écriture, aucune commande
> device, aucune modification d'odomètre.

---

## 0. RÉSUMÉ EXÉCUTIF (faits vérifiés dans le code)

1. **LOGITRAK ne lit PAS l'odomètre aujourd'hui.** Le client Navixy
   (`app/navixy_client.py`) n'implémentait AUCUN endpoint compteur/odomètre avant
   cet audit (`tracker/get_counters`, `counter/value/get`, etc. absents).
2. **La distance des trajets est calculée depuis le GPS**, pas depuis un odomètre
   matériel : `app/navixy_sync.py:265` utilise `tr.get("length")` (longueur de piste
   Navixy issue des points GPS). → Interdit comme source de distance privée (prompt §16).
3. **Le « mode privé » actuel = Deep Sleep**, PAS le Private/Business Mode cible :
   `app/privacy_enforcer.py` envoie `setparam 11000:4` (Deep Sleep) / `11000:0`.
   Le Deep Sleep coupe l'émission GPS/GSM ; l'odomètre n'est donc **pas transmis**
   pendant le privé (il continue en interne au device, mais n'est lisible qu'au réveil).
   Ce n'est PAS l'architecture « GPS Data Masking = Zero + Odometer calculation = Enable ».
4. **`privacy_simulation_mode` = True par défaut** → aucune commande device réelle
   n'est envoyée par défaut.
5. **Aucune machine à états** BUSINESS / PRIVATE_REQUESTED / PRIVATE / … n'existe.
6. **Ajout de cet audit** (READ-ONLY, sans écriture) : méthodes de lecture compteur
   Navixy + endpoint `GET /api/livre/driver/vehicle/odometer` qui renvoie `UNAVAILABLE`
   (jamais 0) tant que la source hardware n'est pas disponible, avec anti-IDOR.

---

## 1. TELTONIKA

### FMC003
- **Total Odometer available**: `NOT VERIFIED` (pas d'accès Configurator ni Navixy runtime)
- **AVL parameter**: `AVL ID 16` d'après la doc Teltonika (Total Odometer) — **NON prouvé runtime**
- **Unit**: mètres au niveau AVL (à convertir en km) — **NON prouvé runtime**
- **Tested**: NO
- **Classification LOGITRAK**: `full` (commandes supportées) — vérifié dans `app/privacy_scan.py` (préfixes `fmc`/`fmb`/`teltonika`).

### FMC130
- **Total Odometer available**: `NOT VERIFIED`
- **AVL parameter**: `AVL ID 16` (doc Teltonika) — **NON prouvé runtime**
- **Unit**: mètres (AVL) → km — **NON prouvé runtime**
- **Tested**: NO
- **Classification LOGITRAK**: `full`.

> ⚠️ La correspondance « Total Odometer = AVL ID 16 » vient de la doc Teltonika,
> **pas** d'une capture runtime de NOTRE flux. À confirmer via §5 (lecture réelle Navixy).

---

## 2. NAVIXY

- **Teltonika odometer received**: `NOT VERIFIED` (nécessite `NAVIXY_HASH` + tracker pilote)
- **Navixy field**: `NOT VERIFIED`. Endpoints compteurs officiels confirmés par la doc :
  - `tracker/get_counters` `{hash, tracker_id}`
  - `tracker/counter/value/get` `{hash, tracker_id, type:"odometer"|"engine_hours"}`
  - `tracker/counter/value/list`, `tracker/counter/data/read` (historique)
  - (écriture) `tracker/counter/value/set` — **NON implémenté, NON testé** (write op interdite en audit)
- **Hardware source selectable**: `NOT VERIFIED` (dépend de la config compteur Navixy du compte)
- **Counter readable**: **implémenté en READ-ONLY** dans `app/navixy_client.py`
  (`get_counters`, `get_counter_value`) — **NON testé runtime** (pas de hash).
- **Counter writable**: `NOT VERIFIED` — volontairement **non implémenté** (audit).

---

## 3. PRIVATE MODE

- **GPS MASKING**: `UNTESTED`.
  - État actuel du code : approche **Deep Sleep** (coupe l'émission) et non
    « GPS Data Masking = Zero ». À reconfigurer côté device pour l'architecture cible.
- **ODOMETER DURING PRIVATE**: `UNTESTED`.
  - En Deep Sleep, l'odomètre n'est **pas transmis** pendant le privé (lisible au réveil).
  - En « Private/Business Mode + Odometer calculation = Enable », l'odomètre continuerait
    et serait transmissible — **à valider terrain**.
- **REMOTE PRIVATE ON/OFF**: `UNTESTED` (techniquement `tracker/raw_command/send` existe et
  est restreint aux modèles `full`, mais la réponse device n'est pas prouvée).
- **CURRENT TRIGGER TYPE**: `NOT VERIFIED` (config device — non lisible sans Configurator/Navixy).
  - Observation utilisateur rapportée : `Weekly Schedule`.
- **REQUIRED TRIGGER TYPE**: `External` (cible pour piloter Private ON/OFF à distance).
  - Si `Weekly Schedule` bloque la commande externe → `PRIVATE MODE REMOTE CONTROL: BLOCKED_BY_CONFIGURATION`
    (à confirmer terrain — **NOT VERIFIED**).

---

## 4. LES 3 ODOMÈTRES (séparés, non assimilés)

| Odomètre | État dans LOGITRAK | Vérifié ? |
|---|---|---|
| **A. Teltonika interne** (Odometer Value, source GNSS observée : ex. 55455 km) | Non lu par LOGITRAK | `NOT VERIFIED` runtime |
| **B. Matériel véhicule (OBD/CAN/LVCAN/FMS)** | Non lu ; existence par véhicule inconnue | `NOT VERIFIED` |
| **C. Navixy counter `odometer`** | Lecture READ-ONLY ajoutée (audit) ; renvoie UNAVAILABLE sans hash | Partiellement (code OK, runtime `NOT VERIFIED`) |

> La distance actuelle des trajets (`distance_km`) = **GPS track length** (source D, à NE PAS
> utiliser pour le privé).

---

## 5. RÉPONSES AUX 10 QUESTIONS CENTRALES (prompt §30)

1. **FMC003/FMC130 transmet-il son Total Odometer à Navixy ?** → `NOT VERIFIED` (pas de hash/tracker pilote).
2. **Sous quel champ Navixy ?** → `NOT VERIFIED` (candidat : counter `type=odometer` via `get_counters`).
3. **Utilisable comme source officielle de l'odomètre Navixy ?** → `UNKNOWN` (dépend de la config compteur du compte).
4. **Lisible depuis notre backend ?** → **OUI côté code** (READ-ONLY implémenté), **runtime NOT VERIFIED** (renvoie UNAVAILABLE sans hash).
5. **Initialiser/resynchroniser le compteur Navixy avec la valeur Teltonika sans casser la source future ?** → **UNKNOWN** (write `counter/value/set` non implémenté/non testé ; risque d'écraser une source hardware → à valider avant tout usage).
6. **L'odomètre continue-t-il réellement en Private Mode ?** → `NOT VERIFIED` (dépend du mode : Deep Sleep = non transmis ; Odometer calculation=Enable = à valider).
7. **Le GPS est-il réellement masqué ?** → `NOT VERIFIED` (Deep Sleep coupe l'émission ; masking « Zero » non configuré).
8. **Private ON/OFF commandable depuis Navixy ?** → `NOT VERIFIED` (endpoint `raw_command/send` présent, réponse device non prouvée).
9. **Weekly Schedule à remplacer par External ?** → `NOT VERIFIED` (config device ; probablement OUI pour un pilotage distant, à confirmer terrain).
10. **Quelle architecture pour LOGITRAK ?** → voir §7 (décision conditionnelle, actuellement **BLOCKED** faute de données runtime).

---

## 6. SÉCURITÉ / INTÉGRITÉ (implémenté & testé)

- **Endpoint** `GET /api/livre/driver/vehicle/odometer` :
  - **auth requise** (401 sinon) ✅ testé
  - **tenant** `default` + **anti-IDOR** : refuse un `vehicle_id` ≠ véhicule de la session (403) ✅ testé
  - **jamais 0 fictif** : sans donnée → `{odometer_km: null, status: "UNAVAILABLE"}` ✅ testé
- **Contrôles d'intégrité** prévus dans `app/odometer_audit.py` : `STALE` si lecture > 24 h,
  `UNAVAILABLE` si vide/injoignable, pas de calcul inter-trackers, pas d'estimation GPS.
- **Tests** : `tests/test_odometer_audit.py` → **4/4 PASS**.

---

## 7. DÉCISION FINALE (conditionnelle)

**STATUT ACTUEL : `BLOCKED`** — décision non finalisable sans données runtime réelles
(`NAVIXY_HASH` + 1 tracker pilote + accès Configurator).

Recommandation **conditionnelle** dès que le pilote sera disponible :
- **SI** `get_counters` renvoie un `odometer` alimenté par le Total Odometer Teltonika
  (source hardware) → **ARCHITECTURE A — RECOMMENDED**
  (Teltonika odometer → Navixy hardware source → LOGITRAK lecture READ-ONLY, déjà codée).
- **SINON, SI** l'odomètre n'est lisible que ponctuellement mais fiable → **ARCHITECTURE B**
  (lecture directe backend, endpoint déjà en place).
- **N'utiliser `counter/value/set` (ARCHITECTURE C)** que pour une **initialisation/resync
  contrôlée**, jamais en synchronisation périodique, et seulement après avoir prouvé (Q5)
  qu'elle n'écrase pas la source hardware.
- **Ne jamais** utiliser la distance GPS reconstruite comme distance privée.

---

## 8. PLAN PILOTE (à exécuter par l'utilisateur — hors sandbox)

1. Configurer `NAVIXY_HASH` (tenant) en préproduction.
2. Choisir **1 seul** tracker pilote (FMC003 ou FMC130).
3. Appeler `GET /api/livre/driver/vehicle/odometer` (véhicule pilote) → attendu `status:"REAL"` + `odometer_km`.
4. Comparer avec la valeur Teltonika Configurator (ex. 55455 km) et la valeur Navixy.
5. Rouler quelques km, relire, vérifier l'incrément cohérent (§26 du cahier des charges).
6. Tester Private/Business Mode (GPS masking=Zero, Odometer calculation=Enable, Trigger=External)
   sur le SEUL pilote ; vérifier GPS non exploitable + odomètre qui continue.
7. Décider A / B / C selon résultats réels.

**NE PAS** déployer en flotte, **NE PAS** écrire d'odomètre, **NE PAS** `setparam` en masse
avant validation pilote.

---

## 9. FICHIERS AJOUTÉS/MODIFIÉS PAR CET AUDIT (READ-ONLY côté device)

- `backend/app/navixy_client.py` : + `get_counters`, `get_counter_value` (LECTURE seule).
- `backend/app/odometer_audit.py` : mapping honnête (UNAVAILABLE/STALE/REAL, jamais 0).
- `backend/app/routes/identification.py` : + `GET /driver/vehicle/odometer` (auth + tenant + anti-IDOR).
- `backend/tests/test_odometer_audit.py` : 4 tests (auth, UNAVAILABLE≠0, anti-IDOR).
- **Aucune** écriture Navixy, **aucune** commande device, **aucune** modification de config/odomètre.
