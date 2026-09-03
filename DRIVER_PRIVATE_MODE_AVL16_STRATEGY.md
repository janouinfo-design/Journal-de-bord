# DRIVER_PRIVATE_MODE_AVL16_STRATEGY.md
## Stratégie odomètre V2 — Socle commun AVL 16 (Teltonika Total Odometer)

## ============================================================================
## PILOTE AVL 16 = tracker 3657864 (compte 121349) — 2026-09-03
## ============================================================================
> Changement de pilote : on travaille désormais sur **3657864** (compte 121349), plus Manchester.

Chaîne AVL 16 — état runtime (READ-ONLY) :
```
[AUTH] success=True  TID=3657864
Sensor Navixy « ODO TOTAL » : input=avl_io_16, multiplier=1, DIVIDER=1, unit=km
  -> mult_ok=True, div_ok=False (div=1 ici, PAS 1000), unit_ok=True
AVL16_RAW_VALUE / SENSOR_VALUE_KM = 140257.0 km  @ 2026-09-03 13:42:57
API_READABLE = YES   AVL16_API_MAPPING = VERIFIED
AVL16_CUMULATIVE = PENDING_REAL_DRIVE   AVL16_SCALE = RUNTIME_PENDING
```

Point de calibration IMPORTANT (confirme la stratégie V2) :
- Sur ce tracker, le sensor affiche 140257.0 km avec **divider=1** (Navixy convertit déjà en amont).
- Sur Manchester, le sensor affichait la bonne valeur avec **divider=1000**.
- => La calibration AVL 16 **varie par tracker**. NE PAS coder un ÷1000 universel.
  La normalisation reste **par tracker** (mapping validé) — c'est déjà le cas dans
  `normalize_teltonika_total_odometer()`.
- Le « ECART (/1000) » affiché par le script est un faux négatif (readings/list renvoie déjà la
  valeur normalisée en km). Valeur exploitable = 140257.0 km (cohérente avec preuve terrain
  avl_io_16=140258496 sur ce véhicule Audi A3).

Reste à fermer : incrémentation réelle (rouler -> SENSOR_KM_DELTA>0) + comparaison tableau de bord.



> Décision d'architecture 2026-09-03, fondée sur preuves terrain. Remplace la stratégie
> « FMC003 = AVL 389 obligatoire ». Les conclusions AVL 389 antérieures ne sont PAS fausses :
> elles sont marquées **SUPERSEDED_AS_PRIMARY_STRATEGY**. Aucune écriture device/Navixy dans
> cette mission (code + tests + doc + vérif runtime READ-ONLY).

---

## A. Ancienne stratégie (SUPERSEDED_AS_PRIMARY_STRATEGY)
```
FMC003 → PRIMARY = OBD OEM Total Mileage (AVL 389)   [dépend du PID OEM du véhicule]
FMC130 → PRIMARY = Teltonika Total Odometer interne
```
Problème : AVL 389 dépend du véhicule. Certains véhicules l'exposent, d'autres non — pour un
même modèle/firmware/config. → dépendance véhicule trop forte pour un déploiement de flotte.

## B. Nouvelles preuves terrain
```
FMC130 : avl_io_16 = 184601494 ; getparam 11807 = 184601  (cohérent Total Odometer interne)
FMC003 (Audi A3) : avl_io_16 = 140258496 ; AVL 389 = ABSENT
FMC003 (Manchester 3467714, VW) : AVL 389 = 165113 (présent) ; AVL 16 en cours d'exposition
Navixy (officiel) : AVL 16 = hw_mileage ; avec Odometer Calculation=Enable + GPS masking=
  "Data Sent As Zero", AVL 16 CONTINUE à augmenter même à 0,0.
```
→ Le FMC003 expose l'AVL 16 **même quand** le véhicule ne fournit pas l'AVL 389.

## C. Pourquoi AVL 389 devient SECONDAIRE
- AVL 16 (Total Odometer interne GNSS) est présent sur FMC003 **et** FMC130 → socle **commun**.
- AVL 389 reste utile (vrai km véhicule) mais **optionnel** : comparaison/validation/diagnostic.
- `PRIVATE_MODE_ALLOWED` ne dépend **plus** de la présence d'AVL 389.

## D. Architecture commune
```
FMC003 / FMC130 → GNSS interne → Teltonika Total Odometer → AVL 16 → Navixy → LOGITRAK → Driver App
```
Jamais : NAVIXY_GPS_CALCULATED (gèle à 0,0 en mode privé).

## E. Mapping AVL 16 (par tracker, preuve runtime — pas le libellé UI)
Conserver par tracker : `tracker_id, sensor_id, raw input (avl_io_16 / hw_mileage), scale,
unit, timestamp`. Navixy peut confondre Mileage / Engine Hours / AVL 16 dans l'UI → se fier
au **mapping runtime**, jamais au nom d'affichage.

## F. Normalisation (scale explicite, jamais présumé)
`normalize_teltonika_total_odometer(raw, mapping)` :
- n'applique `multiplier/divider` que si `scale_status == VERIFIED` ;
- sinon `scale_status = UNVERIFIED`, `normalized_value = None` (+ indice non contractuel).
- Hypothèse probable m→km (÷1000) mais **UNVERIFIED** tant que non calé vs tableau de bord.

## G. Gate production (durcie, par traceur)
`vehicle_private_mode_allowed(model, vc)` = TRUE seulement si :
```
modèle ∈ {FMC003, FMC130} avec strategy=TELTONIKA_TOTAL_ODOMETER
AND vc.private_distance_source == TELTONIKA_TOTAL_ODOMETER
AND vc.raw_avl_id == 16
AND runtime_verified AND cumulative_verified AND private_increment_verified AND field_validated
```
Présence d'avl_io_16 seule = **insuffisant**. `private_mode_production_allowed()` = **FALSE** par défaut.

## H. Protocoles D3 séparés (terrain, sur GO explicite)
- **D3-FMC003** (pilote avec AVL 16 réel) et **D3-FMC130** — validés **séparément**.
- Séquence : lire AVL 16 → GPS normal → passer Privé (GO) → tracker online + positions masquées
  → rouler qq km → delta AVL 16 > 0 → retour Professionnel → GPS normal.
- FMC003 PASS n'implique PAS FMC130 PASS (et inversement).

## I. Risques / inconnues restantes
- Scale AVL 16 (m→km) à **valider** vs compteur tableau de bord.
- Continuité AVL 16 en mode privé (0,0) : **confirmée par doc Navixy**, à **prouver terrain** (D3-B).
- Exposition AVL 16 à l'API dépend de l'écriture device (I/O Total Odometer = Low) — action opérateur.
- FMC640/FMC650 : hors périmètre (NOT_RUNTIME_VERIFIED).

---

## SORTIE ATTENDUE (état courant)
```
STRATEGY_FMC003            = TELTONIKA_TOTAL_ODOMETER
STRATEGY_FMC130            = TELTONIKA_TOTAL_ODOMETER
PRIMARY_AVL_ID             = 16
AVL389_ROLE                = SECONDARY_OPTIONAL
FMC003_AVL16_RUNTIME_EVIDENCE = PRESENT (Audi A3: 140258496)
FMC130_AVL16_RUNTIME_EVIDENCE = PRESENT (184601494 / 11807=184601)
AVL16_SCALE                = UNVERIFIED (à caler vs tableau de bord)
FMC003_FIELD_VALIDATED     = NO
FMC130_FIELD_VALIDATED     = NO
PRIVATE_MODE_PRODUCTION     = DISABLED
NEXT_SAFE_STEP             = valider (READ-ONLY) l'exposition + l'incrémentation d'avl_io_16 sur
                             un tracker pilote en roulage, puis caler le scale vs tableau de bord.
```

## GARDE-FOUS
Aucune écriture device/Navixy, aucun setparam/privatemode/raw_command, aucun bulk, pas de mode
Privé en production. Toute écriture nécessaire => STOP + `CHANGE_REQUIRED` (tracker, raison, état,
changement, risque, rollback) + attente GO explicite.
