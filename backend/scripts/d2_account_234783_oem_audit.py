"""AUDIT AD-HOC compte Navixy 234783 — tracker 3467714 (OEM Mileage AVL 389). READ-ONLY.

============================  SÉCURITÉ / READ-ONLY  ============================
- Ce script est AUTONOME : il n'utilise NI la DB NI les tenants du backend.
- Le credential du compte 234783 est fourni par VOUS via variable d'environnement,
  sur VOTRE VPS. Il n'est JAMAIS écrit dans le script, jamais loggé, jamais renvoyé.
- READ-ONLY strict : aucune écriture, aucune commande device, aucun D3.

CREDENTIAL (à définir au moment du docker exec, PAS dans le fichier) :
  AUDIT_NAVIXY_HASH   = clé API / hash de session du compte Navixy 234783   (obligatoire)
  AUDIT_NAVIXY_URL    = base URL API (défaut https://api.navixy.com/v2)      (optionnel)

USAGE (READ-ONLY) — le secret reste sur votre VPS via -e :
  docker exec -e AUDIT_NAVIXY_HASH="<CLE_DU_COMPTE_234783>" \
    journal_backend python3 /tmp/d2_account_234783_oem_audit.py

  (si le compte est sur une autre instance Navixy, ajouter aussi
   -e AUDIT_NAVIXY_URL="https://<host>/api/v2")

OBJECTIF :
  1. Confirmer que le credential donne accès au compte (user/get_info) — SANS afficher le secret.
  2. Lister les trackers du compte, confirmer le source.model RÉEL de 3467714.
  3. Chercher avl_io_389 (OBD OEM Total Mileage, km) sur 3467714 + tous FMC003/FMC130 du compte.
  4. 2 lectures espacées (SLEEP_S) -> amorcer preuve d'incrémentation (LIVE / CUMULATIVE).
"""
import asyncio
import json
import os
import copy
from datetime import datetime, timedelta

import httpx

FOCUS_TRACKER = 3467714
TARGET_MODELS = ("FMC003", "FMC130")
RECENT_DAYS = 30
SLEEP_S = 90
RAW_OUT = "/tmp/d2_account_234783_oem_raw.json"

_NAVIXY_MODEL_RULES = [
    ("_fmc003", "FMC003"), ("_fmc130", "FMC130"),
    ("_fmc640", "FMC640"), ("_fmc650", "FMC650"),
    ("telfmc003", "FMC003"), ("telfmc130", "FMC130"),
    ("telfmc640", "FMC640"), ("telfmc650", "FMC650"),
    ("telfmu130", "FMU130"),
]


def resolve_model(code):
    if not code:
        return None
    code = str(code).lower()
    for token, model in _NAVIXY_MODEL_RULES:
        if token in code:
            return model
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
        raise SystemExit("ABORT: variable d'env AUDIT_NAVIXY_HASH absente. "
                         "Fournir la cle du compte 234783 via -e AUDIT_NAVIXY_HASH=... (jamais dans le fichier).")
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


def _age_days(ts, now):
    dt = _parse_ts(ts)
    return None if not dt else round((now - dt).total_seconds() / 86400.0, 2)


def _iter_inputs(readings):
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            if isinstance(it, dict):
                yield grp, it


def _extract_avl389(readings):
    others = []
    avl389 = None
    for grp, it in _iter_inputs(readings):
        name = str(it.get("input_name") or it.get("name") or it.get("label") or it.get("field") or "").lower()
        rec = {"group": grp, "field": name or None, "value": it.get("value"),
               "units": it.get("units_type") or it.get("units") or it.get("unit"),
               "timestamp": it.get("update_time") or it.get("time")}
        if name == "avl_io_389":
            avl389 = rec
        elif name.startswith("avl_io_") or any(h in name for h in
                                               ("mileage", "odometer", "odo", "distance")):
            others.append(rec)
    return avl389, others


def _gps_odo(counters):
    for coll in ("list", "counters"):
        for it in (counters.get(coll) or []):
            if isinstance(it, dict) and str(it.get("type")) == "odometer":
                return {"value": it.get("value"), "timestamp": it.get("update_time")}
    return None


async def read_vehicle(tid, label, model_code, now):
    rd = await raw("tracker/readings/list", {"tracker_id": tid})
    counters = await raw("tracker/get_counters", {"tracker_id": tid})
    avl, others = _extract_avl389(rd)
    return {"tid": tid, "label": label, "model_code": model_code,
            "model": resolve_model(model_code), "avl389": avl, "others": others,
            "gps_odo": _gps_odo(counters)}


def _status(row, avl2, now):
    a1 = row.get("avl389")
    if not (a1 and a1.get("value") not in (None, "")):
        row["AVL389_PRESENT"] = "NO"
        row["STATUS"] = "NO_OEM_MILEAGE"
        return row
    row["AVL389_PRESENT"] = "YES"
    v1, ts1 = a1.get("value"), a1.get("timestamp")
    age = _age_days(ts1, now)
    recent = (age is not None and age <= RECENT_DAYS)
    v2 = avl2.get("value") if avl2 else None
    inc = None
    try:
        if v1 is not None and v2 is not None:
            inc = float(v2) > float(v1)
    except Exception:
        inc = None
    row.update({"VALUE": v1, "UNIT": a1.get("units") or "km (AVL389 doc)", "TIMESTAMP": ts1,
                "AGE_DAYS": age, "VALUE_2ND": v2,
                "INCREASED": "YES" if inc else "NO" if inc is False else "UNKNOWN",
                "LIVE": "YES" if recent else ("TO_VERIFY" if age is None else "NO"),
                "CUMULATIVE": "YES" if inc else ("TO_VERIFY" if inc is None else "NOT_OBSERVED")})
    if not recent and age is not None:
        row["STATUS"] = "OEM_MILEAGE_STALE"
    elif inc:
        row["STATUS"] = "OEM_MILEAGE_LIVE"
    else:
        row["STATUS"] = "OEM_MILEAGE_PRESENT_NOT_YET_PROVEN_CUMULATIVE"
    return row


async def run():
    now = datetime.utcnow()
    raw_dump = {"account_check": None, "focus": None, "vehicles": []}

    print("\n" + "=" * 74, flush=True)
    print("AUDIT AD-HOC compte Navixy 234783 — OEM Mileage (AVL 389) — READ-ONLY", flush=True)
    print("=" * 74, flush=True)

    # 1) Auth check (sans exposer le secret)
    info = await raw("user/get_info", {})
    ok = isinstance(info, dict) and info.get("success") is True
    who = ((info.get("user") or {}).get("id") if ok else None)
    raw_dump["account_check"] = {"success": ok, "user_id": who}
    print(f"[AUTH] user/get_info success={ok} user_id={who}", flush=True)
    if not ok:
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info}", flush=True)
        print("  -> Verifier AUDIT_NAVIXY_HASH (et AUDIT_NAVIXY_URL si instance dediee). Rien d'autre fait.",
              flush=True)
        return
    if who is not None and str(who) != "234783":
        print(f"  ATTENTION: user_id retourne ({who}) != 234783 attendu. Poursuite en lecture seule.",
              flush=True)

    # 2) Liste trackers du compte
    tl = await raw("tracker/list", {})
    trackers = tl.get("list", []) if isinstance(tl, dict) else []
    print(f"[LIST] {len(trackers)} tracker(s) sur le compte.", flush=True)

    focus = next((t for t in trackers if t.get("id") == FOCUS_TRACKER), None)
    if focus:
        mc = (focus.get("source") or {}).get("model")
        raw_dump["focus"] = {"model": mc, "resolved": resolve_model(mc), "label": focus.get("label")}
        print(f"[FOCUS] tracker {FOCUS_TRACKER}: source.model={mc!r} -> {resolve_model(mc)} "
              f"(label={focus.get('label')!r})", flush=True)
    else:
        print(f"[FOCUS] tracker {FOCUS_TRACKER} INTROUVABLE sur ce compte.", flush=True)

    # 3) cibles FMC003/FMC130 (focus toujours inclus s'il existe)
    targets = [t for t in trackers
               if resolve_model((t.get("source") or {}).get("model")) in TARGET_MODELS]
    if focus and focus not in targets:
        targets.append(focus)
    print(f"[SCAN] {len(targets)} FMC003/FMC130 (focus inclus).", flush=True)

    rows = []
    for t in targets:
        rows.append(await read_vehicle(t.get("id"), t.get("label"),
                                       (t.get("source") or {}).get("model"), now))

    with_avl = [r for r in rows if r.get("avl389") and r["avl389"].get("value") not in (None, "")]
    print(f"\n{len(with_avl)} vehicule(s) avec avl_io_389 en lecture 1. "
          f"2e lecture dans {SLEEP_S}s...", flush=True)
    avl2_map = {}
    if with_avl:
        await asyncio.sleep(SLEEP_S)
        now2 = datetime.utcnow()
        for r in with_avl:
            rd2 = await raw("tracker/readings/list", {"tracker_id": r["tid"]})
            a2, _ = _extract_avl389(rd2) if isinstance(rd2, dict) else (None, [])
            avl2_map[r["tid"]] = a2
    else:
        now2 = now

    for r in rows:
        _status(r, avl2_map.get(r["tid"]), now2)
        raw_dump["vehicles"].append(_scrub(copy.deepcopy(r)))
        gps = r.get("gps_odo")
        gps_s = (f"{gps['value']} @ {gps['timestamp']}" if gps else "n/a")
        print("\n  " + "-" * 66, flush=True)
        print(f"    TRACKER_ID          = {r['tid']}", flush=True)
        print(f"    VEHICLE             = {r.get('label')}", flush=True)
        print(f"    MODEL_REAL / MODEL  = {r.get('model_code')} / {r.get('model')}", flush=True)
        print(f"    AVL389_PRESENT      = {r.get('AVL389_PRESENT')}", flush=True)
        if r.get("AVL389_PRESENT") == "YES":
            print(f"    VALUE               = {r.get('VALUE')} {r.get('UNIT')}", flush=True)
            print(f"    TIMESTAMP / AGE     = {r.get('TIMESTAMP')} / {r.get('AGE_DAYS')} j", flush=True)
            print(f"    VALUE_2ND/INCREASED = {r.get('VALUE_2ND')} / {r.get('INCREASED')}", flush=True)
            print(f"    LIVE / CUMULATIVE   = {r.get('LIVE')} / {r.get('CUMULATIVE')}", flush=True)
        if r.get("others"):
            print(f"    autres odo/avl_io   = {sorted({o['field'] for o in r['others'] if o.get('field')})}",
                  flush=True)
        print(f"    NAVIXY_GPS_ODOMETER = {gps_s}  (EXCLU)", flush=True)
        print(f"    STATUS              = {r.get('STATUS')}", flush=True)

    print("\n" + "=" * 74, flush=True)
    print("RECAP", flush=True)
    print("=" * 74, flush=True)
    by = {}
    for r in rows:
        by.setdefault(r.get("STATUS"), []).append(r["tid"])
    for st, ids in sorted(by.items(), key=lambda x: str(x[0])):
        print(f"  {st:<48} : {len(ids)}  {ids}", flush=True)
    print("\n  AVL389 = source vehicule/OBD (independante GNSS). Aucune ecriture, aucun D3.", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"  RAW masque -> {RAW_OUT}", flush=True)
    except Exception as e:
        print(f"  (ecriture RAW impossible: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
