"""FMC003 OBD/CAN MILEAGE AUDIT — READ-ONLY STRICT (multi-tenant, par véhicule).

============================  INTERDICTIONS DURES  ============================
READ-ONLY uniquement. N'importe NI n'appelle aucune fonction d'écriture :
  - aucun setparam / getparam via raw_command/send
  - aucun privatemode ON/OFF
  - aucun raw_command/send
  - aucune écriture Navixy / Teltonika / Mongo
  - aucune supposition d'AVL ID universel
Ce script ne touche PAS le dossier FMC130 (audit API clos, en attente Configurator).

OBJECTIF : pour CHAQUE FMC003 réellement présent (tous tenants), déterminer s'il
existe une source de KILOMÉTRAGE CUMULATIF VÉHICULE réelle (indépendante du GPS) :
  1) recherche prioritaire : can_mileage / obd_mileage / vehicle_distance /
     total_distance / total_mileage / can_vehicle_mileage (ou équivalent) ;
  2) recours secondaire : un Teltonika Total Odometer réellement EXPOSÉ à Navixy ;
  3) JAMAIS le compteur GPS-calculé Navixy comme source de distance privée.

RÈGLES :
  - la présence de rpm/speed/fuel NE PROUVE PAS qu'un kilométrage est disponible ;
  - un champ n'est retenu que s'il est VIVANT (récent) ET CUMULATIF (croissant) ;
  - stratégie STRICTEMENT par véhicule (pas de généralisation modèle).

SORTIE par véhicule + statut final parmi :
  CAN_MILEAGE_VALIDATED | TELTONIKA_ODOMETER_VALIDATED | HARDWARE_SOURCE_VALIDATED |
  NO_HARDWARE_ODOMETER | NOT_TESTED

Usage :
  docker exec -e PYTHONPATH=/app -w /app journal_backend python3 /tmp/d2_fmc003_mileage_audit.py
RAW masqué -> /tmp/d2_fmc003_audit_raw.json
"""
import asyncio
import json
import copy
from datetime import datetime, timedelta

import httpx

import app.tenant_context as tc
from app.tenant_context import (set_current_tenant, reset_current_tenant,
                                refresh_tenant_cache)
from app.db import init_db
from app import navixy_client as nc
from app.odometer_capability import resolve_model

TARGET_MODEL = "FMC003"
RAW_OUT = "/tmp/d2_fmc003_audit_raw.json"
RECENT_DAYS = 30  # un kilométrage "vivant" doit être MAJ dans les 30 derniers jours

# Champs kilométrage VÉHICULE recherchés (source non-GPS). Ordre = priorité.
VEHICLE_MILEAGE_HINTS = [
    "can_mileage", "obd_mileage", "can_vehicle_mileage",
    "vehicle_distance", "total_distance", "total_mileage",
    "vehicle_mileage",
]
# Champs Total Odometer hardware Teltonika (recours secondaire).
TOTAL_ODO_HINTS = [
    "total_odometer", "total_odo", "totalodometer",
    "hw_mileage", "hardware_mileage", "hw_odometer", "hardware_odometer",
]

SECRET_KEY_HINTS = [
    "hash", "token", "api_key", "apikey", "password", "secret", "credential",
    "imei", "sim", "iccid", "imsi", "phone", "msisdn", "device_id",
]
GPS_KEY_HINTS = ["lat", "lng", "lon", "latitude", "longitude", "location", "address"]


def _scrub(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(h in kl for h in SECRET_KEY_HINTS):
                out[k] = v if v in (None, "", 0) else f"***MASKED({len(str(v))} chars)***"
            elif kl in GPS_KEY_HINTS or any(kl.endswith("_" + h) for h in GPS_KEY_HINTS):
                out[k] = v if v in (None, "", 0) else "***GPS_MASKED***"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


async def raw(path, payload):
    base = nc._base_url()
    h = nc._hash()
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.post(f"{base}/{path}", json={"hash": h, **payload})
        except Exception as e:
            return {"_transport_error": type(e).__name__}
        try:
            return r.json()
        except Exception:
            return {"_http": r.status_code, "_text": r.text[:200]}


def _parse_ts(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(ts)[:19], fmt)
        except Exception:
            continue
    return None


def _is_recent(ts, now):
    dt = _parse_ts(ts)
    if not dt:
        return False
    return (now - dt) <= timedelta(days=RECENT_DAYS)


def _iter_readings(rd):
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (rd.get(grp) or []):
            if isinstance(it, dict):
                yield grp, it


def _find_fields(readings, hints):
    """Retourne les champs des readings dont le nom contient un hint."""
    hits = []
    for grp, it in _iter_readings(readings):
        name = str(it.get("input_name") or it.get("name") or it.get("label") or it.get("field") or "").lower()
        if any(hint in name for hint in hints):
            hits.append({
                "group": grp,
                "field": it.get("input_name") or it.get("name") or it.get("label") or it.get("field"),
                "value": it.get("value"),
                "units": it.get("units_type") or it.get("units") or it.get("unit"),
                "timestamp": it.get("update_time") or it.get("time"),
                "sensor_id": it.get("sensor_id"),
            })
    return hits


def _navixy_gps_odometer(counters):
    for coll in ("list", "counters"):
        for it in (counters.get(coll) or []):
            if isinstance(it, dict) and str(it.get("type")) == "odometer":
                return {"value": it.get("value"), "timestamp": it.get("update_time")}
    return None


async def audit_vehicle(trk_entry, now):
    tid = trk_entry.get("id")
    label = trk_entry.get("label")
    model_code = (trk_entry.get("source") or {}).get("model")
    fw = (trk_entry.get("source") or {}).get("firmware_version") or trk_entry.get("firmware_version")

    readings = await raw("tracker/readings/list", {"tracker_id": tid})
    counters = await raw("tracker/get_counters", {"tracker_id": tid})

    veh_hits = _find_fields(readings, VEHICLE_MILEAGE_HINTS)
    odo_hits = _find_fields(readings, TOTAL_ODO_HINTS)
    gps_odo = _navixy_gps_odometer(counters)

    # OBD/CAN présent ? (au moins un input obd_/can_ vivant OU présent)
    obd_can_present = False
    for grp, it in _iter_readings(readings):
        nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
        if nm.startswith("obd_") or nm.startswith("can_"):
            obd_can_present = True
            break

    # Choix du meilleur candidat véhicule (mileage), sinon total odo hardware.
    chosen = None
    chosen_kind = None
    for h in veh_hits:
        if h["value"] not in (None, "", 0):
            chosen = h
            chosen_kind = "VEHICLE_MILEAGE"
            break
    if not chosen:
        for h in odo_hits:
            if h["value"] not in (None, "", 0):
                chosen = h
                chosen_kind = "TELTONIKA_TOTAL_ODOMETER"
                break

    mileage_field = chosen["field"] if chosen else None
    mileage_value = chosen["value"] if chosen else None
    unit = chosen["units"] if chosen else None
    ts = chosen["timestamp"] if chosen else None
    is_recent = _is_recent(ts, now) if chosen else False
    # cumulatif : non prouvable en un seul appel -> PENDING sauf preuve historique
    is_cumulative = "PENDING_REAL_DRIVE" if chosen else "N/A"

    total_odo_exposed = "YES" if odo_hits and any(
        h["value"] not in (None, "", 0) for h in odo_hits) else "NO"

    # Statut final par véhicule (règle stricte, sans preuve terrain -> pas de *_VALIDATED définitif)
    if chosen_kind == "VEHICLE_MILEAGE" and is_recent:
        status = "CAN_MILEAGE_CANDIDATE"       # candidat ; *_VALIDATED seulement après preuve terrain
    elif chosen_kind == "TELTONIKA_TOTAL_ODOMETER" and is_recent:
        status = "TELTONIKA_ODOMETER_CANDIDATE"
    elif chosen and not is_recent:
        status = "NO_HARDWARE_ODOMETER"        # champ présent mais périmé -> inutilisable en l'état
    else:
        status = "NO_HARDWARE_ODOMETER"

    private_source = mileage_field if (chosen and is_recent) else "NONE (GPS Navixy exclu)"

    return {
        "TRACKER_ID": tid,
        "VEHICLE": label,
        "MODEL": model_code,
        "FIRMWARE": fw or "NOT_READABLE",
        "OBD_CAN_PRESENT": "YES" if obd_can_present else "NO",
        "MILEAGE_FIELD": mileage_field or "NONE",
        "MILEAGE_VALUE": mileage_value,
        "UNIT": unit or "n/a",
        "TIMESTAMP": ts or "n/a",
        "IS_RECENT": "YES" if is_recent else "NO",
        "IS_CUMULATIVE": is_cumulative,
        "TELTONIKA_TOTAL_ODOMETER_EXPOSED": total_odo_exposed,
        "NAVIXY_GPS_ODOMETER": (f"{gps_odo['value']} @ {gps_odo['timestamp']}"
                                if gps_odo else "n/a") + "  (EXCLU comme source privée)",
        "PRIVATE_DISTANCE_SOURCE": private_source,
        "STATUS": status,
        "_all_vehicle_mileage_hits": veh_hits,
        "_all_total_odo_hits": odo_hits,
    }


async def run():
    db = init_db()
    await refresh_tenant_cache(db)
    tenants = dict(tc._tenant_cache)  # lu APRÈS refresh (la globale du module est réassignée)
    now = datetime.utcnow()

    raw_dump = {"tenants_scanned": [], "vehicles": []}
    print("\n" + "=" * 74, flush=True)
    print("FMC003 OBD/CAN MILEAGE AUDIT — READ-ONLY (multi-tenant, par vehicule)", flush=True)
    print("=" * 74, flush=True)

    total_fmc003 = 0
    all_rows = []

    for tid_tenant, tdoc in tenants.items():
        if not tdoc.get("navixy_hash"):
            continue  # tenant sans credential -> fail-closed, on ignore
        tenant_name = tdoc.get("name", tid_tenant)
        tok = set_current_tenant(tid_tenant)
        try:
            try:
                trackers = await nc.list_trackers()
            except Exception as e:
                print(f"\n[TENANT {tenant_name}] list_trackers ERREUR: {type(e).__name__} "
                      f"(credential invalide/expiré ?) — tenant ignoré.", flush=True)
                raw_dump["tenants_scanned"].append({"tenant": tenant_name, "error": type(e).__name__})
                continue

            fmc003 = [t for t in trackers if resolve_model((t.get("source") or {}).get("model")) == TARGET_MODEL]
            print(f"\n[TENANT {tenant_name}] {len(trackers)} tracker(s), dont {len(fmc003)} FMC003.", flush=True)
            raw_dump["tenants_scanned"].append({"tenant": tenant_name,
                                                "trackers": len(trackers), "fmc003": len(fmc003)})

            for entry in fmc003:
                total_fmc003 += 1
                row = await audit_vehicle(entry, now)
                all_rows.append(row)
                raw_dump["vehicles"].append(_scrub(copy.deepcopy(row)))
                print("\n  " + "-" * 66, flush=True)
                for key in ("TRACKER_ID", "VEHICLE", "MODEL", "FIRMWARE", "OBD_CAN_PRESENT",
                            "MILEAGE_FIELD", "MILEAGE_VALUE", "UNIT", "TIMESTAMP", "IS_RECENT",
                            "IS_CUMULATIVE", "TELTONIKA_TOTAL_ODOMETER_EXPOSED",
                            "NAVIXY_GPS_ODOMETER", "PRIVATE_DISTANCE_SOURCE", "STATUS"):
                    print(f"    {key:<34} = {row[key]}", flush=True)
        finally:
            reset_current_tenant(tok)

    # Récapitulatif
    print("\n" + "=" * 74, flush=True)
    print(f"RECAP FMC003 — {total_fmc003} vehicule(s) audite(s)", flush=True)
    print("=" * 74, flush=True)
    by_status = {}
    for r in all_rows:
        by_status.setdefault(r["STATUS"], []).append(r["TRACKER_ID"])
    for st, ids in sorted(by_status.items()):
        print(f"  {st:<32} : {len(ids)}  {ids}", flush=True)
    print("\n  NOTE: '*_CANDIDATE' = champ vivant/present mais NON encore FIELD-VALIDATED", flush=True)
    print("        (cumulatif reel a prouver via 2 lectures avant/apres roulage). Aucun", flush=True)
    print("        '*_VALIDATED' definitif sans preuve terrain. GPS Navixy toujours EXCLU.", flush=True)
    print("        READ-ONLY : aucune ecriture, aucun D3, FMC130 non touche.", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  RAW JSON masque -> {RAW_OUT}", flush=True)
    except Exception as e:
        print(f"  (impossible d'ecrire {RAW_OUT}: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
