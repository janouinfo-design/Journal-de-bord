"""D3-A DUAL SOURCE — hw_mileage (AVL 16) + Total Odo (AVL 389) — 3467714. READ-ONLY.

Suit EN PARALLÈLE les 2 sources de distance privée candidates :
  - AVL 16  / hw_mileage  (odomètre interne GNSS ; capteur Navixy "Odometer") — UNIVERSEL
  - AVL 389 / "Total Odo" (OEM OBD, vrai km véhicule ; FMC003 compatibles)
Affiche la valeur BRUTE + valeur capteur (API) pour caler la calibration (m->km, x100...).
Vérifie l'incrémentation si le véhicule roule.

READ-ONLY : aucune écriture, aucun changement sensor, aucun privatemode, aucun D3-B.
Credential via env AUDIT_NAVIXY_HASH (compte 234783).
USAGE :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY" journal_backend python3 /tmp/d3a_dual_source_3467714.py
RAW -> /tmp/d3a_dual_source_3467714_raw.json
"""
import asyncio
import json
import os
import copy
from datetime import datetime

import httpx

TID = 3467714
RAW_OUT = "/tmp/d3a_dual_source_3467714_raw.json"
N_READS_MOVING = 4
INTERVAL_S = 60
MIN_DELTA_KM = 0.3

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


def _isnum(x):
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _reading_by_name(readings, names):
    """Retourne la 1re lecture dont input_name/name/field ∈ names (lowercase)."""
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm in names:
                return {"input": nm, "value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time") or it.get("time"),
                        "label": it.get("label")}
    return None


def _sensor_by(sensors, want_input=None, want_avl=None, want_name_sub=None):
    for s in (sensors.get("list") or []):
        inp = str(s.get("input_name") or "").lower()
        name = str(s.get("name") or "").lower()
        if want_input and inp == want_input:
            return s
        if want_name_sub and want_name_sub in name:
            return s
    return None


def _read_hw_mileage(readings):
    # champ brut documenté par Navixy : inputs.hw_mileage ; sinon avl_io_16
    return _reading_by_name(readings, {"hw_mileage", "avl_io_16"})


def _read_total_odo_389(readings):
    return _reading_by_name(readings, {"avl_io_389", "obd_mileage"})


def _read_sensor_named(readings, name_sub):
    for grp in ("inputs", "virtual_sensors", "sensors"):
        for it in (readings.get(grp) or []):
            if name_sub in str(it.get("label") or it.get("name") or "").lower():
                return {"value": it.get("value"), "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time"), "label": it.get("label")}
    return None


def _gps_odo(counters):
    for it in (counters.get("list") or []):
        if str(it.get("type")) == "odometer":
            return {"value": it.get("value"), "timestamp": it.get("update_time")}
    return None


def _suggest_scale(raw_value, unit_hint):
    """Propose un facteur de conversion vers km selon l'unité brute."""
    if not _isnum(raw_value):
        return "raw non numerique"
    rv = float(raw_value)
    if unit_hint and "m" == str(unit_hint).lower():
        return f"unite=m -> diviser par 1000 => {rv/1000:.3f} km"
    if rv > 1_000_000:
        return f"valeur elevee ({rv}) -> probablement en metres -> /1000 => {rv/1000:.1f} km"
    return f"valeur {rv} (verifier vs tableau de bord pour caler le facteur)"


async def run():
    _ = _hash()
    info = await raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    print("[AUTH] success=True", flush=True)

    state = await raw("tracker/get_state", {"tracker_id": TID})
    sensors = await raw("tracker/sensor/list", {"tracker_id": TID})
    readings = await raw("tracker/readings/list", {"tracker_id": TID})
    counters = await raw("tracker/get_counters", {"tracker_id": TID})

    raw_dump = {"generated_utc": datetime.utcnow().isoformat(),
                "initial": _scrub(copy.deepcopy(
                    {"get_state": state, "sensor_list": sensors,
                     "readings_list": readings, "get_counters": counters})),
                "reads": []}

    st = (state or {}).get("state") or {}
    moving = str(st.get("movement_status") or "").lower() == "moving"

    # Sources brutes
    hw = _read_hw_mileage(readings)            # AVL 16 brut
    odo389 = _read_total_odo_389(readings)     # AVL 389 brut
    # Capteurs Navixy (valeurs calibrées) par nom
    sensor_odometer = _read_sensor_named(readings, "odometer") or _read_sensor_named(readings, "odometre")
    sensor_totalodo = _read_sensor_named(readings, "total odo")
    gps = _gps_odo(counters)

    # Métadonnées sensor (calibration)
    s16 = _sensor_by(sensors, want_input="hw_mileage") or _sensor_by(sensors, want_name_sub="odometer") \
        or _sensor_by(sensors, want_name_sub="odometre")
    s389 = _sensor_by(sensors, want_name_sub="total odo")

    def sens_meta(s):
        if not s:
            return "(sensor introuvable)"
        return (f"id={s.get('id')} name={s.get('name')!r} input={s.get('input_name')} "
                f"mult={s.get('multiplier')} div={s.get('divider')} unit={s.get('units_type')}")

    print("\n" + "=" * 70, flush=True)
    print("D3-A DUAL SOURCE — hw_mileage (AVL16) + Total Odo (AVL389) — READ-ONLY", flush=True)
    print("=" * 70, flush=True)
    print(f"MOVING = {'YES' if moving else 'NO'}", flush=True)
    print("", flush=True)

    print("--- SOURCE 1 : AVL 16 / hw_mileage (UNIVERSEL, continue a 0,0 selon Navixy) ---", flush=True)
    print(f"  hw_mileage brut      = {hw['value'] if hw else None} (input={hw['input'] if hw else '-'}, "
          f"unit={hw['units'] if hw else '-'}, @ {hw['timestamp'] if hw else '-'})", flush=True)
    print(f"  sensor 'Odometer'    = {sensor_odometer['value'] if sensor_odometer else None} "
          f"{sensor_odometer['units'] if sensor_odometer else ''}", flush=True)
    print(f"  sensor meta          = {sens_meta(s16)}", flush=True)
    if hw:
        print(f"  echelle              = {_suggest_scale(hw['value'], hw.get('units'))}", flush=True)
    print("", flush=True)

    print("--- SOURCE 2 : AVL 389 / Total Odo (OEM OBD, vrai km vehicule) ---", flush=True)
    print(f"  avl389 brut          = {odo389['value'] if odo389 else None} "
          f"(input={odo389['input'] if odo389 else '-'}, @ {odo389['timestamp'] if odo389 else '-'})",
          flush=True)
    print(f"  sensor 'Total Odo'   = {sensor_totalodo['value'] if sensor_totalodo else None} "
          f"{sensor_totalodo['units'] if sensor_totalodo else ''}", flush=True)
    print(f"  sensor meta          = {sens_meta(s389)}", flush=True)
    print("", flush=True)
    print(f"  NAVIXY_GPS_ODOMETER  = {gps['value'] if gps else None} (REFERENCE — EXCLU)", flush=True)

    # Incrementation si moving (sur les 2 sources)
    def val_of(src_reader):
        r = src_reader(readings)
        return float(r["value"]) if (r and _isnum(r["value"])) else None

    hw_v1 = val_of(_read_hw_mileage)
    odo_v1 = val_of(_read_total_odo_389)
    hw_last, odo_last = hw_v1, odo_v1
    if moving and (hw_v1 is not None or odo_v1 is not None):
        print(f"\n[DRIVE] MOVING -> {N_READS_MOVING} lectures espacees de {INTERVAL_S}s...", flush=True)
        for i in range(N_READS_MOVING - 1):
            await asyncio.sleep(INTERVAL_S)
            rd = await raw("tracker/readings/list", {"tracker_id": TID})
            h = _read_hw_mileage(rd)
            o = _read_total_odo_389(rd)
            if h and _isnum(h["value"]):
                hw_last = float(h["value"])
            if o and _isnum(o["value"]):
                odo_last = float(o["value"])
            raw_dump["reads"].append({"i": i + 1,
                                      "hw": h["value"] if h else None,
                                      "avl389": o["value"] if o else None})
            print(f"   lecture {i+2}: hw={h['value'] if h else None}  avl389={o['value'] if o else None}",
                  flush=True)

    def delta(v1, vlast):
        if v1 is None or vlast is None:
            return None
        return round(vlast - v1, 3)

    hw_d = delta(hw_v1, hw_last)
    odo_d = delta(odo_v1, odo_last)

    print("\n" + "=" * 70, flush=True)
    print("SYNTHESE", flush=True)
    print("=" * 70, flush=True)
    print(f"HW_MILEAGE (AVL16)  present={'YES' if hw else 'NO'}  brut_v1={hw_v1}  brut_last={hw_last}  "
          f"delta={hw_d}", flush=True)
    print(f"AVL389 (Total Odo)  present={'YES' if odo389 else 'NO'}  v1={odo_v1}  last={odo_last}  "
          f"delta={odo_d}", flush=True)
    if not moving:
        print("MOVING=NO -> increment = PENDING_REAL_DRIVE (relancer pendant roulage)", flush=True)
    print("DASHBOARD_COMPARISON = TO_CONFIRM (photo compteur tableau de bord)", flush=True)
    print("\nNOTES:", flush=True)
    print(" - AVL16 attendu en METRES (Configurator Total Odometer = m) -> sensor km : diviser /1000.", flush=True)
    print(" - Si hw_mileage ABSENT : verifier que l'I/O Total Odometer=Low est bien ECRIT dans le", flush=True)
    print("   device (Save to device / FOTA), pas seulement edite sur PC.", flush=True)
    print(" - Aucune ecriture. Aucun privatemode. D3-B non lance.", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f" RAW -> {RAW_OUT}", flush=True)
    except Exception as e:
        print(f" (ecriture RAW impossible: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
