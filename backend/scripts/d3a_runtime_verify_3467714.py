"""D3-A RUNTIME VERIFY — OEM Mileage (AVL 389) sur 3467714 Manchester. READ-ONLY STRICT.

Config device deja faite par l'operateur (113=1, 40000=1, 40430=1, FW 04.02) -> AUCUNE ecriture.
Ce script VERIFIE seulement le runtime Navixy apres reconfiguration :
  - obd_mileage / avl_io_389 se peuplent-ils ? valeur/unite/timestamp/fraicheur
  - le vehicule roule-t-il (get_state) ? si oui -> preuve d'incrementation multi-lectures
  - VIN OBD recent (OBD actif ?) ; odometre GPS Navixy = REFERENCE seulement

Aucune ecriture, aucun setparam, aucun privatemode, aucun D3-B.
Credential via env AUDIT_NAVIXY_HASH (compte 234783).

USAGE :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY" journal_backend python3 /tmp/d3a_runtime_verify_3467714.py
RAW -> /tmp/d3a_runtime_verify_3467714_raw.json
"""
import asyncio
import json
import os
import copy
from datetime import datetime, timedelta

import httpx

TID = 3467714
RAW_OUT = "/tmp/d3a_runtime_verify_3467714_raw.json"
RECENT_HOURS = 24            # "recent" pour la fraicheur de obd_mileage
N_READS_MOVING = 4           # nb de lectures si le vehicule roule
INTERVAL_S = 60              # intervalle entre lectures (si moving)
MIN_DELTA_KM = 0.5           # delta minimal credible pour parler d'incrementation

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


def _read_oem_mileage(readings, state):
    """Cherche obd_mileage (readings) puis avl_io_389 (readings/get_state.additional)."""
    result = {"obd_mileage": None, "avl389": None}
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            rec = {"value": it.get("value"),
                   "units": it.get("units_type") or it.get("units"),
                   "timestamp": it.get("update_time") or it.get("time")}
            if nm == "obd_mileage":
                result["obd_mileage"] = rec
            if nm == "avl_io_389":
                result["avl389"] = rec
    st = (state or {}).get("state") or {}
    add = st.get("additional") or {}
    if isinstance(add, dict) and "avl_io_389" in add and not result["avl389"]:
        result["avl389"] = {"value": add["avl_io_389"].get("value"), "units": None,
                            "timestamp": add["avl_io_389"].get("updated")}
    return result


def _sensor_defined(sensors, input_name):
    return any(str(s.get("input_name")) == input_name for s in (sensors.get("list") or []))


def _vin(readings):
    for it in (readings.get("states") or []):
        if str(it.get("field")) == "obd_vin":
            return {"vin": it.get("value"), "timestamp": it.get("update_time")}
    return None


def _gps_odo(counters):
    for it in (counters.get("list") or []):
        if str(it.get("type")) == "odometer":
            return {"value": it.get("value"), "timestamp": it.get("update_time")}
    return None


def _best_oem_value(oem):
    """Priorite: obd_mileage (sensor mappe), sinon avl_io_389 brut."""
    if oem.get("obd_mileage") and oem["obd_mileage"].get("value") not in (None, ""):
        return "obd_mileage", oem["obd_mileage"]
    if oem.get("avl389") and oem["avl389"].get("value") not in (None, ""):
        return "avl_io_389", oem["avl389"]
    return None, None


async def run():
    _ = _hash()
    info = await raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    print("[AUTH] success=True", flush=True)
    now = datetime.utcnow()
    raw_dump = {"generated_utc": now.isoformat(), "reads": []}

    # Lecture initiale complete
    state = await raw("tracker/get_state", {"tracker_id": TID})
    sensors = await raw("tracker/sensor/list", {"tracker_id": TID})
    readings = await raw("tracker/readings/list", {"tracker_id": TID})
    counters = await raw("tracker/get_counters", {"tracker_id": TID})
    raw_dump["initial"] = _scrub(copy.deepcopy(
        {"get_state": state, "sensor_list": sensors,
         "readings_list": readings, "get_counters": counters}))

    st = (state or {}).get("state") or {}
    movement = str(st.get("movement_status") or "").lower()
    conn = st.get("connection_status")
    moving = movement in ("moving",) and conn in ("active", "idle", None) or movement == "moving"
    moving = (movement == "moving")

    vin = _vin(readings)
    obd_active = bool(vin and _parse_ts(vin["timestamp"])
                      and (now - _parse_ts(vin["timestamp"])) <= timedelta(hours=RECENT_HOURS))
    gps = _gps_odo(counters)

    oem = _read_oem_mileage(readings, state)
    src, val0 = _best_oem_value(oem)
    obd_mileage_defined = _sensor_defined(sensors, "obd_mileage")

    print(f"[STATE] movement={movement!r} connection={conn!r} MOVING={'YES' if moving else 'NO'}", flush=True)
    print(f"[OBD]   VIN={vin['vin'] if vin else None} @ {vin['timestamp'] if vin else 'n/a'} "
          f"-> OBD_ACTIVE={'YES' if obd_active else 'NO'}", flush=True)
    print(f"[OEM]   source={src} valeur_initiale={val0['value'] if val0 else None} "
          f"{val0['units'] if val0 else ''} @ {val0['timestamp'] if val0 else 'n/a'}", flush=True)

    # Preuve d'incrementation : multi-lectures seulement si MOVING et une valeur OEM presente
    v1 = float(val0["value"]) if (val0 and str(val0["value"]).replace('.', '', 1).replace('-', '', 1).isdigit()) else None
    v_last = v1
    ts_series = []
    if val0:
        ts_series.append((val0["value"], val0["timestamp"]))

    delta = None
    increment = "PENDING_REAL_DRIVE"
    if moving and v1 is not None:
        print(f"[DRIVE] MOVING -> {N_READS_MOVING} lectures espacees de {INTERVAL_S}s...", flush=True)
        for i in range(N_READS_MOVING - 1):
            await asyncio.sleep(INTERVAL_S)
            rd = await raw("tracker/readings/list", {"tracker_id": TID})
            stt = await raw("tracker/get_state", {"tracker_id": TID})
            oem_i = _read_oem_mileage(rd, stt)
            _, vi = _best_oem_value(oem_i)
            raw_dump["reads"].append(_scrub({"i": i + 1, "oem": oem_i}))
            if vi and str(vi["value"]).replace('.', '', 1).replace('-', '', 1).isdigit():
                v_last = float(vi["value"])
                ts_series.append((vi["value"], vi["timestamp"]))
                print(f"   lecture {i+2}: {vi['value']} @ {vi['timestamp']}", flush=True)
        if v_last is not None and v1 is not None:
            delta = round(v_last - v1, 3)
            if delta >= MIN_DELTA_KM:
                increment = "OBSERVED_INCREMENT"
            elif delta > 0:
                increment = "TINY_INCREMENT_INCONCLUSIVE"  # trop faible / resolution insuffisante
            else:
                increment = "NO_INCREMENT_OBSERVED"
    elif v1 is None:
        increment = "NO_VALUE_YET"

    # Fraicheur obd_mileage
    oem_ts = _parse_ts(val0["timestamp"]) if val0 else None
    oem_recent = bool(oem_ts and (now - oem_ts) <= timedelta(hours=RECENT_HOURS))

    # ---- VERDICT ----
    has_value = val0 is not None and val0.get("value") not in (None, "")
    if not has_value:
        verdict = ("OEM_MILEAGE_NOT_SUPPORTED_BY_VEHICLE" if obd_active
                   else "OEM_MILEAGE_CONFIG_INCONCLUSIVE")
        # nuance : si OBD actif mais pas de valeur -> plutot NOT_SUPPORTED (PID absent)
    else:
        if increment == "OBSERVED_INCREMENT":
            # VALIDATED exige AUSSI coherence tableau de bord -> a confirmer par l'operateur
            verdict = "OEM_MILEAGE_VALIDATED"
        else:
            verdict = "OEM_MILEAGE_PRESENT_PENDING_DRIVE"

    def yn(x):
        return "YES" if x else "NO"

    print("\n" + "=" * 66, flush=True)
    print("VERDICT D3-A (RUNTIME, READ-ONLY)", flush=True)
    print("=" * 66, flush=True)
    print(f"TRACKER_ID = {TID}", flush=True)
    print("MODEL = FMC003", flush=True)
    print(f"OBD_ACTIVE = {yn(obd_active)}", flush=True)
    print(f"MOVING = {yn(moving)}", flush=True)
    print("", flush=True)
    print(f"OBD_MILEAGE_SENSOR_DEFINED = {yn(obd_mileage_defined)}", flush=True)
    print(f"OBD_MILEAGE_VALUE = {oem.get('obd_mileage', {}).get('value') if oem.get('obd_mileage') else None}", flush=True)
    print(f"OBD_MILEAGE_UNIT = {oem.get('obd_mileage', {}).get('units') if oem.get('obd_mileage') else None}", flush=True)
    print(f"OBD_MILEAGE_TIMESTAMP = {oem.get('obd_mileage', {}).get('timestamp') if oem.get('obd_mileage') else None}", flush=True)
    print(f"OBD_MILEAGE_RECENT = {yn(oem_recent)}", flush=True)
    print("", flush=True)
    print(f"AVL389_PRESENT = {yn(oem.get('avl389'))}", flush=True)
    print(f"AVL389_VALUE = {oem.get('avl389', {}).get('value') if oem.get('avl389') else None}", flush=True)
    print("", flush=True)
    print(f"OEM_MILEAGE_V1 = {v1}", flush=True)
    print(f"OEM_MILEAGE_V2 = {v_last if moving else None}", flush=True)
    print(f"OEM_MILEAGE_DELTA = {delta}", flush=True)
    print(f"OEM_MILEAGE_INCREMENT = {increment}", flush=True)
    print("", flush=True)
    print(f"NAVIXY_GPS_ODOMETER = {gps['value'] if gps else None} @ "
          f"{gps['timestamp'] if gps else 'n/a'}  (REFERENCE SEULEMENT)", flush=True)
    print("", flush=True)
    print(f"D3A_VERDICT = {verdict}", flush=True)
    if verdict == "OEM_MILEAGE_VALIDATED":
        print("  NB: 'VALIDATED' runtime confirme (valeur + incrementation). RESTE a confirmer la", flush=True)
        print("      COHERENCE avec le compteur du TABLEAU DE BORD avant usage definitif.", flush=True)
    print("  (Aucune ecriture. Aucun privatemode. D3-B non lance.)", flush=True)
    print(f"  RAW -> {RAW_OUT}", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"  (ecriture RAW impossible: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
