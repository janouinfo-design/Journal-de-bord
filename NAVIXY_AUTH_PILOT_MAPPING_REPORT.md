# NAVIXY_AUTH_PILOT_MAPPING_REPORT.md
## Phase D1.1 — Auth Navixy (API Key) + résolution tracker pilote réel

> **Suite de** : audit `168efad`, Phase D D1 `a34fdff`.
> **Exécution** : READ-ONLY strict. Aucun appel Navixy réel possible (credential absent).
> Aucune écriture, aucune commande device, aucun secret affiché/journalisé.

---

## RÉSULTAT GLOBAL
```
RUNTIME PILOT: BLOCKED_NO_NAVIXY_CREDENTIAL
```
Le message Phase D1.1 décrivait la procédure **quand** une clé Navixy est disponible.
Dans l'environnement actuel, **aucune clé n'a été fournie** (ni `NAVIXY_API_KEY`, ni
`NAVIXY_HASH`, ni `tenant.navixy_hash`). On reste donc bloqué avant l'auth réelle.

---

## CREDENTIAL
```
NAVIXY_CREDENTIAL_TYPE: NONE          (API_KEY / LEGACY_HASH / NONE)
NAVIXY_AUTH:            BLOCKED       (aucun appel possible sans credential)
```
- **Support ajouté (code)** : variable **`NAVIXY_API_KEY`** désormais **prioritaire** sur
  l'ancien `NAVIXY_HASH` (déprécié, conservé pour compat migration). Le credential est
  toujours transmis à Navixy dans le champ JSON `hash` (format accepté pour une API key
  comme pour un session hash) — **aucun payload d'appel modifié à l'aveugle**.
- **Sécurité** : le secret n'est **jamais** loggé, **jamais** renvoyé par l'API, **jamais**
  transmis au frontend. Un avertissement de dépréciation (sans valeur) est émis si l'ancien
  `NAVIXY_HASH` est utilisé. `admin.py` masque déjà le hash tenant.

### Audit des usages du credential (avant modification)
`NAVIXY_HASH` / `tenant.navixy_hash` est utilisé par : `navixy_client`, `scheduler`,
`driver_beacons`, `routes/ble`, `routes/admin` (masqué), `tenancy`, `odometer_audit`.
→ `NAVIXY_HASH` **non supprimé** (d'autres modules l'utilisent). Migration contrôlée.

---

## AUTH READ-ONLY (§5)
```
Endpoint testé:  aucun (tracker/list NON appelé — credential absent)
NAVIXY_AUTH:     BLOCKED
```
> Dès qu'un credential réel sera présent, l'appel READ-ONLY minimal sera `tracker/list`
> (déjà supporté par le client), sans jamais afficher headers/payload contenant le secret.

---

## TRACKERS RÉELS (§6–§7)
```
REAL_TRACKERS_DISCOVERED: 0   (tracker/list non exécutable)
```
- Les `navixy_tracker_id` 5000–5005 présents en base proviennent du **seed mock**
  (`app/mock_navixy.py`) → **rejetés** comme non réels. Non utilisés comme pilote.
- Modèle de traceur (FMC003/FMC130) : **non déterminable** sans `tracker/list` réel.
  Rappel (conservé) : `vehicle.model` (Mercedes Sprinter…) ≠ modèle de traceur.

---

## MAPPING VÉHICULE ↔ TRACKER (§8–§10)
```
PILOT_MAPPING: UNRESOLVED
```
- Source du mapping actuel : `vehicles.navixy_tracker_id` (seed mock), scoping tenant `default`.
- Aucun matching approximatif effectué (interdit §9 : ni label, ni plaque, ni modèle, ni index).
- Aucun candidat réel → **UNRESOLVED → STOP** (règle §9).

---

## PILOTE (§10)
```
PILOT_TRACKER:        NOT_RESOLVED
PILOT_DEVICE_MODEL:   NOT_VERIFIED
```
Aucun véhicule ne satisfait (tenant + canonical vehicle + tracker Navixy réel + modèle FMC003/FMC130 non ambigu).

---

## ODOMÈTRE (§12–§16) — NON EXÉCUTÉ (bloqué avant)
```
ODOMETER_COUNTER:  UNKNOWN
ODOMETER_VALUE:    NOT_VERIFIED
ODOMETER_SOURCE:   UNKNOWN
ODOMETER_INCREMENT: NOT_TESTED
```
Endpoint `GET /api/livre/driver/vehicle/odometer` reste honnête : renvoie
`{status:"UNAVAILABLE", odometer_km:null, reason:"navixy_not_configured"}` — **jamais 0**,
**aucune estimation GPS**. Sécurité inchangée (auth + tenant + anti-IDOR, le mobile ne fournit
jamais un `tracker_id`).

---

## TESTS AUTOMATIQUES (§19) — exécutés
```
Credential:
  - aucun credential -> NONE / UNAVAILABLE propre .......... PASS
  - legacy NAVIXY_HASH supporté pendant migration .......... PASS
  - NAVIXY_API_KEY prioritaire si les deux existent ........ PASS
  - aucun secret fuité dans type/configured ................ PASS   (tests/test_navixy_credential.py 4/4)
Odomètre:
  - auth requise (401) ..................................... PASS
  - null != 0 (UNAVAILABLE) ................................ PASS
  - session active sans Navixy -> UNAVAILABLE .............. PASS
  - anti-IDOR (403) ........................................ PASS   (tests/test_odometer_audit.py 4/4)
```

---

## STOP GATE (§21)
```
NAVIXY_AUTH       = BLOCKED       -> FAIL
PILOT_MAPPING     = UNRESOLVED    -> FAIL
ODOMETER_VALUE    = NOT_VERIFIED  -> FAIL
ODOMETER_INCREMENT= NOT_TESTED    -> FAIL
```

---

## D1 STATUS
```
BLOCKED
```

## NEXT SAFE STEP
Fournir un **credential Navixy réel** côté serveur, **puis** relancer D1.1 :
1. Définir **`NAVIXY_API_KEY`** (clé API Navixy dédiée serveur) dans l'env backend du tenant
   pilote — OU renseigner `navixy_hash` du tenant. **Ne pas** me l'envoyer en clair ici ;
   configurez-le côté serveur (il ne doit jamais transiter en clair/logs/commit).
2. Je lance alors l'auth READ-ONLY `tracker/list` → `NAVIXY_AUTH: PASS/FAIL`.
3. Je liste les trackers réels (tracker_id, label, device_model si dispo) — sans IMEI complet.
4. Je résous le mapping véhicule ↔ tracker de manière **non ambiguë** ; si plusieurs candidats
   FMC003/FMC130 → je vous **présente la liste** et j'attends votre choix (pas de sélection auto).
5. Je relance `GET /driver/vehicle/odometer` → attendu `status:"REAL"` + `odometer_km`, puis
   `get_counters` pour qualifier la source (TELTONIKA_TOTAL_ODOMETER / VEHICLE_CAN /
   NAVIXY_GPS_CALCULATED / MANUAL / UNKNOWN), puis test d'incrément après déplacement réel.

**Aucune** étape D2/D3/D4/D5 (Private Mode) ne sera lancée tant que D1 n'est pas `PASS`
ou `PASS_WITH_SOURCE_UNVERIFIED`.

---

## GARANTIES DE CETTE MISSION
- READ-ONLY strict : **aucun** `counter/value/set`, **aucun** `raw_command/send`, **aucun**
  `setparam`, **aucun** `privatemode`, **aucune** mise à jour de config, **aucune** action bulk.
- Aucune clé affichée / journalisée / commitée / envoyée au frontend.
- Aucune donnée inventée (pas de 0 km, pas de distance GPS comme odomètre).
