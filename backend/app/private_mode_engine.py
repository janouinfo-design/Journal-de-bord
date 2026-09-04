"""Phase 2 — Moteur de bascule Privé/Professionnel (backend autoritaire).

Architecture : App Chauffeur -> Backend LOGITRAK -> Navixy -> Teltonika Private/Business.
- L'app n'envoie qu'une INTENTION métier : mode=PRIVATE|BUSINESS. Le backend résout
  driver -> tenant -> vehicle -> tracker -> capability -> commande -> confirmation.
- Machine à états : BUSINESS / PRIVATE_REQUESTED / PRIVATE / BUSINESS_REQUESTED / FAILED / UNKNOWN.
- Aucun changement optimiste : l'état ne passe à PRIVATE/BUSINESS qu'APRÈS confirmation.
- Commande device = `privatemode ON/OFF` (JAMAIS Deep Sleep 11000:4).
- Distance privée = AVL16 (Teltonika Total Odometer) delta ; JAMAIS le compteur GPS Navixy.
- Confidentialité : en PRIVATE, aucune position/adresse/polyline exposée (même si Navixy garde
  une last known position gelée).

GARDE-FOUS : l'envoi RÉEL de commande device est GATED (flag env PRIVATE_MODE_DEVICE_WRITE=1) ET
soumis à la gate capability field_validated par tracker. Par défaut = SIMULATION (aucun appel Navixy).
Les fonctions command/confirm/read_odo sont INJECTABLES (tests + découplage).
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from app.odometer_capability import (
    resolve_model, get_capability, VehicleOdometerCapability,
    vehicle_private_mode_allowed, get_pilot_capability,
    SOURCE_TELTONIKA_TOTAL_ODOMETER, AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)

logger = logging.getLogger(__name__)

# --- États (machine à états) ---
BUSINESS = "BUSINESS"
PRIVATE_REQUESTED = "PRIVATE_REQUESTED"
PRIVATE = "PRIVATE"
BUSINESS_REQUESTED = "BUSINESS_REQUESTED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

_TENANT = "default"

# Commandes device (jamais Deep Sleep).
_CMD = {PRIVATE: "privatemode ON", BUSINESS: "privatemode OFF"}


def device_write_enabled() -> bool:
    """L'envoi RÉEL de commande device est-il autorisé ? (défaut NON -> simulation)."""
    return os.environ.get("PRIVATE_MODE_DEVICE_WRITE", "0").strip().lower() in ("1", "true", "yes", "on")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Résolution de capability PAR TRACKER — persistable en Mongo, fallback constante pilote.
# ---------------------------------------------------------------------------
async def resolve_vehicle_capability(db, tracker_id: Optional[int],
                                     device_model: Optional[str]) -> Optional[VehicleOdometerCapability]:
    """Capacité odomètre privé d'un tracker. Source de vérité = Mongo
    `vehicle_private_capabilities` ; fallback = registre pilote (constante, traçabilité/tests).
    Retour None si aucune capability connue."""
    if tracker_id is None:
        return None
    doc = await db.vehicle_private_capabilities.find_one(
        {"tracker_id": int(tracker_id)}, {"_id": 0})
    if doc:
        # Reconstruit un VehicleOdometerCapability depuis le doc Mongo (champs connus).
        allowed_fields = VehicleOdometerCapability.__dataclass_fields__.keys()
        clean = {k: v for k, v in doc.items() if k in allowed_fields}
        try:
            return VehicleOdometerCapability(**clean)
        except TypeError:
            logger.warning("capability doc invalide pour tracker %s", tracker_id)
            return None
    # Fallback : registre pilote (non destructif — sert de preuve/seed).
    return get_pilot_capability(tracker_id)


async def upsert_vehicle_capability(db, vc: VehicleOdometerCapability) -> None:
    """Persiste/actualise la capability d'un tracker (non destructif : upsert par tracker_id)."""
    if vc.tracker_id is None:
        raise ValueError("tracker_id requis")
    d = vc.to_dict()
    d["tenant_id"] = _TENANT
    d["updated_at"] = _now()
    await db.vehicle_private_capabilities.update_one(
        {"tracker_id": int(vc.tracker_id)}, {"$set": d}, upsert=True)


# ---------------------------------------------------------------------------
# État Privé/Business par véhicule
# ---------------------------------------------------------------------------
async def get_mode_state(db, vehicle_id: str) -> dict:
    st = await db.private_mode_state.find_one({"vehicle_id": vehicle_id}, {"_id": 0})
    return st or {"vehicle_id": vehicle_id, "state": UNKNOWN, "updated_at": None}


async def _save_mode_state(db, doc: dict) -> None:
    doc["updated_at"] = _now()
    await db.private_mode_state.update_one(
        {"vehicle_id": doc["vehicle_id"]}, {"$set": doc}, upsert=True)


async def _audit(db, payload: dict) -> None:
    await db.audit_log.insert_one({
        "ts": _now(), "scope": "private_mode", **payload,
    })


# ---------------------------------------------------------------------------
# Hooks device/odomètre — GATED + INJECTABLES (mock par défaut, aucun appel réseau).
# ---------------------------------------------------------------------------
async def _default_send_command(tracker_id: int, command: str) -> dict:
    """Envoi commande device. GATED : si device write off -> SIMULATION (aucun appel Navixy)."""
    if not device_write_enabled():
        return {"applied": False, "mode": "SIMULATION", "command": command}
    from app.navixy_client import send_raw_command, is_configured
    if not is_configured():
        return {"applied": False, "mode": "REAL", "error": "navixy_not_configured"}
    resp = await send_raw_command(int(tracker_id), command, reliable=True)
    return {"applied": True, "mode": "REAL", "command": command,
            "navixy_command_id": resp.get("command_id")}


async def _default_confirm(tracker_id: int, expected_state: str) -> tuple[Optional[str], str]:
    """Confirme l'état réel du device. En SIMULATION : non confirmé côté device
    (retourne (None, 'SIMULATED')). En REAL : à implémenter via lecture d'état device
    (privatemode ?/signaux) — non exécuté sans terrain. Renvoie (state|None, source)."""
    if not device_write_enabled():
        return None, "SIMULATED"
    # REAL : la confirmation terrain se fait via relecture (privatemode ?/état). Non exécuté ici.
    return None, "REAL_PENDING"


async def _default_read_odo_km(tracker_id: int) -> Optional[float]:
    """Lit l'odomètre AVL16 normalisé (km). En SIMULATION : None (pas d'appel réseau)."""
    return None


# ---------------------------------------------------------------------------
# Cœur : demande de bascule de mode (backend autoritaire, gate, idempotence).
# ---------------------------------------------------------------------------
async def request_mode(
    db, driver_id: str, target_mode: str, actor: str,
    *,
    resolve_session: Callable[..., Awaitable[Optional[dict]]],
    send_command: Callable[[int, str], Awaitable[dict]] = _default_send_command,
    confirm: Callable[[int, str], Awaitable[tuple]] = _default_confirm,
    read_odo_km: Callable[[int], Awaitable[Optional[float]]] = _default_read_odo_km,
) -> dict:
    """Traite une intention métier PRIVATE|BUSINESS pour le véhicule de la session du chauffeur.

    - `resolve_session(db, driver_id)` -> session courante (doit contenir vehicle_id).
    Retour : {ok, state, allowed, reason, vehicle_id, tracker_id, private_distance_km?, ...}
    """
    if target_mode not in (PRIVATE, BUSINESS):
        return {"ok": False, "reason": "invalid_mode", "state": UNKNOWN}

    sess = await resolve_session(db, driver_id)
    if not sess or not sess.get("vehicle_id"):
        return {"ok": False, "reason": "no_active_vehicle", "state": UNKNOWN}
    vehicle_id = sess["vehicle_id"]

    vehicle = await db.vehicles.find_one(
        {"id": vehicle_id, "tenant_id": _TENANT}, {"_id": 0}) or {}
    tracker_id = vehicle.get("navixy_tracker_id")
    model = resolve_model(vehicle.get("model"))

    # --- GATE capability (par tracker) ---
    vc = await resolve_vehicle_capability(db, tracker_id, model)
    allowed = bool(tracker_id) and vehicle_private_mode_allowed(model, vc)
    if not allowed:
        reason = "capability_not_field_validated" if tracker_id else "no_tracker"
        await _audit(db, {"driver_id": driver_id, "vehicle_id": vehicle_id,
                          "tracker_id": tracker_id, "requested_mode": target_mode,
                          "result": "refused", "reason": reason})
        return {"ok": False, "allowed": False, "reason": reason,
                "state": (await get_mode_state(db, vehicle_id)).get("state", UNKNOWN),
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    cur = await get_mode_state(db, vehicle_id)
    cur_state = cur.get("state", UNKNOWN)

    # --- Idempotence : déjà dans l'état cible -> no-op (aucune commande device) ---
    if cur_state == target_mode:
        return {"ok": True, "allowed": True, "state": cur_state, "idempotent": True,
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    # --- Anti-concurrence : une transition est déjà en cours ---
    if cur_state in (PRIVATE_REQUESTED, BUSINESS_REQUESTED):
        return {"ok": False, "allowed": True, "state": cur_state, "reason": "transition_in_progress",
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    requested_state = PRIVATE_REQUESTED if target_mode == PRIVATE else BUSINESS_REQUESTED
    base = {"vehicle_id": vehicle_id, "tracker_id": tracker_id, "tenant_id": _TENANT,
            "driver_id": driver_id, "previous_state": cur_state}

    # --- Snapshot odomètre à l'ENTRÉE en privé (avant bascule) ---
    if target_mode == PRIVATE:
        odo_start = await read_odo_km(int(tracker_id))
        base["private_start_time"] = _now()
        base["private_start_odometer_km"] = odo_start
        base["odometer_source"] = SOURCE_TELTONIKA_TOTAL_ODOMETER

    await _save_mode_state(db, {**cur, **base, "state": requested_state})

    # --- Envoi commande device (GATED) ---
    cmd = _CMD[target_mode]
    cmd_res = await send_command(int(tracker_id), cmd)

    # --- Confirmation RÉELLE (jamais optimiste) ---
    confirmed_state, confirm_source = await confirm(int(tracker_id), target_mode)

    if confirmed_state != target_mode:
        # Non confirmé -> état honnête (ne PAS afficher succès)
        final = FAILED if cmd_res.get("mode") == "REAL" else PRIVATE_REQUESTED if target_mode == PRIVATE else BUSINESS_REQUESTED
        await _save_mode_state(db, {**cur, **base, "state": final,
                                    "last_command": cmd, "confirmation_source": confirm_source})
        await _audit(db, {**base, "requested_mode": target_mode, "resulting_state": final,
                          "result": "not_confirmed", "confirmation_source": confirm_source,
                          "command_mode": cmd_res.get("mode")})
        return {"ok": False, "allowed": True, "state": final,
                "reason": "not_confirmed", "confirmation_source": confirm_source,
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    # --- Confirmé : transition finale ---
    result = {"ok": True, "allowed": True, "state": target_mode,
              "confirmation_source": confirm_source,
              "vehicle_id": vehicle_id, "tracker_id": tracker_id}
    new_doc = {**cur, **base, "state": target_mode, "last_command": cmd,
               "confirmation_source": confirm_source}

    # --- Snapshot odomètre à la SORTIE (retour Business) + distance privée ---
    if target_mode == BUSINESS and cur_state in (PRIVATE, PRIVATE_REQUESTED):
        odo_end = await read_odo_km(int(tracker_id))
        odo_start = cur.get("private_start_odometer_km")
        new_doc["private_end_time"] = _now()
        new_doc["private_end_odometer_km"] = odo_end
        dist = _private_distance(odo_start, odo_end)
        new_doc["private_distance_km"] = dist
        result["private_distance_km"] = dist
        if dist is None:
            result["distance_status"] = "UNAVAILABLE"  # jamais inventée

    await _save_mode_state(db, new_doc)
    await _audit(db, {**base, "requested_mode": target_mode, "resulting_state": target_mode,
                      "result": "confirmed", "confirmation_source": confirm_source,
                      "command_mode": cmd_res.get("mode"),
                      "private_distance_km": new_doc.get("private_distance_km")})
    return result


def _private_distance(start_km, end_km) -> Optional[float]:
    """Distance privée = end - start. Conditions strictes ; jamais inventée."""
    try:
        x = float(start_km)
        y = float(end_km)
    except (TypeError, ValueError):
        return None
    if y < x:
        return None  # anomalie -> non fournie
    return round(y - x, 3)


# ---------------------------------------------------------------------------
# Confidentialité : rédaction d'un trajet/état quand PRIVATE.
# ---------------------------------------------------------------------------
_PRIVATE_REDACT_KEYS = ("lat", "lng", "latitude", "longitude", "location", "address",
                        "start_address", "end_address", "polyline", "points", "route",
                        "replay", "breadcrumb", "path", "gps")


def redact_private_location(obj: dict, state: str) -> dict:
    """En PRIVATE : neutralise toute donnée de position (absente/None), conserve les champs métier.
    Ne met JAMAIS 0,0 comme coordonnées métier."""
    if state != PRIVATE or not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if str(k).lower() in _PRIVATE_REDACT_KEYS:
            out[k] = None
        elif isinstance(v, dict):
            out[k] = redact_private_location(v, state)
        else:
            out[k] = v
    return out


def private_trip_dto(state_doc: dict) -> dict:
    """DTO d'un trajet privé : uniquement les champs métier, aucune position."""
    return {
        "vehicle_id": state_doc.get("vehicle_id"),
        "driver_id": state_doc.get("driver_id"),
        "start_time": state_doc.get("private_start_time"),
        "end_time": state_doc.get("private_end_time"),
        "odometer_start_km": state_doc.get("private_start_odometer_km"),
        "odometer_end_km": state_doc.get("private_end_odometer_km"),
        "private_distance_km": state_doc.get("private_distance_km"),
        "odometer_source": state_doc.get("odometer_source"),
        "mode_status": state_doc.get("state"),
        # positions volontairement ABSENTES (pas de lat/lng/adresse/polyline)
    }


# ---------------------------------------------------------------------------
# Politique CENTRALE de confidentialité des TRAJETS (Web/API).
# La source autoritaire = un MARQUEUR MÉTIER explicite du trajet (jamais lat==0/gel).
# ---------------------------------------------------------------------------
# Champs de localisation à retirer d'un trajet privé (jamais 0,0 ; absents/None).
# La liste est volontairement large (rétro-compat + robustesse aux variantes futures).
# Le matching est insensible à la casse (voir redact).
_TRIP_LOCATION_FIELDS = (
    # coordonnées plates
    "start_lat", "start_lng", "end_lat", "end_lng", "lat", "lng", "lon",
    "latitude", "longitude",
    # objets/structures de position imbriquées éventuelles
    "start_location", "end_location", "location", "last_location",
    "last_position", "last_known_position", "current_location", "position",
    "coordinates", "coord", "coords", "geo", "geometry", "bounds",
    # adresses
    "start_address", "end_address", "address", "current_address", "last_address",
    # zones (peuvent trahir une localisation)
    "start_zone_type", "end_zone_type", "zone", "geofence",
    # tracés / points / itinéraires
    "polyline", "points", "route", "path", "breadcrumb", "track", "trail",
)


def trip_is_private(trip: dict) -> bool:
    """Un trajet est PRIVÉ (device) si un marqueur MÉTIER explicite l'indique.
    Source autoritaire = champ du trajet (jamais déduit de lat==0 / position gelée).
    Accepte plusieurs conventions possibles pour rétro-compat."""
    if not isinstance(trip, dict):
        return False
    if trip.get("private_mode") is True:
        return True
    if str(trip.get("mode_status") or "").upper() == PRIVATE:
        return True
    if trip.get("privacy") == "private":
        return True
    return False


def _strip_location_deep(value):
    """Retire récursivement toute donnée de localisation d'une valeur arbitraire.

    - Dans un dict : toute clé (insensible à la casse) présente dans
      _TRIP_LOCATION_FIELDS est mise à None ; les autres valeurs sont
      parcourues récursivement (dict/list) pour attraper une position
      imbriquée dans un champ métier.
    - Dans une list : chaque élément est parcouru récursivement.
    - Ne fabrique JAMAIS de coordonnée artificielle (jamais 0,0).
    - Préserve intégralement les champs métier non liés à la localisation.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in _TRIP_LOCATION_FIELDS:
                out[k] = None
            else:
                out[k] = _strip_location_deep(v)
        return out
    if isinstance(value, list):
        return [_strip_location_deep(item) for item in value]
    return value


def redact_private_trip(trip: dict) -> dict:
    """Masque toute la localisation d'un trajet PRIVÉ (récursivement, à toute
    profondeur), conserve les champs métier (temps, durée, distance privée,
    odomètres, véhicule, chauffeur, mode). Jamais 0,0."""
    if not isinstance(trip, dict) or not trip_is_private(trip):
        return trip
    out = _strip_location_deep(trip)
    out["private_redacted"] = True
    return out


async def is_vehicle_currently_private(db, vehicle_id: Optional[str]) -> bool:
    """État PRIVATE courant d'un véhicule (source autoritaire = private_mode_state)."""
    if not vehicle_id:
        return False
    st = await get_mode_state(db, vehicle_id)
    return st.get("state") == PRIVATE
