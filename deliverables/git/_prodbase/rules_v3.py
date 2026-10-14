"""Auto-classification rule engine.

Simplified model (Iteration 4):
- Vehicle mode override: always_pro / always_perso wins
- Otherwise, per-day schedule: each day is 'work' or 'personal'.
  When 'work', up to 3 enabled time periods define WHEN it is professional.
  Everything outside those periods is personal.
  When 'personal', the whole day is personal.
- Schedules are stored in `db.schedules`. A schedule with driver_id=None is the
  default; per-driver overrides are looked up by driver_id and fall back to default.

Stratégie 'privacy_history_strict' (pilote Journal de bord, scope PAR VÉHICULE) :
l'état PRO/PRIVÉ réellement CONFIRMÉ (télémétrie) prime ; aucun fallback horaire ;
une classification existante n'est JAMAIS remplacée par None ; le manuel est intouchable.
Isolation multi-tenant stricte (fail-safe sans tenant + filtrage tenant explicite).
"""
from datetime import datetime, timezone
from typing import Optional

import logging

logger = logging.getLogger(__name__)


def _parse_hm(s: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _in_any_period(minute_of_day: int, periods: list[dict]) -> bool:
    for p in periods or []:
        if not p.get("enabled"):
            continue
        f = _parse_hm(p.get("from", "00:00"))
        t = _parse_hm(p.get("to", "00:00"))
        if t <= f:
            continue
        if f <= minute_of_day < t:
            return True
    return False


# ---------------------------------------------------------------------------
# Stratégie PRIVACY_HISTORY_STRICT (pilote Journal de bord / mode privé)
# ---------------------------------------------------------------------------
# Règle métier : la classification d'un trajet suit l'ÉTAT PRO/PRIVÉ RÉELLEMENT
# confirmé (télémétrie) au moment du départ. AUCUN fallback horaire.
#  - preuve confirmée BUSINESS <= FRESH avant le départ -> 'professional'
#  - preuve confirmée PRIVATE  <= FRESH avant le départ -> 'personal'
#  - preuve trop ancienne / absente / changement de mode PENDANT le trajet -> None
# Les seuils sont PORTÉS PAR LA STRATÉGIE (pas dispersés en dur ailleurs).
CLASSIFICATION_STRATEGY_LEGACY = "legacy"
CLASSIFICATION_STRATEGY_PRIVACY = "privacy_history_strict"

# Seuil de fraîcheur (secondes) : seule une preuve confirmée au plus FRESH avant le
# départ autorise une auto-classification (confiance HAUTE). Défaut 2 h.
PRIVACY_FRESH_MAX_S = 2 * 3600


def _parse_iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def classify_by_mode_history(trip: dict, confirmed_events: list[dict],
                             fresh_max_s: int = PRIVACY_FRESH_MAX_S) -> Optional[str]:
    """PURE/testable. Décide la classification d'un trajet selon l'historique mode CONFIRMÉ.

    `confirmed_events` : liste d'événements { 'ts': iso, 'state': 'BUSINESS'|'PRIVATE' }
    TRIÉE par ts croissant, ne contenant QUE des états confirmés (preuve forte).

    Retour : 'professional' | 'personal' | None (À classer — fail-closed).
    """
    start = _parse_iso(trip.get("start_time"))
    end = _parse_iso(trip.get("end_time"))
    if not start:
        return None

    # 1) Changement de mode confirmé PENDANT le trajet -> traitement spécial -> À classer.
    if end:
        for ev in confirmed_events:
            et = _parse_iso(ev.get("ts"))
            if et and start < et <= end:
                return None

    # 2) Dernier état confirmé STRICTEMENT avant le départ.
    last = None
    for ev in confirmed_events:
        et = _parse_iso(ev.get("ts"))
        if et and et <= start:
            last = (et, ev.get("state"))
        else:
            break
    if not last:
        return None  # aucune preuve avant -> À classer

    et, state = last
    gap_s = (start - et).total_seconds()
    if gap_s < 0 or gap_s > fresh_max_s:
        return None  # preuve trop ancienne (pas de propagation multi-heures) -> À classer

    if state == "PRIVATE":
        return "personal"
    if state == "BUSINESS":
        return "professional"
    return None


async def _confirmed_mode_events(db, vehicle_id: str) -> list[dict]:
    """Lit audit_log (scope=private_mode) et renvoie les états CONFIRMÉS (preuve forte),
    triés par ts croissant : [{'ts':..., 'state':'BUSINESS'|'PRIVATE'}, ...]."""
    out: list[dict] = []
    cursor = db.audit_log.find(
        {"scope": "private_mode", "vehicle_id": vehicle_id,
         "resulting_state": {"$in": ["BUSINESS", "PRIVATE"]}},
        {"_id": 0, "ts": 1, "resulting_state": 1, "result": 1},
    ).sort("ts", 1)
    async for e in cursor:
        res = str(e.get("result") or "")
        if "confirmed" in res:  # confirmed / confirmed_async / confirmed_late
            out.append({"ts": e.get("ts"), "state": e.get("resulting_state")})
    return out


def classify_trip(trip: dict, vehicle: Optional[dict], settings: dict, schedule: dict) -> str:
    """Return 'professional' or 'personal'.

    Priority cascade (highest first):
      1. `trip.mobile_override`        — driver's choice from the mobile app/PWA
      2. `vehicle.mode`                — 'always_pro' / 'always_perso'
      3. `trip.geofence_classification` — set by geofence engine (if any)
      4. `schedule`                    — per-day work periods (default fallback)

    `schedule` is a dict with shape: { days: [ {day: 0..6, type: 'work'|'personal',
    periods: [ {enabled, from, to}, ... ] }, ... ] }
    """
    # 1. Mobile override (driver's manual choice — absolute priority)
    mob = (trip or {}).get("mobile_override")
    if mob in ("professional", "personal"):
        return mob

    # 2. Vehicle mode override
    if vehicle:
        vmode = vehicle.get("mode")
        if vmode == "always_pro":
            return "professional"
        if vmode == "always_perso":
            return "personal"

    # 3. Geofence classification (precomputed by upstream engine)
    geo = (trip or {}).get("geofence_classification")
    if geo in ("professional", "personal"):
        return geo

    # 4. Schedule fallback
    try:
        start_dt = datetime.fromisoformat(trip["start_time"].replace("Z", "+00:00"))
    except Exception:
        return "professional"

    weekday = start_dt.weekday()  # 0=Mon ... 6=Sun
    day_cfg = None
    for d in schedule.get("days", []):
        if d.get("day") == weekday:
            day_cfg = d
            break
    if not day_cfg or day_cfg.get("type") == "personal":
        return "personal"

    minute_of_day = start_dt.hour * 60 + start_dt.minute
    return "professional" if _in_any_period(minute_of_day, day_cfg.get("periods", [])) else "personal"


async def _get_schedule_for(db, driver_id: Optional[str]) -> dict:
    """Resolve schedule: per-driver override OR default."""
    if driver_id:
        s = await db.schedules.find_one({"driver_id": driver_id}, {"_id": 0})
        if s:
            return s
    s = await db.schedules.find_one({"driver_id": None}, {"_id": 0})
    if not s:
        s = default_schedule(driver_id=None)
        await db.schedules.insert_one(dict(s))
    return s


def _effective_strategy(vehicle: Optional[dict], settings: dict) -> str:
    """Stratégie de classification EFFECTIVE pour un véhicule.

    Priorité : override VÉHICULE (vehicle.classification_mode) > tenant
    (settings.classification_mode) > 'legacy'. Aucun ID hardcodé : le périmètre
    pilote est porté par le champ `classification_mode` du véhicule concerné.
    """
    v = (vehicle or {}).get("classification_mode")
    if v in (CLASSIFICATION_STRATEGY_LEGACY, CLASSIFICATION_STRATEGY_PRIVACY):
        return v
    s = settings.get("classification_mode")
    if s in (CLASSIFICATION_STRATEGY_LEGACY, CLASSIFICATION_STRATEGY_PRIVACY):
        return s
    return CLASSIFICATION_STRATEGY_LEGACY


async def apply_rules_to_all(db):
    """Reclassify auto-classified trips. Stratégie résolue PAR VÉHICULE.

    Chaque trajet est classé selon la stratégie EFFECTIVE de SON véhicule :
      - 'legacy' (défaut)        : logique horaire/zones existante (INCHANGÉE) ;
      - 'privacy_history_strict' : état PRO/PRIVÉ CONFIRMÉ prioritaire, jamais
        d'écrasement d'une classification existante par None, pas de fallback horaire.

    Périmètre pilote = véhicules portant vehicle.classification_mode='privacy_history_strict'
    (override véhicule). Les autres véhicules restent strictement en 'legacy'.

    ISOLATION MULTI-TENANT (fail-safe) : la reclassification NE DOIT JAMAIS s'exécuter
    hors d'un contexte tenant. Si aucun tenant n'est posé (get_tenant_id() is None),
    on REFUSE de tourner (return 0 + log). Cela empêche qu'un appel non scopé lise les
    settings d'un tenant et reclasse les véhicules de TOUS les tenants (cause de la
    régression cross-tenant : events audit sans tenant_id, véhicules multi-tenant impactés).
    """
    from app.tenant_context import get_tenant_id
    tenant_id = get_tenant_id()
    if not tenant_id:
        logger.error("apply_rules_to_all: appel SANS contexte tenant -> REFUSÉ (fail-safe). "
                     "Aucune reclassification effectuée.")
        return 0

    # Défense en profondeur : filtrage EXPLICITE par tenant_id dans toutes les requêtes
    # (en plus du proxy TenantScopedDB), pour ne jamais dépendre uniquement de l'isolation
    # implicite (get_db() renvoie le db BRUT si aucun tenant n'est posé).
    tf = {"tenant_id": tenant_id}
    settings = await db.settings.find_one({"id": "default", **tf}, {"_id": 0}) or default_settings()
    vehicles = {v["id"]: v async for v in db.vehicles.find(tf, {"_id": 0})}

    # Véhicules en stratégie PRIVACY (override véhicule OU tenant en privacy).
    privacy_vehicle_ids = {
        vid for vid, v in vehicles.items()
        if _effective_strategy(v, settings) == CLASSIFICATION_STRATEGY_PRIVACY
    }

    updated = 0
    # 1) Véhicules PRIVACY -> moteur strict (anti-régression). Scope tenant + véhicules.
    if privacy_vehicle_ids:
        updated += await _apply_privacy_history_strict(db, settings, privacy_vehicle_ids, tenant_id)

    # 2) Véhicules LEGACY -> logique horaire existante (STRICTEMENT inchangée).
    forced_vehicle_ids = [
        vid for vid, v in vehicles.items()
        if v.get("mode") in ("always_pro", "always_perso") and vid not in privacy_vehicle_ids
    ]
    default_sched = await _get_schedule_for(db, None)
    # Cache per-driver schedules
    cache: dict = {}
    # Filtrage explicite tenant (défense en profondeur).
    query = {"$and": [tf, {"$or": [{"auto_classified": True}]}]}
    if forced_vehicle_ids:
        query["$and"][1]["$or"].append({"vehicle_id": {"$in": forced_vehicle_ids}})
    async for trip in db.trips.find(query, {"_id": 0}):
        vid = trip.get("vehicle_id")
        if vid in privacy_vehicle_ids:
            continue  # déjà traité par le moteur strict
        drv = trip.get("driver_id")
        if drv in cache:
            sched = cache[drv]
        elif drv:
            sched = await db.schedules.find_one({"driver_id": drv}, {"_id": 0}) or default_sched
            cache[drv] = sched
        else:
            sched = default_sched
        cls = classify_trip(trip, vehicles.get(vid), settings, sched)
        if trip.get("classification") != cls:
            await db.trips.update_one(
                {"id": trip["id"]},
                {"$set": {"classification": cls, "auto_classified": True}},
            )
            updated += 1
    return updated


async def _apply_privacy_history_strict(db, settings, vehicle_ids: Optional[set] = None,
                                        tenant_id: Optional[str] = None) -> int:
    """Stratégie privacy_history_strict : classe par historique mode CONFIRMÉ.

    PÉRIMÈTRE : si `vehicle_ids` est fourni, SEULS ces véhicules sont traités
    (scope pilote via override véhicule). `tenant_id` filtre explicitement (isolation).

    RÈGLE DE PRÉSERVATION (anti-régression) :
    - auto existante + preuve fraîche CONTRADICTOIRE -> corriger ;
    - auto existante + PAS de preuve fraîche        -> CONSERVER l'existant (jamais -> None) ;
    - None + preuve fraîche                         -> classifier ;
    - None + preuve insuffisante                    -> rester None ;
    - manuel (auto_classified=False)                -> jamais touché.

    Autrement dit : on n'ÉCRASE JAMAIS une classification existante par None.
    """
    fresh_max_s = int(settings.get("classification_fresh_max_s") or PRIVACY_FRESH_MAX_S)
    tf = {"tenant_id": tenant_id} if tenant_id else {}
    vehicles = {v["id"]: v async for v in db.vehicles.find(tf, {"_id": 0})}
    events_cache: dict = {}
    updated = 0
    trip_query = {**tf, "auto_classified": {"$ne": False}}
    if vehicle_ids is not None:
        trip_query["vehicle_id"] = {"$in": list(vehicle_ids)}
    async for trip in db.trips.find(trip_query, {"_id": 0}):
        vid = trip.get("vehicle_id")
        # Garde-fou périmètre : ne jamais traiter un véhicule hors scope.
        if vehicle_ids is not None and vid not in vehicle_ids:
            continue
        veh = vehicles.get(vid) or {}

        # Politique véhicule explicite (prioritaire, inchangée).
        vmode = veh.get("mode")
        if vmode == "always_pro":
            cls = "professional"
        elif vmode == "always_perso":
            cls = "personal"
        else:
            # Override mobile chauffeur = preuve explicite (prioritaire).
            mob = trip.get("mobile_override")
            if mob in ("professional", "personal"):
                cls = mob
            else:
                if vid not in events_cache:
                    events_cache[vid] = await _confirmed_mode_events(db, vid)
                cls = classify_by_mode_history(trip, events_cache[vid], fresh_max_s)

        current = trip.get("classification")

        # GARDE-FOU ANTI-RÉGRESSION : ne JAMAIS remplacer une classification
        # existante (professional/personal) par None (preuve insuffisante).
        # On n'écrit que si la cible est une valeur concrète ET différente.
        if cls not in ("professional", "personal"):
            continue  # preuve insuffisante -> on conserve l'existant (ou on laisse None)
        if current == cls:
            continue  # idempotent

        await db.trips.update_one(
            {"id": trip["id"]},
            {"$set": {"classification": cls, "auto_classified": True}},
        )
        # Audit de la correction (traçabilité + tenant_id explicite, jamais de secret).
        try:
            await db.audit_log.insert_one({
                "ts": datetime.now(timezone.utc).isoformat(),
                "scope": "trip_classification",
                "strategy": CLASSIFICATION_STRATEGY_PRIVACY,
                "tenant_id": tenant_id,
                "trip_id": trip.get("id"),
                "vehicle_id": vid,
                "old_classification": current,
                "new_classification": cls,
                "reason": "privacy_history_strict",
            })
        except Exception:
            pass
        updated += 1
    return updated


def default_settings() -> dict:
    return {
        "id": "default",
        "mode": "mixte",  # mixte = visible / masked = anonymisé
    }


def default_schedule(driver_id: Optional[str] = None) -> dict:
    """Default schedule: Mon-Fri = work 07:00-12:00 and 13:00-18:00; Sat/Sun = personal."""
    days = []
    for i in range(7):
        if i < 5:  # Mon..Fri
            days.append({
                "day": i,
                "type": "work",
                "periods": [
                    {"enabled": True, "from": "07:00", "to": "12:00"},
                    {"enabled": True, "from": "13:00", "to": "18:00"},
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                ],
            })
        else:
            days.append({
                "day": i,
                "type": "personal",
                "periods": [
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                    {"enabled": False, "from": "00:00", "to": "00:00"},
                ],
            })
    return {
        "id": f"sched-{driver_id or 'default'}",
        "tenant_id": "default",
        "driver_id": driver_id,
        "days": days,
    }
