"""BLE-based driver identification engine (Phase A — MVP).

Three core operations:

1. **Ingest a detection**: a phone (PWA / future native app) sends a BLE detection
   for the currently logged-in driver. The engine resolves the BLE identifier to
   a vehicle, recomputes confidence, and opens / extends / closes
   `driver_sessions`.

2. **Driver manual override**: the driver presses PRO or PRIVÉ in the app. We
   stamp `mobile_override` on the active session AND propagate it to every trip
   of (driver, vehicle) starting after the toggle until the session closes.

3. **Admin actions**: list / amend / validate sessions; CRUD on BLE tag ↔
   vehicle mapping; simulate a detection (testing without physical hardware).

Sessions lifecycle:
- A session is **open** while at least one detection arrived in the last
  SESSION_TIMEOUT minutes for the same (driver, vehicle).
- When the driver switches to another vehicle (stronger RSSI on a different
  tag), the previous session is closed (status = 'closed').
- Confidence score is recomputed at every detection.

Confidence (0..100):
  35 % — Signal stability (low RSSI variance)
  25 % — Signal strength (median RSSI normalized vs floor)
  20 % — Presence duration (minutes within window)
  20 % — Historical pairing (how often this driver was on this vehicle)

Settings (db.settings keys):
- `ble_enabled`           (default True)
- `ble_min_duration_s`    (default 120)  — must accumulate this before auto-classify
- `ble_min_rssi`          (default -85) — anything weaker is ignored
- `ble_min_confidence`    (default 60)  — below ⇒ status='pending' (asks for validation)
- `allow_driver_override` (default True)
"""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

# A session is considered ongoing if a detection arrived in the last X minutes.
SESSION_TIMEOUT = timedelta(minutes=5)
# Window over which we compute confidence (median RSSI, variance, ...).
RECENT_WINDOW = timedelta(minutes=30)

# Statuts « en cours » d'une session (avant clôture définitive)
OPEN_STATUSES = ["open", "automatic", "pending", "manual", "confirmed", "ending"]

DEFAULT_SETTINGS = {
    "ble_enabled": True,
    "ble_min_duration_s": 120,
    "ble_min_rssi": -85,
    "ble_min_confidence": 60,
    "allow_driver_override": True,
    "app_claim_conflict_window_min": 10,
    "session_close_grace_min": 10,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_ble_settings(db) -> dict:
    s = await db.settings.find_one({"id": "default"}, {"_id": 0}) or {}
    return {k: s.get(k, v) for k, v in DEFAULT_SETTINGS.items()}


def normalize_identifier(raw: str | None) -> str:
    """Canonicalise a BLE identifier.

    Accepts any of:
        BC:57:29:1D:22:C5   (colon MAC)
        BC-57-29-1D-22-C5   (dash MAC)
        BC57291D22C5        (compact MAC)
        bc 57 29 1d 22 c5   (lowercase, spaces)
        KBPro_653127        (device name)
    Returns:
        BC57291D22C5        (compact, uppercase) for MACs
        KBPRO_653127        (uppercase) for arbitrary names

    The function strips ':', '-', ' ', '.', '/' and uppercases. Empty input
    returns an empty string. The same normalisation is applied at WRITE time
    (when an admin saves a tag) AND at READ time (when a detection comes in),
    so any of the input formats matches.
    """
    if not raw:
        return ""
    return "".join(c for c in str(raw) if c not in ":-. /").upper()


# ---------- Tag CRUD helpers ----------
async def list_tags(db) -> list[dict]:
    return await db.ble_tags.find({"tenant_id": "default"}, {"_id": 0}).to_list(1000)


async def upsert_tag(db, payload: dict) -> dict:
    raw_id = payload["identifier"]
    tag = {
        "id": payload.get("id") or str(uuid.uuid4()),
        "tenant_id": "default",
        "vehicle_id": payload["vehicle_id"],
        # Canonical form used for matching incoming detections.
        "identifier": normalize_identifier(raw_id),
        # Keep the original spelling for display (e.g. "BC:57:29:1D:22:C5").
        "identifier_raw": raw_id.strip() if isinstance(raw_id, str) else str(raw_id),
        "label": payload.get("label") or raw_id,
        "created_at": payload.get("created_at") or now_iso(),
        "updated_at": now_iso(),
    }
    await db.ble_tags.update_one({"id": tag["id"]}, {"$set": tag}, upsert=True)
    return tag


async def delete_tag(db, tag_id: str) -> bool:
    r = await db.ble_tags.delete_one({"id": tag_id, "tenant_id": "default"})
    return r.deleted_count > 0


async def _resolve_tag(db, identifier: str) -> Optional[dict]:
    canon = normalize_identifier(identifier)
    if not canon:
        return None
    # Try the canonical column first, fall back to the legacy `identifier` field
    # for tags created before normalisation was introduced.
    tag = await db.ble_tags.find_one(
        {"tenant_id": "default", "identifier": canon}, {"_id": 0},
    )
    if tag:
        return tag
    # Legacy fallback: scan and normalise on the fly (small collection, <1000 rows).
    cursor = db.ble_tags.find({"tenant_id": "default"}, {"_id": 0})
    async for row in cursor:
        if normalize_identifier(row.get("identifier") or "") == canon:
            return row
    # Alias fallback: Chrome Web Bluetooth anonymizes the device MAC and returns
    # an opaque token instead. An admin can pair such a token to a tag via the
    # "Apprentissage" flow — this is where we resolve it.
    alias = await db.ble_aliases.find_one(
        {"tenant_id": "default", "alias_id": canon}, {"_id": 0},
    )
    if alias and alias.get("tag_identifier"):
        tag = await db.ble_tags.find_one(
            {"tenant_id": "default", "identifier": alias["tag_identifier"]}, {"_id": 0},
        )
        return tag
    return None


def _detection_meta(payload: dict) -> dict:
    """Extract the optional rich metadata sent by the Expo native app
    (and tolerated for the PWA when Web Bluetooth provides them).

    Returns a dict ready to be merged into a `ble_detections` document.
    Empty values are stored as None so that the field is present and
    indexable by the Debug query later.
    """
    return {
        "platform": payload.get("platform"),
        "battery": payload.get("battery"),
        "local_name": payload.get("local_name") or payload.get("localName"),
        "device_id": payload.get("device_id") or payload.get("deviceId"),
        "manufacturer_data": payload.get("manufacturer_data") or payload.get("manufacturerData"),
        "service_uuids": payload.get("service_uuids") or payload.get("serviceUUIDs") or payload.get("serviceUuids"),
    }


# ---------- Detection ingestion ----------
async def ingest_detection(db, driver_id: str, payload: dict) -> dict:
    """Store a detection and update the driver's current session.

    Returns a summary `{ session, tag, vehicle, confidence }` for the caller
    (PWA console uses this to know which vehicle was matched).
    """
    settings = await get_ble_settings(db)
    rssi = int(payload.get("rssi") or -100)
    meta = _detection_meta(payload)

    if rssi < settings["ble_min_rssi"]:
        await db.ble_detections.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "driver_id": driver_id,
            "identifier": payload.get("identifier", ""),
            "rssi": rssi,
            "ts": payload.get("ts") or now_iso(),
            "ignored": True,
            "ignore_reason": "rssi_below_floor",
            **meta,
        })
        return {"ignored": True, "reason": "rssi_below_floor"}

    tag = await _resolve_tag(db, payload["identifier"])
    if not tag:
        await db.ble_detections.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "driver_id": driver_id,
            "identifier": payload.get("identifier", ""),
            "rssi": rssi,
            "ts": payload.get("ts") or now_iso(),
            "ignored": True,
            "ignore_reason": "unknown_tag",
            **meta,
        })
        return {"ignored": True, "reason": "unknown_tag"}

    detection = {
        "id": str(uuid.uuid4()),
        "tenant_id": "default",
        "driver_id": driver_id,
        "vehicle_id": tag["vehicle_id"],
        "ble_tag_id": tag["id"],
        "identifier": tag["identifier"],
        "rssi": rssi,
        "ts": payload.get("ts") or now_iso(),
        "ignored": False,
        **meta,
    }
    await db.ble_detections.insert_one(detection)

    # Open / extend / close session
    session = await _update_session(db, driver_id, tag["vehicle_id"], detection, settings)
    vehicle = await db.vehicles.find_one({"id": tag["vehicle_id"]}, {"_id": 0})

    return {
        "ignored": False,
        "session": session,
        "tag": tag,
        "vehicle": vehicle,
        "confidence": session.get("confidence"),
    }


def _merge_sources(current: str | None, incoming: str) -> str:
    if not current:
        return incoming
    if current == incoming:
        return current
    if current == "MANUEL" or incoming == "MANUEL":
        return "MANUEL"
    return "APP+BLE"


async def _try_set_active(db, sess: dict) -> bool:
    """Un seul conducteur actif par véhicule — garanti par index unique partiel."""
    try:
        await db.driver_sessions.update_one(
            {"id": sess["id"], "active_driver": {"$ne": True}},
            {"$set": {"active_driver": True, "active_since": now_iso()}})
        return True
    except DuplicateKeyError:
        return False


async def _update_session(db, driver_id: str, vehicle_id: str,
                          detection: dict, settings: dict,
                          identification_source: str = "APP+BLE") -> dict:
    """Open or extend the current session for (driver, vehicle).

    Closes any other open session for this driver on a different vehicle.
    """
    # Close stale / other sessions
    cutoff = (datetime.now(timezone.utc) - SESSION_TIMEOUT).isoformat()
    async for s in db.driver_sessions.find(
        {"driver_id": driver_id, "status": {"$in": OPEN_STATUSES}},
        {"_id": 0},
    ):
        if s["vehicle_id"] != vehicle_id or (s.get("last_seen") or "") < cutoff:
            await db.driver_sessions.update_one(
                {"id": s["id"]},
                {"$set": {"status": "closed", "active_driver": False,
                          "ended_at": s.get("last_seen") or now_iso()}},
            )

    # Find the still-open one for this exact (driver, vehicle)
    open_sess = await db.driver_sessions.find_one(
        {"driver_id": driver_id, "vehicle_id": vehicle_id,
         "status": {"$in": OPEN_STATUSES}},
        {"_id": 0},
    )

    if not open_sess:
        open_sess = {
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "driver_id": driver_id,
            "vehicle_id": vehicle_id,
            "ble_tag_id": detection.get("ble_tag_id"),
            "source": "ble",
            "identification_source": identification_source,
            "active_driver": False,
            "status": "open",
            "started_at": detection["ts"],
            "ended_at": None,
            "last_seen": detection["ts"],
            "detection_count": 1,
            "last_rssi": detection["rssi"],
            "mobile_override": None,
            "confidence": 0,
            "created_at": now_iso(),
        }
        await db.driver_sessions.insert_one(open_sess)
        open_sess.pop("_id", None)
    else:
        open_sess["last_seen"] = detection["ts"]
        open_sess["detection_count"] = (open_sess.get("detection_count") or 0) + 1
        open_sess["last_rssi"] = detection["rssi"]

    # Confidence recompute
    confidence = await _compute_confidence(db, open_sess, settings)
    open_sess["confidence"] = confidence

    # Status promotion — une identité confirmée (APP) n'est jamais rétrogradée
    # par une simple détection, un conflit reste un conflit jusqu'à résolution.
    if open_sess.get("status") in ("confirmed", "conflict"):
        new_status = open_sess["status"]
    else:
        new_status = _derive_status(open_sess, settings)
    open_sess["status"] = new_status
    merged_src = _merge_sources(open_sess.get("identification_source"), identification_source)
    open_sess["identification_source"] = merged_src

    await db.driver_sessions.update_one(
        {"id": open_sess["id"]},
        {"$set": {
            "last_seen": open_sess["last_seen"],
            "detection_count": open_sess["detection_count"],
            "last_rssi": open_sess["last_rssi"],
            "confidence": confidence,
            "status": new_status,
            "identification_source": merged_src,
        }},
    )

    # Réconciliation multi-personnes / conducteur actif sur ce véhicule
    await _reconcile_vehicle_sessions(db, open_sess)

    # Realtime broadcast (best-effort)
    try:
        from app.realtime import get_broadcaster
        await get_broadcaster().publish(
            "session_updated" if open_sess.get("detection_count", 1) > 1 else "session_opened",
            {"session_id": open_sess["id"], "driver_id": open_sess["driver_id"],
             "vehicle_id": open_sess["vehicle_id"], "confidence": confidence,
             "status": new_status},
        )
    except Exception:
        pass
    return open_sess


async def _flag_conflict(db, sessions: list[dict]) -> None:
    """Marque un conflit explicite (jamais d'attribution silencieuse) + audit + push."""
    ids = [s["id"] for s in sessions]
    vehicle_id = sessions[0]["vehicle_id"]
    driver_ids = list({s["driver_id"] for s in sessions})
    await db.driver_sessions.update_many(
        {"id": {"$in": ids}},
        {"$set": {"status": "conflict", "conflict_at": now_iso(), "active_driver": False}},
    )
    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "driver_identification", "action": "conflict_detected",
        "vehicle_id": vehicle_id, "session_ids": ids,
        "drivers": driver_ids,
        "confidences": {s["driver_id"]: s.get("confidence") for s in sessions},
    })
    try:
        from app.realtime import get_broadcaster
        await get_broadcaster().publish("conflict_detected", {
            "vehicle_id": vehicle_id, "session_ids": ids, "drivers": driver_ids,
        })
    except Exception:
        pass
    try:
        from app.notifications_service import dispatch
        vehicle = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0}) or {}
        await dispatch("ble.conflict", {
            "session_id": ids[0], "vehicle_id": vehicle_id,
            "vehicle_plate": vehicle.get("plate"), "vehicle_label": vehicle.get("model"),
            "drivers": driver_ids,
        }, driver_ids=driver_ids)
    except Exception as e:
        logger.warning("conflict push notification failed: %s", e)


async def _reconcile_vehicle_sessions(db, sess: dict) -> None:
    """Plusieurs personnes détectées sur le même véhicule :
    - candidats BLE multiples sans confirmation → tous « À valider » (jamais de
      choix arbitraire au RSSI le plus fort) ;
    - contradiction avec une identité confirmée → conflit explicite ;
    - candidat unique stable (automatic) → promu conducteur actif (atomique).
    """
    cutoff = (datetime.now(timezone.utc) - SESSION_TIMEOUT).isoformat()
    rivals = await db.driver_sessions.find({
        "tenant_id": "default",
        "vehicle_id": sess["vehicle_id"],
        "driver_id": {"$ne": sess["driver_id"]},
        "status": {"$in": ["open", "automatic", "pending", "manual", "confirmed"]},
        "last_seen": {"$gte": cutoff},
    }, {"_id": 0}).to_list(50)
    if not rivals:
        if sess.get("status") in ("automatic", "confirmed", "manual"):
            await _try_set_active(db, sess)
        return
    group = [sess, *rivals]
    confirmed = [s for s in group if s.get("status") == "confirmed"
                 or s.get("identification_source") == "MANUEL"]
    if confirmed and len(confirmed) < len(group):
        others = [s for s in group if s not in confirmed]
        # présence d'autres tags = occupants détectés (pas un conflit tant
        # qu'aucune identification forte ne les désigne conducteur)
        occupant_ids = [s["id"] for s in others if s.get("status") in ("open", "pending")]
        if occupant_ids:
            await db.driver_sessions.update_many(
                {"id": {"$in": occupant_ids}, "status": {"$in": ["open", "pending"]}},
                {"$set": {"status": "pending", "active_driver": False}})
        contradicting = [s for s in others if s.get("status") in ("automatic", "manual")]
        if contradicting:
            await _flag_conflict(db, confirmed + contradicting)
        return
    if confirmed:
        # plusieurs identités confirmées simultanées → conflit explicite
        await _flag_conflict(db, group)
        return
    # aucun confirmé : plusieurs candidats détectés → tous à valider, aucun actif
    ids = [s["id"] for s in group]
    await db.driver_sessions.update_many(
        {"id": {"$in": ids}, "status": {"$in": ["open", "automatic", "pending"]}},
        {"$set": {"status": "pending", "active_driver": False}})


async def resolve_conflict(db, session_id: str, winner_driver_id: str,
                           actor: str, source: str = "page") -> dict:
    """Admin chooses which driver was really driving. The winning session
    keeps its status (automatic if confidence high enough, else pending);
    the losing ones are closed.
    """
    target = await db.driver_sessions.find_one({"id": session_id}, {"_id": 0})
    if not target:
        raise LookupError("Session inconnue")
    if target.get("status") != "conflict":
        raise PermissionError("Cette session n'est pas en conflit")
    vehicle_id = target["vehicle_id"]
    siblings = await db.driver_sessions.find({
        "tenant_id": "default", "vehicle_id": vehicle_id, "status": "conflict",
    }, {"_id": 0}).to_list(50)

    winner_session = next((s for s in siblings if s["driver_id"] == winner_driver_id), None)
    if not winner_session:
        raise LookupError("Aucune session active pour ce chauffeur sur ce véhicule")

    settings = await get_ble_settings(db)
    final_status = "confirmed"
    losers = [s for s in siblings if s["driver_id"] != winner_driver_id]
    loser_ids = [s["id"] for s in losers]

    await db.driver_sessions.update_one(
        {"id": winner_session["id"]},
        {"$set": {"status": final_status, "identification_source": "MANUEL",
                  "resolved_at": now_iso(),
                  "resolved_by": actor, "resolved_winner": winner_driver_id}},
    )
    if loser_ids:
        await db.driver_sessions.update_many(
            {"id": {"$in": loser_ids}},
            {"$set": {"status": "closed", "active_driver": False,
                      "resolved_at": now_iso(),
                      "resolved_by": actor, "resolved_winner": winner_driver_id,
                      "ended_at": now_iso()}},
        )
    await _try_set_active(db, winner_session)
    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "driver_identification", "action": "conflict_resolved",
        "actor": actor, "source": source, "vehicle_id": vehicle_id,
        "winner_driver_id": winner_driver_id,
        "winner_session_id": winner_session["id"], "loser_session_ids": loser_ids,
    })
    try:
        from app.realtime import get_broadcaster
        await get_broadcaster().publish("conflict_resolved", {
            "vehicle_id": vehicle_id, "winner_driver_id": winner_driver_id,
            "winner_session_id": winner_session["id"], "loser_session_ids": loser_ids,
        })
    except Exception:
        pass

    # Push notification to involved drivers
    try:
        from app.notifications_service import dispatch
        vehicle = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0}) or {}
        involved_drivers = list({s["driver_id"] for s in siblings})
        await dispatch("ble.resolved", {
            "vehicle_id": vehicle_id,
            "vehicle_plate": vehicle.get("plate"),
            "winner_driver_id": winner_driver_id,
            "winner_session_id": winner_session["id"],
        }, driver_ids=involved_drivers)
    except Exception as e:
        logger.warning("resolve push notification failed: %s", e)
    return {"winner_session_id": winner_session["id"], "closed_count": len(loser_ids),
            "final_status": final_status}


def _derive_status(session: dict, settings: dict) -> str:
    if session.get("mobile_override") in ("professional", "personal"):
        return "manual"
    try:
        started = datetime.fromisoformat(session["started_at"])
        seen = datetime.fromisoformat(session["last_seen"])
    except Exception:
        return "open"
    duration_s = (seen - started).total_seconds()
    if duration_s < settings["ble_min_duration_s"]:
        return "open"
    if session["confidence"] >= settings["ble_min_confidence"]:
        return "automatic"
    return "pending"


async def _compute_confidence(db, session: dict, settings: dict) -> int:
    """Score 0..100. See module docstring for breakdown."""
    cutoff = (datetime.now(timezone.utc) - RECENT_WINDOW).isoformat()
    recent = await db.ble_detections.find({
        "tenant_id": "default",
        "driver_id": session["driver_id"],
        "vehicle_id": session["vehicle_id"],
        "ignored": False,
        "ts": {"$gte": cutoff},
    }, {"_id": 0}).to_list(500)
    if not recent:
        return 0

    rssis = [d["rssi"] for d in recent]
    median_rssi = statistics.median(rssis)
    stdev = statistics.pstdev(rssis) if len(rssis) > 1 else 30

    # Stability (max 35) — lower stdev is better. >20 dBm of jitter = 0.
    stability = max(0.0, 1 - min(stdev, 20) / 20) * 35

    # Strength (max 25). Floor=-95, ceiling=-40.
    floor, ceil = -95, -40
    norm = max(0.0, min(1.0, (median_rssi - floor) / (ceil - floor)))
    strength = norm * 25

    # Duration (max 20). 5 min full points.
    try:
        started = datetime.fromisoformat(session["started_at"])
        seen = datetime.fromisoformat(session["last_seen"])
        minutes = (seen - started).total_seconds() / 60
    except Exception:
        minutes = 0
    duration = min(1.0, minutes / 5) * 20

    # Historical pairing (max 20) — fraction of past sessions on this vehicle
    past = await db.driver_sessions.count_documents({
        "tenant_id": "default", "driver_id": session["driver_id"], "status": "closed",
    })
    if past == 0:
        history = 5  # neutral starter
    else:
        same = await db.driver_sessions.count_documents({
            "tenant_id": "default", "driver_id": session["driver_id"],
            "vehicle_id": session["vehicle_id"], "status": "closed",
        })
        history = min(1.0, (same / past)) * 20

    return int(round(stability + strength + duration + history))


# ---------- Driver manual override ----------
async def driver_set_mode(db, driver_id: str, mode: str, actor: str) -> dict:
    """Driver presses PRO or PRIVÉ in the PWA.

    Stamps the current open session AND propagates `mobile_override` to every
    trip (driver, vehicle) starting AT or AFTER the toggle moment.
    Returns the updated session (or 404 if none open).
    """
    assert mode in ("professional", "personal")
    settings = await get_ble_settings(db)
    if not settings["allow_driver_override"]:
        raise PermissionError("Le forçage manuel est désactivé par l'administrateur")

    sess = await db.driver_sessions.find_one({
        "tenant_id": "default", "driver_id": driver_id,
        "status": {"$in": OPEN_STATUSES},
    }, {"_id": 0})
    if not sess:
        raise LookupError("Aucune session active — montez dans un véhicule équipé d'un tag BLE")

    ts = now_iso()
    await db.driver_sessions.update_one(
        {"id": sess["id"]},
        {"$set": {"mobile_override": mode, "status": "manual",
                  "mobile_override_at": ts, "mobile_override_actor": actor}},
    )

    # Propagate to trips of (driver, vehicle) starting at or after this moment
    n = await db.trips.count_documents({
        "tenant_id": "default", "driver_id": driver_id,
        "vehicle_id": sess["vehicle_id"],
        "start_time": {"$gte": ts},
    })
    await db.trips.update_many(
        {"tenant_id": "default", "driver_id": driver_id,
         "vehicle_id": sess["vehicle_id"], "start_time": {"$gte": ts}},
        {"$set": {"mobile_override": mode, "classification": mode,
                  "auto_classified": False}},
    )

    # Audit
    await db.audit_log.insert_one({
        "ts": ts, "scope": "driver_identification", "action": "manual_override",
        "actor": actor, "driver_id": driver_id, "vehicle_id": sess["vehicle_id"],
        "mode": mode, "session_id": sess["id"], "trips_affected": n,
    })

    sess.update({"mobile_override": mode, "status": "manual",
                 "mobile_override_at": ts, "mobile_override_actor": actor})
    return {"session": sess, "trips_affected": n}


async def get_current_session(db, driver_id: str) -> Optional[dict]:
    """For the PWA: return the active session (vehicle, mode, confidence)."""
    sess = await db.driver_sessions.find_one({
        "tenant_id": "default", "driver_id": driver_id,
        "status": {"$in": OPEN_STATUSES},
    }, {"_id": 0})
    if not sess:
        return None
    vehicle = await db.vehicles.find_one({"id": sess["vehicle_id"]}, {"_id": 0}) or {}
    return {**sess, "vehicle": {"id": vehicle.get("id"), "plate": vehicle.get("plate"),
                                "model": vehicle.get("model")}}


# ---------- Admin: list / amend sessions ----------
async def list_sessions(db, limit: int = 200, status: Optional[str] = None,
                        start: Optional[str] = None, end: Optional[str] = None) -> list[dict]:
    query: dict = {"tenant_id": "default"}
    if status and status != "all":
        query["status"] = status
    if start:
        query["started_at"] = {"$gte": start}
    if end:
        query.setdefault("started_at", {})["$lte"] = end
    rows = await db.driver_sessions.find(query, {"_id": 0}).sort("started_at", -1).to_list(limit)
    drivers = {d["id"]: d async for d in db.drivers.find({}, {"_id": 0})}
    vehicles = {v["id"]: v async for v in db.vehicles.find({}, {"_id": 0})}
    out = []
    for r in rows:
        drv = drivers.get(r["driver_id"], {})
        veh = vehicles.get(r["vehicle_id"], {})
        ident = r.get("identification_source") or ("APP+BLE" if r.get("source") == "ble" else "MANUEL")
        out.append({
            **r,
            "identification_source": ident,
            "driver_name": drv.get("name"),
            "vehicle_plate": veh.get("plate"),
            "vehicle_model": veh.get("model"),
        })
    # Occupants : autres sessions en cours sur le même véhicule (présence détectée)
    open_rows = [r for r in out if r.get("status") in OPEN_STATUSES or r.get("status") == "conflict"]
    by_vehicle: dict = {}
    for r in open_rows:
        by_vehicle.setdefault(r["vehicle_id"], []).append(r)
    for r in out:
        peers = [p for p in by_vehicle.get(r["vehicle_id"], []) if p["id"] != r["id"]] \
            if r.get("status") in OPEN_STATUSES or r.get("status") == "conflict" else []
        r["occupants"] = [{"driver_id": p["driver_id"], "driver_name": p.get("driver_name")}
                          for p in peers]
        r["occupants_count"] = len(peers)
    return out


async def amend_session(db, session_id: str, patch: dict, actor: str) -> dict:
    sess = await db.driver_sessions.find_one({"id": session_id}, {"_id": 0})
    if not sess:
        raise LookupError("Session inconnue")
    old = {k: sess.get(k) for k in ("driver_id", "vehicle_id", "mobile_override", "status")}
    update = {}
    for k in ("driver_id", "vehicle_id"):
        if k in patch and patch[k]:
            update[k] = patch[k]
    if "driver_id" in update and update["driver_id"] != sess.get("driver_id"):
        update["identification_source"] = "MANUEL"
    if "status" in patch and patch["status"] in (
        "open", "automatic", "confirmed", "pending", "manual", "closed", "cancelled", "conflict", "ending",
    ):
        update["status"] = patch["status"]
        if patch["status"] in ("closed", "cancelled"):
            update["active_driver"] = False
    if "mobile_override" in patch and patch["mobile_override"] in ("professional", "personal", None):
        update["mobile_override"] = patch["mobile_override"]
    if not update:
        return sess
    update["updated_at"] = now_iso()
    update["updated_by"] = actor
    await db.driver_sessions.update_one({"id": session_id}, {"$set": update})
    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "driver_identification", "action": "amend_session",
        "actor": actor, "session_id": session_id, "before": old, "after": update,
    })
    sess.update(update)
    return sess


async def dashboard_kpis(db, start: Optional[str] = None, end: Optional[str] = None) -> dict:
    base = {"tenant_id": "default"}
    if start:
        base["started_at"] = {"$gte": start}
    if end:
        base.setdefault("started_at", {})["$lte"] = end

    total = await db.driver_sessions.count_documents(base)
    auto = await db.driver_sessions.count_documents({**base, "status": "automatic"})
    confirmed = await db.driver_sessions.count_documents({**base, "status": "confirmed"})
    pending = await db.driver_sessions.count_documents({**base, "status": "pending"})
    conflict = await db.driver_sessions.count_documents({**base, "status": "conflict"})
    # Sources d'identification (APP / BLE / APP+BLE / MANUEL) — séparées de PRO/PRIVÉ
    ident_app = await db.driver_sessions.count_documents(
        {**base, "identification_source": "APP"})
    ident_ble = await db.driver_sessions.count_documents(
        {**base, "identification_source": "BLE"})
    ident_app_ble = await db.driver_sessions.count_documents(
        {**base, "$or": [{"identification_source": "APP+BLE"},
                         {"identification_source": {"$exists": False}, "source": "ble"}]})
    manual_cnt = await db.driver_sessions.count_documents(
        {**base, "$or": [{"identification_source": "MANUEL"}, {"status": "manual"}]})

    # Détections BLE brutes dans la fenêtre
    dq: dict = {"tenant_id": "default", "ignored": False}
    if start:
        dq["ts"] = {"$gte": start}
    if end:
        dq.setdefault("ts", {})["$lte"] = end
    detections = await db.ble_detections.count_documents(dq)

    # Trajets : identification chauffeur + PRO/PRIVÉ (contexte trajets, pas sessions)
    tq: dict = {"tenant_id": "default"}
    if start:
        tq["start_time"] = {"$gte": start}
    if end:
        tq.setdefault("start_time", {})["$lte"] = end
    trips_total = await db.trips.count_documents(tq)
    trips_unidentified = await db.trips.count_documents(
        {**tq, "$or": [{"driver_id": None}, {"driver_id": {"$exists": False}}]})
    forced_pro = await db.trips.count_documents({**tq, "mobile_override": "professional"})
    forced_perso = await db.trips.count_documents({**tq, "mobile_override": "personal"})

    closed_rows = await db.driver_sessions.find(
        {**base, "status": "closed"}, {"_id": 0, "detection_count": 1},
    ).to_list(1000)
    avg_det = sum(r.get("detection_count", 0) for r in closed_rows) / max(len(closed_rows), 1)

    identified = total - pending - conflict
    return {
        "total_sessions": total,
        "identified_app": ident_app,
        "identified_ble": ident_ble,
        "identified_app_ble": ident_app_ble,
        "manual_set": manual_cnt,
        "auto_identified": auto,
        "confirmed": confirmed,
        "pending_validation": pending,
        "conflicts": conflict,
        "success_rate": round(max(identified, 0) / total * 100, 1) if total else 0.0,
        "detections": detections,
        "avg_detections_per_session": round(avg_det, 1),
        "trips": {
            "total": trips_total,
            "unidentified": trips_unidentified,
            "identification_rate": round((trips_total - trips_unidentified) / trips_total * 100, 1)
            if trips_total else 0.0,
            "forced_pro": forced_pro,
            "forced_perso": forced_perso,
        },
        # rétro-compatibilité (anciens noms utilisés par le widget)
        "forced_pro": forced_pro,
        "forced_perso": forced_perso,
    }


# ---------- « Je conduis » — confirmation explicite APP (§9, §15-17, §23, §45) ----------
async def _get_or_create_session(db, driver_id: str, vehicle_id: str,
                                 src: str, ts: str) -> dict:
    sess = await db.driver_sessions.find_one(
        {"driver_id": driver_id, "vehicle_id": vehicle_id,
         "status": {"$in": OPEN_STATUSES + ["conflict"]}},
        {"_id": 0}, sort=[("started_at", -1)])
    if sess:
        return sess
    sess = {
        "id": str(uuid.uuid4()), "tenant_id": "default",
        "driver_id": driver_id, "vehicle_id": vehicle_id,
        "ble_tag_id": None, "source": "app",
        "identification_source": src, "active_driver": False,
        "status": "open", "started_at": ts, "ended_at": None,
        "last_seen": ts, "detection_count": 0, "last_rssi": None,
        "mobile_override": None, "confidence": None, "created_at": now_iso(),
    }
    await db.driver_sessions.insert_one(dict(sess))
    return sess


async def claim_driving(db, driver_id: str, vehicle_id: str, actor: str,
                        client_timestamp: str | None = None) -> dict:
    """« Je conduis » : validation atomique côté serveur — un seul conducteur
    actif par véhicule, jamais d'écrasement silencieux d'une autre identité."""
    settings = await get_ble_settings(db)
    vehicle = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0})
    if not vehicle:
        raise LookupError("Véhicule introuvable")
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    ble_cutoff = (now - RECENT_WINDOW).isoformat()
    has_ble = await db.ble_detections.find_one({
        "driver_id": driver_id, "vehicle_id": vehicle_id,
        "ignored": False, "ts": {"$gte": ble_cutoff}}, {"_id": 1})
    src = "APP+BLE" if has_ble else "APP"

    other = await db.driver_sessions.find_one({
        "vehicle_id": vehicle_id, "driver_id": {"$ne": driver_id},
        "status": {"$in": ["automatic", "manual", "confirmed"]},
        "$or": [{"ended_at": None}, {"ended_at": {"$exists": False}}],
    }, {"_id": 0}, sort=[("started_at", -1)])
    if other:
        window_min = int(settings.get("app_claim_conflict_window_min", 10))
        presence_cutoff = (now - SESSION_TIMEOUT).isoformat()
        confirm_cutoff = (now - timedelta(minutes=window_min)).isoformat()
        other_still_present = (other.get("last_seen") or "") >= presence_cutoff \
            and (other.get("detection_count") or 0) > 0
        other_confirmed_recent = other.get("status") == "confirmed" \
            and (other.get("confirmed_at") or "") >= confirm_cutoff
        if other_still_present or other_confirmed_recent:
            # contradiction (§16-17) → conflit explicite, résolution admin/app requise
            mine = await _get_or_create_session(db, driver_id, vehicle_id, src, ts)
            await _flag_conflict(db, [other, mine])
            return {"status": "conflict", "session": {**mine, "status": "conflict"},
                    "conflict_with_driver_id": other["driver_id"]}
        # changement volontaire de chauffeur (§23) : clôturer l'ancien à l'heure de la confirmation
        await db.driver_sessions.update_one(
            {"id": other["id"]},
            {"$set": {"status": "closed", "ended_at": ts, "active_driver": False,
                      "end_reason": "driver_change"}})
        await db.audit_log.insert_one({
            "ts": ts, "scope": "driver_identification", "action": "driver_change",
            "actor": actor, "vehicle_id": vehicle_id,
            "from_driver_id": other["driver_id"], "to_driver_id": driver_id,
            "source": "APP"})

    # mes sessions sur d'autres véhicules → clôturées
    await db.driver_sessions.update_many(
        {"driver_id": driver_id, "vehicle_id": {"$ne": vehicle_id},
         "status": {"$in": OPEN_STATUSES}},
        {"$set": {"status": "closed", "ended_at": ts, "active_driver": False}})

    mine = await _get_or_create_session(db, driver_id, vehicle_id, src, ts)
    upd = {"status": "confirmed",
           "identification_source": _merge_sources(mine.get("identification_source"), src),
           "confirmed_at": ts, "confirmed_by": actor, "last_seen": ts}
    if client_timestamp:
        upd["client_timestamp"] = str(client_timestamp)[:40]
    await db.driver_sessions.update_one({"id": mine["id"]}, {"$set": upd})
    mine.update(upd)

    try:
        await db.driver_sessions.update_one(
            {"id": mine["id"], "active_driver": {"$ne": True}},
            {"$set": {"active_driver": True, "active_since": ts}})
        mine["active_driver"] = True
    except DuplicateKeyError:
        # deux « Je conduis » quasi simultanés → conflit explicite (§17, §45)
        winner = await db.driver_sessions.find_one(
            {"vehicle_id": vehicle_id, "active_driver": True,
             "driver_id": {"$ne": driver_id}}, {"_id": 0})
        if winner:
            await _flag_conflict(db, [winner, mine])
            return {"status": "conflict", "session": {**mine, "status": "conflict"},
                    "conflict_with_driver_id": winner["driver_id"]}

    # autres candidats non confirmés = occupants détectés (à valider)
    await db.driver_sessions.update_many(
        {"vehicle_id": vehicle_id, "driver_id": {"$ne": driver_id},
         "status": {"$in": ["open", "automatic", "pending"]}},
        {"$set": {"status": "pending", "active_driver": False}})

    await db.audit_log.insert_one({
        "ts": ts, "scope": "driver_identification", "action": "driver_claim",
        "actor": actor, "driver_id": driver_id, "vehicle_id": vehicle_id,
        "session_id": mine["id"], "identification_source": mine["identification_source"],
        "client_timestamp": (str(client_timestamp)[:40] if client_timestamp else None)})
    try:
        from app.realtime import get_broadcaster
        await get_broadcaster().publish("session_updated", {
            "session_id": mine["id"], "driver_id": driver_id,
            "vehicle_id": vehicle_id, "status": "confirmed"})
    except Exception:
        pass
    return {"status": "confirmed",
            "session": {**mine, "vehicle": {"id": vehicle.get("id"),
                                            "plate": vehicle.get("plate"),
                                            "model": vehicle.get("model")}}}


# ---------- Fin de session liée aux trajets Navixy (§20-22) ----------
async def mark_sessions_trip_end(db, trip: dict) -> None:
    """Fin de trajet véhicule → sessions passent en 'ending' avec délai de grâce.
    Ne s'applique qu'aux fins de trajet récentes (jamais au backfill historique)."""
    end_time = trip.get("end_time")
    if not end_time:
        return
    recent_floor = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    if end_time < recent_floor:
        return
    q = {"vehicle_id": trip["vehicle_id"],
         "status": {"$in": ["open", "automatic", "pending", "manual", "confirmed"]},
         "started_at": {"$lte": end_time},
         "last_seen": {"$lte": end_time}}
    await db.driver_sessions.update_many(
        q, {"$set": {"status": "ending", "ending_since": end_time,
                     "vehicle_trip_id": trip.get("id")}})


async def sweep_sessions(db) -> dict:
    """Balayage périodique : ENDING → CLOSED après le délai de grâce ;
    sessions candidates sans détection prolongée → CLOSED (sécurité)."""
    settings = await get_ble_settings(db)
    grace = int(settings.get("session_close_grace_min", 10))
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=grace)).isoformat()
    r1 = await db.driver_sessions.update_many(
        {"status": "ending", "ending_since": {"$lte": cutoff}},
        [{"$set": {"status": "closed", "active_driver": False,
                   "ended_at": {"$ifNull": ["$ended_at", "$ending_since"]}}}])
    stale_cutoff = (now - SESSION_TIMEOUT * 6).isoformat()
    r2 = await db.driver_sessions.update_many(
        {"status": {"$in": ["open", "automatic", "pending"]},
         "last_seen": {"$lte": stale_cutoff}},
        [{"$set": {"status": "closed", "active_driver": False,
                   "ended_at": {"$ifNull": ["$ended_at", "$last_seen"]}}}])
    return {"ending_closed": r1.modified_count, "stale_closed": r2.modified_count}


# ---------- Simulation (for testing without physical hardware) ----------
async def simulate_detection(db, driver_id: str, identifier: str, rssi: int = -55) -> dict:
    """Insert a synthetic detection — used by admins to test the flow."""
    return await ingest_detection(db, driver_id, {
        "identifier": identifier,
        "rssi": rssi,
        "ts": now_iso(),
        "platform": "simulator",
        "battery": 100,
    })
