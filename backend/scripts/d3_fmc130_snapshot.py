"""D3 FMC130 PRECHECK (READ-ONLY) — pilote FMC130, resolver multi-tenant, AUTONOME.

Aucune dépendance à d3b_snapshot : tous les helpers (parse, avl16, masquage) sont
embarqués. READ-ONLY strict : aucune commande privatemode, aucun setparam, aucune
modification de sensor/device, aucune bascule.

Résolution du credential (AUCUN AUDIT_NAVIXY_HASH manuel) :
    tracker 781479 -> vehicle -> tenant_id
      -> get_integration_credential(tenant_id, "NAVIXY")  [fail-closed, jamais cross-tenant]
      -> Navixy READ-ONLY (get_state / sensor/list / readings/list)

Ne JAMAIS afficher : API key / hash / token / credential tenant.
Tracker via env TID (défaut 781479).

Mapping ATTENDU (observé, non forcé) : input=avl_io_16, multiplier=1, divider=1000, unit=km
"""
import asyncio
import os
import sys
from datetime import datetime

import httpx

# Racine backend sur le sys.path pour importer `app` (layout /app ou /app/backend).
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _BACKEND_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TID = int(os.environ.get("TID", "781479"))
_AVL16_INPUTS = {"avl_io_16", "hw_mileage"}
_ODO_INPUT_HINTS = ("avl_io_16", "hw_mileage", "total_od")
_ODO_LABEL_HINTS = ("odo total", "odometer", "odometre", "total odo", "mileage")
_RECENT_MAX_S = 3600


# ---------- helpers embarqués (autonomes) ----------
def _isnum(x):
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _parse(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(ts)[:19], fmt)
        except Exception:
            continue
    return None


def _find_avl16(readings):
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm in _AVL16_INPUTS:
                return {"value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time") or it.get("time")}
    for grp in ("inputs", "virtual_sensors", "sensors"):
        for it in (readings.get(grp) or []):
            label = str(it.get("label") or it.get("name") or "").lower()
            if any(h in label for h in _ODO_LABEL_HINTS):
                return {"value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time") or it.get("time")}
    return None


def _masking_verdict(lat, lng, gps_ts, avl_ts, moving, ignition):
    try:
        if lat is not None and lng is not None and abs(float(lat)) < 1e-6 and abs(float(lng)) < 1e-6:
            return "MASKED", "coords 0,0 (Data Sent As Zero)"
    except (TypeError, ValueError):
        pass
    g = _parse(gps_ts)
    a = _parse(avl_ts)
    if g and a:
        gap = (a - g).total_seconds()
        if gap >= 120 and (moving or ignition):
            return "MASKED", ("position GELEE: GPS fige depuis %ds alors que AVL16 frais "
                              "et vehicule actif" % int(gap))
    if lat is not None and lng is not None:
        if g and a and (a - g).total_seconds() < 120:
            return "NOT_MASKED", "coords reelles recentes"
        return "NOT_MASKED", "coords reelles (fraicheur indeterminee)"
    return "INCONCLUSIVE", "position indeterminable"


def _find_avl16_sensor(sensors):
    best = None
    for s in (sensors.get("list") or []):
        inp = str(s.get("input_name") or "").lower()
        name = str(s.get("name") or "").lower()
        if any(h in inp for h in _ODO_INPUT_HINTS):
            return s
        if any(h in name for h in _ODO_LABEL_HINTS):
            best = best or s
    return best


def _recent(ts):
    d = _parse(ts)
    if not d:
        return False
    try:
        return (datetime.utcnow() - d).total_seconds() <= _RECENT_MAX_S
    except Exception:
        return False


def _find_can_mileage(readings, sensors):
    """Lit can_mileage (source SECONDAIRE de comparaison) : valeur/unite/timestamp
    depuis readings, + definition du sensor si presente. READ-ONLY."""
    val = ts = unit = None
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm == "can_mileage":
                val = it.get("value")
                unit = it.get("units_type") or it.get("units")
                ts = it.get("update_time") or it.get("time")
                break
        if val is not None:
            break
    sensor = None
    for s in (sensors.get("list") or []):
        if str(s.get("input_name") or "").lower() == "can_mileage":
            sensor = s
            break
    return {
        "present": (val is not None) or (sensor is not None),
        "value": val, "unit": unit, "timestamp": ts,
        "sensor_id": sensor.get("id") if sensor else None,
        "sensor_name": sensor.get("name") if sensor else None,
        "multiplier": sensor.get("multiplier") if sensor else None,
        "divider": sensor.get("divider") if sensor else None,
    }


# ---------- résolution tenant + credential ----------
async def _resolve_tenant_and_cred():
    from app.db import init_db, get_db
    from app.tenant_context import refresh_tenant_cache
    from app.integrations import get_integration_credential
    init_db()
    db = get_db()
    await refresh_tenant_cache(db)
    vehicle = None
    for field in ("navixy_tracker_id", "tracker_id"):
        for val in (TID, str(TID)):
            vehicle = await db.vehicles.find_one({field: val}, {"_id": 0})
            if vehicle:
                break
        if vehicle:
            break
    if not vehicle:
        return None, None, None
    tenant_id = vehicle.get("tenant_id")
    if not tenant_id:
        return vehicle, None, None
    cred = get_integration_credential(tenant_id, "NAVIXY")
    return vehicle, tenant_id, cred


def _base_url(cred):
    return (cred.get("api_url") or os.environ.get("NAVIXY_API_URL")
            or "https://api.navixy.com/v2").rstrip("/")


async def _raw(cred, path, payload):
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.post("%s/%s" % (_base_url(cred), path),
                             json={"hash": cred["credential"], **payload})
        except Exception as e:
            return {"_transport_error": type(e).__name__}
        try:
            return r.json()
        except Exception:
            return {"_http": r.status_code}


async def precheck():
    vehicle, tenant_id, cred = await _resolve_tenant_and_cred()
    print("\n===== FMC130 D3 PRECHECK (READ-ONLY) — tracker %d =====" % TID, flush=True)
    print("TRACKER_ID = %s" % TID, flush=True)
    if vehicle is None or tenant_id is None:
        print("MODEL = %s" % (vehicle.get("model") if vehicle else None), flush=True)
        print("TENANT_ID = %s" % tenant_id, flush=True)
        print("\nFMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = TENANT_UNRESOLVED", flush=True)
        return
    if not cred or not cred.get("credential"):
        print("MODEL = %s" % vehicle.get("model"), flush=True)
        print("TENANT_ID = %s" % tenant_id, flush=True)
        print("\nFMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = NAVIXY_CREDENTIAL_MISSING", flush=True)
        return
    info = await _raw(cred, "user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        print("MODEL = %s" % vehicle.get("model"), flush=True)
        print("TENANT_ID = %s" % tenant_id, flush=True)
        print("CRED_SOURCE = %s (valeur jamais affichee)" % cred.get("source"), flush=True)
        print("\nFMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = NAVIXY_AUTH_FAILED", flush=True)
        return
    state = await _raw(cred, "tracker/get_state", {"tracker_id": TID})
    sensors = await _raw(cred, "tracker/sensor/list", {"tracker_id": TID})
    readings = await _raw(cred, "tracker/readings/list", {"tracker_id": TID})
    st = (state or {}).get("state") or {}
    gps = st.get("gps") or {}
    loc = gps.get("location") or {}
    lat = loc.get("lat") if isinstance(loc, dict) else None
    lng = loc.get("lng") if isinstance(loc, dict) else None
    online = st.get("connection_status") in ("active", "idle")
    moving = str(st.get("movement_status") or "").lower() == "moving"
    ignition = bool(st.get("ignition"))
    avl16 = _find_avl16(readings or {})
    avl16_val = avl16.get("value") if avl16 else None
    avl16_ts = avl16.get("timestamp") if avl16 else None
    avl16_present = avl16 is not None
    avl16_readable = _isnum(avl16_val)
    avl16_recent = _recent(avl16_ts)
    verdict, reason = _masking_verdict(lat, lng, gps.get("updated"), avl16_ts, moving, ignition)
    gps_normal = (verdict == "NOT_MASKED")
    sensor = _find_avl16_sensor(sensors or {})
    s_defined = sensor is not None
    s_id = sensor.get("id") if sensor else None
    s_input = sensor.get("input_name") if sensor else None
    s_mult = sensor.get("multiplier") if sensor else None
    s_div = sensor.get("divider") if sensor else None
    s_unit = (sensor.get("units_type") or sensor.get("units")) if sensor else None
    sensor_value_km = avl16_val if avl16_readable else None
    mapping_expected = (
        s_defined
        and str(s_input).lower() in _ODO_INPUT_HINTS
        and (s_mult in (1, 1.0, None))
        and (s_div in (1000, 1000.0))
        and (str(s_unit).lower() in ("km", "kilometer", "kilometre"))
    )
    scale_verified = bool(mapping_expected and avl16_readable)

    # ---- Source SECONDAIRE de comparaison : can_mileage (READ-ONLY) ----
    cm = _find_can_mileage(readings or {}, sensors or {})
    cm_readable = _isnum(cm.get("value"))
    cm_recent = _recent(cm.get("timestamp"))
    if not cm.get("present"):
        cm_status = "ABSENT"
    elif cm_readable and cm_recent:
        cm_status = "RUNTIME_FRESH"
    elif cm_readable and not cm_recent:
        cm_status = "STALE"
    else:
        cm_status = "INCONCLUSIVE"

    # Statut AVL16 : distinguer NON EXPOSÉ (device/config) de NON SUPPORTÉ (jamais).
    # Le FMC130 SUPPORTE AVL16 -> si absent ici = NOT_CURRENTLY_EXPOSED.
    if avl16_present and scale_verified:
        avl16_status = "PRESENT"
    elif avl16_present:
        avl16_status = "PRESENT_MAPPING_UNVERIFIED"
    else:
        avl16_status = "NOT_CURRENTLY_EXPOSED"

    # Odomètre plateforme Navixy (GPS-calculé) — RÉFÉRENCE uniquement, EXCLU du privé.
    navixy_gps_odo = None
    for grp in ("counters",):
        for it in (readings.get(grp) or []):
            if str(it.get("type") or it.get("name") or "").lower() in ("odometer", "mileage"):
                navixy_gps_odo = it.get("value")
                break

    print("MODEL = %s" % vehicle.get("model"), flush=True)
    print("TENANT_ID = %s" % tenant_id, flush=True)
    print("CRED_SOURCE = %s (valeur jamais affichee)" % cred.get("source"), flush=True)
    print("TRACKER_ONLINE = %s" % online, flush=True)
    print("GPS_NORMAL = %s (%s: %s)" % (gps_normal, verdict, reason), flush=True)
    print("", flush=True)
    print("--- PRIMARY: AVL16 (Teltonika Total Odometer) ---", flush=True)
    print("AVL16_STATUS = %s" % avl16_status, flush=True)
    print("AVL16_PRESENT = %s" % avl16_present, flush=True)
    print("AVL16_RAW_VALUE = %s" % avl16_val, flush=True)
    print("AVL16_TIMESTAMP = %s" % avl16_ts, flush=True)
    print("AVL16_RECENT = %s" % avl16_recent, flush=True)
    print("SENSOR_DEFINED = %s" % s_defined, flush=True)
    print("SENSOR_ID = %s" % s_id, flush=True)
    print("SENSOR_INPUT = %s" % s_input, flush=True)
    print("SENSOR_MULTIPLIER = %s" % s_mult, flush=True)
    print("SENSOR_DIVIDER = %s" % s_div, flush=True)
    print("SENSOR_UNIT = %s" % s_unit, flush=True)
    print("SENSOR_VALUE_KM = %s" % sensor_value_km, flush=True)
    print("AVL16_API_READABLE = %s" % avl16_readable, flush=True)
    print("AVL16_SCALE_VERIFIED = %s" % scale_verified, flush=True)
    print("", flush=True)
    print("--- SECONDARY (comparaison, fallback): can_mileage ---", flush=True)
    print("CAN_MILEAGE_PRESENT = %s" % cm.get("present"), flush=True)
    print("CAN_MILEAGE_VALUE = %s" % cm.get("value"), flush=True)
    print("CAN_MILEAGE_UNIT = %s" % cm.get("unit"), flush=True)
    print("CAN_MILEAGE_TIMESTAMP = %s" % cm.get("timestamp"), flush=True)
    print("CAN_MILEAGE_SENSOR_ID = %s" % cm.get("sensor_id"), flush=True)
    print("CAN_MILEAGE_MULTIPLIER = %s" % cm.get("multiplier"), flush=True)
    print("CAN_MILEAGE_DIVIDER = %s" % cm.get("divider"), flush=True)
    print("CAN_MILEAGE_RUNTIME = %s" % cm_status, flush=True)
    print("", flush=True)
    print("--- REFERENCE (EXCLU du calcul prive) ---", flush=True)
    print("NAVIXY_GPS_ODOMETER = %s" % navixy_gps_odo, flush=True)
    print("", flush=True)
    ok = (online and gps_normal and avl16_present and avl16_recent
          and avl16_readable and scale_verified)
    if ok:
        print("FMC130_D3_PRECHECK = PASS", flush=True)
        print("BLOCKING_REASON = (aucun)", flush=True)
    else:
        reasons = []
        if not online:
            reasons.append("TRACKER_OFFLINE")
        if not gps_normal:
            reasons.append("GPS_NOT_NORMAL")
        if not avl16_present:
            reasons.append("AVL16_NOT_CURRENTLY_EXPOSED")
        if avl16_present and not avl16_recent:
            reasons.append("AVL16_STALE")
        if avl16_present and not avl16_readable:
            reasons.append("AVL16_NOT_READABLE")
        if avl16_present and not scale_verified:
            reasons.append("MAPPING_NOT_VERIFIED")
        print("FMC130_D3_PRECHECK = BLOCKED", flush=True)
        print("BLOCKING_REASON = " + ", ".join(reasons), flush=True)
        # Aide au diagnostic si AVL16 absent mais can_mileage vivant
        if not avl16_present and cm_status == "RUNTIME_FRESH":
            print("NOTE = AVL16 NOT_CURRENTLY_EXPOSED mais can_mileage RUNTIME_FRESH "
                  "-> verifier config Total Odometer I/O (11806/11815/Total Odometer I/O) ; "
                  "can_mileage = SECONDARY_VALIDATED_SOURCE candidate.", flush=True)
    print("\n(READ-ONLY : aucune commande, aucun privatemode/setparam, aucune modif sensor/device.)", flush=True)
    print("D3_FMC130_EXECUTION = NOT_STARTED | PRIVATE_MODE_GLOBAL = DISABLED | REAL_DEVICE_COMMANDS = MOCK/SIMULATION", flush=True)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "precheck"
    if phase not in ("precheck", "before", "mapping"):
        print("usage: d3_fmc130_snapshot.py [precheck | before | mapping]")
        return
    print("[D3 FMC130] tracker=%s (READ-ONLY, resolver multi-tenant, autonome)" % TID, flush=True)
    asyncio.run(precheck())


if __name__ == "__main__":
    main()
