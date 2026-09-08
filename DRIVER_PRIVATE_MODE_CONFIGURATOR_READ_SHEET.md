# FICHE DE RELEVÉ — TELTONIKA CONFIGURATOR (LECTURE SEULE)
## Private Mode / Total Odometer — 3 pilotes (A / B / C)

> **⚠️ LECTURE SEULE — RÈGLE ABSOLUE**
> - Se connecter au device en Configurator (ou RMS), **lire** les écrans, **relever** les valeurs.
> - **NE JAMAIS** cliquer sur : `Save to device`, `Write to device`, `Apply`, `Synchronize`,
>   `Load to device`, `Send`, ni modifier un champ.
> - Ne **pas** envoyer de commande (`privatemode`, `setparam`, `getparam` via SMS/raw…).
> - En cas de doute, **ne rien valider** et fermer sans enregistrer.
> - Capturer une **capture d'écran** de chaque écran clé (Odometer, I/O Total Odometer,
>   Private/Business, Trigger) — masquer IMEI/SIM/numéro sur les captures.
>
> Objectif : déterminer, **sans rien écrire**, si un **Total Odometer** exploitable existe et si un
> **mode Privé** est configurable — pour statuer `READY_FOR_D3_CONFIG_PILOT` ou
> `NO_VALID_PRIVATE_ODOMETER_SOURCE` par pilote.

---

## Pilotes sélectionnés (sur données runtime réelles)

| Pilote | Tracker | Véhicule | Modèle Navixy | Raison du choix |
|---|---|---|---|---|
| **A** | `781479` | LOGITRAK AUDI | telfmu130_fmc130 (FMC130) | Pilote FMC130 fixe — cible Total Odometer interne GNSS |
| **B** | `______` (au choix) | ex. `3131157` 5-Alliance 01 **ou** `479009` 2-GE 752 796 | telfmb003_fmc003 (FMC003) | FMC003 avec **OBD présent et actif** (roulage récent) |
| **C** | `3079431` | KAIO Renault Zoe | telfmb003_fmc003 (FMC003) | FMC003 **électrique** sans mileage OBD — test Total Odometer GNSS indépendant du véhicule |

> Pilote B : choisir **un seul** véhicule confirmé thermique/OBD actif au moment du relevé.
> Cochez le tracker retenu : ☐ 3131157  ☐ 479003  ☐ 479009  ☐ 3612095

---

## Comment lire (repères d'écrans Configurator)
- **Device Info / Status** (haut de l'app) : Firmware, Configuration version, Model.
- **System → Odometer** : `Odometer Calculation Source`, `Total Odometer` (valeur), `Trip Odometer`.
  - `Odometer Calculation Source` possibles : **GNSS** / **OBD** / **LV-CAN** / **ALL-CAN**.
- **I/O** : chercher l'élément **`Total Odometer`** → `Priority` (None/Low/High), `Operand`, et
  la colonne/étiquette qui indique **l'AVL ID** (⚠️ **relever l'ID réellement affiché**, ne pas
  supposer 16).
- **Features / Trip → Private/Business** (nom variable selon firmware) : mode Privé supporté,
  `GPS Data Masking` (ou « send coordinates in private »), comportement odomètre en Privé,
  `Trigger` (Digital input / Timer / SMS…).
- **OBD / CAN (Bluetooth OBD ou LV-CAN)** : type de connexion configuré, `Vehicle Mileage` /
  `Total Vehicle Distance` présent dans les I/O ?

---

# ============ PILOTE A — FMC130 (tracker 781479, LOGITRAK AUDI) ============

Pour **chaque** paramètre : `CURRENT_VALUE` | `AVAILABLE (YES/NO)` | `SOURCE` (écran où lu) | `NOTES`.

| # | Paramètre | CURRENT_VALUE | AVAILABLE | SOURCE (écran) | NOTES |
|---|---|---|---|---|---|
| A1 | Modèle exact (device) | | | | |
| A2 | Firmware version | | | | |
| A3 | Configuration version | | | | |
| A4 | **Odometer Calculation Source** (GNSS/OBD/LV-CAN/ALL-CAN) | | | | |
| A5 | **Total Odometer** (valeur actuelle) + unité | | | | |
| A6 | Trip Odometer actif ? | | | | |
| A7 | **Total Odometer I/O activé ?** (Priority ≠ None) | | | | |
| A8 | **AVL ID réellement affiché** pour Total Odometer | | | | ne pas supposer 16 |
| A9 | Private/Business Mode **disponible** ? | | | | |
| A10 | **GPS Data Masking** (présent/configurable ?) | | | | |
| A11 | **Odometer calculation during Private Mode** (option ?) | | | | continue en privé ? |
| A12 | **Trigger Type** du mode Privé (Digital in/Timer/SMS…) | | | | |
| A13 | OBD/CAN : `Vehicle Mileage`/`Total Vehicle Distance` présent ? | | | | (explique le CAN figé 2022) |

**Captures A :** ☐ Odometer  ☐ I/O Total Odometer  ☐ Private/Business  ☐ Trigger

### ✅ PILOTE A — RELEVÉ RÉEL depuis `Config_costa(3).cfg` (export FMC130, READ-ONLY)
> Source : fichier de config Teltonika fourni (gzip décompressé). Mapping des IDs **sourcé**
> sur le wiki Teltonika FMC130 (Parameter list / Trip-Odometer settings), non supposé.

**Header :** `FmType=FMC130` | `HwVersion=FMC1_4` | Firmware `Title=03.29.00 or higher` |
`ConfigurationVersion=10.0.0.0`

| Param (ID) | Valeur | Signification (wiki FMC130) |
|---|---|---|
| 11800 | **1** | Trip scenario / priorité = **Low (activé)** |
| 11801 | 1 | Eventual records = Enable |
| 11802 | **0** | Trip odometer mode = **Continuous** |
| 11803 | 5 | Start speed = 5 km/h |
| **11806** | **0** | **Odometer Calculation Source = GNSS** ★ point décisif |
| **11807** | **54193** | **Odometer Value = 54193 km** (valeur stockée dans la config) |
| 11815 | 0 | (sous-param groupe Trip — non déterminant ici) |
| 11500 / 11501 | 1 / 1 | Bluetooth/OBD activé côté config (mais OBD non renouvelé depuis 2024, cf runtime) |

**Synthèse Pilote A :**
```
TOTAL_ODOMETER_SUPPORTED:                  YES
TOTAL_ODOMETER_ENABLED:                    YES (Trip scenario actif, valeur stockée présente)
TOTAL_ODOMETER_SOURCE:                     GNSS            (11806=0)  ★ indépendant de l'OBD/CAN
TOTAL_ODOMETER_CURRENT_VALUE:              54193 km        (11807 — valeur de config, pas forcément live)
TOTAL_ODOMETER_AVL_ID:                     UNVERIFIED      (le .cfg ne prouve pas l'IO/AVL réellement ENVOYÉ)
PRIVATE_MODE_SUPPORTED:                    NO (natif)      (aucun paramètre Private/Business natif dans ce .cfg)
GPS_MASKING_CONFIGURABLE:                  NO (côté device — le masquage relève de Navixy/plateforme)
PRIVATE_ODOMETER_CALCULATION_CONFIGURABLE: N/A
EXTERNAL_TRIGGER_SUPPORTED:                Digital Input possible, mais pas de scénario privé natif
```

**Correction d'un indice précédent :** la source de calcul est le param **11806** (=0=GNSS),
**pas** 11811. La valeur `11811=16` appartient à la matrice de sous-paramètres Trip et **n'est
PAS** une preuve d'AVL ID 16 → `TOTAL_ODOMETER_AVL_ID` reste **UNVERIFIED**.

**Verdict Pilote A :** `READY_FOR_D3_CONFIG_PILOT`
> L'odomètre interne du FMC130 est calculé sur **GNSS** (indépendant de l'OBD/CAN mort) et possède
> une valeur réelle (54193 km, Continuous). C'est la source non-GPS-plateforme recherchée. **MAIS**
> il n'est **pas encore exposé à Navixy** (runtime D2 : aucun champ total_odometer reçu ; seul
> l'odometer GPS-calculé Navixy et le can_mileage mort existent). Deux prérequis restants (config
> pilot, sur GO explicite) :
> 1. **Activer l'envoi de l'élément I/O Total Odometer** (écriture config → PAS maintenant) et
>    vérifier réception côté Navixy + relever l'**AVL ID réel**.
> 2. Prouver en D3 que cet odomètre GNSS interne **continue** quand la position transmise est masquée.

---

# ============ PILOTE B — FMC003 avec OBD ACTIF (tracker : __________) ============

| # | Paramètre | CURRENT_VALUE | AVAILABLE | SOURCE (écran) | NOTES |
|---|---|---|---|---|---|
| B1 | Modèle exact / Firmware | | | | |
| B2 | Configuration version | | | | |
| B3 | Type OBD/CAN configuré (OBD BT / LV-CAN / ALL-CAN) | | | | |
| B4 | Données OBD réellement **activées** (liste I/O OBD) | | | | |
| B5 | **Vehicle Mileage / Total Vehicle Distance** présent ? | | | | source véhicule |
| B6 | Valeur Vehicle Mileage (si présent) + unité | | | | |
| B7 | **Odometer Calculation Source** (GNSS/OBD/CAN) | | | | |
| B8 | **Total Odometer Teltonika** (valeur actuelle) | | | | |
| B9 | **Total Odometer I/O activé ?** | | | | |
| B10 | **AVL ID réellement affiché** (Total Odometer) | | | | |
| B11 | Private/Business Mode disponible ? | | | | |
| B12 | GPS Data Masking configurable ? | | | | |
| B13 | Odometer calculation during Private Mode | | | | |
| B14 | Trigger Type | | | | |

**Captures B :** ☐ OBD/CAN I/O  ☐ Odometer  ☐ I/O Total Odometer  ☐ Private/Business

---

# ============ PILOTE C — FMC003 ÉLECTRIQUE sans mileage OBD (tracker 3079431, Renault Zoe) ============

> **Objectif clé** : déterminer si le FMC003 peut calculer son **propre Total Odometer sur GNSS**,
> **indépendamment** du mileage fourni par le véhicule. Si OUI → l'absence de PID OBD sur les
> Zoe/Enyaq/EX30 **ne condamne pas** le mode privé.

| # | Paramètre | CURRENT_VALUE | AVAILABLE | SOURCE (écran) | NOTES |
|---|---|---|---|---|---|
| C1 | Modèle exact / Firmware | | | | |
| C2 | Configuration version | | | | |
| C3 | OBD/CAN : un mileage véhicule est-il présent ? (attendu NON) | | | | confirme absence PID EV |
| C4 | **Odometer Calculation Source** — peut-il être **GNSS** ? | | | | ★ point décisif |
| C5 | **Total Odometer Teltonika** (valeur actuelle) | | | | |
| C6 | Le Total Odometer **augmente-t-il** (relevé à 2 instants) ? | | | | noter 2 valeurs + heures |
| C7 | **Total Odometer I/O activé ?** | | | | |
| C8 | **AVL ID réellement affiché** (Total Odometer) | | | | |
| C9 | Private/Business Mode disponible ? | | | | |
| C10 | GPS Data Masking configurable ? | | | | |
| C11 | Odometer calculation during Private Mode | | | | GNSS conservé en privé ? |
| C12 | Trigger Type | | | | |

**Captures C :** ☐ Odometer (GNSS source)  ☐ I/O Total Odometer  ☐ Private/Business

---

# SYNTHÈSE À PRODUIRE (par pilote, après relevé)

Reporter pour **A**, **B**, **C** :

```
PILOTE: A / B / C
TRACKER_ID:
VEHICLE:
MODEL:
FIRMWARE:
CONFIG_VERSION:

TOTAL_ODOMETER_SUPPORTED:              YES / NO
TOTAL_ODOMETER_ENABLED:                YES / NO
TOTAL_ODOMETER_SOURCE:                 GNSS / OBD / LV-CAN / ALL-CAN / UNKNOWN
TOTAL_ODOMETER_CURRENT_VALUE:          <valeur + unité>
TOTAL_ODOMETER_AVL_ID:                 <ID réellement affiché>   (sinon UNVERIFIED)
PRIVATE_MODE_SUPPORTED:                YES / NO
GPS_MASKING_CONFIGURABLE:              YES / NO
PRIVATE_ODOMETER_CALCULATION_CONFIGURABLE: YES / NO
EXTERNAL_TRIGGER_SUPPORTED:            YES / NO
```

Puis, **par pilote**, conclure UNIQUEMENT par :
```
READY_FOR_D3_CONFIG_PILOT
   ou
NO_VALID_PRIVATE_ODOMETER_SOURCE
```

---

# ARBRE DE DÉCISION (rappel — ne pas conclure trop tôt)

```
Total Odometer activable ET calculé sur une source qui CONTINUE quand
la position transmise est masquée (idéalement GNSS interne)
        │
        ├── OUI ─────────────► READY_FOR_D3_CONFIG_PILOT
        │                        (GPS masqué + km conservés → D3 sur AUTORISATION explicite)
        │
        └── NON ─────────────► NO_VALID_PRIVATE_ODOMETER_SOURCE
                                 → PAS de distance privée hardware fiable pour ce véhicule
                                 → DÉCISION PRODUIT LOGITRAK requise (au cas par cas) :
                                     • mode privé applicatif (sans distance hardware)
                                     • kilométrage privé = UNAVAILABLE
                                     • autre source véhicule (si disponible)
                                     • bouton Privé désactivé pour ce véhicule
```

> **Important** : un échec de l'odomètre hardware **ne déclare PAS** tout le Private Mode impossible.
> Il déclenche seulement une **décision produit** sur ce que LOGITRAK doit faire quand aucune source
> hardware fiable n'existe.

---

# INTERDICTIONS (rappel)
- ❌ `Save/Write/Apply/Synchronize` — aucune écriture Configurator.
- ❌ `privatemode`, `setparam`, `raw_command/send` — aucune commande device.
- ❌ Modification Navixy / Teltonika / Mongo.
- ❌ Supposer un AVL ID universel (relever l'ID réel).
- ❌ Lancer D3.
- ✅ Lecture seule + captures + relevé des valeurs uniquement.
