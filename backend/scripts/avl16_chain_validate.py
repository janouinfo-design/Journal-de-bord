"""AVL16 CHAIN VALIDATION — pilote 3467714 (Manchester). READ-ONLY STRICT.

Ferme la chaîne : Total Odometer Teltonika -> AVL16 -> sensor Navixy -> API -> km normalisé -> incrément.

Vérifie :
  1. sensor Navixy AVL IO 16 : Parameter=AVL IO[N], input=16 (avl_io_16), unit=km, mult=1, div=1000 ;
  2. AVL16_RAW_VALUE / AVL16_TIMESTAMP (valeur brute) ;
  3. SENSOR_VALUE_KM / SENSOR_TIMESTAMP (valeur normalisée exposée par l'API) ;
  4. API_READABLE ;
  5. >=2 relevés en roulage -> RAW_DELTA>0 et SENSOR_KM_DELTA>0.

READ-ONLY : aucune écriture, aucun changement sensor, aucun privatemode, aucun D3.
Credential via env AUDIT_NAVIXY_HASH (compte 234783).
USAGE :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY" journal_backend python3 /tmp/avl16_chain_validate.py
Options env : TID (défaut 3467714), READS (défaut 4), INTERVAL (défaut 60).
RAW -> /tmp/avl16_chain_validate_raw.json
"""
import asyncio
import json
import os
import copy
from datetime import datetime

import httpx

TID = int(os.environ.get("TID", "3467714"))
N_READS = int(os.environ.get("READS", "4"))
INTERVAL_S = int(os.environ.get("INTERVAL", "60"))
RAW_OUT = "/tmp/avl16_chain_validate_raw.json"
EXPECTED_DIVIDER = 1000.0   # attendu (m->km) ; on VÉRIFIE, on n'impose pas

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


def _find_avl16_sensor(sensors):
    """Sensor Navixy mappé sur AVL 16 (input avl_io_16) OU hw_mileage."""
    for s in (sensors.get("list") or []):
        inp = str(s.get("input_name") or "").lower()
        if inp in ("avl_io_16", "hw_mileage"):
            return s
    return None


def _read_input(readings, names):
    """Lit un input brut (valeur/ts/unit) par nom dans readings/list."""
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm in names:
                return {"input": nm, "value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "converted_value": it.get("converted_value"),
                        "timestamp": it.get("update_time") or it.get("time")}
    return None


def _read_sensor_km(readings, sensor_name_sub):
    """Lit la valeur exposée par le sensor Navixy (par libellé)."""
    for grp in ("inputs", "virtual_sensors", "sensors"):
        for it in (readings.get(grp) or []):
            if sensor_name_sub in str(it.get("label") or it.get("name") or "").lower():
                return {"value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time")}
    return None


async def _snapshot():
    sensors = await raw("tracker/sensor/list", {"tracker_id": TID})
    readings = await raw("tracker/readings/list", {"tracker_id": TID})
    state = await raw("tracker/get_state", {"tracker_id": TID})
    return sensors, readings, state


async def run():
    _ = _hash()
    info = await raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    print(f"[AUTH] success=True  TID={TID}", flush=True)

    sensors, readings, state = await _snapshot()
    raw_dump = {"generated_utc": datetime.utcnow().isoformat(),
                "sensor_list": _scrub(copy.deepcopy(sensors)),
                "reads": []}

    st = (state or {}).get("state") or {}
    moving = str(st.get("movement_status") or "").lower() == "moving"

    # 1) Sensor AVL 16
    s16 = _find_avl16_sensor(sensors)
    print("\n----- [1] SENSOR NAVIXY AVL IO 16 -----", flush=True)
    if s16:
        print(f"  id={s16.get('id')} name={s16.get('name')!r} input={s16.get('input_name')}", flush=True)
        print(f"  multiplier={s16.get('multiplier')} divider={s16.get('divider')} "
              f"unit={s16.get('units_type')}", flush=True)
        div_ok = float(s16.get('divider') or 0) == EXPECTED_DIVIDER
        mult_ok = float(s16.get('multiplier') or 0) == 1.0
        unit_ok = str(s16.get('units_type') or '').lower() in ("kilometre", "km")
        print(f"  attendu: mult=1 div=1000 unit=km -> mult_ok={mult_ok} div_ok={div_ok} unit_ok={unit_ok}",
              flush=True)
    else:
        print("  SENSOR AVL 16 INTROUVABLE (input avl_io_16 / hw_mileage). "
              "-> creer le sensor OU verifier le mapping.", flush=True)

    # 2/3) valeurs brute + sensor km
    raw16 = _read_input(readings, {"avl_io_16", "hw_mileage"})
    sens_km = None
    if s16 and s16.get("name"):
        sens_km = _read_sensor_km(readings, str(s16["name"]).lower()[:6])
    print("\n----- [2/3] VALEURS -----", flush=True)
    print(f"  AVL16_RAW_VALUE   = {raw16['value'] if raw16 else None} "
          f"(input={raw16['input'] if raw16 else '-'}, unit={raw16['units'] if raw16 else '-'})", flush=True)
    print(f"  AVL16_TIMESTAMP   = {raw16['timestamp'] if raw16 else None}", flush=True)
    print(f"  SENSOR_VALUE_KM   = {sens_km['value'] if sens_km else None} "
          f"{sens_km['units'] if sens_km else ''}", flush=True)
    print(f"  SENSOR_TIMESTAMP  = {sens_km['timestamp'] if sens_km else None}", flush=True)

    api_readable = bool(raw16 and raw16.get("value") not in (None, "")) or \
        bool(sens_km and sens_km.get("value") not in (None, ""))
    print(f"  API_READABLE      = {'YES' if api_readable else 'NO'}", flush=True)

    # NB: tracker/readings/list renvoie DÉJÀ la valeur NORMALISÉE (après divider du sensor).
    # La valeur brute en mètres n'est PAS exposée ici (voir sensor/data/read / historique hw_mileage).
    # On juge la cohérence par : valeur normalisée ≈ compteur de référence (tableau de bord).
    coherence = None
    if raw16 and sens_km and _isnum(raw16["value"]) and _isnum(sens_km["value"]):
        same = abs(float(raw16["value"]) - float(sens_km["value"])) < 0.01
        print(f"  NOTE: readings/list = valeur normalisee (km). raw==sensor -> {same} "
              f"(le brut en metres n'est pas expose par cet endpoint).", flush=True)
        coherence = same

    # 4/5) incrementation
    print(f"\n----- [4/5] INCREMENTATION (MOVING={'YES' if moving else 'NO'}) -----", flush=True)
    raw_v1 = float(raw16["value"]) if (raw16 and _isnum(raw16["value"])) else None
    km_v1 = float(sens_km["value"]) if (sens_km and _isnum(sens_km["value"])) else None
    raw_last, km_last = raw_v1, km_v1
    if raw_v1 is not None or km_v1 is not None:
        raw_dump["reads"].append({"i": 0, "raw": raw_v1, "km": km_v1})
    if moving and (raw_v1 is not None or km_v1 is not None):
        for i in range(N_READS - 1):
            await asyncio.sleep(INTERVAL_S)
            _, rd, _stt = await _snapshot()
            r = _read_input(rd, {"avl_io_16", "hw_mileage"})
            k = _read_sensor_km(rd, str(s16["name"]).lower()[:6]) if s16 and s16.get("name") else None
            if r and _isnum(r["value"]):
                raw_last = float(r["value"])
            if k and _isnum(k["value"]):
                km_last = float(k["value"])
            raw_dump["reads"].append({"i": i + 1,
                                      "raw": r["value"] if r else None,
                                      "km": k["value"] if k else None})
            print(f"   lecture {i+2}: raw={r['value'] if r else None}  km={k['value'] if k else None}",
                  flush=True)
    else:
        print("   MOVING=NO -> increment PENDING_REAL_DRIVE (relancer en roulage).", flush=True)

    raw_delta = (round(raw_last - raw_v1, 3) if (raw_v1 is not None and raw_last is not None) else None)
    km_delta = (round(km_last - km_v1, 3) if (km_v1 is not None and km_last is not None) else None)

    # Verdicts partiels
    api_mapping = "VERIFIED" if (s16 and api_readable) else ("PARTIAL" if s16 else "NOT_MAPPED")
    cumulative = ("VERIFIED" if (raw_delta and raw_delta > 0) or (km_delta and km_delta > 0)
                  else ("PENDING_REAL_DRIVE" if not moving else "NO_INCREMENT_OBSERVED"))
    if api_readable and coherence:
        scale = "RUNTIME_PENDING (valeur km coherente ; confirmer vs tableau de bord + increment)"
    elif api_readable:
        scale = "RUNTIME_PENDING (verifier vs tableau de bord)"
    else:
        scale = "UNVERIFIED"

    print("\n" + "=" * 66, flush=True)
    print("SYNTHESE — CHAINE AVL16", flush=True)
    print("=" * 66, flush=True)
    print(f"  API_READABLE        = {'YES' if api_readable else 'NO'}", flush=True)
    print(f"  AVL16_API_MAPPING   = {api_mapping}", flush=True)
    print(f"  RAW_DELTA           = {raw_delta}", flush=True)
    print(f"  SENSOR_KM_DELTA     = {km_delta}", flush=True)
    print(f"  AVL16_CUMULATIVE    = {cumulative}", flush=True)
    print(f"  AVL16_SCALE         = {scale}", flush=True)
    print("  DASHBOARD_COMPARISON= TO_CONFIRM (compteur reference Configurator / tableau de bord)", flush=True)
    print("  NOTE: passer AVL16_SCALE/CUMULATIVE a VERIFIED seulement apres incrément reel + coherence.", flush=True)
    print("  Aucune ecriture. Aucun privatemode. D3 non prepare a ce stade.", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"  RAW -> {RAW_OUT}", flush=True)
    except Exception as e:
        print(f"  (ecriture RAW impossible: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
