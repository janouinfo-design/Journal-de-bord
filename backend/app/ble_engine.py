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

logger = logging.getLogger(__name__)

# A session is considered ongoing if a detection arrived in the last X minutes.
SESSION_TIMEOUT = timedelta(minutes=5)
# Window over which we compute confidence (median RSSI, variance, ...).
RECENT_WINDOW = timedelta(minutes=30)

DEFAULT_SETTINGS = {
    "ble_enabled": True,
    "ble_min_duration_s": 120,
    "ble_min_rssi": -85,
    "ble_min_confidence": 60,
    "allow_driver_override": True,
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


async def _update_session(db, driver_id: str, vehicle_id: str,
                          detection: dict, settings: dict) -> dict:
    """Open or extend the current session for (driver, vehicle).

    Closes any other open session for this driver on a different vehicle.
    """
    # Close stale / other sessions
    cutoff = (datetime.now(timezone.utc) - SESSION_TIMEOUT).isoformat()
    async for s in db.driver_sessions.find(
        {"driver_id": driver_id, "status": {"$in": ["open", "automatic", "pending", "manual"]}},
        {"_id": 0},
    ):
        if s["vehicle_id"] != vehicle_id or (s.get("last_seen") or "") < cutoff:
            await db.driver_sessions.update_one(
                {"id": s["id"]},
                {"$set": {"status": "closed", "ended_at": s.get("last_seen") or now_iso()}},
            )

    # Find the still-open one for this exact (driver, vehicle)
    open_sess = await db.driver_sessions.find_one(
        {"driver_id": driver_id, "vehicle_id": vehicle_id,
         "status": {"$in": ["open", "automatic", "pending", "manual"]}},
        {"_id": 0},
    )

    if not open_sess:
        open_sess = {
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "driver_id": driver_id,
            "vehicle_id": vehicle_id,
            "ble_tag_id": detection["ble_tag_id"],
            "source": "ble",
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

    # Status promotion
    new_status = _derive_status(open_sess, settings)
    open_sess["status"] = new_status

    await db.driver_sessions.update_one(
        {"id": open_sess["id"]},
        {"$set": {
            "last_seen": open_sess["last_seen"],
            "detection_count": open_sess["detection_count"],
            "last_rssi": open_sess["last_rssi"],
            "confidence": confidence,
            "status": new_status,
        }},
    )

    # Conflict detection — if other open sessions on the same vehicle exist
    # for OTHER drivers with similar confidence, flag both as 'conflict'.
    await _maybe_flag_conflict(db, open_sess)

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


async def _maybe_flag_conflict(db, sess: dict, confidence_delta: int = 30) -> None:
    """If 2+ drivers have open sessions on the same vehicle within the timeout
    window AND their confidence scores are within `confidence_delta` points,
    mark ALL involved sessions as `status='conflict'`. Emit a realtime event.

    Default delta=30 is intentionally lenient: as soon as a second phone
    detects the same vehicle with a non-trivial confidence (>= 30), the
    admin should review. Never auto-pick a winner.
    """
    cutoff = (datetime.now(timezone.utc) - SESSION_TIMEOUT).isoformat()
    rivals = await db.driver_sessions.find({
        "tenant_id": "default",
        "vehicle_id": sess["vehicle_id"],
        "driver_id": {"$ne": sess["driver_id"]},
        "status": {"$in": ["open", "automatic", "pending", "manual"]},
        "last_seen": {"$gte": cutoff},
    }, {"_id": 0}).to_list(50)
    if not rivals:
        return
    my_conf = sess.get("confidence") or 0
    close = [r for r in rivals if abs((r.get("confidence") or 0) - my_conf) <= confidence_delta]
    if not close:
        return
    involved_ids = [sess["id"], *(r["id"] for r in close)]
    await db.driver_sessions.update_many(
        {"id": {"$in": involved_ids}},
        {"$set": {"status": "conflict", "conflict_at": now_iso()}},
    )
    await db.audit_log.insert_one({
        "ts": now_iso(), "scope": "driver_identification", "action": "conflict_detected",
        "vehicle_id": sess["vehicle_id"], "session_ids": involved_ids,
        "drivers": [sess["driver_id"], *(r["driver_id"] for r in close)],
        "confidences": {sess["driver_id"]: my_conf,
                        **{r["driver_id"]: r.get("confidence") for r in close}},
    })
    try:
        from app.realtime import get_broadcaster
        await get_broadcaster().publish("conflict_detected", {
            "vehicle_id": sess["vehicle_id"],
            "session_ids": involved_ids,
            "drivers": [sess["driver_id"], *(r["driver_id"] for r in close)],
        })
    except Exception:
        pass

    # Push notification to involved drivers + admins
    try:
        from app.notifications_service import dispatch
        vehicle = await db.vehicles.find_one({"id": sess["vehicle_id"]}, {"_id": 0}) or {}
        driver_ids = [sess["driver_id"], *(r["driver_id"] for r in close)]
        await dispatch("ble.conflict", {
            "session_id": sess["id"],
            "vehicle_id": sess["vehicle_id"],
            "vehicle_plate": vehicle.get("plate"),
            "vehicle_label": vehicle.get("model"),
            "drivers": driver_ids,
        }, driver_ids=driver_ids)
    except Exception as e:
        logger.warning("conflict push notification failed: %s", e)


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
    final_status = (
        "confirmed" if (winner_session.get("confidence") or 0) >= settings["ble_min_confidence"]
        else "pending"
    )
    losers = [s for s in siblings if s["driver_id"] != winner_driver_id]
    loser_ids = [s["id"] for s in losers]

    await db.driver_sessions.update_one(
        {"id": winner_session["id"]},
        {"$set": {"status": final_status, "resolved_at": now_iso(),
                  "resolved_by": actor, "resolved_winner": winner_driver_id}},
    )
    if loser_ids:
        await db.driver_sessions.update_many(
            {"id": {"$in": loser_ids}},
            {"$set": {"status": "closed", "resolved_at": now_iso(),
                      "resolved_by": actor, "resolved_winner": winner_driver_id,
                      "ended_at": now_iso()}},
        )
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
        "status": {"$in": ["open", "automatic", "pending", "manual"]},
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
        "status": {"$in": ["open", "automatic", "pending", "manual"]},
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
        out.append({
            **r,
            "driver_name": drv.get("name"),
            "vehicle_plate": veh.get("plate"),
            "vehicle_model": veh.get("model"),
        })
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
    if "status" in patch and patch["status"] in (
        "open", "automatic", "confirmed", "pending", "manual", "closed", "cancelled", "conflict",
    ):
        update["status"] = patch["status"]
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
    pending = await db.driver_sessions.count_documents({**base, "status": "pending"})
    manual = await db.driver_sessions.count_documents({**base, "status": "manual"})
    conflict = await db.driver_sessions.count_documents({**base, "status": "conflict"})
    forced_pro = await db.driver_sessions.count_documents({**base, "mobile_override": "professional"})
    forced_perso = await db.driver_sessions.count_documents({**base, "mobile_override": "personal"})

    # Avg detections per closed session as proxy for stability
    closed_rows = await db.driver_sessions.find(
        {**base, "status": "closed"}, {"_id": 0, "detection_count": 1},
    ).to_list(1000)
    avg_det = sum(r.get("detection_count", 0) for r in closed_rows) / max(len(closed_rows), 1)

    return {
        "total_sessions": total,
        "auto_identified": auto,
        "pending_validation": pending,
        "manual_set": manual,
        "conflicts": conflict,
        "forced_pro": forced_pro,
        "forced_perso": forced_perso,
        "success_rate": round(auto / total * 100, 1) if total else 0.0,
        "avg_detections_per_session": round(avg_det, 1),
    }


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
