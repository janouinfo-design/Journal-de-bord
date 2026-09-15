"""D3-A SNAPSHOT (Etapes 0+1) — tracker 3467714 (compte 234783). READ-ONLY STRICT.

============================  READ-ONLY — AUCUNE ECRITURE  ============================
- Confirme le modele reel via Navixy source.model.
- Lit UNIQUEMENT ce qui est disponible en runtime Navixy (sensor/list, readings/list,
  get_state, get_counters).
- Parametres device 113/40000/40005/40430 : NON lisibles via l'API User Navixy.
  Le script NE TENTE AUCUN getparam / raw_command/send. Il les marque NOT_READABLE_VIA_NAVIXY
  et rappelle qu'ils doivent venir du .cfg Configurator -> SOURCE = CONFIGURATOR_CFG.
- Etape 2 (ecriture) NON incluse. Aucun setparam, aucun privatemode.

Credential via env AUDIT_NAVIXY_HASH (compte 234783), jamais dans le fichier.

USAGE :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY" journal_backend python3 /tmp/d3a_snapshot_3467714.py
RAW -> /tmp/d3a_snapshot_3467714_raw.json
"""
import asyncio
import json
import os
import copy
from datetime import datetime

import httpx

TID = 3467714
EXPECTED_MODEL = "FMC003"
RAW_OUT = "/tmp/d3a_snapshot_3467714_raw.json"

# Valeurs relevees dans le .cfg fourni (Config_FMC003.cfg) — SOURCE=CONFIGURATOR_CFG.
# ATTENTION : ce .cfg avait FmType=FMC130 en en-tete ; a confirmer qu'il correspond bien
# a 3467714 (FMC003 selon Navixy). Sinon considerer ces valeurs comme NON confirmees.
CFG_REFERENCE = {
    "113_codec8ext": "1",
    "40000_obd_feature": "ABSENT_dans_cfg",
    "40005_vin_source": "ABSENT_dans_cfg",
    "40430_oem_total_mileage_priority": "ABSENT_dans_cfg",
    "_note": "SOURCE=CONFIGURATOR_CFG ; .cfg en-tete FmType=FMC130 -> a confirmer = bon device",
}

_RULES = [("_fmc003", "FMC003"), ("_fmc130", "FMC130"), ("telfmc003", "FMC003"),
          ("telfmc130", "FMC130"), ("telfmu130", "FMU130")]


def resolve_model(code):
    if not code:
        return None
    code = str(code).lower()
    for tok, m in _RULES:
        if tok in code:
            return m
    return None


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


def _find_sensor(sensor_list, input_name):
    for s in (sensor_list.get("list") or []):
        if str(s.get("input_name")) == input_name:
            return s
    return None


def _find_reading(readings, input_name):
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "")
            if nm == input_name:
                return {"value": it.get("value"), "timestamp": it.get("update_time") or it.get("time"),
                        "units": it.get("units_type") or it.get("units")}
    return None


def _has_avl389(readings, state):
    # recherche runtime uniquement (readings + get_state)
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm == "avl_io_389":
                return {"where": f"readings/{grp}", "value": it.get("value"),
                        "timestamp": it.get("update_time")}
    st = (state or {}).get("state") or {}
    add = st.get("additional") or {}
    if isinstance(add, dict) and "avl_io_389" in add:
        return {"where": "get_state.additional", "value": add["avl_io_389"].get("value"),
                "timestamp": add["avl_io_389"].get("updated")}
    return None


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


async def run():
    _ = _hash()
    info = await raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    print("[AUTH] success=True", flush=True)

    # --- ETAPE 0 : modele ---
    tl = await raw("tracker/list", {})
    trk = next((t for t in (tl.get("list") or []) if t.get("id") == TID), None)
    if not trk:
        print(f"[ETAPE 0] tracker {TID} INTROUVABLE sur ce compte -> STOP.", flush=True)
        return
    model_code = (trk.get("source") or {}).get("model")
    model = resolve_model(model_code)
    fw = (trk.get("source") or {}).get("firmware_version") or trk.get("firmware_version")
    label = trk.get("label")
    print(f"[ETAPE 0] source.model={model_code!r} -> {model} (label={label!r}) fw={fw!r}", flush=True)
    model_ok = (model == EXPECTED_MODEL)
    if not model_ok:
        print(f"  ATTENTION: modele {model} != {EXPECTED_MODEL} attendu.", flush=True)

    # --- ETAPE 1 : snapshot runtime ---
    state = await raw("tracker/get_state", {"tracker_id": TID})
    readings = await raw("tracker/readings/list", {"tracker_id": TID})
    counters = await raw("tracker/get_counters", {"tracker_id": TID})
    sensors = await raw("tracker/sensor/list", {"tracker_id": TID})

    obd_mileage_sensor = _find_sensor(sensors, "obd_mileage")
    obd_mileage_reading = _find_reading(readings, "obd_mileage")
    avl389 = _has_avl389(readings, state)
    vin = _vin(readings)
    gps = _gps_odo(counters)

    raw_dump = {
        "generated_utc": datetime.utcnow().isoformat(),
        "step0": {"model_code": model_code, "model": model, "firmware": fw, "label": label},
        "cfg_reference": CFG_REFERENCE,
        "runtime": _scrub(copy.deepcopy({
            "get_state": state, "readings_list": readings,
            "get_counters": counters, "sensor_list": sensors})),
    }
    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"  (ecriture RAW impossible: {type(e).__name__})", flush=True)

    # --- SYNTHESE (format demande) ---
    def yn(x):
        return "YES" if x else "NO"

    fw_out = fw or "NOT_READABLE_VIA_NAVIXY (voir Configurator)"
    obd_mileage_defined = obd_mileage_sensor is not None
    obd_mileage_value = obd_mileage_reading["value"] if obd_mileage_reading else None
    obd_mileage_ts = obd_mileage_reading["timestamp"] if obd_mileage_reading else None

    blocking = []
    if not model_ok:
        blocking.append(f"modele={model} (attendu FMC003)")
    # 40000/40430 inconnus via Navixy -> pas bloquant en soi, mais a confirmer via cfg du BON device
    if CFG_REFERENCE["40000_obd_feature"] != "1":
        blocking.append("40000 (OBD Feature) non confirme a 1 (cfg du bon device requis)")
    if not str(CFG_REFERENCE["40430_oem_total_mileage_priority"]).isdigit():
        blocking.append("40430 (OEM Total Mileage priority) non confirme (cfg du bon device requis)")

    ready = "NO"  # par prudence : write-ready seulement apres confirmation cfg du BON device + GO
    print("\n" + "=" * 70, flush=True)
    print("SNAPSHOT D3-A (Etapes 0+1) — READ-ONLY", flush=True)
    print("=" * 70, flush=True)
    print(f"TRACKER_ID = {TID}", flush=True)
    print(f"MODEL = {model}  (source.model={model_code})", flush=True)
    print(f"FIRMWARE = {fw_out}", flush=True)
    print("", flush=True)
    print(f"CODEC_8_EXTENDED = {CFG_REFERENCE['113_codec8ext']}  [SOURCE=CONFIGURATOR_CFG*]", flush=True)
    print(f"OBD_FEATURE = {CFG_REFERENCE['40000_obd_feature']}  [SOURCE=CONFIGURATOR_CFG*]", flush=True)
    print(f"VIN_SOURCE = {CFG_REFERENCE['40005_vin_source']}  [SOURCE=CONFIGURATOR_CFG* — LECTURE SEULE]",
          flush=True)
    print(f"OEM_TOTAL_MILEAGE_PRIORITY = {CFG_REFERENCE['40430_oem_total_mileage_priority']}  "
          f"[SOURCE=CONFIGURATOR_CFG*]", flush=True)
    print("  *NB: params device NON lisibles via Navixy (aucun getparam tente). Le .cfg fourni avait", flush=True)
    print("   FmType=FMC130 -> confirmer qu'il correspond bien a 3467714 (FMC003) sinon NON confirme.", flush=True)
    print("", flush=True)
    print(f"OBD_MILEAGE_SENSOR_DEFINED = {yn(obd_mileage_defined)}", flush=True)
    print(f"OBD_MILEAGE_VALUE = {obd_mileage_value}", flush=True)
    print(f"OBD_MILEAGE_TIMESTAMP = {obd_mileage_ts}", flush=True)
    print(f"AVL389_PRESENT_RUNTIME = {yn(avl389)}"
          + (f"  ({avl389})" if avl389 else ""), flush=True)
    print("", flush=True)
    print(f"OBD_VIN = {vin['vin'] if vin else None}  (@ {vin['timestamp'] if vin else 'n/a'})", flush=True)
    print(f"NAVIXY_GPS_ODOMETER = {gps['value'] if gps else None} @ "
          f"{gps['timestamp'] if gps else 'n/a'}  (REFERENCE SEULEMENT — EXCLU distance privee)", flush=True)
    print("", flush=True)
    print(f"AVL389_165000_PROVENANCE = UNRESOLVED", flush=True)
    print(f"D3A_CONFIG_WRITE_READY = {ready}", flush=True)
    print(f"BLOCKING_REASON = {'; '.join(blocking) if blocking else 'aucun (mais GO explicite requis)'}",
          flush=True)
    print("\nNOTE: Etape 2 NON lancee. Aucun 40000:1/40430:1, aucun setparam, aucun privatemode.", flush=True)
    print(f"RAW -> {RAW_OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
