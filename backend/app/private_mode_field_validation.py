"""LOT P3E-5 -- Validation terrain FMC003 (field validation), PAR TRACKER.

But : promouvoir une capability `vehicle_private_capabilities` d'un tracker FMC003
de l'état `INPUT_DISCOVERED` (flags False) vers un profil `FIELD_VALIDATED`,
UNIQUEMENT après une preuve terrain end-to-end complète (PASS).

Principes (fail-closed, par tracker, auditable) :
  * `start` ouvre une session dans `private_mode_field_validations` (métadonnées).
  * L'opérateur/Ivan effectue la vraie manœuvre via l'app :
        Professionnel -> Privé -> roulage réel -> Professionnel.
    Ce module n'envoie JAMAIS de commande device (aucune écriture Navixy).
  * `finalize` collecte en LECTURE SEULE les preuves sur la fenêtre de la session
    (historique Navixy des ACK device, hw_mileage, points GPS), les évalue, et
    NE PROMEUT la capability (upsert atomique) QUE si PASS complet.
  * FAIL / INCONCLUSIVE / EXPIRED -> aucune écriture de capability.
  * Strictement limité au tracker demandé (jamais de généralisation FMC003/FMC130).
  * N'active PAS le pilote (`vehicle.private_mode_pilot`) : action admin séparée.

Aucune modification des gates existantes. Additif uniquement.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

# --------------------------------------------------------------------------- #
# Constantes P3E-5
# --------------------------------------------------------------------------- #
P3E5_VALIDATOR_VERSION = "P3E5-1.0"
VALIDATIONS_COLLECTION = "private_mode_field_validations"
PROFILE_READY_SOURCE = "P3E5_FIELD_VALIDATION"

# Statuts de session de validation.
ST_STARTED = "STARTED"
ST_PASS = "PASS"
ST_FAIL = "FAIL"
ST_INCONCLUSIVE = "INCONCLUSIVE"
ST_EXPIRED = "EXPIRED"

# TTL de session (au-delà -> EXPIRED).
SESSION_TTL_HOURS = 2
# Fenêtre de lecture Raw IoT / tracks (bornée).
READ_WINDOW_HOURS = 6

# Fraîcheur position (s) : une position est "fraîche" si plus récente que ce seuil.
POSITION_FRESH_MAX_S = 300
# Écart max (m) pour considérer une position "figée" entre deux points.
FROZEN_MAX_MOVE_M = 25.0
# Distance minimale (km) exigée pour prouver croissance/échelle.
MIN_DISTANCE_KM = 0.3
# Tolérance relative échelle (Δhw_mileage vs distance GPS de référence).
SCALE_TOLERANCE = 0.25
# Incrément minimal (km) de hw_mileage pendant le privé.
MIN_PRIVATE_INCREMENT_KM = 0.1

# Libellés ACK device (réponse Navixy `extra.command.response.body`).
ACK_PRIVATE_ON = "Privatemode ON"
ACK_PRIVATE_OFF = "Privatemode OFF"

# Raisons normalisées (stables, testables).
R_NOT_FMC003 = "MODEL_NOT_FMC003"
R_NO_TRACKER = "NO_TRACKER"
R_VEHICLE_NOT_FOUND = "VEHICLE_NOT_FOUND"
R_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
R_SESSION_NOT_OPEN = "SESSION_NOT_OPEN"
R_SESSION_ALREADY_OPEN = "SESSION_ALREADY_OPEN"
R_EXPIRED = "SESSION_EXPIRED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# --------------------------------------------------------------------------- #
# Parsing temps tolérant (ISO-8601 aware).
# --------------------------------------------------------------------------- #
def parse_time(value) -> Optional[datetime]:
    """ISO-8601 -> datetime aware, ou None. Tolère 'Z' et offsets sans ':'."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # format Navixy "YYYY-MM-DD HH:MM:SS" (supposé UTC compte) -> aware UTC
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _haversine_km(lat1, lng1, lat2, lng2) -> Optional[float]:
    try:
        a1, o1, a2, o2 = map(lambda v: math.radians(float(v)), (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    dlat = a2 - a1
    dlng = o2 - o1
    h = math.sin(dlat / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(dlng / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _track_distance_km(points: list) -> float:
    """Somme des segments haversine (km) sur une liste de points GPS triés par temps."""
    total = 0.0
    prev = None
    for p in points or []:
        lat = p.get("lat")
        lng = p.get("lng")
        if lat is None or lng is None:
            continue
        if prev is not None:
            d = _haversine_km(prev[0], prev[1], lat, lng)
            if d is not None:
                total += d
        prev = (lat, lng)
    return total


# --------------------------------------------------------------------------- #
# Fonctions de PREUVE pures (testables sans Navixy/DB).
# Chacune renvoie {"ok": bool, "reason": str|None, ...détails}.
# --------------------------------------------------------------------------- #
def prove_hw_mileage_fresh(obs: Optional[dict], now: datetime) -> dict:
    """P0 : hw_mileage présent + valeur valide + timestamp frais."""
    if not obs:
        return {"ok": False, "reason": "HW_MILEAGE_ABSENT"}
    val = _to_float(obs.get("value"))
    if val is None or val < 0:
        return {"ok": False, "reason": "HW_MILEAGE_VALUE_INVALID"}
    ts = parse_time(obs.get("time"))
    if ts is None:
        return {"ok": False, "reason": "HW_MILEAGE_TIMESTAMP_INVALID"}
    age = (now - ts).total_seconds()
    if age < -POSITION_FRESH_MAX_S:
        return {"ok": False, "reason": "HW_MILEAGE_FUTURE_TIMESTAMP"}
    fresh = age <= POSITION_FRESH_MAX_S
    return {"ok": bool(fresh), "reason": None if fresh else "HW_MILEAGE_STALE",
            "value_km": val, "time": obs.get("time"), "age_s": age}


def prove_cumulative_and_scale(hw_before_km: Optional[float],
                               hw_after_km: Optional[float],
                               gps_distance_km: Optional[float]) -> dict:
    """P1 : Δhw_mileage > 0 (cumulatif) ET cohérent avec la distance GPS de
    référence (échelle km, 1/1). Les deux sont requis.
    `gps_distance_km` = distance indépendante (track GPS) sur le MÊME segment PRO."""
    hb = _to_float(hw_before_km)
    ha = _to_float(hw_after_km)
    gd = _to_float(gps_distance_km)
    if hb is None or ha is None:
        return {"ok": False, "reason": "HW_MILEAGE_SEGMENT_INCOMPLETE"}
    delta = ha - hb
    if delta <= 0:
        return {"ok": False, "reason": "HW_MILEAGE_NOT_INCREASING", "delta_km": delta}
    if delta < MIN_DISTANCE_KM:
        return {"ok": False, "reason": "DISTANCE_TOO_SHORT", "delta_km": delta}
    if gd is None or gd < MIN_DISTANCE_KM:
        return {"ok": False, "reason": "GPS_REFERENCE_INSUFFICIENT",
                "delta_km": delta, "gps_distance_km": gd}
    rel = abs(delta - gd) / max(gd, MIN_DISTANCE_KM)
    if rel > SCALE_TOLERANCE:
        return {"ok": False, "reason": "SCALE_MISMATCH",
                "delta_km": delta, "gps_distance_km": gd, "rel_error": rel}
    return {"ok": True, "reason": None, "delta_km": delta,
            "gps_distance_km": gd, "rel_error": rel, "scale": "km_1_1"}


def find_command_ack(history: list, expected_body: str,
                     window_from: datetime, window_to: datetime) -> dict:
    """P2/P5 : cherche un ACK device dont `extra.command.response.body` contient
    `expected_body`, avec réponse success, dans [window_from, window_to]."""
    for entry in history or []:
        extra = (entry.get("extra") or {})
        cmd = (extra.get("command") or {})
        resp = (cmd.get("response") or {})
        body = str(resp.get("body") or "")
        if expected_body.lower() not in body.lower():
            continue
        if resp.get("success") is False:
            continue
        t = parse_time(entry.get("time") or entry.get("get_time") or cmd.get("time"))
        if t is None:
            continue
        if window_from <= t <= window_to:
            return {"ok": True, "reason": None, "time": t.isoformat(), "body": body}
    return {"ok": False, "reason": "ACK_NOT_FOUND"}


def prove_position_frozen(points_during: list) -> dict:
    """P3 : pendant le privé, la position transmise GÈLE (déplacement max entre
    points <= FROZEN_MAX_MOVE_M). Avec >=2 points. S'il n'y a aucun point, on
    considère INCONCLUSIVE (ambigu) -> not ok."""
    pts = [p for p in (points_during or []) if p.get("lat") is not None and p.get("lng") is not None]
    if len(pts) < 2:
        # Pas assez de points pour prouver le gel de manière déterministe.
        return {"ok": False, "reason": "POSITION_FROZEN_INCONCLUSIVE", "points": len(pts)}
    max_move_m = 0.0
    for a, b in zip(pts, pts[1:]):
        d = _haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])
        if d is not None:
            max_move_m = max(max_move_m, d * 1000.0)
    frozen = max_move_m <= FROZEN_MAX_MOVE_M
    return {"ok": bool(frozen),
            "reason": None if frozen else "POSITION_NOT_FROZEN",
            "max_move_m": round(max_move_m, 1), "points": len(pts)}


def prove_private_increment(hw_at_on_km: Optional[float],
                            hw_at_off_km: Optional[float]) -> dict:
    """P4 : hw_mileage AUGMENTE pendant le privé (position gelée)."""
    on = _to_float(hw_at_on_km)
    off = _to_float(hw_at_off_km)
    if on is None or off is None:
        return {"ok": False, "reason": "PRIVATE_HW_SEGMENT_INCOMPLETE"}
    delta = off - on
    if delta < MIN_PRIVATE_INCREMENT_KM:
        return {"ok": False, "reason": "PRIVATE_HW_NOT_INCREASING", "delta_km": delta}
    return {"ok": True, "reason": None, "delta_km": delta}


def prove_position_fresh(points_after: list, now: datetime) -> dict:
    """P6 : après retour PRO, une position FRAÎCHE réapparaît (get_time récent)."""
    latest = None
    for p in points_after or []:
        t = parse_time(p.get("get_time") or p.get("time"))
        if t is not None and (latest is None or t > latest):
            latest = t
    if latest is None:
        return {"ok": False, "reason": "NO_POSITION_AFTER_BUSINESS"}
    age = (now - latest).total_seconds()
    fresh = -POSITION_FRESH_MAX_S <= age <= POSITION_FRESH_MAX_S
    return {"ok": bool(fresh), "reason": None if fresh else "POSITION_NOT_FRESH",
            "latest": latest.isoformat(), "age_s": age}


# --------------------------------------------------------------------------- #
# Verdict déterministe.
# --------------------------------------------------------------------------- #
PROOF_ORDER = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]
# Preuves "ambiguës" (données manquantes) -> INCONCLUSIVE plutôt que FAIL franc.
_INCONCLUSIVE_REASONS = {
    "HW_MILEAGE_ABSENT", "HW_MILEAGE_TIMESTAMP_INVALID",
    "POSITION_FROZEN_INCONCLUSIVE", "ACK_NOT_FOUND",
    "GPS_REFERENCE_INSUFFICIENT", "NO_POSITION_AFTER_BUSINESS",
    "HW_MILEAGE_SEGMENT_INCOMPLETE", "PRIVATE_HW_SEGMENT_INCOMPLETE",
    "PRO_SEGMENT_UNDEFINED", "PRIVATE_SEGMENT_UNDEFINED", "POST_SEGMENT_UNDEFINED",
}


def evaluate_verdict(evidence: dict) -> dict:
    """Agrège P0..P6 en un verdict déterministe.
    - tous OK                       -> PASS
    - au moins une preuve FAIL      -> FAIL
    - sinon (donnée manquante)      -> INCONCLUSIVE
    Fail-closed : toute preuve absente de `evidence` est traitée comme non prouvée.
    """
    reasons = []
    all_ok = True
    any_hard_fail = False
    for key in PROOF_ORDER:
        proof = evidence.get(key) or {"ok": False, "reason": f"{key}_MISSING"}
        if not proof.get("ok"):
            all_ok = False
            reason = proof.get("reason") or f"{key}_FAILED"
            reasons.append(f"{key}:{reason}")
            if reason not in _INCONCLUSIVE_REASONS and not reason.endswith("_MISSING"):
                any_hard_fail = True
    if all_ok:
        return {"verdict": ST_PASS, "reasons": []}
    if any_hard_fail:
        return {"verdict": ST_FAIL, "reasons": reasons}
    return {"verdict": ST_INCONCLUSIVE, "reasons": reasons}


# --------------------------------------------------------------------------- #
# Payload de promotion (capability) — construit SANS écrire (testable).
# --------------------------------------------------------------------------- #

def build_promotion_set(*, tenant_id: str, vehicle_id: str, tracker_id: int,
                        device_model: str, validation_id: str,
                        now_iso: str) -> dict:
    """Payload `$set` atomique au PASS terrain FMC003."""
    return {
        "tenant_id": tenant_id,
        "vehicle_id": vehicle_id,
        "tracker_id": int(tracker_id),
        "device_model": device_model,
        "private_distance_source": "NAVIXY_HW_MILEAGE",
        "raw_avl_id": None,
        "navixy_input": "hw_mileage",
        "navixy_sensor_id": None,
        "raw_unit": "km",
        "normalized_unit": "km",
        "multiplier": 1.0,
        "divider": 1.0,
        "scale_status": "VERIFIED",
        "runtime_verified": True,
        "cumulative_verified": True,
        "private_increment_verified": True,
        "field_validated": True,
        "profile_ready": True,
        "profile_ready_source": PROFILE_READY_SOURCE,
        "profile_ready_at": now_iso,
        "private_confirmation_strategy": "AVL_INPUT",
        "private_confirmation_avl_id": 391,
        "private_confirmation_private_source": "AVL391_VALUE_1",
        "private_confirmation_business_source": "RAW_LOCATION_RESUME",
        "capability": "FIELD_VALIDATED",
        "validation_scope": "TRACKER",
        "field_validated_at": now_iso,
        "field_validation_id": validation_id,
        "updated_at": now_iso,
    }



# --------------------------------------------------------------------------- #
# Orchestration (IO : DB + Navixy en lazy import).
# --------------------------------------------------------------------------- #
async def _resolve_vehicle(db, *, tenant_id: str, vehicle_id: str) -> dict:
    """Résout le véhicule dans le tenant (réutilise le résolveur provisioning)."""
    from app.private_mode_provisioning import (
        resolve_provisioning_vehicle, ProvisioningResolveError,
    )
    try:
        return await resolve_provisioning_vehicle(db, tenant_id=tenant_id, vehicle_id=vehicle_id)
    except ProvisioningResolveError:
        return {}


async def start_field_validation(db, *, tenant_id: str, vehicle_id: str, actor: str) -> dict:
    """Ouvre une session de validation terrain (fail-closed, FMC003 uniquement)."""
    resolved = await _resolve_vehicle(db, tenant_id=tenant_id, vehicle_id=vehicle_id)
    if not resolved:
        return {"ok": False, "reason": R_VEHICLE_NOT_FOUND}
    tracker_id = resolved.get("tracker_id")
    logical_model = resolved.get("logical_model")
    if logical_model != "FMC003":
        return {"ok": False, "reason": R_NOT_FMC003, "device_model": logical_model}
    if not tracker_id:
        return {"ok": False, "reason": R_NO_TRACKER}

    # Une seule session STARTED non expirée par tracker (fail-closed, pas de
    # concurrence, pas de réutilisation silencieuse).
    existing = await _find_open_session(db, tenant_id=tenant_id, tracker_id=int(tracker_id))
    if existing is not None:
        return {"ok": False, "reason": R_SESSION_ALREADY_OPEN,
                "validation_id": existing.get("validation_id")}

    validation_id = str(uuid.uuid4())
    started_at = _now()
    doc = {
        "validation_id": validation_id,
        "tenant_id": tenant_id,
        "vehicle_id": vehicle_id,
        "tracker_id": int(tracker_id),
        "device_model": logical_model,
        "status": ST_STARTED,
        "started_at": started_at.isoformat(),
        "finalized_at": None,
        "window": {"from": started_at.isoformat(), "to": None},
        "evidence": {},
        "reasons": [],
        "validator_version": P3E5_VALIDATOR_VERSION,
        "actor": actor,
    }
    await db[VALIDATIONS_COLLECTION].insert_one(dict(doc))
    await _audit(db, tenant_id, "P3E5_STARTED",
                 {"validation_id": validation_id, "vehicle_id": vehicle_id,
                  "tracker_id": int(tracker_id), "actor": actor})
    doc.pop("_id", None)
    return {"ok": True, **doc}


async def get_field_validation_status(db, *, tenant_id: str, validation_id: str) -> dict:
    doc = await db[VALIDATIONS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "validation_id": validation_id}, {"_id": 0})
    if not doc:
        return {"ok": False, "reason": R_SESSION_NOT_FOUND}
    return {"ok": True, **doc}


async def _find_open_session(db, *, tenant_id: str, tracker_id: int) -> Optional[dict]:
    """Session STARTED NON expirée pour ce tracker, sinon None.
    Une session STARTED mais au-delà du TTL ne bloque PAS une nouvelle ouverture."""
    doc = await db[VALIDATIONS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "tracker_id": int(tracker_id), "status": ST_STARTED},
        {"_id": 0})
    if not doc:
        return None
    started = parse_time(doc.get("started_at"))
    if started is not None and (_now() - started) > timedelta(hours=SESSION_TTL_HOURS):
        return None  # expirée -> ne bloque pas
    return doc



def prove_hw_profile_and_cumulative(
    capability_doc,
    hw_at_on_km,
    hw_at_off_km,
) -> dict:
    """P1 P3E-10.

    L'échelle physique km/1:1 doit déjà être persistée VERIFIED.
    Le segment terrain PRIVATE doit ensuite démontrer que hw_mileage
    fonctionne réellement et reste cumulatif.

    Les flags runtime_verified/cumulative_verified ne sont volontairement
    PAS utilisés comme précondition : ce sont précisément des sorties de la
    certification terrain.
    """

    cap = capability_doc or {}

    if cap.get("navixy_input") != "hw_mileage":
        return {
            "ok": False,
            "reason": "HW_PROFILE_SOURCE_INVALID",
        }

    if cap.get("scale_status") != "VERIFIED":
        return {
            "ok": False,
            "reason": "HW_SCALE_NOT_VERIFIED",
        }

    if (
        cap.get("raw_unit") != "km"
        or cap.get("normalized_unit") != "km"
    ):
        return {
            "ok": False,
            "reason": "HW_SCALE_UNIT_INVALID",
        }

    try:
        multiplier = float(cap.get("multiplier"))
        divider = float(cap.get("divider"))
    except (TypeError, ValueError, OverflowError):
        return {
            "ok": False,
            "reason": "HW_SCALE_FACTOR_INVALID",
        }

    if multiplier != 1.0 or divider != 1.0:
        return {
            "ok": False,
            "reason": "HW_SCALE_FACTOR_INVALID",
        }

    on = _to_float(hw_at_on_km)
    off = _to_float(hw_at_off_km)

    if on is None or off is None:
        return {
            "ok": False,
            "reason": "HW_MILEAGE_SEGMENT_INCOMPLETE",
        }

    delta = off - on

    if delta < MIN_DISTANCE_KM:
        return {
            "ok": False,
            "reason": "HW_MILEAGE_NOT_CUMULATIVE",
            "delta_km": delta,
        }

    return {
        "ok": True,
        "reason": None,
        "delta_km": delta,
        "source": "NAVIXY_HW_MILEAGE",
        "scale": "km_1_1",
        "scale_status": "VERIFIED",
        "runtime_proven": True,
        "cumulative_proven": True,
    }


async def _collect_evidence(
    db,
    *,
    tenant_id: str,
    tracker_id: int,
    window_from: datetime,
    window_to: datetime,
    now: datetime,
) -> dict:
    """P3E-10 — collecte FMC003 asymétrique, lecture seule.

    PRIVATE :
      P2 = AVL391=1
      P3 = RAW masqué après P2

    Compteur :
      P0 = hw_mileage frais
      P1 = échelle persistée VERIFIED + progression terrain
      P4 = incrément hw_mileage pendant PRIVATE

    BUSINESS :
      P5 = première reprise RAW valide après une phase masquée
      P6 = seconde trame RAW valide postérieure à P5
    """

    from app import navixy_client as nav
    from app import private_mode_engine as pm_engine

    ev = {}

    def fmt_raw(dt):
        return (
            dt.astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    # --------------------------------------------------------
    # P0 — source hw_mileage disponible/fraîche
    # --------------------------------------------------------

    obs_last = await nav.read_raw_hw_mileage(
        int(tracker_id),
        frm=fmt_raw(window_from),
        to=fmt_raw(window_to),
    )

    ev["P0"] = prove_hw_mileage_fresh(
        obs_last,
        now,
    )

    # --------------------------------------------------------
    # P2 — PRIVATE : événement explicite AVL391=1
    # --------------------------------------------------------

    p2 = await pm_engine.avl_input_confirm(
        tenant_id,
        int(tracker_id),
        pm_engine.PRIVATE,
        window_from.isoformat(),
        391,
        window_to_iso=window_to.isoformat(),
        first_match=True,
    )

    ev["P2"] = p2

    t_on = (
        parse_time(p2.get("time") or p2.get("observed_at"))
        if p2.get("ok")
        else None
    )

    # --------------------------------------------------------
    # P3 — masquage RAW après PRIVATE
    # --------------------------------------------------------

    if t_on is not None:
        p3 = await pm_engine.raw_private_mask_confirm(
            tenant_id,
            int(tracker_id),
            t_on.isoformat(),
            window_to_iso=window_to.isoformat(),
            first_match=True,
        )
    else:
        p3 = {
            "ok": False,
            "reason": "PRIVATE_BOUNDARY_MISSING",
        }

    ev["P3"] = p3

    t_mask = (
        parse_time(p3.get("time") or p3.get("observed_at"))
        if p3.get("ok")
        else None
    )

    # --------------------------------------------------------
    # P5 — BUSINESS : première reprise RAW valide
    # après qu'une phase masquée a réellement été observée.
    # --------------------------------------------------------

    if t_on is not None:
        p5 = await pm_engine.raw_business_resume_confirm(
            tenant_id,
            int(tracker_id),
            t_on.isoformat(),
            window_to_iso=window_to.isoformat(),
            first_match=True,
            require_masked_before=True,
        )
    else:
        p5 = {
            "ok": False,
            "reason": "PRIVATE_BOUNDARY_MISSING",
        }

    ev["P5"] = p5

    t_off = (
        parse_time(p5.get("time") or p5.get("observed_at"))
        if p5.get("ok")
        else None
    )

    # --------------------------------------------------------
    # Compteur sur le segment PRIVATE
    # --------------------------------------------------------

    hw_on = None
    hw_off = None

    if (
        t_on is not None
        and t_off is not None
        and t_off > t_on
    ):
        hw_on = await nav.read_raw_hw_mileage(
            int(tracker_id),
            frm=fmt_raw(t_on),
            to=fmt_raw(
                min(
                    t_on + timedelta(minutes=1),
                    t_off,
                )
            ),
        )

        hw_off = await nav.read_raw_hw_mileage(
            int(tracker_id),
            frm=fmt_raw(t_on),
            to=fmt_raw(t_off),
        )

    cap = await db.vehicle_private_capabilities.find_one(
        {
            "tenant_id": tenant_id,
            "tracker_id": int(tracker_id),
        },
        {
            "_id": 0,
            "navixy_input": 1,
            "scale_status": 1,
            "raw_unit": 1,
            "normalized_unit": 1,
            "multiplier": 1,
            "divider": 1,
        },
    )

    ev["P1"] = prove_hw_profile_and_cumulative(
        cap,
        (hw_on or {}).get("value"),
        (hw_off or {}).get("value"),
    )

    ev["P4"] = prove_private_increment(
        (hw_on or {}).get("value"),
        (hw_off or {}).get("value"),
    )

    # --------------------------------------------------------
    # P6 — une DEUXIÈME position réelle doit apparaître
    # strictement après la première reprise BUSINESS.
    # Ainsi P5 et P6 ne reposent pas sur la même trame.
    # --------------------------------------------------------

    if t_off is not None:
        p6 = await pm_engine.raw_business_resume_confirm(
            tenant_id,
            int(tracker_id),
            t_off.isoformat(),
            window_to_iso=window_to.isoformat(),
            first_match=True,
            require_masked_before=False,
        )
    else:
        p6 = {
            "ok": False,
            "reason": "BUSINESS_BOUNDARY_MISSING",
        }

    ev["P6"] = p6

    t_followup = (
        parse_time(p6.get("time") or p6.get("observed_at"))
        if p6.get("ok")
        else None
    )

    segments_ok = bool(
        t_on is not None
        and t_mask is not None
        and t_off is not None
        and t_followup is not None
        and t_on < t_mask
        and t_mask < t_off
        and t_off < t_followup
    )

    ev["_segments"] = {
        "t_on": (
            t_on.isoformat()
            if t_on else None
        ),
        "t_mask": (
            t_mask.isoformat()
            if t_mask else None
        ),
        "t_off": (
            t_off.isoformat()
            if t_off else None
        ),
        "t_followup": (
            t_followup.isoformat()
            if t_followup else None
        ),
        "segments_ok": segments_ok,
        "gps_reference_km": None,
        "protocol": "P3E10_FMC003_ASYMMETRIC_RAW",
    }

    return ev





async def finalize_field_validation(db, *, tenant_id: str, validation_id: str,
                                    actor: str) -> dict:
    """Collecte + verdict ; promotion atomique UNIQUEMENT si PASS complet."""
    sess = await db[VALIDATIONS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "validation_id": validation_id}, {"_id": 0})
    if not sess:
        return {"ok": False, "reason": R_SESSION_NOT_FOUND}
    if sess.get("status") != ST_STARTED:
        return {"ok": False, "reason": R_SESSION_NOT_OPEN, "status": sess.get("status")}

    started = parse_time(sess.get("started_at")) or _now()
    now = _now()
    # Expiration ?
    if (now - started) > timedelta(hours=SESSION_TTL_HOURS):
        await _close_session(db, tenant_id, validation_id, ST_EXPIRED, [R_EXPIRED], {}, now)
        await _audit(db, tenant_id, "P3E5_EXPIRED", {"validation_id": validation_id})
        return {"ok": True, "verdict": ST_EXPIRED, "reasons": [R_EXPIRED]}

    window_from = started
    window_to = now
    try:
        evidence = await _collect_evidence(
            db, tenant_id=tenant_id, tracker_id=int(sess["tracker_id"]),
            window_from=window_from, window_to=window_to, now=now)
    except Exception as exc:  # Navixy indisponible / erreur réseau -> INCONCLUSIVE
        reasons = ["COLLECT_ERROR:%s" % type(exc).__name__]
        await _close_session(db, tenant_id, validation_id, ST_INCONCLUSIVE,
                             reasons, {}, now, window_from, window_to)
        await _audit(db, tenant_id, "P3E5_INCONCLUSIVE",
                     {"validation_id": validation_id, "reasons": reasons})
        return {"ok": True, "verdict": ST_INCONCLUSIVE, "reasons": reasons}

    result = evaluate_verdict(evidence)
    verdict = result["verdict"]
    reasons = result["reasons"]

    await _close_session(db, tenant_id, validation_id, verdict, reasons,
                         evidence, now, window_from, window_to)

    promoted = False
    if verdict == ST_PASS:
        await _promote_field_validated(
            db, tenant_id=tenant_id, vehicle_id=sess["vehicle_id"],
            tracker_id=int(sess["tracker_id"]), device_model=sess["device_model"],
            validation_id=validation_id, now_iso=now.isoformat())
        promoted = True
        await _audit(db, tenant_id, "P3E5_PROMOTED",
                     {"validation_id": validation_id, "vehicle_id": sess["vehicle_id"],
                      "tracker_id": int(sess["tracker_id"]), "actor": actor})
    else:
        await _audit(db, tenant_id, "P3E5_%s" % verdict,
                     {"validation_id": validation_id, "reasons": reasons, "actor": actor})

    return {"ok": True, "verdict": verdict, "reasons": reasons,
            "promoted": promoted, "evidence": evidence}


async def _close_session(db, tenant_id, validation_id, status, reasons, evidence,
                         now, window_from=None, window_to=None) -> None:
    patch = {"status": status, "finalized_at": now.isoformat(),
             "reasons": reasons, "evidence": evidence}
    if window_from is not None:
        patch["window"] = {"from": window_from.isoformat(),
                           "to": (window_to or now).isoformat()}
    await db[VALIDATIONS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "validation_id": validation_id},
        {"$set": patch})


async def _promote_field_validated(db, *, tenant_id, vehicle_id, tracker_id,
                                   device_model, validation_id, now_iso) -> None:
    """Upsert ATOMIQUE de la capability (un seul $set). JAMAIS appelé hors PASS."""
    payload = build_promotion_set(
        tenant_id=tenant_id, vehicle_id=vehicle_id, tracker_id=int(tracker_id),
        device_model=device_model, validation_id=validation_id, now_iso=now_iso)
    await db.vehicle_private_capabilities.update_one(
        {"tenant_id": tenant_id, "tracker_id": int(tracker_id)},
        {"$set": payload}, upsert=True)


async def _audit(db, tenant_id: str, action: str, payload: dict) -> None:
    try:
        await db.audit_log.insert_one({
            "ts": _now_iso(), "scope": "private_mode_field_validation",
            "action": action, "tenant_id": tenant_id,
            "validator_version": P3E5_VALIDATOR_VERSION, **payload})
    except Exception:
        pass
