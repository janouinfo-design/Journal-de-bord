# DRIVER_PRIVATE_MODE_D3_CONFIG_OEM_MILEAGE.md
## Protocole D3-CONFIG — OEM Mileage (AVL 389) — GATED / NON EXÉCUTÉ

## ============================================================================
## EXIGENCES PRODUIT « MODE PRIVÉ » (DÉCISION MÉTIER — RÉFÉRENCE DE GATE)
## ============================================================================
> Décidé avec l'opérateur (2026-09-03). Ces exigences priment sur toute implémentation.

**Définition du Mode Privé (cible) :**
```
GPS_COORDINATES        = MASKED      (aucune position/adresse/trace/replay visible)
TRACKER                = ONLINE      (reste joignable — retour Professionnel à distance possible)
PRIVATE_DISTANCE       = CONTINUES_TO_INCREMENT   (km privés comptabilisés)
```

**Méthode = vrai `privatemode`** (PAS Deep Sleep `11000:4` qui couperait le GSM) :
- masque les coordonnées GPS transmises ;
- garde le traceur joignable ;
- permet le retour Professionnel à distance ;
- continue à comptabiliser les km parcourus en période privée.

**Source de la distance privée (admissible) — NE PAS dire « non-GPS » :**
- `OBD OEM Total Mileage` / **AVL 389** → km véhicule OBD, indépendant du GNSS ; OU
- **Teltonika Total Odometer calculé sur GNSS interne** → admissible UNIQUEMENT si D3 prouve qu'il
  continue d'incrémenter quand les **coordonnées transmises** sont masquées.
- ❌ **Jamais** calculer les km privés depuis les coordonnées GPS masquées ni le trajet Navixy.

**GATE PRODUCTION (absolue) :**
```
PRIVATE_MODE_PRODUCTION_ALLOWED = TRUE
   uniquement si une source kilométrique fiable est FIELD_VALIDATED pendant le mode Privé.
Sinon -> bouton Privé DÉSACTIVÉ en production. PAS de mode Privé final avec distance "indisponible".
```

**Découplage actuel constaté (à relier en Phase 2) :** le bouton chauffeur (`driver_set_mode` →
`mobile_override`) classe les trajets mais NE déclenche PAS de masquage device. Le lien
bouton→masquage device sera ajouté, mais l'ENVOI RÉEL reste GATED (simulation) jusqu'à la
FIELD-VALIDATION ci-dessus. Objectif D3-B = prouver simultanément
`GPS_COORDINATES=MASKED` + `TRACKER=ONLINE` + `PRIVATE_DISTANCE=CONTINUES_TO_INCREMENT`.



## ============================================================================
## D3-A RUNTIME VERIFY (2026-09-03 08:32) — 3467714 Manchester — READ-ONLY
## ============================================================================
```
TRACKER_ID = 3467714   MODEL = FMC003   IMEI 864636064631720   FW 04.02.00.Rev.602
OBD_ACTIVE = YES   (VIN WV2ZZZSK3PX065783 @ 08:32:46, rpm 1504, speed 45 km/h — temps réel)
MOVING = YES       (le véhicule roulait pendant le test)

CONFIG DEVICE (déjà faite par l'operateur) : 113=1, 40000=1, 40430=1  ✅

OBD_MILEAGE_SENSOR_DEFINED = YES  (« OBD : Kilométrage OBD total », km, id 5371584)
OBD_MILEAGE_VALUE = None          ← TOUJOURS VIDE malgré config OK + OBD actif + roulage
AVL389_PRESENT = NO
OEM_MILEAGE_INCREMENT = NO_VALUE_YET
NAVIXY_GPS_ODOMETER = 16578.1 km @ 08:32:16  (REFERENCE SEULEMENT)

D3A_VERDICT = INCONCLUSIVE_SLEEP_MODE  (verdict NOT_SUPPORTED RÉTRACTÉ)
  → À 08:32 le tracker se réveillait à peine / cycle sleep : l'absence de obd_mileage NE PROUVE PAS
    l'absence du PID OEM. Test à refaire dans de bonnes conditions (voir ci-dessous).
```

### ⚡ PREUVE AIR CONSOLE FOTA (2026-09-03 ~10:04) — l'AVL 389 EXISTE ET INCRÉMENTE
```
Air Console FOTA (flux BRUT device 3467714) :
  avl_io_389 = 165113   → OBD OEM Total Mileage = 165 113 km (le VRAI compteur véhicule)
  avl_io_390 = 495      (OEM fuel level)
  avl_io_256 = WV2ZZZSK3PX065783 (VIN)
Incrementation prouvée : capture initiale ~165000 -> 165113 (+113 km). CUMULATIF + VIVANT.
```
**RÉTRACTATION : le verdict `NOT_SUPPORTED_BY_VEHICLE` est FAUX.** Le véhicule FOURNIT bien le PID
OEM mileage, le device le transmet. Nouveau statut :
```
OEM_MILEAGE_SUPPORTED_BY_VEHICLE = YES  (prouvé Air Console : 165113 km, incrémente)
OEM_MILEAGE_VISIBLE_VIA_NAVIXY_API = NO (obd_mileage vide / avl_io_389 absent des readings)
=> PROBLÈME = RÉCEPTION/MAPPING CÔTÉ NAVIXY (ni véhicule, ni config device, ni sleep)
```
Causes possibles : (a) délai de propagation (Air Console 10:04 > dernier test 09:56) ;
(b) le sensor Navixy `obd_mileage` n'est pas lié à l'input AVL 389 / Navixy ne décode pas cet AVL /
le device n'envoie l'AVL 389 qu'au flux FOTA et pas au serveur Navixy.
**Action : re-lire l'API Navixy MAINTENANT (post-10:04). Si toujours absent -> corriger le mapping
Navixy (config plateforme, PAS device).**


### RE-TEST (2026-09-03 09:55) — conditions IDÉALES (sleep mode écarté)
```
ignition = TRUE, rpm 2043, speed 27 km/h, coolant 92°C, connection=active, MOVING=YES
VIN/rpm/speed/fuel = TOUS @ 09:55:24 (OBD pleinement actif)
Le vehicule a roulé ~26 km entre 08:32 et 09:53 (GPS odo 16578 -> 16604) => roulage REEL confirmé.

OBD_MILEAGE_VALUE = None (TOUJOURS VIDE)   AVL389_PRESENT = NO   OEM_MILEAGE = NO_VALUE_YET
```
**Verdict confirmé (sleep mode écarté) : `OEM_MILEAGE_NOT_REPORTED_DESPITE_IDEAL_CONDITIONS`.**
Le VW `WV2ZZZSK3PX065783` ne fournit pas le PID OEM total mileage exploitable par le FMC003 dans
cette configuration, moteur tournant. Ce n'est ni la config (113/40000/40430 OK), ni l'OBD (actif),
ni le sleep (écarté).

**Dernière piste config OEM (écriture, GATED) :** le **profil OEM OBD** (`40002=10` au .cfg) doit
correspondre au groupe **VAG (VW/Audi/Škoda/Seat)**. Si le profil sélectionné n'est pas celui du VW,
le PID mileage n'est pas décodé. À vérifier/ajuster dans Configurator (côté opérateur). Sinon,
l'OEM AVL 389 est à considérer **non exploitable sur ce véhicule**.

### BASCULE STRATÉGIQUE → piste « Total Odometer GNSS interne »
Source admissible alternative (citée par l'opérateur) : **Teltonika Total Odometer calculé sur GNSS
interne** (`11806=0`, valeur `11807`). Dans le .cfg Manchester : `11806=0` (GNSS), `11807=60 km`
→ le device CALCULE bien un Total Odometer interne. **MAIS il n'est PAS exposé à Navixy** (aucun
`total_odometer`/`avl_io_16` dans readings ; seul le compteur `odometer` Navixy GPS-calculé plateforme
existe — EXCLU car il s'arrête si les coordonnées sont masquées).
→ Pour l'utiliser : activer l'envoi de l'I/O **Total Odometer** (AVL 16) dans la config (écriture,
GATED) ; puis prouver (a) qu'il incrémente, (b) qu'il continue quand les coordonnées sont masquées
(privatemode). C'est la nouvelle cible de D3.


### Interprétation (nuancée)
Conditions **idéales** réunies — config parfaite (Codec 8 Ext + OBD Feature + OEM Total Mileage
priority), OBD **actif** (VIN/rpm/vitesse temps réel), véhicule **en mouvement** — et pourtant
`obd_mileage` (AVL 389) **ne se peuple pas**. Ce n'est donc **ni** un problème de config, **ni** un
problème de liaison OBD : c'est le **PID OEM « total mileage » qui n'est pas fourni/décodé** pour ce
VW précis.

### Nuances (ne pas figer « NOT_SUPPORTED » définitivement)
1. Le **profil OEM OBD** Teltonika sélectionné (param `40002=10` vu au .cfg) doit correspondre au
   **groupe VAG** (VW/Audi/Skoda/Seat). Si le profil OEM n'est pas le bon, le PID mileage n'est pas décodé.
2. Le PID OEM mileage peut remonter à **très basse fréquence** (à confirmer sur une fenêtre plus longue).
3. Beaucoup de véhicules **ne fournissent tout simplement pas** ce PID via OBD standard.

### Conséquence stratégique
- Pour **ce VW**, l'OEM mileage (AVL 389) **n'est pas exploitable en l'état**.
- **Piste parallèle à reprendre** : Total Odometer **GNSS interne** (`11806=0`) — non exposé Navixy
  aujourd'hui, activation I/O à étudier (écriture, gated).
- Tester l'OEM mileage sur un véhicule **d'une autre marque** pourrait donner un résultat différent
  (le support AVL 389 est **véhicule-dépendant**, comme documenté).

## ============================================================================

## ============================================================================
## SNAPSHOT D3-A (Etapes 0+1) — tracker 3467714 « Manchester » — READ-ONLY
## ============================================================================
```
TRACKER_ID = 3467714
MODEL = FMC003            (source.model = telfmb003_fmc003)  ✓ confirmé
FIRMWARE = NOT_READABLE_VIA_NAVIXY (relever via Configurator)

CODEC_8_EXTENDED = NON_CONFIRMÉ_POUR_CE_DEVICE   [le .cfg fourni = FmType=FMC130, pas ce FMC003]
OBD_FEATURE (40000) = INCONNU                    [idem — .cfg du bon device requis]
VIN_SOURCE (40005) = INCONNU (lecture seule)     [idem]
OEM_TOTAL_MILEAGE_PRIORITY (40430) = INCONNU     [idem]

OBD_MILEAGE_SENSOR_DEFINED = YES   (sensor id 5371584 « OBD : Kilométrage OBD total », km)
OBD_MILEAGE_VALUE = None           (sensor défini mais VIDE dans readings)
OBD_MILEAGE_TIMESTAMP = None
AVL389_PRESENT_RUNTIME = NO        (absent readings + get_state.additional)

OBD_VIN = WV2ZZZSK3PX065783  (@ 2026-09-02 18:01:03 — VW utilitaire, OBD ACTIF/récent)
NAVIXY_GPS_ODOMETER = 16539.43 km @ 2026-09-02 17:59:56  (RÉFÉRENCE SEULEMENT — EXCLU)

AVL389_165000_PROVENANCE = UNRESOLVED
D3A_CONFIG_WRITE_READY = NO
BLOCKING_REASON = config device réelle de 3467714 inconnue (besoin du .cfg export du FMC003
  « Manchester », le .cfg précédent étant FmType=FMC130 → mauvais device) ; firmware non lisible
  via Navixy ; GO explicite requis avant toute écriture.
```
> Note : OBD parfaitement actif (VIN VW + rpm/temp/carburant temps réel), sensor `obd_mileage`
> **défini mais vide** → l'AVL 389 n'est pas transmis (OEM mileage non activé côté device).
> Hypothèse cohérente : le vrai compteur du VW ≈ 165 000 km (utilitaire) — d'où la capture — mais
> `PROVENANCE=UNRESOLVED` maintenue. Le GPS odo Navixy (16 539) ne compte que depuis l'installation.



> **STATUT : PRÉPARÉ, NON EXÉCUTÉ.** Aucune écriture device ne sera faite sans **GO explicite**
> de l'opérateur, tracker par tracker. Aucun `privatemode` dans ce protocole (c'est D3-B, plus tard).
> Source de vérité : Teltonika wiki — **AVL ID 389 = OBD OEM Total Mileage (km)** ; transmission
> conditionnée à **Codec 8 Extended (113=1) + OBD Feature (40000=1) + OEM Total Mileage priority
> (40430≥1)** ET au **support réel du PID OEM par le véhicule**.

---

## 0. PORTÉE ET GARDE-FOUS (non négociables)
- **UN SEUL tracker** : pilote privilégié **`3467714`** (compte Navixy `234783`).
- **Modèle à CONFIRMER d'abord** via `source.model` Navixy (doit être FMC003). Si ≠ FMC003 → STOP.
- **Aucun bulk**, aucun autre véhicule, aucune exécution sans GO explicite.
- **`40005` (VIN Source) : NE PAS MODIFIER.** Relever sa valeur et vérifier sa signification pour le
  firmware exact **avant** toute décision. (Modification hors périmètre de ce protocole.)
- **Ne pas supposer** que `40000:1;40430:1` suffit : le véhicule doit **fournir** le PID OEM, et le
  **profil OEM** requis doit être disponible pour ce firmware/config Teltonika.
- **Aucun `privatemode`** ici. D3-B (Private Mode) ne viendra **qu'après** `OEM_MILEAGE_VALIDATED`.
- La capture `avl_io_389 = 165000` = **PROVENANCE NON ÉTABLIE** → n'est PAS une preuve runtime tant
  que son écran/date/tracker ne sont pas identifiés. Ne pas l'utiliser comme référence.

---

## 1. SÉPARATION D3-A / D3-B (sécurité)
```
D3-A  Configurer OEM Mileage
        → AVL 389 (obd_mileage) apparaît ?
        → valeur correcte vs compteur réel du véhicule ?
        → incrémente en roulant ?
        → OEM_MILEAGE_VALIDATED
Seulement ensuite :
D3-B  Private Mode
        → GPS transmis masqué
        + AVL 389 continue d'incrémenter
        → FIELD_VALIDATED
```
Bénéfice : en cas d'échec, on sait **immédiatement** si le problème vient du **kilométrage OEM**
(D3-A) ou du **Private Mode** (D3-B).

> **Piste parallèle conservée (NE PAS abandonner) :** Total Odometer **GNSS interne** du FMC130
> (`11806=0`) reste la 2ᵉ voie, notamment pour les véhicules sans PID OEM.

---

## 2. ÉTAPE 0 — CONFIRMER LE MODÈLE (READ-ONLY, PRÉALABLE OBLIGATOIRE)
Objectif : garantir que `3467714` est bien un **FMC003** avant tout.
```
LIRE : tracker/list -> source.model de 3467714
GATE : resolve_model(source.model) == "FMC003"   sinon -> STOP (mauvais device)
```

---

## 3. ÉTAPE 1 — SNAPSHOT « AVANT » (READ-ONLY COMPLET)
À capturer et archiver **avant toute écriture** (device + Navixy) :

| # | Élément | Source | Notes |
|---|---|---|---|
| S1 | Modèle exact | Navixy `source.model` + Configurator `FmType` | doit être FMC003 |
| S2 | Firmware | Configurator (Title/FW) | ex. « 03.29.00 or higher » |
| S3 | `113` Codec 8 Extended | .cfg / Configurator | attendu = 1 |
| S4 | `40000` OBD Feature | .cfg / Configurator | **relever** (0/1) |
| S5 | `40005` VIN Source | .cfg / Configurator | **RELEVER SEULEMENT — ne pas modifier** |
| S6 | `40430` OEM Total Mileage priority | .cfg / Configurator | **relever** (0/1/2/3) |
| S7 | Sensor `obd_mileage` présent ? | Navixy `sensor/list` | défini ? |
| S8 | `obd_mileage` valeur + timestamp | Navixy `readings/list` | probablement VIDE avant |
| S9 | `avl_io_389` présent ? valeur ? | `readings/list` + `get_state` | probablement absent |
| S10 | VIN reçu OBD | `readings/list` states `obd_vin` | ex. WV2ZZZSK… (VW) |
| S11 | Odomètre GPS Navixy | `get_counters` type=odometer | **référence comparative UNIQUEMENT** |
| S12 | Odomètre réel tableau de bord véhicule | relevé physique | pour comparer à l'OEM mileage |

> Le snapshot AVANT est **obligatoire** : il sert de point de comparaison et de base au rollback.

---

## 4. ÉTAPE 2 — CONFIGURATION MINIMALE (ÉCRITURE — GATED, sur GO explicite)
> **NE PAS EXÉCUTER sans GO.** Configuration **minimale** strictement nécessaire pour AVL 389.
> Idéalement via **Teltonika Configurator** (traçable) plutôt que SMS/raw.

Paramètres à activer (minimum) :
```
113   = 1   (Codec 8 Extended)  -> normalement DÉJÀ à 1 (ne rien faire si déjà 1)
40000 = 1   (OBD Feature)        -> activer si S4 = 0
40430 = 1   (OEM Total Mileage priority : Low)  -> activer si S6 = 0
```
**Interdits dans cette étape :**
- ❌ Ne pas toucher `40005` (VIN Source).
- ❌ Aucun autre paramètre modifié.
- ❌ Aucun `privatemode`, aucun reset odomètre, aucune autre écriture.

> Rappel : cette activation **ne garantit pas** la valeur. Si le véhicule ne fournit pas le PID OEM
> (ou profil OEM indisponible), `obd_mileage` restera **vide** → verdict `NOT_SUPPORTED_BY_VEHICLE`.

---

## 5. ÉTAPE 3 — VÉRIFICATION APPARITION (READ-ONLY)
Après configuration + reconnexion device :
```
LIRE readings/list + get_state (plusieurs fois sur ~10-30 min, moteur ON) :
  - obd_mileage a-t-il maintenant une VALEUR ?  (et/ou avl_io_389 apparaît-il ?)
  - noter valeur + timestamp + fraîcheur
```
- Si toujours vide après config + moteur tournant → `OEM_MILEAGE_NOT_SUPPORTED_BY_VEHICLE`
  (ou profil OEM manquant) → passer au rollback (§8).

---

## 6. ÉTAPE 4 — CONTRÔLE DE COHÉRENCE DE LA VALEUR (READ-ONLY)
```
Comparer obd_mileage (AVL 389) au COMPTEUR RÉEL du tableau de bord (S12) :
  écart acceptable ? (unité km, ordre de grandeur correct)
Comparer aussi à l'odomètre GPS Navixy (S11) — RÉFÉRENCE SEULEMENT, jamais comme vérité.
```
- Valeur incohérente (ex. échelle ×1000, unité douteuse comme `obd_custom_odometer`) →
  `OEM_MILEAGE_CONFIG_INCONCLUSIVE`.

---

## 7. ÉTAPE 5 — PREUVE D'INCRÉMENTATION (petit roulage, READ-ONLY)
```
Relever obd_mileage AVANT un court trajet (V1, t1).
Effectuer un PETIT ROULAGE réel (quelques km).
Relever obd_mileage APRÈS (V2, t2).
Vérifier : V2 > V1, et (V2 - V1) ≈ distance réellement parcourue.
```
- `V2 > V1` et cohérent → candidat solide.
- Pas d'augmentation malgré roulage → `OEM_MILEAGE_CONFIG_INCONCLUSIVE`.

---

## 8. ÉTAPE 6 — ROLLBACK DOCUMENTÉ
> À exécuter si échec, ou pour revenir à l'état initial après le test (selon décision opérateur).
```
Restaurer les valeurs du SNAPSHOT AVANT :
  - si 40000 était 0 avant -> remettre 40000 = 0
  - si 40430 était 0 avant -> remettre 40430 = 0
  - 113 : laisser tel quel s'il était déjà 1 (ne pas toucher)
  - 40005 : n'a jamais été modifié (rien à restaurer)
Recharger la config d'origine (sauvegarde .cfg AVANT si disponible = rollback le plus sûr).
Vérifier en READ-ONLY le retour à l'état S3-S9 initial.
```
> **Sauvegarder le .cfg AVANT** (export Configurator) est le rollback le plus fiable.

---

## 9. VERDICT D3-A (un seul)
```
OEM_MILEAGE_VALIDATED
   (obd_mileage/AVL 389 présent, valeur cohérente vs compteur réel, incrémente en roulant)
OEM_MILEAGE_NOT_SUPPORTED_BY_VEHICLE
   (config correcte mais aucune valeur — PID OEM non fourni / profil OEM indisponible)
OEM_MILEAGE_CONFIG_INCONCLUSIVE
   (valeur présente mais incohérente / n'incrémente pas / ambiguïté firmware-profil)
```
- **Ne PAS lancer D3-B (Private Mode) tant que ≠ `OEM_MILEAGE_VALIDATED`.**

---

## 10. APRÈS D3-A (aperçu — NON préparé ici)
- Si `OEM_MILEAGE_VALIDATED` → préparer séparément **D3-B Private Mode** :
  masquage GPS transmis + vérifier que AVL 389 **continue d'incrémenter** → `FIELD_VALIDATED`.
- Si `NOT_SUPPORTED` / `INCONCLUSIVE` → basculer sur la **piste parallèle** Total Odometer GNSS
  interne (FMC130) et/ou décision produit (privacy applicative).

---

## 11. RÉCAP DES INTERDICTIONS
- ❌ Plus d'un tracker ; ❌ bulk ; ❌ exécution sans GO explicite.
- ❌ Modifier `40005` (VIN Source) ; ❌ `privatemode` ; ❌ reset odomètre ; ❌ tout paramètre hors 40000/40430.
- ✅ Snapshot AVANT obligatoire ; ✅ sauvegarde .cfg AVANT ; ✅ rollback documenté ; ✅ lectures = READ-ONLY.
- ⏸️ La capture `avl_io_389=165000` reste **PROVENANCE NON ÉTABLIE** jusqu'à identification écran/date/tracker.
