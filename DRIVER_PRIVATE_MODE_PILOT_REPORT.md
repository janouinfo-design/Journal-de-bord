# DRIVER_PRIVATE_MODE_PILOT_REPORT.md
## Phase D — Pilote runtime Odomètre + Private/Business Mode (UN seul tracker)

> **Suite de** : `DRIVER_ODOMETER_NAVIXY_AUDIT.md` (commit audit `168efad`).
> **Exécution** : D1 uniquement (odomètre READ-ONLY). Aucune commande device, aucune
> écriture Navixy, aucune modification de configuration/odomètre. Aucune donnée inventée.

---

## RÉSULTAT GLOBAL

```
RUNTIME PILOT: BLOCKED_NO_NAVIXY_HASH
```

**Raison exacte** : `NAVIXY_HASH` n'est configuré ni au niveau environnement ni au niveau
tenant. La chaîne Teltonika → Navixy → LOGITRAK ne peut donc **pas** être testée en runtime.
Conformément au cahier des charges (§2 et §8 STOP GATE), **on s'arrête à D1** : on ne résout
pas de tracker pilote réel, on ne lit pas d'odomètre réel, et on **ne touche pas** au
Private Mode.

---

## ENVIRONMENT
```
NAVIXY_HASH_CONFIGURED: NO        (env: NON ; tenants en base: NON — aucun hash présent)
PILOT:                  NOT_RESOLVED
MODEL:                  NOT_VERIFIED
FIRMWARE:               NOT_VERIFIED
TENANT:                 default (mono-tenant de test)
```
> Le hash et l'IMEI ne sont jamais affichés ni journalisés (aucune valeur à masquer ici : absente).

---

## SÉLECTION DU TRACKER PILOTE (§3)
```
STATUS: NOT_RESOLVED
```
- 6 véhicules du tenant `default` possèdent un champ `navixy_tracker_id` (5000–5005),
  **mais** ces identifiants proviennent du **seed mock** (`app/mock_navixy.py`), **pas** d'un
  compte Navixy réel.
- Le champ `model` correspond au **modèle véhicule** (Mercedes Sprinter, VW Crafter, …),
  **pas** au modèle de traceur (FMC003 / FMC130). Aucun tracker FMC réel n'est identifiable ici.
- Il n'existe donc **aucun candidat pilote runtime valide**. On ne choisit PAS arbitrairement
  un tracker (règle §3).

---

## PHASE D1 — ODOMÈTRE READ-ONLY (exécuté)

Appel réel effectué : `GET /api/livre/driver/vehicle/odometer` (chauffeur authentifié, session active).

Réponse runtime observée (honnête, jamais de 0 fictif, aucune estimation GPS) :
```json
{
  "vehicle_id": "…",
  "vehicle_plate": "GE 123456",
  "odometer_km": null,
  "source": null,
  "timestamp": null,
  "status": "UNAVAILABLE",
  "fresh": false,
  "reason": "navixy_not_configured"
}
```

```
D1 ODOMETER READ:
  status       = UNAVAILABLE
  odometer_km  = null
  source       = null
  timestamp    = null
  fresh        = false
```
→ Résultat **non acceptable** pour poursuivre (le cahier exige `status = REAL`). **STOP avant Private Mode** (§4, §8).

---

## ODOMETER
```
NAVIXY_COUNTER: NOT_VERIFIED   (lecture READ-ONLY codée : get_counters / counter/value/get,
                                mais non exécutable sans NAVIXY_HASH)
SOURCE:         UNKNOWN        (impossible de prouver HARDWARE vs GPS_CALCULATED vs MANUAL)
BEFORE:         NOT_VERIFIED
AFTER:          NOT_VERIFIED
DELTA:          NOT_VERIFIED
RUNTIME STATUS: UNAVAILABLE (navixy_not_configured)
```

### Comparaison Teltonika ↔ Navixy ↔ LOGITRAK (§6)
```
Teltonika: NOT_VERIFIED    (pas d'accès Configurator dans cet environnement)
Navixy:    NOT_VERIFIED    (pas de hash)
LOGITRAK:  null (UNAVAILABLE)
delta:         NOT_VERIFIED
delta_backend: NOT_VERIFIED
```

### Test d'incrément (§7)
```
ODOMETER_INCREMENT: NOT_TESTED   (aucune lecture réelle possible)
```

---

## STOP GATE D1 (§8)
```
NAVIXY_HASH             = NO           -> FAIL
PILOT TRACKER           = NOT_RESOLVED -> FAIL
ODOMETER                = UNAVAILABLE  -> FAIL
ODOMETER SOURCE         = UNKNOWN      -> FAIL
ODOMETER INCREMENT      = NOT_TESTED   -> FAIL
```
→ **Une ou plusieurs conditions échouent → STOP. `privatemode ON` NON envoyé.**

---

## PRIVATE CONFIG (§9) — NON EXÉCUTÉ
```
MASKING:        NOT_VERIFIED
ODOMETER_CALC:  NOT_VERIFIED
TRIGGER_TYPE:   NOT_VERIFIED   (observation antérieure rapportée : "Weekly Schedule" — non relue runtime)
```
> La configuration Private/Business du pilote n'a **pas** été relue (pas d'accès device/Navixy).
> Aucune supposition n'est faite sur l'état actuel.

---

## AUDIT DEEP SLEEP vs PRIVACY (§10) — analyse code (READ-ONLY)

Matrice conceptuelle (à implémenter après validation pilote, PAS maintenant) :

| Fonction        | Ancienne logique (actuelle)        | Nouvelle cible                      |
|-----------------|------------------------------------|-------------------------------------|
| Privé chauffeur | Deep Sleep (`setparam 11000:4`)    | Private/Business Mode               |
| GPS privé       | Traceur endormi (n'émet plus)      | Coordonnées masquées (0,0)          |
| Odomètre privé  | Non transmis (device en sommeil)   | Continue + transmis                 |
| Retour Pro      | Réveil (`setparam 11000:0`)        | `privatemode OFF`                   |

**Constat clé** : `PRIVACY_MODE` et `DEVICE_SLEEP` sont **conceptuellement distincts**.
`privacy_enforcer.py` mélange aujourd'hui les deux (le « privé » = mettre le device en sommeil).
`privacy_simulation_mode = True` par défaut → aucune commande réelle envoyée.
**Action** : NE PAS supprimer Deep Sleep maintenant (il peut servir à une autre fonction).
La séparation sera faite lors de l'implémentation, uniquement après pilote VALIDATED.

---

## COMMAND (§13–§14) — NON EXÉCUTÉ
```
PRIVATE ON:            NOT_EXECUTED (bloqué par STOP GATE D1)
DEVICE CONFIRMATION:   NOT_VERIFIED
PRIVATE OFF:           NOT_EXECUTED
DEVICE CONFIRMATION:   NOT_VERIFIED
```

## PRIVACY (§15)
```
GPS MASKING:                          UNKNOWN (non testé)
PRIVATE LOCATION EXPOSED BY LOGITRAK: NO
```
> **NO** garanti : aucun trajet privé n'est exposé — et pour cause, aucune session privée n'a
> été créée. Le backend refuse déjà d'inventer une position (0,0 ≠ position réelle).

## PRIVATE DISTANCE (§16, §18)
```
START ODOMETER: NOT_VERIFIED
END ODOMETER:   NOT_VERIFIED
DISTANCE:       NULL (DISTANCE UNAVAILABLE)
SOURCE:         none (jamais d'estimation GPS)
```

---

## FINAL GATES (§26)
```
ODOMETER_RUNTIME:        BLOCKED
ODOMETER_INCREMENT:      NOT_VERIFIED
PRIVATE_COMMAND:         NOT_VERIFIED
PRIVATE_CONFIRMATION:    NOT_VERIFIED
GPS_MASKING:             NOT_VERIFIED
ODOMETER_DURING_PRIVATE: NOT_VERIFIED
BUSINESS_RETURN:         NOT_VERIFIED
ODOMETER_CONTINUITY:     NOT_VERIFIED
```

---

## DÉCISION (§27)
```
PILOT BLOCKED
```
Raison : credential Navixy absent (§ D1.1 : `NAVIXY_CREDENTIAL_TYPE = NONE`, ni
`NAVIXY_API_KEY` ni `NAVIXY_HASH`) → aucune lecture odomètre runtime, aucun tracker
pilote réel résolvable. Le bouton Privé/Pro production **ne doit PAS** être commencé.

> **MàJ Phase D1.1** : support `NAVIXY_API_KEY` (prioritaire, secret jamais exposé) ajouté
> côté code + tests credential 4/4. Voir `NAVIXY_AUTH_PILOT_MAPPING_REPORT.md`. Statut
> runtime toujours **BLOCKED** faute de clé réelle fournie.

**On NE déclare PAS** : PILOT VALIDATED — donc **PAS** de « READY FOR DRIVER APP PRIVATE/PRO
IMPLEMENTATION ».

---

## ACTION UTILISATEUR REQUISE POUR DÉBLOQUER D1 (puis D2→D5)

1. **Configurer `NAVIXY_HASH`** (hash de session Navixy 32 hex) pour le tenant pilote, sur un
   environnement ayant un **compte Navixy réel** relié aux traceurs.
   - Soit `NAVIXY_HASH=...` dans l'env backend, soit `navixy_hash` dans le doc tenant.
2. **Désigner 1 SEUL tracker pilote** réel : un **FMC003 ou FMC130** appartenant au tenant,
   associé à un véhicule, accessible via Navixy. Me communiquer :
   `pilot_vehicle_id`, `navixy_tracker_id`, modèle, tenant (jamais l'IMEI complet).
3. **Vérifier le mapping véhicule ↔ tracker** réel (le seed mock 5000–5005 n'est pas réel).

Dès que (1)+(2)+(3) sont fournis, je relance **D1** :
`GET /api/livre/driver/vehicle/odometer` → attendu `status:"REAL"` + `odometer_km`, puis
inspection `get_counters` pour qualifier la source (HARDWARE / GPS_CALCULATED / UNKNOWN),
puis test d'incrément après déplacement réel. **Aucune** étape Private Mode ne sera lancée
tant que D1 n'est pas `PASS`.

---

## CE QUI EST DÉJÀ PRÊT CÔTÉ CODE (pour accélérer dès déblocage)
- Lecture READ-ONLY : `navixy_client.get_counters` / `get_counter_value` (endpoints Navixy officiels).
- Mapping honnête : `app/odometer_audit.py` (REAL / STALE / UNAVAILABLE / ERROR ; jamais 0 ; pas de GPS).
- Endpoint sécurisé : `GET /api/livre/driver/vehicle/odometer` (auth + tenant + anti-IDOR) — testé 4/4.
- **Aucune** écriture, **aucune** commande device : conforme à la contrainte « pilote seulement, pas de rollout ».
