"""Routes — Calibration du kilométrage réel (baseline AVL16) depuis le tableau de bord.

Sécurité :
- RBAC : admin + superadmin UNIQUEMENT (require_roles("admin") -> superadmin passe aussi).
  Manager / driver / lecture_seule -> 403. Opération exceptionnelle (baseline télématique).
- Multi-tenant strict : le tenant vient du contexte serveur (jamais du frontend).
- Verrou device DÉDIÉ ODOMETER_CALIBRATION_DEVICE_WRITE (défaut 0) -> fail-fast si off.
- Aucun secret exposé. Aucune position exposée.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import require_roles
from app.db import get_db
from app import odometer_calibration as oc

router = APIRouter(tags=["odometer-calibration"])


def _tenant_of(user) -> str:
    return user.get("tenant_id") or "default"


@router.get("/vehicles/{vehicle_id}/odometer")
async def get_vehicle_odometer_state(vehicle_id: str, user=Depends(require_roles("admin"))):
    """État odomètre télématique d'un véhicule + historique de calibration (READ-ONLY).

    Retour : {vehicle, telematics_km, source, last_update, capability, can_calibrate,
              device_write_enabled, calibrations:[...]}.
    """
    db = get_db()
    tenant_id = _tenant_of(user)
    vehicle = await db.vehicles.find_one({"id": vehicle_id, "tenant_id": tenant_id}, {"_id": 0})
    if not vehicle:
        raise HTTPException(404, "Véhicule introuvable")

    tracker_id = vehicle.get("navixy_tracker_id")
    model = oc.resolve_model(vehicle.get("model"))
    supported = oc._model_supports_calibration(model)

    # Lecture LIVE AVL16 (READ-ONLY) — sensor Navixy avl_io_16, jamais l'odomètre générique.
    # Fail-closed & honnête : indispo -> None (UI affiche N/A). Aucune écriture, aucune commande.
    telematics_km = None
    last_update = None
    source = oc.SOURCE_TELTONIKA_AVL16
    avl16_recent = False
    avl16_raw = None
    if supported:
        live = await oc.read_live_avl16_km(db, tenant_id=tenant_id, vehicle_id=vehicle_id)
        telematics_km = live.get("value_km")
        last_update = live.get("timestamp")
        avl16_recent = bool(live.get("recent"))
        avl16_raw = live.get("raw_value")

    cap = await db.vehicle_private_capabilities.find_one(
        {"tracker_id": int(tracker_id)} if tracker_id else {"tracker_id": None},
        {"_id": 0, "navixy_sensor_id": 1, "private_distance_source": 1, "raw_avl_id": 1,
         "navixy_input": 1, "multiplier": 1, "divider": 1, "odometer_calibrated": 1,
         "calibration_baseline_km": 1, "calibration_at": 1, "last_value_km": 1,
         "last_timestamp": 1}) or {}
    # Repli sur la dernière valeur connue en capability UNIQUEMENT si le live est indisponible
    # (jamais 0 inventé ; null reste null).
    if telematics_km is None and cap.get("last_value_km") is not None:
        telematics_km = cap.get("last_value_km")
        last_update = cap.get("last_timestamp")

    calibrations = await oc.list_calibrations(db, tenant_id=tenant_id, vehicle_id=vehicle_id)

    # can_calibrate = gate PILOTE complète (env + write + tenant + tracker allowlistés).
    # Le backend reste autoritaire ; l'UI n'active le bouton que si can_calibrate est vrai.
    gate_ok, gate_reason = oc.calibration_pilot_gate(tenant_id, tracker_id)
    can_calibrate = bool(supported and gate_ok)

    return {
        "vehicle": {"id": vehicle.get("id"), "plate": vehicle.get("plate"),
                    "model": vehicle.get("model")},
        "tracker_id": tracker_id,
        "device_model": model,
        "supported": supported,
        "telematics_km": telematics_km,
        "source": source,
        "last_update": last_update,
        "avl16_recent": avl16_recent,
        "avl16_raw": avl16_raw,
        "capability": cap,
        "device_write_enabled": oc.calibration_device_write_enabled(),
        "can_calibrate": can_calibrate,
        "can_calibrate_reason": None if can_calibrate else gate_reason,
        "param_max_km": oc.PARAM_MAX_KM,
        "large_delta_warn_km": oc.LARGE_DELTA_WARN_KM,
        "calibrations": calibrations,
    }


class CalibrateIn(BaseModel):
    dashboard_km: int              # kilomètres ENTIERS (11807). Décimales refusées côté validation.
    command_style: Optional[str] = "setparam"   # "setparam" | "odoset"
    confirm: Optional[bool] = False               # double confirmation UI (écart important)


@router.post("/vehicles/{vehicle_id}/odometer/calibrate")
async def calibrate_vehicle_odometer_route(
    vehicle_id: str, payload: CalibrateIn, user=Depends(require_roles("admin"))):
    """Recalibre la baseline AVL16 du véhicule depuis le km tableau de bord.

    - RBAC admin/superadmin (driver/manager -> 403 via require_roles).
    - Verrou dédié : si ODOMETER_CALIBRATION_DEVICE_WRITE=0 -> 503 (aucune commande).
    - Confirmation réelle requise (relecture AVL16) pour odometer_calibrated=true.
    """
    db = get_db()
    tenant_id = _tenant_of(user)
    res = await oc.calibrate_vehicle_odometer(
        db, tenant_id=tenant_id, vehicle_id=vehicle_id,
        dashboard_km=payload.dashboard_km, actor=user.get("email", "?"),
        command_style=payload.command_style or "setparam",
    )
    # Refus « durs » -> code HTTP explicite (jamais un 500 nu).
    if res.get("ok") is False and res.get("http") and res.get("result") == oc.CALIB_REFUSED:
        raise HTTPException(res["http"], res.get("reason") or "ODOMETER_CALIBRATION_REFUSED")
    return res
