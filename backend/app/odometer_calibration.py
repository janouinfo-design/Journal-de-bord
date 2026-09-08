"""Calibration du kilométrage réel (baseline AVL16) à partir du compteur tableau de bord.

OBJECTIF PRODUIT
----------------
Permettre à un administrateur de fixer la BASELINE absolue du Total Odometer Teltonika
(AVL ID 16, exposé Navixy en `avl_io_16`) à partir du kilométrage RÉEL relevé sur le
tableau de bord du véhicule. Après calibration, l'AVL16 devient la référence de calcul
des Km Pro / Km Privé (delta = AVL16_after - AVL16_before).

CONTRAT TELTONIKA (vérifié — jamais supposé)
--------------------------------------------
- Paramètre 11807 = "Odometer Value" ; unité = KILOMÈTRES (entier) ; plage 0..4 294 967
  (source : FMC130 Configurator + wiki Teltonika Parameter list).
- Le device retransmet ensuite l'AVL16 en MÈTRES ; Navixy le normalise (÷1000) en km.
  => On ENVOIE des km entiers au device ; on VÉRIFIE en km normalisés côté Navixy.
- Commande brute : `setparam 11807:<km>` (famille SMS/GPRS). Alternative documentée :
  `odoset:<km>`. La commande EFFECTIVE reste à confirmer au test terrain (D_calibration).

GARDE-FOUS ABSOLUS
------------------
- Verrou DÉDIÉ `ODOMETER_CALIBRATION_DEVICE_WRITE` (défaut 0/false). Découplé du Mode Privé.
  Tant qu'il est off -> AUCUNE commande device ne peut partir (fail-fast, aucune écriture).
- Jamais de secret lu/loggé. Multi-tenant strict. RBAC (admin/superadmin) au niveau route.
- CALIBRATION_EVENT : le SAUT de baseline (ex 56 378 -> 139 620 km) n'est JAMAIS compté
  comme distance parcourue. Toute distance qui TRAVERSE une calibration = indisponible
  (jamais le saut). Les deltas Pro/Privé reprennent après la nouvelle baseline confirmée.
- Confirmation RÉELLE : commande envoyée != calibration réussie. `odometer_calibrated=True`
  seulement après relecture AVL16 cohérente avec la valeur demandée (tolérance bornée).
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from app.odometer_capability import (
    resolve_model, get_capability, STRATEGY_TELTONIKA_TOTAL_ODOMETER,
    SOURCE_TELTONIKA_TOTAL_ODOMETER, AVL_TOTAL_ODOMETER, STATUS_DEPRECATED,
)

logger = logging.getLogger(__name__)

# --- Contrat paramètre Teltonika 11807 (km entier) ---
TELTONIKA_ODOMETER_PARAM_ID = 11807
PARAM_MIN_KM = 0
PARAM_MAX_KM = 4_294_967           # borne Teltonika (Configurator)
CONFIRM_TOLERANCE_KM = 1.0         # écart max toléré entre valeur demandée et AVL16 relu

# --- Source de distance (profil AVL16 validé) ---
SOURCE_TELTONIKA_AVL16 = "TELTONIKA_AVL16"

# --- Marqueur d'évènement de calibration (rupture de baseline) ---
CALIBRATION_EVENT = "CALIBRATION_EVENT"
CALIBRATION_SOURCE_MANUAL = "MANUAL_DASHBOARD_READING"

# --- Résultats de calibration ---
CALIB_CONFIRMED = "CONFIRMED"
CALIB_PENDING = "PENDING"          # commande envoyée, confirmation AVL16 pas encore prouvée
CALIB_FAILED = "FAILED"            # incohérence / pas de trame AVL16 cohérente
CALIB_REFUSED = "REFUSED"          # gate/validation

# --- Raisons de refus normalisées (exposables au frontend, non sensibles) ---
R_DEVICE_WRITE_DISABLED = "ODOMETER_CALIBRATION_DEVICE_WRITE_DISABLED"
R_NOT_SUPPORTED = "ODOMETER_CALIBRATION_NOT_SUPPORTED"     # modèle non AVL16
R_NO_VEHICLE = "ODOMETER_CALIBRATION_NO_VEHICLE"
R_NO_TRACKER = "ODOMETER_CALIBRATION_NO_TRACKER"
R_INVALID_VALUE = "ODOMETER_CALIBRATION_INVALID_VALUE"
R_DEVICE_OFFLINE = "ODOMETER_CALIBRATION_DEVICE_OFFLINE"
R_NOT_CONFIRMED = "ODOMETER_CALIBRATION_NOT_CONFIRMED"

HTTP_BY_REASON = {
    R_DEVICE_WRITE_DISABLED: 503,
    R_NOT_SUPPORTED: 409,
    R_NO_VEHICLE: 404,
    R_NO_TRACKER: 409,
    R_INVALID_VALUE: 400,
    R_DEVICE_OFFLINE: 409,
    R_NOT_CONFIRMED: 202,
}

# Seuil d'alerte d'écart (UI double-confirmation). N'empêche pas, prévient.
LARGE_DELTA_WARN_KM = 1000.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Verrou DÉDIÉ (découplé du Mode Privé). Défaut FALSE (fail-closed).
# ---------------------------------------------------------------------------
def calibration_device_write_enabled() -> bool:
    """L'envoi RÉEL de la commande de calibration est-il autorisé ?
    Verrou dédié `ODOMETER_CALIBRATION_DEVICE_WRITE` (défaut 0). JAMAIS couplé au Mode Privé."""
    return os.environ.get("ODOMETER_CALIBRATION_DEVICE_WRITE", "0").strip().lower() in (
        "1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Validation de la valeur saisie (km entier strict — pas de troncature silencieuse).
# ---------------------------------------------------------------------------
def validate_dashboard_km(value) -> tuple[Optional[int], Optional[str]]:
    """Valide un kilométrage tableau de bord : ENTIER, dans [0, PARAM_MAX_KM].

    Retour (km_int|None, error|None). Refuse explicitement les décimales (jamais tronqué).
    """
    if value is None:
        return None, "Valeur requise"
    # bool est un int en Python -> refuser explicitement
    if isinstance(value, bool):
        return None, "Valeur invalide"
    # float décimal -> refus (pas de troncature)
    if isinstance(value, float):
        if not value.is_integer():
            return None, "Saisir un kilométrage ENTIER (sans décimale)"
        value = int(value)
    if isinstance(value, str):
        s = value.strip().replace(" ", "").replace("'", "")
        if s == "" or not s.lstrip("+").isdigit():
            # rejette "139620.8", "abc", "" ...
            return None, "Saisir un kilométrage ENTIER (sans décimale)"
        value = int(s)
    if not isinstance(value, int):
        return None, "Valeur invalide"
    if value < PARAM_MIN_KM or value > PARAM_MAX_KM:
        return None, f"Kilométrage hors plage (0 .. {PARAM_MAX_KM} km)"
    return value, None


# ---------------------------------------------------------------------------
# Construction de la commande device (GATED — non envoyée si write off).
# ---------------------------------------------------------------------------
def build_calibration_command(dashboard_km: int, style: str = "setparam") -> str:
    """Commande brute Teltonika pour fixer l'odomètre (km entier).

    style="setparam" -> "setparam 11807:<km>"  (défaut)
    style="odoset"   -> "odoset:<km>"           (alternative documentée)
    La commande EFFECTIVE est à confirmer au test terrain (D_calibration).
    """
    km = int(dashboard_km)
    if style == "odoset":
        return f"odoset:{km}"
    return f"setparam {TELTONIKA_ODOMETER_PARAM_ID}:{km}"


def _model_supports_calibration(model: Optional[str]) -> bool:
    """Seuls les modèles à stratégie AVL16 (FMC003/FMC130, non dépréciés) sont calibrables."""
    cap = get_capability(model)
    return bool(cap and cap.strategy == STRATEGY_TELTONIKA_TOTAL_ODOMETER
                and cap.primary_source == SOURCE_TELTONIKA_TOTAL_ODOMETER
                and cap.status != STATUS_DEPRECATED)


# ---------------------------------------------------------------------------
# Hooks device/AVL16 — INJECTABLES (mock par défaut, aucun appel réseau).
# ---------------------------------------------------------------------------
async def _default_send_command(tracker_id: int, command: str) -> dict:
    """Envoi de la commande de calibration. GATED par ODOMETER_CALIBRATION_DEVICE_WRITE.
    Si write off -> SIMULATION (aucun appel Navixy)."""
    if not calibration_device_write_enabled():
        return {"applied": False, "mode": "SIMULATION", "command": command}
    from app.navixy_client import send_raw_command, is_configured
    if not is_configured():
        return {"applied": False, "mode": "REAL", "error": "navixy_not_configured"}
    resp = await send_raw_command(int(tracker_id), command, reliable=True)
    return {"applied": True, "mode": "REAL", "command": command,
            "navixy_command_id": resp.get("command_id")}


async def _default_read_avl16_km(tracker_id: int) -> Optional[float]:
    """Lecture READ-ONLY de l'AVL16 normalisé (km) via le sensor avl_io_16.
    Par défaut None (jamais inventé). Injecté dans les tests / au test terrain."""
    return None


# ---------------------------------------------------------------------------
# Persistance : historique append-only + baseline de capability.
# ---------------------------------------------------------------------------
async def _record_calibration_event(db, doc: dict) -> str:
    """Ajoute (append-only) un CALIBRATION_EVENT à l'historique. Ne JAMAIS écraser."""
    import uuid
    doc = {"id": str(uuid.uuid4()), "type": CALIBRATION_EVENT, "created_at": _now(), **doc}
    await db.odometer_calibrations.insert_one(doc)
    return doc["id"]


async def _update_capability_baseline(db, *, tracker_id: int, vehicle_id: str,
                                      device_model: Optional[str], sensor_id: Optional[int],
                                      avl16_after_km: Optional[float], calibrated_at: str,
                                      confirmed: bool) -> None:
    """Met à jour (upsert par tracker_id) la source/baseline AVL16 de la capability.
    Ne fixe JAMAIS field_validated (réservé au D3 terrain). Enregistre la source explicite.
    """
    patch = {
        "tracker_id": int(tracker_id),
        "vehicle_id": vehicle_id,
        "device_model": device_model,
        "private_distance_source": SOURCE_TELTONIKA_AVL16,  # source explicite (jamais odomètre Navixy)
        "raw_avl_id": AVL_TOTAL_ODOMETER,
        "navixy_input": "avl_io_16",
        "navixy_sensor_id": sensor_id,
        "multiplier": 1.0,
        "divider": 1000.0,
        "normalized_unit": "km",
        "odometer_calibrated": bool(confirmed),
        "calibration_source": CALIBRATION_SOURCE_MANUAL,
        "calibration_baseline_km": avl16_after_km if confirmed else None,
        "calibration_at": calibrated_at if confirmed else None,
        "updated_at": _now(),
    }
    await db.vehicle_private_capabilities.update_one(
        {"tracker_id": int(tracker_id)}, {"$set": patch}, upsert=True)


async def _audit(db, payload: dict) -> None:
    await db.audit_log.insert_one({"ts": _now(), "scope": "odometer_calibration", **payload})


# ---------------------------------------------------------------------------
# ANTI-FAUX-DELTA — cœur de la protection (§15).
# ---------------------------------------------------------------------------
async def crosses_calibration(db, vehicle_id: str, t0: Optional[str], t1: Optional[str]) -> bool:
    """True si un CALIBRATION_EVENT confirmé existe dans l'intervalle ]t0, t1].
    Utilisé pour NE JAMAIS calculer une distance qui traverse une calibration."""
    if not vehicle_id or not t0 or not t1:
        return False
    n = await db.odometer_calibrations.count_documents({
        "vehicle_id": vehicle_id, "result": CALIB_CONFIRMED,
        "calibrated_at": {"$gt": t0, "$lte": t1},
    })
    return n > 0


def safe_avl16_delta_km(before_km, after_km, *, crosses: bool) -> Optional[float]:
    """Delta AVL16 SÛR (km). Retourne None (indisponible) si :
      - une calibration traverse l'intervalle (crosses=True) -> jamais le saut ;
      - valeurs non numériques ;
      - régression (after < before) -> anomalie, jamais inventée.
    """
    if crosses:
        return None
    try:
        b = float(before_km)
        a = float(after_km)
    except (TypeError, ValueError):
        return None
    if a < b:
        return None
    return round(a - b, 3)


# ---------------------------------------------------------------------------
# CŒUR : calibrate_vehicle_odometer (backend autoritaire, gate, confirmation).
# ---------------------------------------------------------------------------
async def calibrate_vehicle_odometer(
    db, *, tenant_id: str, vehicle_id: str, dashboard_km, actor: str,
    command_style: str = "setparam",
    send_command: Callable[[int, str], Awaitable[dict]] = _default_send_command,
    read_avl16_km: Callable[[int], Awaitable[Optional[float]]] = _default_read_avl16_km,
    device_online: Optional[bool] = None,
) -> dict:
    """Calibre la baseline AVL16 d'un véhicule à partir du km tableau de bord.

    Étapes : résolution véhicule/tenant -> capability AVL16 -> validation valeur ->
    lecture AVL16 avant -> gate write (fail-fast si off) -> commande -> confirmation
    (relecture AVL16 cohérente) -> CALIBRATION_EVENT + baseline (append-only).

    Retour : {ok, result, reason?, http?, requested_dashboard_km, avl16_before_km,
              avl16_after_km, difference_km, odometer_calibrated, event_id?, ...}
    Aucune position exposée. Aucun secret. Multi-tenant strict.
    """
    tid = tenant_id or "default"

    # 1) Véhicule (tenant scopé)
    vehicle = await db.vehicles.find_one({"id": vehicle_id, "tenant_id": tid}, {"_id": 0})
    if not vehicle:
        return {"ok": False, "result": CALIB_REFUSED, "reason": R_NO_VEHICLE,
                "http": HTTP_BY_REASON[R_NO_VEHICLE]}

    tracker_id = vehicle.get("navixy_tracker_id")
    if not tracker_id:
        return {"ok": False, "result": CALIB_REFUSED, "reason": R_NO_TRACKER,
                "http": HTTP_BY_REASON[R_NO_TRACKER], "vehicle_id": vehicle_id}

    model = resolve_model(vehicle.get("model"))
    if not _model_supports_calibration(model):
        return {"ok": False, "result": CALIB_REFUSED, "reason": R_NOT_SUPPORTED,
                "http": HTTP_BY_REASON[R_NOT_SUPPORTED], "vehicle_id": vehicle_id,
                "tracker_id": tracker_id, "device_model": model}

    # 2) Validation valeur (entier strict)
    km, err = validate_dashboard_km(dashboard_km)
    if err:
        return {"ok": False, "result": CALIB_REFUSED, "reason": R_INVALID_VALUE,
                "http": HTTP_BY_REASON[R_INVALID_VALUE], "detail": err,
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    # 3) Lecture AVL16 AVANT (READ-ONLY)
    avl16_before = await read_avl16_km(int(tracker_id))

    # 3b) Device online requis (si l'info est fournie)
    if device_online is False:
        return {"ok": False, "result": CALIB_REFUSED, "reason": R_DEVICE_OFFLINE,
                "http": HTTP_BY_REASON[R_DEVICE_OFFLINE], "vehicle_id": vehicle_id,
                "tracker_id": tracker_id, "avl16_before_km": avl16_before}

    large_delta = None
    if avl16_before is not None:
        large_delta = abs(km - float(avl16_before)) >= LARGE_DELTA_WARN_KM

    # 4) GATE d'écriture device (FAIL-FAST si off) — AUCUNE commande, aucun event.
    if not calibration_device_write_enabled():
        await _audit(db, {"actor": actor, "vehicle_id": vehicle_id, "tracker_id": tracker_id,
                          "tenant_id": tid, "requested_dashboard_km": km,
                          "avl16_before_km": avl16_before, "result": "refused",
                          "reason": R_DEVICE_WRITE_DISABLED})
        return {"ok": False, "result": CALIB_REFUSED, "reason": R_DEVICE_WRITE_DISABLED,
                "http": HTTP_BY_REASON[R_DEVICE_WRITE_DISABLED], "vehicle_id": vehicle_id,
                "tracker_id": tracker_id, "requested_dashboard_km": km,
                "avl16_before_km": avl16_before, "odometer_calibrated": False,
                "large_delta_warning": large_delta}

    # 5) Envoi commande (GATED — n'arrive ici que si write ON)
    command = build_calibration_command(km, style=command_style)
    cmd_res = await send_command(int(tracker_id), command)

    # 6) Confirmation RÉELLE : relecture AVL16 cohérente (jamais "command accepted" seul)
    avl16_after = await read_avl16_km(int(tracker_id))
    difference = None
    confirmed = False
    if avl16_after is not None:
        try:
            difference = round(float(avl16_after) - float(km), 3)
            confirmed = abs(difference) <= CONFIRM_TOLERANCE_KM
        except (TypeError, ValueError):
            difference = None
            confirmed = False

    result = CALIB_CONFIRMED if confirmed else (
        CALIB_PENDING if avl16_after is None else CALIB_FAILED)
    calibrated_at = _now()

    # 7) Historique append-only (TOUJOURS tracé, même non confirmé) — jamais écrasé
    event_id = await _record_calibration_event(db, {
        "tenant_id": tid, "vehicle_id": vehicle_id, "tracker_id": tracker_id,
        "device_model": model, "requested_dashboard_km": km,
        "avl16_before_km": avl16_before, "avl16_after_km": avl16_after,
        "difference_km": difference, "result": result,
        "odometer_calibrated": confirmed, "calibration_source": CALIBRATION_SOURCE_MANUAL,
        "calibrated_by": actor, "calibrated_at": calibrated_at,
        "command": command, "command_mode": cmd_res.get("mode"),
        "navixy_command_id": cmd_res.get("navixy_command_id"),
    })

    # 8) Baseline de capability (source explicite AVL16) — uniquement si confirmé
    sensor_id = None
    cap_doc = await db.vehicle_private_capabilities.find_one(
        {"tracker_id": int(tracker_id)}, {"_id": 0, "navixy_sensor_id": 1})
    if cap_doc:
        sensor_id = cap_doc.get("navixy_sensor_id")
    await _update_capability_baseline(
        db, tracker_id=int(tracker_id), vehicle_id=vehicle_id, device_model=model,
        sensor_id=sensor_id, avl16_after_km=avl16_after, calibrated_at=calibrated_at,
        confirmed=confirmed)

    await _audit(db, {"actor": actor, "vehicle_id": vehicle_id, "tracker_id": tracker_id,
                      "tenant_id": tid, "requested_dashboard_km": km,
                      "avl16_before_km": avl16_before, "avl16_after_km": avl16_after,
                      "difference_km": difference, "result": result,
                      "odometer_calibrated": confirmed, "event_id": event_id,
                      "command_mode": cmd_res.get("mode")})

    out = {
        "ok": bool(confirmed),
        "result": result,
        "vehicle_id": vehicle_id, "tracker_id": tracker_id, "device_model": model,
        "requested_dashboard_km": km,
        "avl16_before_km": avl16_before,
        "avl16_after_km": avl16_after,
        "difference_km": difference,
        "odometer_calibrated": confirmed,
        "calibration_source": CALIBRATION_SOURCE_MANUAL,
        "calibrated_at": calibrated_at,
        "event_id": event_id,
        "large_delta_warning": large_delta,
    }
    if not confirmed:
        out["reason"] = R_NOT_CONFIRMED
    return out


async def list_calibrations(db, *, tenant_id: str, vehicle_id: str, limit: int = 50) -> list[dict]:
    """Historique des calibrations d'un véhicule (append-only), le plus récent d'abord.
    Aucun secret. Tenant scopé."""
    rows = await db.odometer_calibrations.find(
        {"tenant_id": tenant_id or "default", "vehicle_id": vehicle_id}, {"_id": 0}
    ).sort("calibrated_at", -1).to_list(int(limit))
    return rows
