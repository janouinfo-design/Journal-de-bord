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
        device_model="FMC003", navixy_model_code=None,
        source_type="UNKNOWN", raw_avl_id=None, unit=None, is_cumulative=None,
        private_business_supported=DOCUMENTED,   # doc: Private/Business + GPS masking
        gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN,
        remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN,
        evidence_level=UNKNOWN, verified=False, status=STATUS_NOT_TESTED,
        notes="Doc: Odometer source GNSS/OBD; distance privée incluable au Total Odometer. À confirmer firmware/config réels.",
    ),
    "FMC130": HardwareOdometerCapability(
        device_model="FMC130",
        private_business_supported=DOCUMENTED, gps_data_masking_supported=DOCUMENTED,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status=STATUS_NOT_TESTED,
        notes="Total vs Trip Odometer à auditer séparément. Ne pas assimiler à FMU130.",
    ),
    "FMU130": HardwareOdometerCapability(
        device_model="FMU130", navixy_model_code="telfmu130",
        source_type="NAVIXY_GPS_CALCULATED",   # RUNTIME D1: seul compteur = GPS-calculé
        raw_avl_id=None, navixy_input=None, unit="km", is_cumulative=True,
        private_business_supported=UNKNOWN,     # config device non lisible via API Navixy
        gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN,
        remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=NOT_SUPPORTED,  # RUNTIME D1: aucun sensor mileage HW exposé
        evidence_level=RUNTIME_VERIFIED,        # pour le CONSTAT "pas de mileage HW exposé"
        verified=False, status=STATUS_PILOT,
        notes=("D1 runtime (tracker 625282, GE-898 507): odomètre Navixy = GPS-calculé; "
               "OBD présent (conso/rpm/vitesse) SANS PID mileage; engine_hours absent; "
               "pas de can_mileage/obd_mileage/total_odometer exposé. Total Odometer INTERNE "
               "Teltonika non lisible via API Navixy (nécessite Configurator)."),
    ),
    "FMC640": HardwareOdometerCapability(
        device_model="FMC640",
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status=STATUS_NOT_TESTED,
        notes="Famille FMX6xx: AVL IDs potentiellement différents (Trip/Total/Tachograph). Ne PAS imposer AVL16.",
    ),
    "FMC650": HardwareOdometerCapability(
        device_model="FMC650",
        private_business_supported=UNKNOWN, gps_data_masking_supported=UNKNOWN,
        odometer_during_private=UNKNOWN, remote_privatemode_supported=UNKNOWN,
        navixy_sensor_exposable=UNKNOWN, evidence_level=UNKNOWN, verified=False,
        status=STATUS_NOT_TESTED,
        notes=("Famille FMX6xx. Doc (À VÉRIFIER runtime/field): AVL199=Trip Odometer, "
               "AVL216=Total Odometer, AVL192=Tachograph total vehicle distance. "
               "Aucune de ces valeurs n'est 'verified' tant que non prouvée sur device réel."),
    ),
}

# Mapping code Navixy -> modèle logique (préfixes ; complété au fil des audits runtime).
NAVIXY_MODEL_PREFIX = {
    "telfmc003": "FMC003",
    "telfmc130": "FMC130",
    "telfmu130": "FMU130",
    "telfmc640": "FMC640",
    "telfmc650": "FMC650",
}


def resolve_model(navixy_model_code: Optional[str]) -> Optional[str]:
    """Résout le modèle logique depuis le code Navixy (ex 'telfmu130' -> 'FMU130').
    Retourne None si inconnu — le backend traitera alors la capacité comme UNVERIFIED."""
    if not navixy_model_code:
        return None
    code = str(navixy_model_code).lower()
    for prefix, model in NAVIXY_MODEL_PREFIX.items():
        if code.startswith(prefix):
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
