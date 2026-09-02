"""Registre de capacités odomètre/confidentialité par MODÈLE de traceur.

Principe LOGITRAK (multi-modèles) : la STRATÉGIE de kilométrage privé dépend du MODÈLE,
et pour certains modèles (FMC003) du VÉHICULE. Le backend ne code jamais `use_avl_16()`
en dur : il RÉSOUT la stratégie/source via ce registre + une capacité par véhicule.

STRATÉGIES CIBLES (décision métier) :
- FMC003  -> VEHICLE_OBD_CAN_MILEAGE (par VÉHICULE ; fallback TELTONIKA_TOTAL_ODOMETER). Disponibilité VEHICLE_DEPENDENT.
- FMC130  -> TELTONIKA_TOTAL_ODOMETER (traceur fixe ; odomètre interne). Disponibilité DEVICE/CONFIG_DEPENDENT.
- FMU130  -> DEPRECATED (hors scope futur ; parc retiré ~2027). Aucun nouveau dev.
- FMC640  -> HARDWARE_CAN_FMS_TACHO (poids lourd). VEHICLE/CONFIG_DEPENDENT.
- FMC650  -> HARDWARE_CAN_FMS_TACHO (poids lourd). VEHICLE/CONFIG_DEPENDENT.

RÈGLES ABSOLUES :
- Le compteur Navixy GPS-calculé n'est JAMAIS une source de distance privée.
- `verified` = True UNIQUEMENT sur preuve TERRAIN (FIELD_VERIFIED).
- Gate prod : MODEL (+ VEHICLE pour FMC003) + SOURCE VALIDÉE + FIELD_VALIDATED.
- Aucune AVL universelle.

Niveaux de preuve : UNKNOWN < DOCUMENTED < RUNTIME_VERIFIED < FIELD_VERIFIED
(NOT_SUPPORTED = démontré non supporté)
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional

# Niveaux d'évidence
UNKNOWN = "UNKNOWN"
DOCUMENTED = "DOCUMENTED"
RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
FIELD_VERIFIED = "FIELD_VERIFIED"
NOT_SUPPORTED = "NOT_SUPPORTED"

# États modèle (gate production par modèle)
STATUS_NOT_TESTED = "NOT_TESTED"
STATUS_PILOT = "PILOT"
STATUS_VALIDATED = "VALIDATED"        # field-verified end-to-end
STATUS_BLOCKED = "BLOCKED"
STATUS_DEPRECATED = "DEPRECATED"      # hors scope futur (ex FMU130)

# Stratégies cibles par modèle
STRATEGY_TELTONIKA_TOTAL_ODOMETER = "TELTONIKA_TOTAL_ODOMETER"
STRATEGY_VEHICLE_OBD_CAN_MILEAGE = "VEHICLE_OBD_CAN_MILEAGE"
STRATEGY_HARDWARE_CAN_FMS_TACHO = "HARDWARE_CAN_FMS_TACHO"
STRATEGY_DEPRECATED = "DEPRECATED"

# Disponibilité de la stratégie
AVAIL_VEHICLE_DEPENDENT = "VEHICLE_DEPENDENT"
AVAIL_DEVICE_CONFIG_DEPENDENT = "DEVICE_CONFIG_DEPENDENT"
AVAIL_NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class HardwareOdometerCapability:
    device_model: str                       # ex "FMC130" (famille logique)
    navixy_model_code: Optional[str] = None # ex "telfmu130_fmc130" (code Navixy runtime)
    # Stratégie cible (décision métier) + disponibilité
    strategy: str = "UNKNOWN"               # STRATEGY_* ci-dessus
    availability: str = UNKNOWN             # AVAIL_* (VEHICLE_DEPENDENT pour FMC003...)
    # Source odomètre candidate (résolue runtime/field)
    source_type: str = "UNKNOWN"            # TELTONIKA_TOTAL_ODOMETER | VEHICLE_CAN | OBD | TACHOGRAPH | NAVIXY_GPS_CALCULATED | NONE
    raw_avl_id: Optional[int] = None        # JAMAIS imposé sans preuve
    navixy_input: Optional[str] = None      # input_name Navixy si exposé
    unit: Optional[str] = None              # "m" | "km"
    is_cumulative: Optional[bool] = None     # Total (True) vs Trip (False)
    # Confidentialité
    private_business_supported: str = UNKNOWN
    gps_data_masking_supported: str = UNKNOWN
    odometer_during_private: str = UNKNOWN   # l'odomètre HW continue-t-il quand GPS masqué ?
    remote_privatemode_supported: str = UNKNOWN
    navixy_sensor_exposable: str = UNKNOWN
    # Exigences / preuve
    minimum_firmware: Optional[str] = None
    evidence_level: str = UNKNOWN            # niveau de preuve global odomètre HW
    verified: bool = False                   # True UNIQUEMENT si FIELD_VERIFIED
    status: str = STATUS_NOT_TESTED
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Registre initial. Valeurs = DOCUMENTED au mieux (doc Teltonika) ou UNKNOWN.
# AUCUN `verified=True`, AUCUN `raw_avl_id` traité comme prouvé.
# Les colonnes seront enrichies par les audits RUNTIME (D2) puis FIELD (D3).
# ---------------------------------------------------------------------------
REGISTRY: dict[str, HardwareOdometerCapability] = {
    "FMC003": HardwareOdometerCapability(
        device_model="FMC003", navixy_model_code="telfmb003_fmc003",
        strategy=STRATEGY_VEHICLE_OBD_CAN_MILEAGE,   # cible: km véhicule OBD/CAN
        availability=AVAIL_VEHICLE_DEPENDENT,        # dépend du véhicule/ECU/PID -> PAR VÉHICULE
        source_type="UNKNOWN",                       # à résoudre par véhicule
        raw_avl_id=None, unit=None, is_cumulative=None,
        private_business_supported=DOCUMENTED, gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN,
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_NOT_TESTED,
        notes=("STRATÉGIE=VEHICLE_OBD_CAN_MILEAGE (fallback TELTONIKA_TOTAL_ODOMETER). "
               "Capacité VEHICLE_DEPENDENT: valider véhicule par véhicule (voir Fmc003VehicleCapability). "
               "RUNTIME D2 (ex 3079431 Renault Zoe): OBD conso/rpm/vitesse mais AUCUN mileage — "
               "l'absence sur CE véhicule ne prouve pas l'incapacité du modèle. 14 devices au parc."),
    ),
    "FMC130": HardwareOdometerCapability(
        device_model="FMC130", navixy_model_code="telfmu130_fmc130",
        strategy=STRATEGY_TELTONIKA_TOTAL_ODOMETER,  # cible: odomètre INTERNE du traceur (fixe)
        availability=AVAIL_DEVICE_CONFIG_DEPENDENT,
        source_type="UNKNOWN",                       # Total Odometer interne non encore exposé/prouvé
        raw_avl_id=None, navixy_input="can_mileage", unit="km", is_cumulative=None,
        private_business_supported=DOCUMENTED, gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN,
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_NOT_TESTED,
        notes=("STRATÉGIE=TELTONIKA_TOTAL_ODOMETER (traceur fixe). Le compteur Navixy GPS-calculé "
               "N'EST PAS admissible. can_mileage observé (id 5411571, km) mais DONNÉE PÉRIMÉE 2022 "
               "-> source secondaire/comparaison seulement, NON architecture cible. "
               "À AUDITER (READ-ONLY): le Total Odometer INTERNE du FMC130 est-il transmis à Navixy, "
               "et continue-t-il en Private Mode ? (mission 'FMC130 TOTAL ODOMETER AUDIT')."),
    ),
    "FMU130": HardwareOdometerCapability(
        device_model="FMU130", navixy_model_code="telfmu130",
        strategy=STRATEGY_DEPRECATED, availability=AVAIL_NOT_APPLICABLE,
        source_type="NAVIXY_GPS_CALCULATED",
        raw_avl_id=None, navixy_input=None, unit="km", is_cumulative=True,
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=NOT_SUPPORTED, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=NOT_SUPPORTED,
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_DEPRECATED,
        notes=("DÉCISION MÉTIER: FMU130 DEPRECATED pour le Private Mode LOGITRAK (parc retiré ~2027). "
               "PRIVATE_MODE_ROLLOUT=NO, FURTHER_VALIDATION=NOT_REQUIRED. Historique D1/D2 conservé: "
               "tracker 625282, odomètre = GPS-calculé, aucune source HW. Aucun nouveau dev spécifique."),
    ),
    "FMC640": HardwareOdometerCapability(
        device_model="FMC640",
        strategy=STRATEGY_HARDWARE_CAN_FMS_TACHO, availability=AVAIL_VEHICLE_DEPENDENT,
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status="NOT_PRESENT",
        notes=("STRATÉGIE=HARDWARE_CAN_FMS_TACHO (poids lourd). Sources à déterminer runtime: "
               "CAN/FMS/Tachograph/Total Odometer. Ne PAS imposer AVL16 (famille FMX6xx). "
               "RUNTIME D2: ABSENT des 3 comptes Navixy réels."),
    ),
    "FMC650": HardwareOdometerCapability(
        device_model="FMC650",
        strategy=STRATEGY_HARDWARE_CAN_FMS_TACHO, availability=AVAIL_VEHICLE_DEPENDENT,
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status="NOT_PRESENT",
        notes=("STRATÉGIE=HARDWARE_CAN_FMS_TACHO (poids lourd). Doc (À VÉRIFIER si présent un jour): "
               "AVL199=Trip, AVL216=Total, AVL192=Tachograph — non 'verified'. "
               "RUNTIME D2: ABSENT des 3 comptes Navixy réels."),
    ),
}

# Mapping code Navixy -> modèle logique.
# ⚠️ Piège de nommage confirmé runtime : le code peut contenir 'telfmu130' ET un suffixe
# '_fmc130' → c'est alors un FMC130 (pas un FMU130). On teste donc les suffixes explicites
# AVANT le préfixe telfmu130 seul.
NAVIXY_MODEL_RULES = [
    ("_fmc003", "FMC003"),   # ex 'telfmb003_fmc003'
    ("_fmc130", "FMC130"),   # ex 'telfmu130_fmc130'  (FMC130 !)
    ("_fmc640", "FMC640"),
    ("_fmc650", "FMC650"),
    ("telfmc003", "FMC003"),
    ("telfmc130", "FMC130"),
    ("telfmc640", "FMC640"),
    ("telfmc650", "FMC650"),
    ("telfmu130", "FMU130"),  # FMU130 pur (aucun suffixe _fmcXXX)
]


def resolve_model(navixy_model_code: Optional[str]) -> Optional[str]:
    """Résout le modèle logique depuis le code Navixy.
    ex 'telfmu130' -> FMU130 ; 'telfmu130_fmc130' -> FMC130 ; 'telfmb003_fmc003' -> FMC003.
    Retourne None si inconnu — le backend traitera alors la capacité comme UNVERIFIED."""
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


def private_mode_allowed(device_model: Optional[str],
                         vehicle_capability: Optional[str] = None) -> bool:
    """Gate PRODUCTION. Le mode Privé n'est activable QUE si :
      - le MODÈLE est FIELD-VALIDATED (verified=True + status=VALIDATED), ET
      - pour un modèle VEHICLE_DEPENDENT (ex FMC003), la CAPACITÉ DU VÉHICULE est validée
        (vehicle_capability ∈ {CAN_MILEAGE_VALIDATED, TELTONIKA_ODOMETER_VALIDATED,
         HARDWARE_SOURCE_VALIDATED}).
    Un modèle DEPRECATED (FMU130) renvoie toujours False.
    """
    cap = get_capability(device_model)
    if not cap or cap.status == STATUS_DEPRECATED:
        return False
    if not (cap.verified and cap.status == STATUS_VALIDATED):
        return False
    if cap.availability == AVAIL_VEHICLE_DEPENDENT:
        return vehicle_capability in (
            "CAN_MILEAGE_VALIDATED", "TELTONIKA_ODOMETER_VALIDATED", "HARDWARE_SOURCE_VALIDATED",
        )
    return True


# ---------------------------------------------------------------------------
# Capacité PAR VÉHICULE (indispensable pour FMC003 : la source dépend du véhicule/ECU/PID).
# ---------------------------------------------------------------------------
# Valeurs de capacité véhicule (FMC003 & autres modèles VEHICLE_DEPENDENT) :
VC_CAN_MILEAGE_VALIDATED = "CAN_MILEAGE_VALIDATED"
VC_TELTONIKA_ODOMETER_VALIDATED = "TELTONIKA_ODOMETER_VALIDATED"
VC_HARDWARE_SOURCE_VALIDATED = "HARDWARE_SOURCE_VALIDATED"
VC_NO_HARDWARE_ODOMETER = "NO_HARDWARE_ODOMETER"
VC_NOT_TESTED = "NOT_TESTED"


@dataclass
class VehicleOdometerCapability:
    """Capacité odomètre privé d'UN véhicule précis (clé: vehicle_id ou tracker_id).
    Utilisée surtout pour FMC003 (source dépendante du véhicule)."""
    vehicle_id: str
    tracker_id: Optional[int] = None
    device_model: Optional[str] = None
    capability: str = VC_NOT_TESTED          # VC_* ci-dessus
    source_type: str = "UNKNOWN"             # VEHICLE_CAN | TELTONIKA_TOTAL_ODOMETER | ...
    navixy_input: Optional[str] = None
    unit: Optional[str] = None
    last_value: Optional[float] = None
    last_timestamp: Optional[str] = None
    fresh: Optional[bool] = None
    field_validated: bool = False            # True uniquement après D3 terrain PASS
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def vehicle_private_mode_allowed(model: Optional[str], vc: Optional[VehicleOdometerCapability]) -> bool:
    """Gate finale pour un tracker/véhicule concret (résout modèle + véhicule)."""
    if not vc or not vc.field_validated:
        return False
    return private_mode_allowed(model, vehicle_capability=vc.capability)

