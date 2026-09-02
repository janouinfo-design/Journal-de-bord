# DRIVER_PRIVATE_MODE_D3_CONFIG_OEM_MILEAGE.md
## Protocole D3-CONFIG — OEM Mileage (AVL 389) — GATED / NON EXÉCUTÉ

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
