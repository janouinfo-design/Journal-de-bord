"""D3-A « Total Odo » (AVL 389) — FMC003 Manchester 3467714. READ-ONLY STRICT.

Objectif : confirmer que l'AVL 389 (mappé en sensor Navixy « Total Odo ») est exploitable
par LOGITRAK via l'API, et DIAGNOSTIQUER l'échelle (165.11 affiché vs ~165113 brut).

READ-ONLY : aucune écriture, AUCUN changement de sensor, aucun privatemode, aucun D3-B.
Le script LIT et EXPLIQUE ; il ne corrige rien (la correction d'échelle sera proposée, pas appliquée).

Distingue : AVL389_RAW_VALUE / NAVIXY_SENSOR_VALUE / UNIT / MULTIPLIER / DIVIDER / API_VALUE.

Credential via env AUDIT_NAVIXY_HASH (compte 234783).
USAGE :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY" journal_backend python3 /tmp/d3a_total_odo_3467714.py
RAW -> /tmp/d3a_total_odo_3467714_raw.json
"""
import asyncio
import json
import os
import copy
from datetime import datetime, timedelta

import httpx

TID = 3467714
RAW_OUT = "/tmp/d3a_total_odo_3467714_raw.json"
RECENT_HOURS = 24
N_READS_MOVING = 4
INTERVAL_S = 60
MIN_DELTA = 0.05  # seuil credible d'increment (unite du sensor)

# Noms/labels susceptibles de porter l'OEM mileage (le sensor a ete nomme "Total Odo").
ODO_LABEL_HINTS = ["total odo", "total_odo", "totalodo", "odo", "kilométrage", "kilometrage",
                   "mileage", "odometer"]
ODO_INPUT_HINTS = ["avl_io_389", "obd_mileage", "total_odo", "total_odometer"]

SECRET_KEY_HINTS = ["hash", "token", "api_key", "apikey", "password", "secret",
                    "credential", "imei", "sim", "iccid", "imsi", "phone", "msisdn", "device_id"]
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


def _base_url():
    return os.environ.get("AUDIT_NAVIXY_URL", "https://api.navixy.com/v2").rstrip("/")


def _hash():
    h = os.environ.get("AUDIT_NAVIXY_HASH", "").strip()
    if not h:
        raise SystemExit("ABORT: AUDIT_NAVIXY_HASH absent (cle du compte 234783 via -e).")
    return h


async def raw(path, payload):
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            r = await c.post(f"{_base_url()}/{path}", json={"hash": _hash(), **payload})
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


def _isnum(x):
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _find_odo_sensor(sensors):
    """Repère le sensor 'Total Odo' / obd_mileage dans sensor/list, retourne le dict complet."""
    best = None
    for s in (sensors.get("list") or []):
        name = str(s.get("name") or "").lower()
        inp = str(s.get("input_name") or "").lower()
        if any(h in inp for h in ODO_INPUT_HINTS) or any(h in name for h in ODO_LABEL_HINTS):
            # priorite a un input odometrique explicite
            if any(h in inp for h in ("avl_io_389", "obd_mileage", "total_od")):
                return s
            best = best or s
    return best


def _find_reading(readings, input_name, label_sub=None):
    """Cherche la valeur courante d'un input (readings/list)."""
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            lb = str(it.get("label") or "").lower()
            if (input_name and nm == input_name.lower()) or \
               (label_sub and label_sub in lb):
                return {"value": it.get("value"),
                        "converted_value": it.get("converted_value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time") or it.get("time"),
                        "raw_input_name": it.get("input_name") or it.get("name")}
    return None


def _find_avl389_raw(readings, state):
    """Valeur BRUTE de avl_io_389 si exposée telle quelle (readings ou get_state.additional)."""
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm == "avl_io_389":
                return {"value": it.get("value"), "timestamp": it.get("update_time"),
                        "where": f"readings/{grp}"}
    st = (state or {}).get("state") or {}
    add = st.get("additional") or {}
    if isinstance(add, dict) and "avl_io_389" in add:
        return {"value": add["avl_io_389"].get("value"),
                "timestamp": add["avl_io_389"].get("updated"), "where": "get_state.additional"}
    return None


async def _read_odo_value(sensor, readings):
    """Retourne la valeur courante du sensor odo via son input_name ou son label."""
    if not sensor:
        return None
    inp = sensor.get("input_name")
    r = _find_reading(readings, input_name=inp) if inp else None
    if not r:
        r = _find_reading(readings, input_name=None,
                          label_sub=str(sensor.get("name") or "").lower()[:6])
    return r


async def run():
    _ = _hash()
    info = await raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    print("[AUTH] success=True", flush=True)
    now = datetime.utcnow()

    state = await raw("tracker/get_state", {"tracker_id": TID})
    sensors = await raw("tracker/sensor/list", {"tracker_id": TID})
    readings = await raw("tracker/readings/list", {"tracker_id": TID})

    raw_dump = {"generated_utc": now.isoformat(),
                "initial": _scrub(copy.deepcopy(
                    {"get_state": state, "sensor_list": sensors, "readings_list": readings})),
                "reads": []}

    sensor = _find_odo_sensor(sensors)
    avl_raw = _find_avl389_raw(readings, state)
    r0 = await _read_odo_value(sensor, readings)

    st = (state or {}).get("state") or {}
    moving = str(st.get("movement_status") or "").lower() == "moving"

    # Mapping sensor (multiplier/divider/unite/formule)
    mult = sensor.get("multiplier") if sensor else None
    divi = sensor.get("divider") if sensor else None
    unit = (sensor.get("units_type") or sensor.get("units")) if sensor else None
    sid = sensor.get("id") if sensor else None
    sname = sensor.get("name") if sensor else None
    sinput = sensor.get("input_name") if sensor else None

    # Diagnostic d'echelle : comparer AVL brut vs valeur sensor
    api_value = r0.get("value") if r0 else None
    api_ts = r0.get("timestamp") if r0 else None
    raw_value = avl_raw.get("value") if avl_raw else None

    # Multi-lectures si moving (preuve d'increment sur la valeur exploitable par l'API)
    v1 = float(api_value) if _isnum(api_value) else None
    v_last = v1
    if v1 is not None:
        raw_dump["reads"].append({"i": 0, "value": api_value, "ts": api_ts})
    delta = None
    increment = "PENDING_REAL_DRIVE"
    if moving and v1 is not None:
        print(f"[DRIVE] MOVING -> {N_READS_MOVING} lectures espacees de {INTERVAL_S}s...", flush=True)
        for i in range(N_READS_MOVING - 1):
            await asyncio.sleep(INTERVAL_S)
            rd = await raw("tracker/readings/list", {"tracker_id": TID})
            ri = await _read_odo_value(sensor, rd)
            vi = ri.get("value") if ri else None
            if _isnum(vi):
                v_last = float(vi)
                raw_dump["reads"].append({"i": i + 1, "value": vi, "ts": ri.get("timestamp")})
                print(f"   lecture {i+2}: {vi} @ {ri.get('timestamp')}", flush=True)
        if v_last is not None and v1 is not None:
            delta = round(v_last - v1, 4)
            increment = "OBSERVED_INCREMENT" if delta >= MIN_DELTA else (
                "TINY_OR_NONE" if delta >= 0 else "DECREASED_ANOMALY")
    elif v1 is None:
        increment = "NO_VALUE_YET"

    # Analyse d'echelle
    scale_status = "UNKNOWN"
    scale_note = ""
    if _isnum(raw_value) and _isnum(api_value):
        ratio = float(raw_value) / float(api_value) if float(api_value) != 0 else None
        if ratio and 900 <= ratio <= 1100:
            scale_status = "DIVIDER_1000_APPLIED"
            scale_note = (f"AVL brut {raw_value} / API {api_value} ≈ x{round(ratio)} "
                          f"-> divider=1000 applique a tort (unite probable: km entiers).")
        elif ratio and 0.9 <= ratio <= 1.1:
            scale_status = "OK_1_TO_1"
            scale_note = "AVL brut ≈ valeur API (pas de division parasite)."
        else:
            scale_status = "RATIO_OTHER"
            scale_note = f"ratio brut/API = {ratio}."
    elif _isnum(api_value) and not _isnum(raw_value):
        # AVL brut non expose separement ; deduire du couple 165.11 vs attendu
        scale_status = "RAW_NOT_EXPOSED"
        scale_note = ("avl_io_389 brut non expose separement dans l'API ; le sensor 'Total Odo' "
                      "porte la valeur transformee. Verifier divider/unite du sensor.")

    print("\n" + "=" * 68, flush=True)
    print("D3-A « Total Odo » (AVL 389) — RUNTIME READ-ONLY", flush=True)
    print("=" * 68, flush=True)
    print(f"TRACKER = {TID}", flush=True)
    print("MODEL = FMC003", flush=True)
    print("", flush=True)
    print(f"AVL389_PRESENT = {'YES' if avl_raw else 'NO (brut non expose separement)'}", flush=True)
    print(f"AVL389_RAW_VALUE = {raw_value}", flush=True)
    print(f"AVL389_TIMESTAMP = {avl_raw.get('timestamp') if avl_raw else None}", flush=True)
    print("", flush=True)
    print(f"TOTAL_ODO_SENSOR_DEFINED = {'YES' if sensor else 'NO'}", flush=True)
    print(f"TOTAL_ODO_SENSOR_ID = {sid}", flush=True)
    print(f"TOTAL_ODO_SENSOR_NAME = {sname}", flush=True)
    print(f"TOTAL_ODO_SENSOR_INPUT = {sinput}", flush=True)
    print(f"TOTAL_ODO_SENSOR_VALUE (API) = {api_value}", flush=True)
    print(f"TOTAL_ODO_SENSOR_UNIT = {unit}", flush=True)
    print(f"TOTAL_ODO_MULTIPLIER = {mult}", flush=True)
    print(f"TOTAL_ODO_DIVIDER = {divi}", flush=True)
    print(f"API_TIMESTAMP = {api_ts}", flush=True)
    print("", flush=True)
    print(f"LOGITRAK_API_READABLE = {'YES' if api_value is not None else 'NO'}"
          f"  (via tracker/readings/list + tracker/sensor/list)", flush=True)
    print(f"MOVING = {'YES' if moving else 'NO'}", flush=True)
    print(f"INCREMENT_PROVEN = {increment}"
          + (f" (delta={delta})" if delta is not None else ""), flush=True)
    print("DASHBOARD_COMPARISON = TO_CONFIRM (compteur tableau de bord non fourni)", flush=True)
    print("", flush=True)
    print(f"SCALE_STATUS = {scale_status}", flush=True)
    if scale_note:
        print(f"  -> {scale_note}", flush=True)
    if scale_status == "DIVIDER_1000_APPLIED":
        print("  CORRECTION PROPOSÉE (NON appliquée) : dans le sensor Navixy 'Total Odo',", flush=True)
        print("    régler divider=1 (au lieu de 1000) OU unité en km entiers, pour afficher la", flush=True)
        print("    valeur brute AVL (~165113) au lieu de 165.11.", flush=True)

    # Verdict
    has_value = api_value is not None
    if not has_value:
        verdict = "OEM_MILEAGE_INCONCLUSIVE"
    elif scale_status in ("DIVIDER_1000_APPLIED", "RATIO_OTHER"):
        verdict = "OEM_MILEAGE_SCALE_NEEDS_FIX"
    elif increment == "OBSERVED_INCREMENT":
        verdict = "OEM_MILEAGE_PENDING_DASHBOARD_CONFIRMATION"  # technique OK, reste compteur reel
    else:
        verdict = "OEM_MILEAGE_PENDING_DASHBOARD_CONFIRMATION"

    print("", flush=True)
    print(f"D3A_VERDICT = {verdict}", flush=True)
    print("  (OEM_MILEAGE_VALIDATED exige AUSSI la comparaison au compteur reel du tableau de bord.)",
          flush=True)
    print("  Aucune ecriture. Aucun changement sensor. Aucun privatemode. Aucun D3-B.", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"  RAW -> {RAW_OUT}", flush=True)
    except Exception as e:
        print(f"  (ecriture RAW impossible: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
