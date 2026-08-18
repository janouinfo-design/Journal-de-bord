"""BLE driver identification — tags, detections, sessions, dashboard, settings."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, require_roles
from app.db import get_db
from app import ble_engine

from app.routes._helpers import resolve_driver_id_for_user

router = APIRouter(tags=["ble"])


# ---------- Tags ----------
@router.get("/ble/tags")
async def ble_tags_list(user=Depends(require_roles("admin", "manager"))):
    return await ble_engine.list_tags(get_db())


@router.post("/ble/tags")
async def ble_tags_upsert(payload: dict, user=Depends(require_roles("admin"))):
    if not payload.get("vehicle_id") or not payload.get("identifier"):
        raise HTTPException(400, "vehicle_id et identifier sont requis")
    return await ble_engine.upsert_tag(get_db(), payload)


@router.delete("/ble/tags/{tag_id}")
async def ble_tags_delete(tag_id: str, user=Depends(require_roles("admin"))):
    ok = await ble_engine.delete_tag(get_db(), tag_id)
    if not ok:
        raise HTTPException(404, "Tag introuvable")
    return {"deleted": True}


# ---------- Aliases (BLE pairing / "Apprentissage") ----------
# Chrome Web Bluetooth returns an opaque, device-specific token instead of the
# real MAC for privacy reasons. To make automatic matching work on Chrome
# Android without changing the beacon firmware, an admin can manually pair the
# token to an existing tag — that's what these endpoints do.
import uuid as _uuid
from app.ble_engine import normalize_identifier as _normalize


@router.get("/ble/aliases")
async def ble_aliases_list(user=Depends(require_roles("admin", "manager"))):
    db = get_db()
    rows = await db.ble_aliases.find(
        {"tenant_id": "default"}, {"_id": 0},
    ).sort("created_at", -1).to_list(1000)
    # Enrich with vehicle plate for the UI
    tag_idents = list({r.get("tag_identifier") for r in rows if r.get("tag_identifier")})
    tags_by_ident = {}
    if tag_idents:
        async for t in db.ble_tags.find(
            {"tenant_id": "default", "identifier": {"$in": tag_idents}},
            {"_id": 0, "identifier": 1, "vehicle_id": 1},
        ):
            tags_by_ident[t["identifier"]] = t
    vids = [t.get("vehicle_id") for t in tags_by_ident.values() if t.get("vehicle_id")]
    veh_by_id = {}
    if vids:
        async for v in db.vehicles.find(
            {"id": {"$in": vids}}, {"_id": 0, "id": 1, "plate": 1, "model": 1},
        ):
            veh_by_id[v["id"]] = v
    for r in rows:
        tag = tags_by_ident.get(r.get("tag_identifier"), {})
        v = veh_by_id.get(tag.get("vehicle_id"), {})
        r["vehicle_id"] = tag.get("vehicle_id")
        r["vehicle_plate"] = v.get("plate")
    return rows


@router.post("/ble/aliases")
async def ble_aliases_create(payload: dict, user=Depends(require_roles("admin"))):
    """Pair an opaque alias_id (Chrome Web Bluetooth token) to an existing tag.

    Future detections matching `alias_id` will be resolved to the same vehicle
    and driver as the underlying tag.
    """
    alias_id_raw = (payload.get("alias_id") or "").strip()
    tag_identifier_raw = (payload.get("tag_identifier") or "").strip()
    if not alias_id_raw or not tag_identifier_raw:
        raise HTTPException(400, "alias_id et tag_identifier sont requis")
    alias_canon = _normalize(alias_id_raw)
    tag_canon = _normalize(tag_identifier_raw)
    if not alias_canon or not tag_canon:
        raise HTTPException(400, "Identifiants invalides")
    if alias_canon == tag_canon:
        raise HTTPException(400, "L'alias ne peut pas être identique au tag.")

    db = get_db()
    tag = await db.ble_tags.find_one(
        {"tenant_id": "default", "identifier": tag_canon}, {"_id": 0},
    )
    if not tag:
        raise HTTPException(404, f"Aucun tag enregistré avec identifier={tag_canon}")

    existing = await db.ble_aliases.find_one(
        {"tenant_id": "default", "alias_id": alias_canon}, {"_id": 0},
    )
    record = {
        "id": existing.get("id") if existing else str(_uuid.uuid4()),
        "tenant_id": "default",
        "alias_id": alias_canon,
        "alias_id_raw": alias_id_raw,
        "tag_identifier": tag_canon,
        "label": payload.get("label"),
        "created_at": existing.get("created_at") if existing else ble_engine.now_iso(),
        "created_by": user.get("email"),
        "updated_at": ble_engine.now_iso(),
    }
    await db.ble_aliases.update_one(
        {"tenant_id": "default", "alias_id": alias_canon},
        {"$set": record}, upsert=True,
    )
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "alias_pair",
        "actor": user.get("email"),
        "diff": {"alias": alias_canon, "tag": tag_canon},
    })
    return record


@router.delete("/ble/aliases/{alias_db_id}")
async def ble_aliases_delete(alias_db_id: str, user=Depends(require_roles("admin"))):
    db = get_db()
    r = await db.ble_aliases.delete_one(
        {"id": alias_db_id, "tenant_id": "default"},
    )
    if r.deleted_count == 0:
        raise HTTPException(404, "Alias introuvable")
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "alias_delete",
        "actor": user.get("email"), "diff": {"id": alias_db_id},
    })
    return {"deleted": True}


# ---------- Detections & simulation ----------
@router.post("/ble/detections")
async def ble_ingest(payload: dict, user=Depends(get_current_user)):
    """Ingestion endpoint for the chauffeur PWA / native app.

    Payload accepts either a single detection or `{"detections": [...]}`.
    """
    db = get_db()
    driver_id = await resolve_driver_id_for_user(db, user)
    if not driver_id:
        raise HTTPException(400, "Utilisateur non lié à un chauffeur")
    items = payload.get("detections")
    if items is None:
        items = [payload]
    if not items:
        raise HTTPException(400, "Aucune détection fournie")
    results = []
    for it in items:
        if not it.get("identifier"):
            continue
        results.append(await ble_engine.ingest_detection(db, driver_id, it))
    return {"count": len(results), "results": results}


@router.post("/ble/simulate")
async def ble_simulate(payload: dict, user=Depends(require_roles("admin"))):
    """Admin tool: simulate a detection for a given driver."""
    db = get_db()
    driver_id = payload.get("driver_id") or await resolve_driver_id_for_user(db, user)
    if not driver_id or not payload.get("identifier"):
        raise HTTPException(400, "driver_id et identifier sont requis")
    rssi = int(payload.get("rssi") or -55)
    return await ble_engine.simulate_detection(db, driver_id, payload["identifier"], rssi)


# ---------- Sessions ----------
@router.get("/ble/sessions")
async def ble_sessions(
    limit: int = 200, status: Optional[str] = None,
    start: Optional[str] = None, end: Optional[str] = None,
    source: Optional[str] = None, driver_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    user=Depends(require_roles("admin", "manager")),
):
    return await ble_engine.list_sessions(
        get_db(), limit=limit, status=status, start=start, end=end,
        source=source, driver_id=driver_id, vehicle_id=vehicle_id)


@router.put("/ble/sessions/{session_id}")
async def ble_session_amend(session_id: str, patch: dict,
                            user=Depends(require_roles("admin", "manager"))):
    try:
        return await ble_engine.amend_session(get_db(), session_id, patch, actor=user.get("email", "?"))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.delete("/ble/sessions/{session_id}")
async def ble_session_delete(session_id: str,
                             user=Depends(require_roles("admin"))):
    """Hard-delete a session (admin only). Use when an obviously bogus or
    duplicate session must disappear from the historical view."""
    db = get_db()
    res = await db.driver_sessions.delete_one(
        {"id": session_id, "tenant_id": "default"},
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "Session introuvable")
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "delete_session",
        "actor": user.get("email"), "session_id": session_id,
    })
    return {"deleted": True}


# Patterns that identify test data (case-insensitive, post-normalisation).
_TEST_PATTERNS = ["TEST", "CONFLICTAG", "TESTTAG", "TESTBEACON", "MOCK"]


def _is_test_identifier(canon: str) -> bool:
    if not canon:
        return False
    return any(p in canon for p in _TEST_PATTERNS)


@router.post("/ble/cleanup-test-data")
async def ble_cleanup_test_data(payload: dict = None,
                                user=Depends(require_roles("admin"))):
    """Bulk-delete test tags + sessions generated by automated tests.

    Heuristic: any tag whose canonical identifier contains TEST / CONFLICTAG /
    TESTTAG / TESTBEACON / MOCK, plus all sessions tied to those tags.

    Body:
        { "dry_run": true }  → only count (default)
        { "dry_run": false } → actually delete
    """
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    db = get_db()

    # Find matching tags
    tags = await db.ble_tags.find({"tenant_id": "default"}, {"_id": 0}).to_list(5000)
    matching_tags = [t for t in tags
                     if _is_test_identifier(ble_engine.normalize_identifier(t.get("identifier") or ""))]
    matching_ids = [t["id"] for t in matching_tags]
    matching_canons = list({ble_engine.normalize_identifier(t.get("identifier") or "")
                            for t in matching_tags})

    # Sessions tied to those tags (by tag_id OR by identifier match)
    session_filter = {
        "tenant_id": "default",
        "$or": [
            {"tag_id": {"$in": matching_ids}} if matching_ids else {"tag_id": "__none__"},
            {"ble_tag_id": {"$in": matching_ids}} if matching_ids else {"ble_tag_id": "__none__"},
            {"identifier": {"$in": matching_canons}} if matching_canons else {"identifier": "__none__"},
        ],
    }
    sessions_count = await db.driver_sessions.count_documents(session_filter)

    if dry_run:
        return {
            "dry_run": True,
            "tags_to_delete": len(matching_tags),
            "sessions_to_delete": sessions_count,
            "sample_identifiers": [t.get("identifier") for t in matching_tags[:8]],
        }

    deleted_tags = 0
    deleted_sessions = 0
    if matching_ids:
        r1 = await db.ble_tags.delete_many({"id": {"$in": matching_ids}})
        deleted_tags = r1.deleted_count
    if sessions_count:
        r2 = await db.driver_sessions.delete_many(session_filter)
        deleted_sessions = r2.deleted_count

    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "cleanup_test_data",
        "actor": user.get("email"),
        "tags_deleted": deleted_tags, "sessions_deleted": deleted_sessions,
    })
    return {
        "dry_run": False,
        "tags_deleted": deleted_tags,
        "sessions_deleted": deleted_sessions,
    }


@router.post("/ble/sessions/clear-all")
async def ble_sessions_clear_all(payload: dict = None,
                                 user=Depends(require_roles("admin"))):
    """Hard-delete ALL BLE sessions for the tenant (admin only).

    Use to clean up demo / accumulated noise in the Identification table.
    Body:
        { "dry_run": true }  → only count (default)
        { "dry_run": false } → actually delete
    """
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    db = get_db()
    count = await db.driver_sessions.count_documents({"tenant_id": "default"})
    if dry_run:
        return {"dry_run": True, "sessions_to_delete": count}
    res = await db.driver_sessions.delete_many({"tenant_id": "default"})
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "clear_all_sessions",
        "actor": user.get("email"), "deleted": res.deleted_count,
    })
    return {"dry_run": False, "sessions_deleted": res.deleted_count}


@router.post("/ble/sessions/seed-demo")
async def ble_sessions_seed_demo(user=Depends(require_roles("admin"))):
    """Create 5 demo BLE sessions, each with a different driver + vehicle.

    Useful after a clear-all to repopulate the Identification table with
    realistic-looking data for screenshots / customer demos.
    """
    import uuid
    from datetime import datetime, timezone, timedelta

    db = get_db()
    drivers = await db.drivers.find(
        {"tenant_id": "default"}, {"_id": 0, "id": 1, "name": 1},
    ).sort("name", 1).to_list(50)
    # Keep only drivers with a proper human-readable name
    drivers = [d for d in drivers if d.get("name") and not d["name"].isdigit()][:5]
    if len(drivers) < 5:
        raise HTTPException(400, f"Besoin de 5 chauffeurs distincts (trouvés: {len(drivers)})")

    vehicles = await db.vehicles.find(
        {"tenant_id": "default"}, {"_id": 0, "id": 1, "plate": 1},
    ).sort("plate", 1).to_list(50)
    if len(vehicles) < 5:
        raise HTTPException(400, f"Besoin de 5 véhicules distincts (trouvés: {len(vehicles)})")

    statuses = ["automatic", "confirmed", "pending", "manual", "closed"]
    confidences = [92, 88, 64, 72, 95]
    now = datetime.now(timezone.utc)
    created = []
    for i in range(5):
        started = now - timedelta(hours=i + 1, minutes=i * 13)
        ended = started + timedelta(minutes=45 + i * 5)
        sess = {
            "id": str(uuid.uuid4()),
            "tenant_id": "default",
            "driver_id": drivers[i]["id"],
            "vehicle_id": vehicles[i]["id"],
            "ble_tag_id": None,
            "source": "ble",
            "status": statuses[i],
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat() if statuses[i] in ("closed", "confirmed") else None,
            "last_seen": ended.isoformat(),
            "detection_count": 20 + i * 8,
            "last_rssi": -55 - i * 2,
            "mobile_override": None,
            "confidence": confidences[i],
            "created_at": ble_engine.now_iso(),
        }
        await db.driver_sessions.insert_one(sess)
        sess.pop("_id", None)
        created.append({"driver": drivers[i]["name"],
                        "vehicle": vehicles[i]["plate"],
                        "status": statuses[i]})

    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "seed_demo_sessions",
        "actor": user.get("email"), "created": len(created),
    })
    return {"created": len(created), "sessions": created}


@router.post("/ble/sessions/{session_id}/resolve")
async def ble_session_resolve(session_id: str, payload: dict,
                              user=Depends(require_roles("admin"))):
    """Admin manually resolves a multi-driver BLE conflict.

    Body: `{winner_driver_id: <driver-id>, source?: 'page'|'header_inbox'}`.
    """
    winner = (payload or {}).get("winner_driver_id")
    source = (payload or {}).get("source") or "page"
    if not winner:
        raise HTTPException(400, "winner_driver_id requis")
    try:
        return await ble_engine.resolve_conflict(
            get_db(), session_id, winner,
            actor=user.get("email", "?"), source=source,
        )
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))


# ---------- Beacons chauffeurs (Navixy) ----------
@router.post("/ble/beacons/poll-now")
async def ble_beacons_poll_now(window_min: Optional[int] = None,
                               user=Depends(require_roles("admin"))):
    """Interroge immédiatement l'API Beacon Navixy pour le tenant courant.
    Sert de preuve terrain : tag chauffeur → traceur → Navixy → backend."""
    from app.db import get_raw_db
    from app.driver_beacons import poll_tenant_beacons
    from app.tenant_context import get_tenant_id
    tid = get_tenant_id() or "default"
    tenant = await get_raw_db().tenants.find_one({"id": tid}, {"_id": 0})
    if not tenant or not tenant.get("navixy_hash"):
        raise HTTPException(400, "Clé Navixy non configurée pour ce client")
    wm = max(1, min(int(window_min), 1440)) if window_min else None
    result = await poll_tenant_beacons(tenant, window_min=wm)
    return {"tenant_id": tid, **result}


# ---------- Dashboard & settings ----------
@router.get("/ble/dashboard")
async def ble_dashboard(start: Optional[str] = None, end: Optional[str] = None,
                        user=Depends(require_roles("admin", "manager"))):
    return await ble_engine.dashboard_kpis(get_db(), start=start, end=end)


@router.get("/ble/settings")
async def ble_settings_get(user=Depends(require_roles("admin", "manager"))):
    return await ble_engine.get_ble_settings(get_db())


# ---------- Debug ----------
@router.post("/ble/debug/clear-detections")
async def ble_debug_clear_detections(payload: dict = None,
                                     user=Depends(require_roles("admin"))):
    """Delete raw BLE detections (admin only).

    Body:
        { "dry_run": true,  "only_test": true }  → preview, test-only
        { "dry_run": false, "only_test": true }  → delete only test data
        { "dry_run": false, "only_test": false } → wipe ALL detections

    Test data heuristic: `platform == 'simulator'` OR identifier canonical form
    matches one of the TEST patterns (TEST, CONFLICTAG, TESTTAG, TESTBEACON, MOCK).
    """
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    only_test = bool(payload.get("only_test", True))
    db = get_db()

    if only_test:
        # Match either simulator platform OR test-pattern identifier
        all_rows = await db.ble_detections.find(
            {"tenant_id": "default"}, {"_id": 0, "id": 1, "identifier": 1, "platform": 1},
        ).to_list(50000)
        ids_to_delete = []
        for r in all_rows:
            canon = ble_engine.normalize_identifier(r.get("identifier") or "")
            if r.get("platform") == "simulator" or _is_test_identifier(canon):
                ids_to_delete.append(r["id"])
        count = len(ids_to_delete)
        if dry_run:
            return {"dry_run": True, "only_test": True, "detections_to_delete": count}
        if not count:
            return {"dry_run": False, "only_test": True, "detections_deleted": 0}
        res = await db.ble_detections.delete_many({"id": {"$in": ids_to_delete}})
        await db.audit_log.insert_one({
            "ts": ble_engine.now_iso(), "scope": "ble", "action": "clear_test_detections",
            "actor": user.get("email"), "deleted": res.deleted_count,
        })
        return {"dry_run": False, "only_test": True, "detections_deleted": res.deleted_count}

    # only_test=false → wipe all
    count = await db.ble_detections.count_documents({"tenant_id": "default"})
    if dry_run:
        return {"dry_run": True, "only_test": False, "detections_to_delete": count}
    res = await db.ble_detections.delete_many({"tenant_id": "default"})
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble", "action": "clear_all_detections",
        "actor": user.get("email"), "deleted": res.deleted_count,
    })
    return {"dry_run": False, "only_test": False, "detections_deleted": res.deleted_count}


@router.get("/ble/debug/recent-detections")
async def ble_debug_recent(limit: int = 100,
                           user=Depends(require_roles("admin"))):
    """Recent raw BLE detections — for live debugging of beacon discovery."""
    db = get_db()
    rows = await db.ble_detections.find(
        {"tenant_id": "default"}, {"_id": 0},
    ).sort("ts", -1).limit(min(limit, 500)).to_list(min(limit, 500))

    # Rolling RSSI average per identifier across the returned window
    rssi_acc: dict[str, list[int]] = {}
    for r in rows:
        canon = ble_engine.normalize_identifier(r.get("identifier") or "")
        if canon and isinstance(r.get("rssi"), (int, float)):
            rssi_acc.setdefault(canon, []).append(r["rssi"])

    # Enrich with driver name + normalised identifier + average RSSI for clarity
    out = []
    for r in rows:
        driver = await db.drivers.find_one(
            {"id": r.get("driver_id")}, {"_id": 0, "name": 1, "email": 1},
        ) or {}
        canon = ble_engine.normalize_identifier(r.get("identifier") or "")
        rssi_list = rssi_acc.get(canon, [])
        rssi_avg = round(sum(rssi_list) / len(rssi_list), 1) if rssi_list else None
        out.append({
            "ts": r.get("ts"),
            "driver_id": r.get("driver_id"),
            "driver_name": driver.get("name") or driver.get("email") or "—",
            "identifier_raw": r.get("identifier"),
            "identifier_canon": canon,
            "local_name": r.get("local_name"),
            "device_id": r.get("device_id"),
            "rssi": r.get("rssi"),
            "rssi_avg": rssi_avg,
            "platform": r.get("platform"),
            "battery": r.get("battery"),
            "manufacturer_data": r.get("manufacturer_data"),
            "service_uuids": r.get("service_uuids"),
            "matched_tag_id": r.get("ble_tag_id") or r.get("tag_id"),
            "ignored": r.get("ignored"),
            "ignore_reason": r.get("ignore_reason"),
        })
    return out


@router.put("/ble/settings")
async def ble_settings_put(payload: dict, user=Depends(require_roles("admin"))):
    db = get_db()
    allowed = {k for k in ble_engine.DEFAULT_SETTINGS}
    update = {k: payload[k] for k in payload if k in allowed}
    if not update:
        raise HTTPException(400, "Aucun champ valide")
    await db.settings.update_one({"id": "default"}, {"$set": update}, upsert=True)
    await db.audit_log.insert_one({
        "ts": ble_engine.now_iso(), "scope": "ble_settings", "action": "update",
        "actor": user.get("email"), "payload": update,
    })
    return await ble_engine.get_ble_settings(db)
