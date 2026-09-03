"""Registre de capacités odomètre/confidentialité par MODÈLE et PAR TRACEUR (Stratégie V2).

=====================  STRATÉGIE V2 (2026-09-03) — SOCLE COMMUN AVL 16  =====================
Décision d'architecture (fondée sur preuves terrain) :

    TELTONIKA TOTAL ODOMETER  ──  AVL ID 16  ──  { FMC003, FMC130 }

- FMC003 -> PRIMARY = TELTONIKA_TOTAL_ODOMETER (AVL 16, GNSS interne).
            SECONDARY = OBD_OEM_TOTAL_MILEAGE (AVL 389) *si le véhicule le fournit*.
- FMC130 -> PRIMARY = TELTONIKA_TOTAL_ODOMETER (AVL 16, GNSS interne).
            SECONDARY = CAN_MILEAGE / NONE selon disponibilité.
- FMU130 -> DEPRECATED (aucun dev).
- FMC640/FMC650 -> NOT_RUNTIME_VERIFIED (ne PAS appliquer AVL 16 automatiquement).

Pourquoi AVL 389 devient SECONDAIRE : il dépend du véhicule et du PID OEM. Preuve terrain :
un FMC003 sur Audi A3 expose AVL 16 alors que AVL 389 est ABSENT. On réduit donc la dépendance
au véhicule en standardisant sur le compteur interne Teltonika (AVL 16).

RÈGLES ABSOLUES :
- Le compteur Navixy GPS-calculé n'est JAMAIS une source de distance privée (il gèle à 0,0).
- La SIMPLE présence de avl_io_16 n'autorise PAS le mode privé.
- `field_validated=True` UNIQUEMENT sur preuve TERRAIN (D3 PASS end-to-end).
- Capacité PAR TRACEUR/VÉHICULE (jamais `if model in [...]: allowed=True`).
- Aucune AVL figée sans preuve ; le scale AVL 16 doit être normalisé et VALIDÉ.
- PRIVATE_MODE_PRODUCTION reste DISABLED tant que non FIELD_VALIDATED.

Niveaux de preuve : UNKNOWN < DOCUMENTED < RUNTIME_VERIFIED < FIELD_VERIFIED
(NOT_SUPPORTED = démontré non supporté)
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Niveaux d'évidence
# ---------------------------------------------------------------------------
UNKNOWN = "UNKNOWN"
DOCUMENTED = "DOCUMENTED"
RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
FIELD_VERIFIED = "FIELD_VERIFIED"
NOT_SUPPORTED = "NOT_SUPPORTED"

# ---------------------------------------------------------------------------
# États modèle (gate production par modèle) — anciens conservés (rétrocompat)
# ---------------------------------------------------------------------------
STATUS_NOT_TESTED = "NOT_TESTED"
STATUS_PILOT = "PILOT"
STATUS_VALIDATED = "VALIDATED"        # field-verified end-to-end
STATUS_BLOCKED = "BLOCKED"
STATUS_DEPRECATED = "DEPRECATED"      # hors scope futur (ex FMU130)
STATUS_NOT_PRESENT = "NOT_PRESENT"

# Statuts de capability V2 (progression de validation AVL 16)
CAP_NOT_TESTED = "NOT_TESTED"
CAP_AVL16_NOT_EXPOSED = "AVL16_NOT_EXPOSED"
CAP_AVL16_RUNTIME_VERIFIED = "AVL16_RUNTIME_VERIFIED"
CAP_AVL16_CUMULATIVE_VERIFIED = "AVL16_CUMULATIVE_VERIFIED"
CAP_PRIVATE_ODOMETER_PENDING = "PRIVATE_ODOMETER_PENDING"
CAP_FIELD_VALIDATED = "FIELD_VALIDATED"
CAP_NO_VALID_PRIVATE_ODOMETER = "NO_VALID_PRIVATE_ODOMETER"
CAP_DEPRECATED = "DEPRECATED"

# ---------------------------------------------------------------------------
# Stratégies cibles par modèle (anciennes conservées)
# ---------------------------------------------------------------------------
STRATEGY_TELTONIKA_TOTAL_ODOMETER = "TELTONIKA_TOTAL_ODOMETER"
STRATEGY_VEHICLE_OBD_CAN_MILEAGE = "VEHICLE_OBD_CAN_MILEAGE"   # legacy (rétrocompat imports)
STRATEGY_HARDWARE_CAN_FMS_TACHO = "HARDWARE_CAN_FMS_TACHO"
STRATEGY_DEPRECATED = "DEPRECATED"

# ---------------------------------------------------------------------------
# Types de source odomètre
# ---------------------------------------------------------------------------
SOURCE_TELTONIKA_TOTAL_ODOMETER = "TELTONIKA_TOTAL_ODOMETER"   # AVL 16 (GNSS interne) — PRIMARY
SOURCE_OBD_OEM_TOTAL_MILEAGE = "OBD_OEM_TOTAL_MILEAGE"         # AVL 389 (OBD OEM) — SECONDARY
SOURCE_CAN_MILEAGE = "CAN_MILEAGE"                             # can_mileage — secondaire éventuel
SOURCE_NAVIXY_GPS_CALCULATED = "NAVIXY_GPS_CALCULATED"        # JAMAIS admissible en privé
SOURCE_NONE = "NONE"

# AVL ID cible (documenté, NON figé comme "verified" tant que non prouvé par tracker)
AVL_TOTAL_ODOMETER = 16          # Teltonika Total Odometer / hw_mileage
AVL_OBD_OEM_TOTAL_MILEAGE = 389  # OBD OEM Total Mileage (secondaire)

# Disponibilité de la stratégie
AVAIL_VEHICLE_DEPENDENT = "VEHICLE_DEPENDENT"           # legacy
AVAIL_DEVICE_CONFIG_DEPENDENT = "DEVICE_CONFIG_DEPENDENT"
AVAIL_NOT_APPLICABLE = "NOT_APPLICABLE"
# Alias V2 explicite
AVAIL_DEVICE_CONFIG = AVAIL_DEVICE_CONFIG_DEPENDENT

# Statut d'échelle (normalisation AVL 16)
SCALE_UNVERIFIED = "UNVERIFIED"
SCALE_RUNTIME_PENDING = "RUNTIME_PENDING"   # forte présomption /1000, à confirmer via API + incrément
SCALE_VERIFIED = "VERIFIED"


@dataclass
class HardwareOdometerCapability:
    device_model: str                       # ex "FMC130" (famille logique)
    navixy_model_code: Optional[str] = None # ex "telfmu130_fmc130" (code Navixy runtime)
    # Stratégie cible (décision métier) + disponibilité
    strategy: str = "UNKNOWN"               # STRATEGY_*
    availability: str = UNKNOWN             # AVAIL_*
    # Sources (V2)
    primary_source: str = "UNKNOWN"         # SOURCE_* — cible principale
    secondary_source: str = SOURCE_NONE     # SOURCE_* — validation/bonus si dispo
    # Source odomètre candidate (résolue runtime/field) — legacy conservé
    source_type: str = "UNKNOWN"
    raw_avl_id: Optional[int] = None        # JAMAIS imposé sans preuve terrain
    navixy_input: Optional[str] = None      # input_name Navixy si exposé
    unit: Optional[str] = None              # "m" | "km"
    is_cumulative: Optional[bool] = None
    # Confidentialité
    private_business_supported: str = UNKNOWN
    gps_data_masking_supported: str = UNKNOWN
    odometer_during_private: str = UNKNOWN
    remote_privatemode_supported: str = UNKNOWN
    navixy_sensor_exposable: str = UNKNOWN
    # Exigences / preuve
    minimum_firmware: Optional[str] = None
    evidence_level: str = UNKNOWN
    verified: bool = False                   # True UNIQUEMENT si FIELD_VERIFIED
    status: str = STATUS_NOT_TESTED
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Registre V2 — stratégie commune AVL 16 pour FMC003 + FMC130.
# AUCUN `verified=True`, AUCUN `raw_avl_id` figé comme prouvé.
# ---------------------------------------------------------------------------
REGISTRY: dict[str, HardwareOdometerCapability] = {
    "FMC003": HardwareOdometerCapability(
        device_model="FMC003", navixy_model_code="telfmb003_fmc003",
        strategy=STRATEGY_TELTONIKA_TOTAL_ODOMETER,      # V2: socle commun AVL 16
        availability=AVAIL_DEVICE_CONFIG,                # dépend de la config device (pas du PID OEM)
        primary_source=SOURCE_TELTONIKA_TOTAL_ODOMETER,  # AVL 16 (GNSS interne)
        secondary_source=SOURCE_OBD_OEM_TOTAL_MILEAGE,   # AVL 389 si le véhicule le fournit
        source_type="UNKNOWN",
        raw_avl_id=None, navixy_input=None, unit=None, is_cumulative=None,
        private_business_supported=DOCUMENTED, gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN,
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_NOT_TESTED,
        notes=("V2: PRIMARY=TELTONIKA_TOTAL_ODOMETER (AVL 16, GNSS interne). "
               "SECONDARY=OBD_OEM_TOTAL_MILEAGE (AVL 389) si véhicule compatible. "
               "Preuve terrain: FMC003 sur Audi A3 -> avl_io_16 PRÉSENT (140258496), AVL 389 ABSENT. "
               "AVL 389 n'est PLUS requis. Scale AVL 16 à normaliser+valider (probable /1000 m->km). "
               "private_mode_allowed exige FIELD_VALIDATED par tracker (voir capability véhicule)."),
    ),
    "FMC130": HardwareOdometerCapability(
        device_model="FMC130", navixy_model_code="telfmu130_fmc130",
        strategy=STRATEGY_TELTONIKA_TOTAL_ODOMETER,
        availability=AVAIL_DEVICE_CONFIG,
        primary_source=SOURCE_TELTONIKA_TOTAL_ODOMETER,  # AVL 16 (GNSS interne)
        secondary_source=SOURCE_CAN_MILEAGE,             # can_mileage / NONE selon dispo
        source_type="UNKNOWN",
        raw_avl_id=None, navixy_input=None, unit=None, is_cumulative=None,
        private_business_supported=DOCUMENTED, gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN,
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_NOT_TESTED,
        notes=("V2: PRIMARY=TELTONIKA_TOTAL_ODOMETER (AVL 16, GNSS interne). Navixy confirme: "
               "AVL 16 = hw_mileage ; avec Odometer Calculation=Enable + GPS masking=Data Sent As Zero, "
               "AVL 16 CONTINUE à 0,0. Preuve terrain: avl_io_16=184601494, getparam 11807=184601 "
               "(cohérent m->km /1000, à VALIDER). SECONDARY=can_mileage si présent (souvent périmé). "
               "GPS Navixy JAMAIS admissible. FIELD_VALIDATED requis avant prod."),
    ),
    "FMU130": HardwareOdometerCapability(
        device_model="FMU130", navixy_model_code="telfmu130",
        strategy=STRATEGY_DEPRECATED, availability=AVAIL_NOT_APPLICABLE,
        primary_source=SOURCE_NAVIXY_GPS_CALCULATED, secondary_source=SOURCE_NONE,
        source_type="NAVIXY_GPS_CALCULATED",
        raw_avl_id=None, navixy_input=None, unit="km", is_cumulative=True,
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=NOT_SUPPORTED, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=NOT_SUPPORTED,
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_DEPRECATED,
        notes=("DEPRECATED (parc retiré ~2027). NO FURTHER ACTION. Historique D1/D2 conservé."),
    ),
    "FMC640": HardwareOdometerCapability(
        device_model="FMC640",
        strategy=STRATEGY_HARDWARE_CAN_FMS_TACHO, availability=AVAIL_VEHICLE_DEPENDENT,
        primary_source="UNKNOWN", secondary_source=SOURCE_NONE,
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status=STATUS_NOT_PRESENT,
        notes=("Poids lourd. NE PAS appliquer la stratégie AVL 16 automatiquement. "
               "NOT_RUNTIME_VERIFIED jusqu'à tests réels. ABSENT des comptes Navixy connus."),
    ),
    "FMC650": HardwareOdometerCapability(
        device_model="FMC650",
        strategy=STRATEGY_HARDWARE_CAN_FMS_TACHO, availability=AVAIL_VEHICLE_DEPENDENT,
        primary_source="UNKNOWN", secondary_source=SOURCE_NONE,
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status=STATUS_NOT_PRESENT,
        notes=("Poids lourd. NE PAS appliquer la stratégie AVL 16 automatiquement. "
               "NOT_RUNTIME_VERIFIED jusqu'à tests réels. ABSENT des comptes Navixy connus."),
    ),
}

# ---------------------------------------------------------------------------
# Mapping code Navixy -> modèle logique.
# ⚠️ Piège de nommage : 'telfmu130_fmc130' -> FMC130 (pas FMU130). Suffixes testés d'abord.
# ---------------------------------------------------------------------------
NAVIXY_MODEL_RULES = [
    ("_fmc003", "FMC003"),
    ("_fmc130", "FMC130"),
    ("_fmc640", "FMC640"),
    ("_fmc650", "FMC650"),
    ("telfmc003", "FMC003"),
    ("telfmc130", "FMC130"),
    ("telfmc640", "FMC640"),
    ("telfmc650", "FMC650"),
    ("telfmu130", "FMU130"),
]


def resolve_model(navixy_model_code: Optional[str]) -> Optional[str]:
    """Résout le modèle logique depuis le code Navixy."""
    if not navixy_model_code:
        return None
    code = str(navixy_model_code).lower()
    for token, model in NAVIXY_MODEL_RULES:
        if token in code:
            return model
    return None


def get_capability(device_model: Optional[str]) -> Optional[HardwareOdometerCapability]:
    if not device_model:
        return None
    return REGISTRY.get(device_model)


# ---------------------------------------------------------------------------
# Normalisation du Total Odometer Teltonika (AVL 16). Scale EXPLICITE + validé.
# ---------------------------------------------------------------------------
def normalize_teltonika_total_odometer(raw_value, mapping: Optional[dict] = None) -> dict:
    """Normalise une valeur brute AVL 16 vers des km, selon un mapping EXPLICITE par tracker.

    mapping (par tracker/sensor) : {raw_unit, multiplier, divider, normalized_unit, scale_status}
    - Ne JAMAIS présumer `raw/1000` : on applique le mapping fourni.
    - Si aucun mapping validé -> scale_status=UNVERIFIED et normalized_value=None.

    Retour : {raw_value, normalized_value, normalized_unit, scale_status, note}
    """
    mapping = mapping or {}
    scale_status = mapping.get("scale_status", SCALE_UNVERIFIED)
    try:
        rv = float(raw_value)
    except (TypeError, ValueError):
        return {"raw_value": raw_value, "normalized_value": None,
                "normalized_unit": mapping.get("normalized_unit", "km"),
                "scale_status": SCALE_UNVERIFIED, "note": "raw non numérique"}

    mult = mapping.get("multiplier")
    div = mapping.get("divider")
    if scale_status == SCALE_VERIFIED and (mult is not None or div is not None):
        val = rv * (float(mult) if mult is not None else 1.0)
        if div:
            val = val / float(div)
        return {"raw_value": rv, "normalized_value": round(val, 3),
                "normalized_unit": mapping.get("normalized_unit", "km"),
                "scale_status": SCALE_VERIFIED, "note": "mapping validé appliqué"}

    # Scale non validé : on ne renvoie PAS de km "faux". On donne un indice non contractuel.
    hint = None
    if rv > 1_000_000:
        hint = round(rv / 1000.0, 3)  # hypothèse m->km, NON contractuelle
    return {"raw_value": rv, "normalized_value": None,
            "normalized_unit": mapping.get("normalized_unit", "km"),
            "scale_status": SCALE_UNVERIFIED,
            "note": (f"scale non validé (hypothèse m->km ~ {hint} km, à confirmer vs tableau de bord)"
                     if hint is not None else "scale non validé")}


# ---------------------------------------------------------------------------
# Capacité PAR TRACEUR/VÉHICULE (V2) — la source/gate se résout par device réel.
# ---------------------------------------------------------------------------
# Valeurs de capacité (legacy conservées pour rétrocompat imports/tests) :
VC_CAN_MILEAGE_VALIDATED = "CAN_MILEAGE_VALIDATED"
VC_TELTONIKA_ODOMETER_VALIDATED = "TELTONIKA_ODOMETER_VALIDATED"
VC_HARDWARE_SOURCE_VALIDATED = "HARDWARE_SOURCE_VALIDATED"
VC_NO_HARDWARE_ODOMETER = "NO_HARDWARE_ODOMETER"
VC_NOT_TESTED = "NOT_TESTED"


@dataclass
class VehicleOdometerCapability:
    """Capacité odomètre privé d'UN traceur/véhicule précis (V2).

    La stratégie cible étant AVL 16 (Total Odometer), on suit explicitement chaque
    étape de validation. La présence de avl_io_16 seule NE suffit PAS.
    """
    vehicle_id: str
    tracker_id: Optional[int] = None
    device_model: Optional[str] = None
    # Source privée résolue pour CE tracker
    private_distance_source: str = "UNKNOWN"     # SOURCE_* (attendu TELTONIKA_TOTAL_ODOMETER)
    raw_avl_id: Optional[int] = None             # 16 attendu, seulement si mapping réel
    navixy_input: Optional[str] = None           # avl_io_16 / hw_mileage
    navixy_sensor_id: Optional[int] = None
    raw_unit: Optional[str] = None
    normalized_unit: str = "km"
    multiplier: Optional[float] = None
    divider: Optional[float] = None
    scale_status: str = SCALE_UNVERIFIED
    last_value_raw: Optional[float] = None
    last_value_km: Optional[float] = None
    last_timestamp: Optional[str] = None
    fresh: Optional[bool] = None
    # Étapes de preuve (chaînées) — toutes requises pour la gate
    runtime_verified: bool = False               # avl_io_16 réellement reçu via l'API
    cumulative_verified: bool = False            # augmente avec la distance (delta>0 en roulant)
    private_increment_verified: bool = False     # continue quand GPS masqué (D3-B)
    field_validated: bool = False                # D3 terrain PASS complet
    capability: str = CAP_NOT_TESTED             # CAP_* (statut lisible)
    # rétro-compat : ancien champ 'source_type'/'unit'/'last_value'/'last_timestamp'
    source_type: str = "UNKNOWN"
    unit: Optional[str] = None
    last_value: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _model_supports_avl16_strategy(model: Optional[str]) -> bool:
    """Seuls FMC003 & FMC130 ont la stratégie AVL 16 (V2). Jamais en dur ailleurs."""
    cap = get_capability(model)
    return bool(cap and cap.strategy == STRATEGY_TELTONIKA_TOTAL_ODOMETER
                and cap.primary_source == SOURCE_TELTONIKA_TOTAL_ODOMETER
                and cap.status != STATUS_DEPRECATED)


def vehicle_private_mode_allowed(model: Optional[str],
                                 vc: Optional[VehicleOdometerCapability]) -> bool:
    """Gate PRODUCTION V2 — par traceur/véhicule. TRUE seulement si TOUTES ces conditions :
      - modèle supporté avec stratégie TELTONIKA_TOTAL_ODOMETER (FMC003/FMC130) ;
      - private_distance_source == TELTONIKA_TOTAL_ODOMETER ;
      - raw_avl_id == 16 (mapping réel) ;
      - runtime_verified ET cumulative_verified ET private_increment_verified ET field_validated.
    La simple présence d'avl_io_16 ne suffit PAS.
    """
    if not vc:
        return False
    if not _model_supports_avl16_strategy(model):
        return False
    if vc.private_distance_source != SOURCE_TELTONIKA_TOTAL_ODOMETER:
        return False
    if vc.raw_avl_id != AVL_TOTAL_ODOMETER:
        return False
    return bool(vc.runtime_verified and vc.cumulative_verified
                and vc.private_increment_verified and vc.field_validated)


def private_mode_allowed(device_model: Optional[str],
                         vehicle_capability=None) -> bool:
    """Gate PRODUCTION niveau MODÈLE (rétrocompat).

    IMPORTANT V2 : la vraie gate est PAR TRACEUR (`vehicle_private_mode_allowed`).
    Au niveau modèle seul, on renvoie TRUE uniquement si le modèle est lui-même
    FIELD-VALIDATED (verified=True + status=VALIDATED) — ce qui reste False par défaut.
    `vehicle_capability` (str legacy) est accepté mais NON suffisant seul.
    """
    cap = get_capability(device_model)
    if not cap or cap.status == STATUS_DEPRECATED:
        return False
    if not (cap.verified and cap.status == STATUS_VALIDATED):
        return False
    # Rétro-compat : si une capacité véhicule (str) est fournie, elle doit être validée.
    if vehicle_capability is not None:
        return vehicle_capability in (
            VC_CAN_MILEAGE_VALIDATED, VC_TELTONIKA_ODOMETER_VALIDATED, VC_HARDWARE_SOURCE_VALIDATED,
        )
    return True


# ---------------------------------------------------------------------------
# Gate production GLOBALE (drapeau métier). Reste DISABLED tant qu'aucun modèle/tracker
# n'est FIELD_VALIDATED end-to-end.
# ---------------------------------------------------------------------------
def private_mode_production_allowed() -> bool:
    """TRUE seulement si au moins un modèle est field-validated ET la gate le confirme.
    Par défaut FALSE (aucun modèle validé). Exigence métier : pas de mode Privé prod
    sans distance privée fiable."""
    for model, cap in REGISTRY.items():
        if cap.verified and cap.status == STATUS_VALIDATED and _model_supports_avl16_strategy(model):
            return True
    return False



# ---------------------------------------------------------------------------
# Capacités PILOTES validées RUNTIME (par tracker) — traçabilité des preuves réelles.
# `field_validated` reste False (D3-B mode Privé non encore prouvé) -> gate = False.
# Ces entrées documentent l'état atteint ; elles n'autorisent PAS le mode privé prod.
# ---------------------------------------------------------------------------
PILOT_VEHICLE_CAPABILITIES: dict[int, VehicleOdometerCapability] = {
    3657864: VehicleOdometerCapability(
        vehicle_id="pilot-3657864", tracker_id=3657864, device_model="FMC003",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER,
        raw_avl_id=AVL_TOTAL_ODOMETER, navixy_input="avl_io_16", navixy_sensor_id=5570680,
        raw_unit="m", normalized_unit="km", multiplier=1.0, divider=1000.0,
        scale_status=SCALE_VERIFIED,
        last_value_km=140264.62, last_timestamp="2026-09-03 14:53:39", fresh=True,
        runtime_verified=True,        # avl_io_16 reçu via l'API ✅
        cumulative_verified=True,     # +5.3 km prouvé en roulant ✅
        private_increment_verified=False,  # D3-B non exécuté
        field_validated=False,        # pas de PASS terrain mode Privé
        capability=CAP_AVL16_CUMULATIVE_VERIFIED,
        source_type=SOURCE_TELTONIKA_TOTAL_ODOMETER, unit="km", last_value=140264.62,
        notes=("Pilote V2. Chaîne AVL16 validée runtime: sensor 'ODO TOTAL' avl_io_16 mult=1 div=1000 "
               "km ; API_READABLE ; +5.3 km en roulage ; 140264.62 ≈ 140268 tableau de bord (Audi, "
               "écart = roulage 14:53->15:00). RESTE D3-B (GPS=0,0 + AVL16 continue) avant prod."),
    ),
}


def get_pilot_capability(tracker_id: Optional[int]) -> Optional[VehicleOdometerCapability]:
    """Capacité pilote runtime pour un tracker (traçabilité). None si non enregistré."""
    if tracker_id is None:
        return None
    return PILOT_VEHICLE_CAPABILITIES.get(int(tracker_id))
