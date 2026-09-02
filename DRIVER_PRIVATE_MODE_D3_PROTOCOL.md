# DRIVER_PRIVATE_MODE_D3_PROTOCOL.md
## Phase D3 — Pilote terrain Private/Business + can_mileage — FMC130 tracker 781479 UNIQUEMENT

> **NE PAS EXÉCUTER AUTOMATIQUEMENT.** Ce document + le script `d3_pilot.py` sont PRÉPARÉS.
> L'exécution des gates d'ÉCRITURE (GATE 2, 4, 7) exige une **autorisation explicite** par gate.
> Cible : **UN SEUL** device — FMC130, tracker **781479** (LOGITRAK AUDI), tenant `default`.
> INTERDIT : bulk, autres modèles (FMC003/FMU130/FMC640/FMC650), `trip.length`,
> `counter/value/set`, toute modif de config autre que `Trigger Type` (si nécessaire).


> ## 🔴 MISE À JOUR PRÉ-D3 (bloquant) — GATE 1 ÉCHOUE : pas de source odomètre HW vivante
> Vérification READ-ONLY du `can_mileage` sur le FMC130 pilote (781479) :
> ```
> CAN_MILEAGE_SENSOR_EXISTS: YES (id 5411571, unité km, mult=1, div=1)
> CAN_MILEAGE_VALUE:         80078.5 km
> CAN_MILEAGE_TIMESTAMP:     2022-03-26   ← PÉRIMÉ ~4 ans
> SENSOR_HISTORY (2026):     [] vide
> CAN_MILEAGE_FRESH:         NO
> CAN_MILEAGE_CLASSIFICATION: UNKNOWN (donnée morte, incrément non testable)
> ```
> → Le sensor `can_mileage` **existe mais ne reçoit plus de données depuis 2022** (bus CAN
> ne remonte plus le km). Confirmé par l'opérateur : « FMC130 n'a pas can_mileage » (exploitable).
> **GATE 1 non satisfaite → D3 NE DÉMARRE PAS.** Aucune écriture device. `privatemode` NON envoyé.
>
> **Verdict parc (runtime réel) :** aucune source odomètre **hardware vivante** (FMC003=aucune,
> FMC130=CAN mort, FMU130=aucune). Seules sources vivantes = **GPS-calculées** → **incompatibles**
> avec le masquage GPS. ⇒ L'architecture « GPS masqué + odomètre qui continue » est
> **NON RÉALISABLE sur le parc actuel** sans action matérielle/config préalable.
>
> **Prochaines options (aucune n'est D3 en l'état) :**
> 1. **Réactiver le CAN** sur les FMC130 (recâblage/PID CAN mileage) → puis re-preflight `can_mileage` vivant → D3.
> 2. **Option A** : activer le **Total Odometer Teltonika (GNSS interne)** via Configurator et vérifier
>    terrain qu'il continue quand le GPS *transmis* est masqué (GNSS interne ≠ GPS transmis).
> 3. **Option C** : confidentialité **applicative** LOGITRAK (masquage côté backend/app), distance
>    privée = `DISTANCE UNAVAILABLE` si aucune source non-GPS ; ne pas masquer au niveau device.
>
> Le registre `odometer_capability.py` reflète ce verdict : FMC130 `status=BLOCKED`,
> `odometer_during_private=NOT_SUPPORTED`. Bouton Privé prod **désactivé** pour tous les modèles.

---

## PRÉ-REQUIS (avant GATE 1) — LECTURE MANUELLE TELTONIKA CONFIGURATOR
À relever à la main (lecture seule) sur le device 781479, AVANT toute écriture :
```
FIRMWARE_VERSION:            ____
PRIVATE_BUSINESS_ENABLED:    ____ (Enabled/Disabled)
GPS_DATA_MASKING:            ____ (attendu cible: "Data sent as Zero")
ODOMETER_CALCULATION:        ____ (attendu cible: "Enable")
TRIGGER_TYPE:                ____ (Weekly Schedule | External | DIN | ...)
SCENARIO/PRIORITY/EVENTUAL:  ____
CONFIG_ORIGINALE_SAUVEGARDEE: OUI/NON  (export .cfg Configurator conservé = base du rollback)
```
> Si `TRIGGER_TYPE = Weekly Schedule` → une commande externe `privatemode ON/OFF` **NE marchera pas**.
> Il faudra `Trigger Type = External` (GATE 2, écriture, sur autorisation explicite).

---

## GATE 1 — CONFIG (lecture / pré-conditions)
Conditions à réunir (toutes) :
- [ ] MODEL = FMC130 (résolu via `resolve_model('telfmu130_fmc130')`)
- [ ] TRACKER = 781479
- [ ] FIRMWARE connu (relevé Configurator)
- [ ] Config Private/Business connue (relevée Configurator)
- [ ] **Config originale sauvegardée** (export .cfg) — base du rollback
- [ ] `can_mileage` validé RUNTIME : CUMULATIVE_ODOMETER + incrément cohérent (étape 1 READ-ONLY)
→ Si une case manque : **STOP**, ne pas passer GATE 2.

## GATE 2 — ÉCRITURE CONFIG (conditionnelle, autorisation explicite)
Uniquement si `TRIGGER_TYPE ≠ External` ET autorisation explicite :
- Modifier **UNIQUEMENT** `Trigger Type → External`. Aucune autre modif.
- Moyens possibles (au choix, 1 device) :
  - Teltonika Configurator (manuel) ; OU
  - `setparam 11849:<val External>` via Navixy `raw_command/send` (⚠️ ÉCRITURE — hors READ-ONLY).
- Vérifier que la nouvelle valeur est appliquée (relecture Configurator).
- **Rollback documenté** : réappliquer la config originale (.cfg) ou `setparam 11849:<val d'origine>`.
> ⚠️ Le param ID `11849` (Trigger Type) vient de la doc Teltonika → **à confirmer** pour le firmware
> réel du 781479 avant écriture. Ne pas écrire un ID non confirmé.

## GATE 3 — SNAPSHOT (lecture)
```
CAN_MILEAGE_START = X            (sensor can_mileage, valeur + timestamp)
GPS_POSITION_BEFORE = AVAILABLE  (get_state: lat/lng réels)
PRIVATE_STATE_BEFORE = OFF
```

## GATE 4 — PRIVATE ON (écriture device, autorisation explicite)
- Envoyer **uniquement au 781479** : `privatemode ON` (via `raw_command/send`, réservé au device full).
- **HTTP 200 ≠ confirmation device.** Attendre la confirmation réelle (état device / AVL Private).
- Vérifier :
```
PRIVATE_STATE = ON
GPS transmis = masked/zero (selon config)
```

## GATE 5 — TEST STATIQUE (lecture, AVANT de rouler)
- Vérifier que les readings CAN **continuent** pendant PRIVATE : `can_mileage`, `can_consumption`, RPM…
- **Si `can_mileage` disparaît immédiatement → STOP, remettre BUSINESS (privatemode OFF), D3 = FAIL.**

## GATE 6 — ROULAGE TERRAIN
- Seulement si `can_mileage` reste disponible : rouler réellement quelques km.
- **Aucune** distance GPS utilisée pendant PRIVATE.

## GATE 7 — PRIVATE OFF (écriture device)
- Envoyer `privatemode OFF` au 781479. Vérifier :
```
PRIVATE_STATE = OFF
GPS réel revenu (get_state: lat/lng réels)
```

## GATE 8 — DISTANCE PRIVÉE (calcul)
```
CAN_MILEAGE_END = Y
PRIVATE_DISTANCE_KM = Y - X
```
PASS uniquement si : Y>X · même tracker · même sensor · unité identique · timestamps cohérents ·
GPS réellement masqué pendant PRIVATE · GPS revenu après OFF.

## GATE 9 — ROLLBACK
- Si `Trigger Type` a été modifié : **ne pas restaurer automatiquement** (décision : garder External
  comme cible ou non). **Conserver** la config originale + la procédure exacte de rollback.

---

## RÉSULTAT ATTENDU D3
```
FMC130_PRIVATE_MODE:              PASS/FAIL
GPS_MASKING:                      PASS/FAIL
CAN_MILEAGE_DURING_PRIVATE:       PASS/FAIL
CAN_MILEAGE_INCREMENT:            PASS/FAIL
PRIVATE_DISTANCE_CALCULATION:     PASS/FAIL
BUSINESS_RETURN:                  PASS/FAIL
ROLLBACK_READY:                   YES/NO
FIELD_VALIDATION:                 PASS/FAIL
```
Uniquement si **tout** PASS :
```
FMC130_PRIVATE_MODE_CAPABILITY = FIELD_VALIDATED
```
Alors seulement, dans le registre `odometer_capability.py`, FMC130 pourra passer
`verified=True, status=VALIDATED` → `private_mode_allowed('FMC130')` deviendra `True`.
**Jusque-là, le bouton Privé de production reste DÉSACTIVÉ pour TOUS les modèles.**

## GARDE-FOUS ABSOLUS
- 1 seul tracker (781479). Jamais de bulk. Jamais toucher FMC003/FMU130/FMC640/FMC650.
- Jamais `trip.length` / distance GPS comme mesure privée. Jamais `counter/value/set`.
- Écritures device (GATE 2/4/7) seulement sur autorisation explicite, gate par gate.
- FMC130 validé ≠ « Teltonika validé » : la validation est MODÈLE + FIRMWARE + CONFIG.
