"""Identification chauffeur par tag BLE porté — chaîne Navixy Beacon API.

Chaîne prouvée en réel (Étape 0) :
    Beacon chauffeur → traceur Teltonika (FMU130/FMC130) → Navixy → ce module.

Endpoints Navixy utilisés (validés sur le parc réel) :
    POST {api}/beacon/data/read        — historique {tracker_id, hardware_id, rssi, get_time}
    POST {api}/beacon/data/last_values — dernières valeurs

Règles (§10-15 du cahier des charges) :
- un tag chauffeur = drivers.ble_id (normalisé dans ble_id_norm), unique par tenant ;
- une détection = présence, PAS une preuve de conduite ;
- un seul tag stable → session « automatic » selon les règles de confiance ;
- plusieurs tags → tous « À valider », jamais de choix au RSSI le plus fort ;
- jamais de donnée inventée : si Navixy ne renvoie rien, rien n'est créé.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app.ble_engine import _update_session, get_ble_settings, normalize_identifier, now_iso
from app.db import get_db, get_raw_db
from app.tenant_context import reset_current_tenant, set_current_tenant

logger = logging.getLogger(__name__)

NAVIXY_TS_FMT = "%Y-%m-%d %H:%M:%S"


async def poll_all_tenants() -> dict:
    raw = get_raw_db()
    results = {}
    async for tenant in raw.tenants.find(
            {"status": "active", "navixy_hash": {"$nin": [None, ""]}}, {"_id": 0}):
        try:
            results[tenant["id"]] = await poll_tenant_beacons(tenant)
        except Exception as e:
            logger.error("Beacon poll tenant %s: %s", tenant["id"], e)
            results[tenant["id"]] = {"error": str(e)[:200]}
    return results


async def poll_tenant_beacons(tenant: dict, window_min: int | None = None) -> dict:
    raw = get_raw_db()
    tid = tenant["id"]

    drivers = await raw.drivers.find(
        {"tenant_id": tid, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "name": 1, "ble_id": 1, "ble_id_norm": 1}).to_list(2000)
    by_tag = {}
    for d in drivers:
        norm = d.get("ble_id_norm") or normalize_identifier(d.get("ble_id"))
        if norm:
            by_tag[norm] = d
    if not by_tag:
        return {"skipped": "no_driver_tags"}

    vehicles = await raw.vehicles.find(
        {"tenant_id": tid, "navixy_tracker_id": {"$ne": None}},
        {"_id": 0, "id": 1, "plate": 1, "navixy_tracker_id": 1}).to_list(2000)
    by_tracker = {v["navixy_tracker_id"]: v for v in vehicles if v.get("navixy_tracker_id")}
    if not by_tracker:
        return {"skipped": "no_tracked_vehicles"}

    state_id = f"beacon_poll_{tid}"
    st = await raw.app_state.find_one({"id": state_id}) or {}
    now = datetime.now(timezone.utc)
    if window_min:
        frm = now - timedelta(minutes=window_min)
    elif st.get("last_ts"):
        frm = datetime.strptime(st["last_ts"], NAVIXY_TS_FMT).replace(tzinfo=timezone.utc)
    else:
        frm = now - timedelta(minutes=15)

    api = (tenant.get("navixy_api_url") or "https://api.navixy.com/v2").rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"{api}/beacon/data/read", json={
            "hash": tenant["navixy_hash"],
            "trackers": list(by_tracker.keys()),
            "from": frm.strftime(NAVIXY_TS_FMT),
            "to": now.strftime(NAVIXY_TS_FMT),
        })
    if r.status_code != 200:
        return {"error": f"navixy_http_{r.status_code}"}
    data = r.json()
    if not data.get("success"):
        return {"error": f"navixy_{data.get('status', {}).get('code', 'unknown')}"}
    records = data.get("list") or []

    processed = 0
    token = set_current_tenant(tid)
    try:
        db = get_db()
        settings = await get_ble_settings(db)
        for rec in sorted(records, key=lambda x: x.get("get_time") or ""):
            norm = normalize_identifier(rec.get("hardware_id"))
            drv = by_tag.get(norm)
            veh = by_tracker.get(rec.get("tracker_id"))
            if not drv or not veh:
                continue  # beacon inconnu ou traceur non mappé — jamais inventé
            try:
                ts_iso = datetime.strptime(rec["get_time"], NAVIXY_TS_FMT) \
                    .replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
            dup = await db.ble_detections.find_one(
                {"driver_id": drv["id"], "vehicle_id": veh["id"],
                 "ts": ts_iso, "source": "navixy_beacon"}, {"_id": 1})
            if dup:
                continue
            rssi = int(rec.get("rssi") or -100)
            detection = {
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "source": "navixy_beacon",
                "driver_id": drv["id"], "vehicle_id": veh["id"],
                "ble_tag_id": None, "identifier": norm,
                "rssi": rssi, "ts": ts_iso, "ignored": False,
            }
            if rssi < settings["ble_min_rssi"]:
                detection.update({"ignored": True, "ignore_reason": "rssi_below_floor"})
                await db.ble_detections.insert_one(detection)
                continue
            await db.ble_detections.insert_one(detection)
            await _update_session(db, drv["id"], veh["id"], detection, settings,
                                  identification_source="BLE")
            processed += 1
    finally:
        reset_current_tenant(token)

    await raw.app_state.update_one(
        {"id": state_id},
        {"$set": {"id": state_id,
                  "last_ts": (now - timedelta(seconds=60)).strftime(NAVIXY_TS_FMT),
                  "last_run": now_iso(), "last_records": len(records),
                  "last_processed": processed}},
        upsert=True)
    return {"records": len(records), "processed": processed}
