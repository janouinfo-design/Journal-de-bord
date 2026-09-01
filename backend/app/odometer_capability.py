"""Registre de capacités odomètre/confidentialité par MODÈLE de traceur.

Principe LOGITRAK (multi-modèles) : la capacité « Private/Business + odomètre qui
continue en mode privé » dépend de **MODÈLE + FIRMWARE + CONFIGURATION**, JAMAIS de la
marque « Teltonika » globale. Le backend ne doit jamais coder `use_avl_16()` en dur :
il RÉSOUT la capacité via ce registre.

RÈGLE ABSOLUE :
- `verified` ne peut être `True` que sur preuve TERRAIN (FIELD_VERIFIED), jamais à partir
  de la documentation seule.
- Tant qu'un modèle n'est pas VALIDATED (field), `private_mode_capability = UNVERIFIED`
  et le bouton Privé NE DOIT PAS être activé en production pour ce modèle.

Niveaux de preuve (du plus faible au plus fort) :
  UNKNOWN < DOCUMENTED < RUNTIME_VERIFIED < FIELD_VERIFIED
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


@dataclass
class HardwareOdometerCapability:
    device_model: str                       # ex "FMU130" (famille logique)
    navixy_model_code: Optional[str] = None # ex "telfmu130" (code Navixy runtime)
    # Odomètre matériel candidat
    source_type: str = "UNKNOWN"            # TELTONIKA_TOTAL_ODOMETER | VEHICLE_CAN | OBD | TACHOGRAPH | NAVIXY_GPS_CALCULATED | NONE
    raw_avl_id: Optional[int] = None        # ex 16 / 199 / 216 / 192 — JAMAIS imposé sans preuve
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
        source_type="NAVIXY_GPS_CALCULATED",  # RUNTIME D2: aucun mileage HW exposé
        raw_avl_id=None, unit="km", is_cumulative=True,
        private_business_supported=DOCUMENTED,   # doc: Private/Business + GPS masking
        gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN,
        remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=NOT_SUPPORTED,   # RUNTIME D2: OBD présent, PAS de can_mileage/odo HW
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_NOT_TESTED,
        notes=("RUNTIME D2 (ex tracker 3079431, Renault Zoe): counters=odometer(GPS)+engine_hours; "
               "sensors OBD (conso/rpm/vitesse) mais AUCUN can_mileage/odo HW. 14 devices au parc. "
               "Doc: Odometer GNSS/OBD; à confirmer Configurator si un Total Odometer HW est activable."),
    ),
    "FMC130": HardwareOdometerCapability(
        device_model="FMC130", navixy_model_code="telfmu130_fmc130",
        source_type="VEHICLE_CAN",              # RUNTIME D2: can_mileage exposé !
        raw_avl_id=None, navixy_input="can_mileage", unit=None, is_cumulative=None,
        private_business_supported=DOCUMENTED, gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN,        # à prouver terrain (D3): CAN continue si GPS masqué
        remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=RUNTIME_VERIFIED,  # can_mileage réellement présent
        evidence_level=RUNTIME_VERIFIED, verified=False, status=STATUS_NOT_TESTED,
        notes=("RUNTIME D2 (ex tracker 781479, LOGITRAK AUDI, code telfmu130_fmc130 = FMC130): "
               "sensors incluent can_mileage + can_consumption + avl_io_463 + ble_beacon_id. "
               "-> OPTION B (CAN mileage) CANDIDATE VIABLE : source HW indépendante du GPS. "
               "11 devices au parc. Reste à prouver terrain que can_mileage continue en Private Mode."),
    ),
    "FMU130": HardwareOdometerCapability(
        device_model="FMU130", navixy_model_code="telfmu130",
        source_type="NAVIXY_GPS_CALCULATED",   # RUNTIME D1: seul compteur = GPS-calculé
        raw_avl_id=None, navixy_input=None, unit="km", is_cumulative=True,
        private_business_supported=UNKNOWN,     # config device non lisible via API Navixy
        gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN,
        remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=NOT_SUPPORTED,  # RUNTIME D1/D2: aucun sensor mileage HW exposé
        evidence_level=RUNTIME_VERIFIED,
        verified=False, status=STATUS_PILOT,
        notes=("D1/D2 runtime (tracker 625282, GE-898 507): odomètre Navixy = GPS-calculé; "
               "OBD présent SANS PID mileage; pas de can_mileage/odo HW; engine_hours absent. "
               "-> pas de source HW exposée; OPTION B indisponible sur ce device tel que configuré."),
    ),
    "FMC640": HardwareOdometerCapability(
        device_model="FMC640",
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status="NOT_PRESENT",
        notes="RUNTIME D2: ABSENT des 3 comptes Navixy réels. Famille FMX6xx: ne PAS imposer AVL16.",
    ),
    "FMC650": HardwareOdometerCapability(
        device_model="FMC650",
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status="NOT_PRESENT",
        notes=("RUNTIME D2: ABSENT des 3 comptes Navixy réels. Famille FMX6xx. "
               "Doc (À VÉRIFIER si un jour présent): AVL199=Trip, AVL216=Total, AVL192=Tachograph. Non 'verified'."),
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


def private_mode_allowed(device_model: Optional[str]) -> bool:
    """Gate PRODUCTION par modèle : le mode Privé n'est activable QUE si le modèle est
    FIELD-VALIDATED (verified=True + status=VALIDATED). Sinon: interdit (UNVERIFIED)."""
    cap = get_capability(device_model)
    return bool(cap and cap.verified and cap.status == STATUS_VALIDATED)
