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
    CONFIRM_STRATEGY_FROZEN_POSITION, CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
)

logger = logging.getLogger(__name__)

# --- États (machine à états) ---
BUSINESS = "BUSINESS"
PRIVATE_REQUESTED = "PRIVATE_REQUESTED"
PRIVATE = "PRIVATE"
BUSINESS_REQUESTED = "BUSINESS_REQUESTED"
PENDING_CONFIRMATION = "PENDING_CONFIRMATION"  # commande envoyée, confirmation device pas encore prouvée
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

# Sources de confirmation (provenance de la preuve).
SRC_DEVICE_RESPONSE = "DEVICE_RESPONSE"       # réponse explicite du device (non dispo actuellement)
SRC_DEVICE_STATE_READ = "DEVICE_STATE_READ"   # lecture d'état explicite (non dispo actuellement)
SRC_TELEMETRY = "TELEMETRY_CONFIRMED"         # dérivé télémétrie (position gelée/reprise) — profil validé
SRC_SIMULATED = "SIMULATED_CONFIRMED"         # TEST/DEV uniquement, jamais en prod
SRC_UNCONFIRMED = "UNCONFIRMED"               # commande envoyée, pas encore de preuve

# Résultat terminal d'une transition (exposé à l'UI, jamais perdu silencieusement).
TRANSITION_CONFIRMED = "CONFIRMED"            # preuve télémétrique obtenue
TRANSITION_TIMEOUT = "TIMEOUT"                # fenêtre de confirmation dépassée sans preuve

_TENANT = "default"

# Commandes device (jamais Deep Sleep).
_CMD = {PRIVATE: "privatemode ON", BUSINESS: "privatemode OFF"}


def device_write_enabled() -> bool:
    """L'envoi RÉEL de commande device est-il autorisé ? (défaut NON -> simulation)."""
    return os.environ.get("PRIVATE_MODE_DEVICE_WRITE", "0").strip().lower() in ("1", "true", "yes", "on")


def simulate_confirm_enabled() -> bool:
    """TEST/DEV UNIQUEMENT : simule une confirmation device (bascule confirmée sans matériel).
    FAIL-CLOSED : jamais actif en production (APP_ENV doit être dev/preview/local) ET requiert
    PRIVATE_MODE_SIMULATE_CONFIRM=1. Sert aux tests E2E logiciels, jamais au rollout réel."""
    app_env = os.environ.get("APP_ENV", "production").strip().lower()
    if app_env not in ("development", "dev", "preview", "local", "test"):
        return False
    return os.environ.get("PRIVATE_MODE_SIMULATE_CONFIRM", "0").strip().lower() in ("1", "true", "yes", "on")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts):
    """Parse un timestamp ISO ou 'YYYY-MM-DD HH:MM:SS' en datetime aware (UTC). None si invalide."""
    if not ts:
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = datetime.strptime(s[:19], fmt)
                break
            except Exception:
                d = None
        if d is None:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


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
    """Confirmation IMMÉDIATE (synchrone) au moment de l'envoi.

    - TEST/DEV avec PRIVATE_MODE_SIMULATE_CONFIRM : simule une confirmation (E2E logiciel).
    - Sinon : PAS de confirmation immédiate. La confirmation RÉELLE se fait de façon
      ASYNCHRONE via la télémétrie (resolve_pending_confirmation), car aucune réponse
      device synchrone n'est disponible via l'API Navixy actuelle. On retourne donc
      (None, UNCONFIRMED) -> l'état deviendra PENDING_CONFIRMATION, jamais FAILED.
    Renvoie (state|None, source)."""
    if simulate_confirm_enabled():
        return expected_state, SRC_SIMULATED  # TEST/DEV uniquement, jamais en prod
    return None, SRC_UNCONFIRMED


# ---------------------------------------------------------------------------
# Confirmation TÉLÉMÉTRIQUE (Niveau C) — READ-ONLY, bornée, profil validé uniquement.
# Preuve terrain FMC003 : en PRIVÉ la position transmise GÈLE (gps.updated ne progresse
# plus) alors que le véhicule est actif ; au retour BUSINESS la position REPREND
# (gps.updated progresse à nouveau après l'envoi de la commande OFF).
# ---------------------------------------------------------------------------
def _model_supports_telemetry_confirm(capability) -> bool:
    """La confirmation télémétrique n'est autorisée que pour un profil FIELD_VALIDATED.
    Deux cas (jamais généralisé automatiquement) :
      - FMC003 prouvé terrain (comportement existant, gel de position) ;
      - tout tracker field_validated avec stratégie explicite LAST_KNOWN_POSITION (ex FMC130 781479).
    """
    if not capability:
        return False
    if not getattr(capability, "field_validated", False):
        return False
    model = str(getattr(capability, "device_model", "") or "").upper()
    strategy = getattr(capability, "private_confirmation_strategy", None)
    if model == "FMC003":
        return True                                   # comportement existant INCHANGÉ
    if strategy == CONFIRM_STRATEGY_LAST_KNOWN_POSITION:
        return True                                   # profil explicite (jamais tous les FMC130)
    return False


def _confirm_strategy(capability) -> str:
    """Stratégie de confirmation effective d'une capability.
    FMC003 sans stratégie explicite -> FROZEN_POSITION (comportement historique)."""
    strat = getattr(capability, "private_confirmation_strategy", None)
    if strat:
        return strat
    model = str(getattr(capability, "device_model", "") or "").upper()
    return CONFIRM_STRATEGY_FROZEN_POSITION if model == "FMC003" else CONFIRM_STRATEGY_FROZEN_POSITION


def _haversine_m(lat1, lng1, lat2, lng2) -> Optional[float]:
    """Distance en mètres entre 2 points GPS. None si une coordonnée est invalide."""
    try:
        import math
        a1, o1, a2, o2 = map(lambda v: math.radians(float(v)), (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    import math
    dlat = a2 - a1
    dlng = o2 - o1
    h = math.sin(dlat / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(dlng / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


# Rayons (m) : dans MASK_RADIUS = position "dernière connue" (masquée) ; au-delà de RESUME_MIN
# = position réellement reprise (retour Business prouvé).
_MASK_RADIUS_M = float(os.environ.get("PRIVATE_MASK_RADIUS_M", "200"))
_RESUME_MIN_M = float(os.environ.get("PRIVATE_RESUME_MIN_M", "200"))

# --- Confirmation LAST_KNOWN_POSITION : preuve par POSITION DOMINANTE multi-samples ---
# Le masquage est prouvé par une position STABLE/RÉPÉTÉE sur plusieurs observations pendant
# qu'AVL16 progresse (preuve terrain FMC130 781479 : 32/36 = 0.889). PAS par une distance à l'ancre.
LKP_MIN_SAMPLES = int(os.environ.get("PRIVATE_LKP_MIN_SAMPLES", "5"))       # jamais sur 1 seul sample
LKP_DOMINANT_MIN_RATIO = float(os.environ.get("PRIVATE_LKP_DOMINANT_RATIO", "0.7"))  # terrain 0.889
LKP_DOMINANT_RADIUS_M = float(os.environ.get("PRIVATE_LKP_DOMINANT_RADIUS_M", "25"))  # jitter GPS toléré
LKP_RESUME_MIN_M = float(os.environ.get("PRIVATE_LKP_RESUME_MIN_M", "30"))  # petit déplacement réel = reprise


def _dominant_position(samples) -> tuple[Optional[float], int, int]:
    """Cherche la POSITION DOMINANTE d'une liste de samples [{lat,lng},...].

    Regroupe les samples à <= LKP_DOMINANT_RADIUS_M les uns des autres (cluster autour de chaque
    point candidat) et retourne (ratio_dominant, count_dominant, total). Un point 0,0 est ignoré
    du calcul de mouvement mais compté comme "masqué" ailleurs. Retour (None,0,0) si aucun point.
    """
    pts = [(s.get("lat"), s.get("lng")) for s in (samples or [])
           if s.get("lat") is not None and s.get("lng") is not None]
    total = len(pts)
    if total == 0:
        return None, 0, 0
    best = 0
    for cx, cy in pts:
        c = 0
        for lat, lng in pts:
            d = _haversine_m(cx, cy, lat, lng)
            if d is not None and d <= LKP_DOMINANT_RADIUS_M:
                c += 1
        best = max(best, c)
    return (best / total), best, total


def _samples_show_movement(samples) -> bool:
    """True si les positions se DÉPLACENT réellement (progression GPS reprise) :
    il existe au moins 2 samples distants de plus de LKP_RESUME_MIN_M (au-delà du jitter)."""
    pts = [(s.get("lat"), s.get("lng")) for s in (samples or [])
           if s.get("lat") is not None and s.get("lng") is not None
           and not _is_zero(s.get("lat"), s.get("lng"))]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = _haversine_m(pts[i][0], pts[i][1], pts[j][0], pts[j][1])
            if d is not None and d > LKP_RESUME_MIN_M:
                return True
    return False


async def _fetch_gps_samples(tenant_id: str, tracker_id: int,
                             since_iso: Optional[str]) -> list[dict]:
    """Lit plusieurs points GPS récents (READ-ONLY) via `track/read` avec le credential du tenant.
    Retour liste [{lat,lng,time}]. [] si indisponible. Ne logge/expose jamais le credential."""
    from app.integrations import get_integration_credential
    cred = get_integration_credential(tenant_id, "NAVIXY")
    if not cred or not cred.get("credential"):
        return []
    base = (cred.get("api_url") or os.environ.get("NAVIXY_API_URL")
            or "https://api.navixy.com/v2").rstrip("/")
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    start = _parse(since_iso) or (now - timedelta(minutes=30))
    fmt = "%Y-%m-%d %H:%M:%S"
    body = {"hash": cred["credential"], "tracker_id": int(tracker_id),
            "from": start.strftime(fmt), "to": (now + timedelta(minutes=1)).strftime(fmt),
            "simplify": False, "point_limit": 200}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post(f"{base}/track/read", json=body)
            data = r.json() or {}
    except Exception:
        return []
    out = []
    for p in (data.get("list") or []):
        if isinstance(p, dict):
            out.append({"lat": p.get("lat"), "lng": p.get("lng"),
                        "time": p.get("get_time") or p.get("time")})
    return out


async def _fetch_gps_state(tenant_id: str, tracker_id: int) -> Optional[dict]:
    """Lit l'état GPS transmis (READ-ONLY) via le credential du tenant. None si indispo.
    Ne logge/expose jamais le credential."""
    from app.integrations import get_integration_credential
    cred = get_integration_credential(tenant_id, "NAVIXY")
    if not cred or not cred.get("credential"):
        return None
    import httpx
    base = (cred.get("api_url") or os.environ.get("NAVIXY_API_URL")
            or "https://api.navixy.com/v2").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{base}/tracker/get_state",
                             json={"hash": cred["credential"], "tracker_id": int(tracker_id)})
            st = (r.json() or {}).get("state") or {}
    except Exception:
        return None
    gps = st.get("gps") or {}
    loc = gps.get("location") or {}
    return {
        "connection_status": st.get("connection_status"),
        "movement_status": st.get("movement_status"),
        "ignition": bool(st.get("ignition")),
        "gps_updated": gps.get("updated"),
        "speed": gps.get("speed"),
        "lat": loc.get("lat"), "lng": loc.get("lng"),
    }


def _is_zero(lat, lng) -> bool:
    try:
        return lat is not None and lng is not None and abs(float(lat)) < 1e-6 and abs(float(lng)) < 1e-6
    except (TypeError, ValueError):
        return False


async def telemetry_confirm(tenant_id: str, tracker_id: int, requested_state: str,
                            command_sent_at_iso: Optional[str], capability,
                            *, state_doc: Optional[dict] = None,
                            read_odo_km: Optional[Callable[[int], Awaitable[Optional[float]]]] = None,
                            fetch_samples: Optional[Callable[..., Awaitable[list]]] = None
                            ) -> tuple[Optional[str], str]:
    """Tente de confirmer l'état RÉEL du device par télémétrie (Niveau C).

    Deux stratégies (gated par capability field_validated) :
      - FROZEN_POSITION (FMC003) : PRIVATE si position 0,0 ou gelée depuis l'envoi (device actif).
        Comportement historique INCHANGÉ.
      - LAST_KNOWN_POSITION (FMC130 781479, prouvé terrain) : la confidentialité est prouvée par
        une POSITION DOMINANTE STABLE/RÉPÉTÉE sur PLUSIEURS samples (ratio >= LKP_DOMINANT_MIN_RATIO)
        TANDIS QUE l'AVL16 AUGMENTE — jamais par une simple distance à l'ancre, jamais sur 1 sample.
        Un déplacement réel de 50/100/150 m (positions qui suivent le véhicule) -> NON confirmé.
    BUSINESS : trame postérieure à l'envoi OFF, coords réelles, et PROGRESSION GPS reprise
    (petit déplacement réel suffit ; on n'impose PAS >200 m).
    Un simple `applied:true` Navixy n'est JAMAIS une preuve. Anti-stale : compare à command_sent_at.
    Retour (confirmed_state|None, source).
    """
    if not _model_supports_telemetry_confirm(capability):
        return None, SRC_UNCONFIRMED
    st = await _fetch_gps_state(tenant_id, tracker_id)
    if not st:
        return None, SRC_UNCONFIRMED
    sent = _parse(command_sent_at_iso) if command_sent_at_iso else None
    gps_upd = _parse(st.get("gps_updated"))
    active = (st.get("movement_status") == "moving") or st.get("ignition")
    strategy = _confirm_strategy(capability)
    sd = state_doc or {}

    # ----- Stratégie LAST_KNOWN_POSITION (profil FMC130 781479 field-validated) -----
    if strategy == CONFIRM_STRATEGY_LAST_KNOWN_POSITION:
        cur_lat, cur_lng = st.get("lat"), st.get("lng")
        fetch = fetch_samples or _fetch_gps_samples
        samples = await fetch(tenant_id, int(tracker_id), command_sent_at_iso)

        if requested_state == PRIVATE:
            # 1) AVL16 doit AUGMENTER depuis le snapshot de départ (roulage réel en privé).
            odo_start = sd.get("private_start_odometer_km")
            odo_now = await read_odo_km(int(tracker_id)) if read_odo_km else None
            odo_increases = (odo_start is not None and odo_now is not None
                             and float(odo_now) > float(odo_start))
            if not (active and odo_increases):
                return None, SRC_UNCONFIRMED
            # 2) Position masquée : 0,0 immédiat OU position DOMINANTE stable multi-samples.
            if _is_zero(cur_lat, cur_lng):
                return PRIVATE, SRC_TELEMETRY
            # jamais sur un seul sample : exiger un minimum d'observations
            if not samples or len(samples) < LKP_MIN_SAMPLES:
                return None, SRC_UNCONFIRMED
            ratio, dom_count, total = _dominant_position(samples)
            # position stable/répétée (ne suit plus le véhicule) alors que l'odo progresse -> masqué
            if ratio is not None and ratio >= LKP_DOMINANT_MIN_RATIO:
                return PRIVATE, SRC_TELEMETRY
            # positions qui se déplacent réellement (le GPS suit encore) -> pas encore masqué
            return None, SRC_UNCONFIRMED

        if requested_state == BUSINESS:
            # trame postérieure à l'envoi OFF + coords réelles
            if not (sent and gps_upd and gps_upd > sent):
                return None, SRC_UNCONFIRMED
            if _is_zero(cur_lat, cur_lng):
                return None, SRC_UNCONFIRMED
            # Preuve de REPRISE : progression GPS réelle (petit déplacement suffit, pas de seuil 200 m).
            # Soit les samples post-OFF montrent un mouvement, soit la position a quitté la zone
            # dominante privée d'au moins LKP_RESUME_MIN_M.
            if _samples_show_movement(samples):
                return BUSINESS, SRC_TELEMETRY
            anchor_lat = sd.get("private_gps_anchor_lat")
            anchor_lng = sd.get("private_gps_anchor_lng")
            if anchor_lat is not None and anchor_lng is not None:
                d = _haversine_m(anchor_lat, anchor_lng, cur_lat, cur_lng)
                if d is not None and d >= LKP_RESUME_MIN_M:
                    return BUSINESS, SRC_TELEMETRY
            return None, SRC_UNCONFIRMED
        return None, SRC_UNCONFIRMED

    # ----- Stratégie FROZEN_POSITION (FMC003 — comportement existant INCHANGÉ) -----
    if requested_state == PRIVATE:
        if _is_zero(st.get("lat"), st.get("lng")):
            return PRIVATE, SRC_TELEMETRY
        if sent and gps_upd and gps_upd <= sent and active:
            return PRIVATE, SRC_TELEMETRY
        return None, SRC_UNCONFIRMED

    if requested_state == BUSINESS:
        if sent and gps_upd and gps_upd > sent and not _is_zero(st.get("lat"), st.get("lng")):
            return BUSINESS, SRC_TELEMETRY
        return None, SRC_UNCONFIRMED

    return None, SRC_UNCONFIRMED


async def _default_read_odo_km(tracker_id: int) -> Optional[float]:
    """Lit l'odomètre AVL16 normalisé (km).
    - TEST/DEV avec simulate-confirm : renvoie une valeur horodatée monotone (E2E distance).
    - SIMULATION/REAL sans lecture : None (jamais inventé en prod)."""
    if simulate_confirm_enabled():
        import time
        # valeur monotone croissante (base fixe + secondes) -> delta > 0 entre start et end
        return round(56000.0 + (time.time() % 100000) / 1000.0, 3)
    return None


# Statuts explicites du snapshot odomètre (jamais 0 inventé ; null reste null).
ODO_SNAPSHOT_OK = "OK"
ODO_SNAPSHOT_UNAVAILABLE = "UNAVAILABLE"
ODO_SNAPSHOT_INVALID = "INVALID"


async def _read_odometer_snapshot(db, tenant_id, vehicle_id, tracker_id,
                                  read_odo_km) -> tuple[Optional[float], str]:
    """Snapshot odomètre AVL16 (km) pour la bascule Privé/Business. READ-ONLY, null≠0.

    Réutilise le lecteur CANONIQUE `read_live_avl16_km` en production (aucun 2e moteur).
    Retourne (value_km|None, status) où status ∈ OK|UNAVAILABLE|INVALID.

    - read_odo_km INJECTÉ (tests) : utilisé tel quel (préserve les tests avec mocks).
    - simulate-confirm (DEV E2E) : valeur monotone simulée.
    - PROD (lecteur par défaut) : read_live_avl16_km(db, tenant, vehicle) tenant-scopé.
    """
    # 1) Injection de test : le lecteur fourni prime, on ne touche pas au réseau.
    if read_odo_km is not _default_read_odo_km:
        v = await read_odo_km(int(tracker_id))
        return (v, ODO_SNAPSHOT_OK if v is not None else ODO_SNAPSHOT_UNAVAILABLE)
    # 2) DEV E2E simulate : valeur simulée monotone.
    if simulate_confirm_enabled():
        v = await _default_read_odo_km(int(tracker_id))
        return (v, ODO_SNAPSHOT_OK if v is not None else ODO_SNAPSHOT_UNAVAILABLE)
    # 3) PROD : lecteur AVL16 canonique (jamais l'odomètre générique, jamais 0).
    if db is None or not tenant_id or not vehicle_id:
        return (None, ODO_SNAPSHOT_UNAVAILABLE)
    from app.odometer_calibration import read_live_avl16_km
    reading = await read_live_avl16_km(db, tenant_id=tenant_id, vehicle_id=vehicle_id)
    reason = reading.get("reason")
    val = reading.get("value_km")
    if val is not None and reason is None:
        return (val, ODO_SNAPSHOT_OK)
    if reason == "VALUE_INVALID":
        return (None, ODO_SNAPSHOT_INVALID)
    return (None, ODO_SNAPSHOT_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Cœur : demande de bascule de mode (backend autoritaire, gate, idempotence).
# ---------------------------------------------------------------------------
async def request_mode(
    db, driver_id: str, target_mode: str, actor: str,
    *,
    resolve_session: Callable[..., Awaitable[Optional[dict]]],
    tenant_id: Optional[str] = None,
    send_command: Callable[[int, str], Awaitable[dict]] = _default_send_command,
    confirm: Callable[[int, str], Awaitable[tuple]] = _default_confirm,
    read_odo_km: Callable[[int], Awaitable[Optional[float]]] = _default_read_odo_km,
) -> dict:
    """Traite une intention métier PRIVATE|BUSINESS pour le véhicule de la session du chauffeur.

    - `resolve_session(db, driver_id)` -> session courante (doit contenir vehicle_id).
    - `tenant_id` : tenant réel de l'utilisateur (isolation multi-tenant). Défaut "default".
    Retour : {ok, state, allowed, reason, vehicle_id, tracker_id, private_distance_km?, ...}
    """
    if target_mode not in (PRIVATE, BUSINESS):
        return {"ok": False, "reason": "invalid_mode", "state": UNKNOWN}

    tid = tenant_id or _TENANT

    # --- Fail-closed niveau 1/2 : feature globale + kill switch AVANT toute résolution ---
    from app import private_mode_gate as gate
    if not gate.feature_enabled():
        return {"ok": False, "allowed": False, "reason": gate.R_FEATURE_DISABLED,
                "http": gate.HTTP_BY_REASON[gate.R_FEATURE_DISABLED], "state": UNKNOWN}
    if await gate.kill_switch_active(db):
        return {"ok": False, "allowed": False, "reason": gate.R_KILL_SWITCH,
                "http": gate.HTTP_BY_REASON[gate.R_KILL_SWITCH], "state": UNKNOWN}

    sess = await resolve_session(db, driver_id)
    if not sess or not sess.get("vehicle_id"):
        return {"ok": False, "reason": "no_active_vehicle", "state": UNKNOWN}
    vehicle_id = sess["vehicle_id"]

    vehicle = await db.vehicles.find_one(
        {"id": vehicle_id, "tenant_id": tid}, {"_id": 0}) or {}
    tracker_id = vehicle.get("navixy_tracker_id")
    model = resolve_model(vehicle.get("model"))

    # --- GATE CENTRALE d'autorisation (fail-closed, une seule source de vérité) ---
    from app.tenant_context import get_tenant_doc
    vc = await resolve_vehicle_capability(db, tracker_id, model)
    decision = await gate.can_use_private_mode(
        db, tenant_id=tid, tenant_doc=get_tenant_doc(tid),
        vehicle_doc=vehicle, capability=vc,
    )
    allowed = decision["allowed"]
    if not allowed:
        reason = decision["reason"]
        await _audit(db, {"driver_id": driver_id, "vehicle_id": vehicle_id,
                          "tracker_id": tracker_id, "requested_mode": target_mode,
                          "result": "refused", "reason": reason, "tenant_id": tid,
                          "gate_level": decision.get("level")})
        return {"ok": False, "allowed": False, "reason": reason,
                "http": decision.get("http", 403),
                "state": (await get_mode_state(db, vehicle_id)).get("state", UNKNOWN),
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    cur = await get_mode_state(db, vehicle_id)
    cur_state = cur.get("state", UNKNOWN)

    # --- Idempotence : déjà dans l'état cible -> no-op (aucune commande device) ---
    if cur_state == target_mode:
        return {"ok": True, "allowed": True, "can_switch": True, "state": cur_state,
                "idempotent": True, "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    # --- Anti-concurrence : une transition est déjà en cours (requested ou pending) ---
    if cur_state in (PRIVATE_REQUESTED, BUSINESS_REQUESTED, PENDING_CONFIRMATION):
        return {"ok": False, "allowed": True, "can_switch": False,
                "state": cur_state, "reason": gate.R_TRANSITION_IN_PROGRESS,
                "http": gate.HTTP_BY_REASON[gate.R_TRANSITION_IN_PROGRESS],
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    # --- FAIL-FAST : écriture device désactivée (PRIVATE_MODE_DEVICE_WRITE=0) ---
    # Éligibilité OK (allowed=True) MAIS aucune commande ne peut être envoyée au device.
    # On REFUSE AVANT toute création d'état transitoire : jamais de PRIVATE_REQUESTED /
    # BUSINESS_REQUESTED / PENDING_CONFIRMATION, jamais de commande device. L'état confirmé
    # précédent reste STRICTEMENT INCHANGÉ (BUSINESS->BUSINESS, PRIVATE->PRIVATE, UNKNOWN->UNKNOWN).
    if not device_write_enabled():
        await _audit(db, {"driver_id": driver_id, "vehicle_id": vehicle_id,
                          "tracker_id": tracker_id, "requested_mode": target_mode,
                          "result": "refused", "reason": gate.R_DEVICE_WRITE_DISABLED,
                          "tenant_id": tid, "state_preserved": cur_state})
        return {"ok": False, "allowed": True, "can_switch": False,
                "reason": gate.R_DEVICE_WRITE_DISABLED,
                "http": gate.HTTP_BY_REASON[gate.R_DEVICE_WRITE_DISABLED],
                "state": cur_state,  # INCHANGÉ (aucune transition créée)
                "vehicle_id": vehicle_id, "tracker_id": tracker_id}

    requested_state = PRIVATE_REQUESTED if target_mode == PRIVATE else BUSINESS_REQUESTED
    base = {"vehicle_id": vehicle_id, "tracker_id": tracker_id, "tenant_id": tid,
            "driver_id": driver_id, "previous_state": cur_state}

    # --- Snapshot odomètre à l'ENTRÉE en privé (avant bascule) ---
    if target_mode == PRIVATE:
        odo_start, snap_status = await _read_odometer_snapshot(
            db, tid, vehicle_id, tracker_id, read_odo_km)
        base["private_start_time"] = _now()
        base["private_start_odometer_km"] = odo_start        # null reste null (jamais 0)
        base["odometer_snapshot_status"] = snap_status       # OK|UNAVAILABLE|INVALID
        base["odometer_source"] = SOURCE_TELTONIKA_TOTAL_ODOMETER
        # Ancre GPS de dernière position connue (stratégie LAST_KNOWN_POSITION) — INTERNE :
        # sert uniquement à confirmer/masquer, jamais exposée au frontend. Best-effort.
        try:
            gps0 = await _fetch_gps_state(tid, int(tracker_id))
        except Exception:
            gps0 = None
        if gps0 and gps0.get("lat") is not None and gps0.get("lng") is not None:
            base["private_gps_anchor_lat"] = gps0.get("lat")
            base["private_gps_anchor_lng"] = gps0.get("lng")

    await _save_mode_state(db, {**cur, **base, "state": requested_state})

    # --- Envoi commande device (GATED) ---
    cmd = _CMD[target_mode]
    cmd_res = await send_command(int(tracker_id), cmd)

    # --- Confirmation IMMÉDIATE (jamais optimiste) ---
    confirmed_state, confirm_source = await confirm(int(tracker_id), target_mode)

    if confirmed_state != target_mode:
        # Pas de confirmation immédiate. On distingue :
        #  - commande RÉELLE envoyée (mode REAL) -> PENDING_CONFIRMATION (honnête : envoyée,
        #    confirmation télémétrique à venir de façon asynchrone). JAMAIS FAILED d'office.
        #  - simulation/off -> reste en REQUESTED (aucune commande réelle partie).
        if cmd_res.get("mode") == "REAL":
            pend = {**cur, **base, "state": PENDING_CONFIRMATION,
                    "requested_target": target_mode, "last_command": cmd,
                    "command_sent_at": _now(), "confirmation_source": SRC_UNCONFIRMED,
                    "navixy_command_id": cmd_res.get("navixy_command_id")}
            await _save_mode_state(db, pend)
            await _audit(db, {**base, "requested_mode": target_mode,
                              "resulting_state": PENDING_CONFIRMATION, "result": "sent_pending",
                              "confirmation_source": SRC_UNCONFIRMED,
                              "command_mode": "REAL",
                              "navixy_command_id": cmd_res.get("navixy_command_id")})
            return {"ok": True, "allowed": True, "state": PENDING_CONFIRMATION,
                    "pending": True, "reason": "pending_confirmation",
                    "confirmation_source": SRC_UNCONFIRMED,
                    "vehicle_id": vehicle_id, "tracker_id": tracker_id}
        # Non-REAL (simulation off / navixy non configuré) : état transitoire honnête.
        final = PRIVATE_REQUESTED if target_mode == PRIVATE else BUSINESS_REQUESTED
        await _save_mode_state(db, {**cur, **base, "state": final,
                                    "requested_target": target_mode, "last_command": cmd,
                                    "confirmation_source": confirm_source})
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
        odo_end, _ = await _read_odometer_snapshot(
            db, tid, vehicle_id, tracker_id, read_odo_km)
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


# Fenêtre max d'attente d'une confirmation télémétrique avant de basculer en UNKNOWN.
PENDING_TIMEOUT_S = int(os.environ.get("PRIVATE_MODE_PENDING_TIMEOUT_S", "300"))


async def resolve_pending_confirmation(db, vehicle_id: str, tenant_id: Optional[str] = None,
                                       *, read_odo_km=_default_read_odo_km) -> dict:
    """Résout (best-effort, READ-ONLY) un état PENDING_CONFIRMATION via la télémétrie.

    - Confirme -> CONFIRMED PRIVATE/BUSINESS (source TELEMETRY_CONFIRMED) + calcule la distance
      privée au retour Business.
    - Si pas de preuve ET timeout dépassé -> UNKNOWN (honnête, jamais faux succès/échec).
    - Sinon reste PENDING_CONFIRMATION.
    Appelable à chaque GET d'état (et/ou par le scheduler). N'envoie AUCUNE commande.
    """
    st = await get_mode_state(db, vehicle_id)
    if st.get("state") != PENDING_CONFIRMATION:
        return st
    tid = tenant_id or st.get("tenant_id") or _TENANT
    tracker_id = st.get("tracker_id")
    requested = st.get("requested_target")
    if not tracker_id or requested not in (PRIVATE, BUSINESS):
        return st

    # capability (gate télémétrie : profil field_validated uniquement)
    vehicle = await db.vehicles.find_one({"id": vehicle_id, "tenant_id": tid}, {"_id": 0}) or {}
    vc = await resolve_vehicle_capability(db, tracker_id, resolve_model(vehicle.get("model")))

    confirmed, source = await telemetry_confirm(
        tid, int(tracker_id), requested, st.get("command_sent_at"), vc,
        state_doc=st, read_odo_km=read_odo_km)

    if confirmed == requested:
        new_doc = {**st, "state": requested, "confirmation_source": source,
                   "confirmed_at": _now(), "transition_result": TRANSITION_CONFIRMED}
        new_doc.pop("requested_target", None)
        # distance privée au retour Business (jamais inventée)
        if requested == BUSINESS and st.get("private_start_odometer_km") is not None:
            odo_end, _ = await _read_odometer_snapshot(
                db, tid, vehicle_id, tracker_id, read_odo_km)
            new_doc["private_end_time"] = _now()
            new_doc["private_end_odometer_km"] = odo_end
            new_doc["private_distance_km"] = _private_distance(
                st.get("private_start_odometer_km"), odo_end)
        # Nettoyage des coordonnées d'ancre (usage interne de confirmation uniquement).
        if requested == BUSINESS:
            new_doc.pop("private_gps_anchor_lat", None)
            new_doc.pop("private_gps_anchor_lng", None)
        await _save_mode_state(db, new_doc)
        await _audit(db, {"vehicle_id": vehicle_id, "tracker_id": tracker_id, "tenant_id": tid,
                          "requested_mode": requested, "resulting_state": requested,
                          "result": "confirmed_async", "confirmation_source": source})
        return new_doc

    # pas de preuve -> timeout ?
    sent = _parse(st.get("command_sent_at"))
    if sent:
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - sent).total_seconds()
        if age >= PENDING_TIMEOUT_S:
            # Fenêtre dépassée SANS preuve télémétrique. On ne prétend JAMAIS connaître
            # l'état réel du device. On libère les boutons (pending=false) tout en
            # PRÉSERVANT l'historique (requested_target/last_command/command_sent_at via **st).
            prev = st.get("previous_state")
            # Retour au dernier état CONFIRMÉ si connu (BUSINESS/PRIVATE) ; sinon UNKNOWN.
            final_state = prev if prev in (BUSINESS, PRIVATE) else UNKNOWN
            timed = {**st, "state": final_state,
                     "confirmation_source": SRC_UNCONFIRMED,
                     "transition_result": TRANSITION_TIMEOUT,
                     "pending_timeout_at": _now()}
            await _save_mode_state(db, timed)
            await _audit(db, {"vehicle_id": vehicle_id, "tracker_id": tracker_id, "tenant_id": tid,
                              "requested_mode": requested, "resulting_state": final_state,
                              "result": "pending_timeout",
                              "transition_result": TRANSITION_TIMEOUT,
                              "previous_state": prev})
            return timed
    return st  # toujours PENDING


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
