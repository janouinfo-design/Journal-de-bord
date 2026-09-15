"""RE-AUDIT OEM MILEAGE (AVL 389) — READ-ONLY STRICT (multi-tenant, FMC003 + FMC130).

============================  INTERDICTIONS DURES  ============================
READ-ONLY. Aucune écriture, aucune commande device, aucun D3.
N'importe/n'appelle aucune fonction d'écriture (pas de send_raw_command, setparam,
privatemode, counter set, sensor update, config write).

CONTEXTE : la capture montre `avl_io_389` = 165000 sur le tracker 3467714.
Teltonika documente AVL ID 389 = "OBD OEM Total Mileage" (km), lu via PID OEM
spécifique au véhicule → SOURCE VÉHICULE (OBD), INDÉPENDANTE DU GNSS.
AVL 389 (>255) nécessite Codec 8 Extended (param 113=1) pour être transmis.

TERMINOLOGIE (stricte) :
  - AVL 389 / OBD OEM Total Mileage      = source VÉHICULE (OBD), indépendante du GNSS
  - Teltonika Total Odometer (11806=0)   = source GNSS INTERNE du traceur (PAS "non-GPS")
  - Navixy odometer counter              = GPS calculé PLATEFORME -> TOUJOURS EXCLU (distance privée)

OBJECTIFS :
  0. Lire le source.model RÉEL de 3467714 via Navixy (ne pas se fier au nom de fichier).
  1. Pour CHAQUE FMC003/FMC130 (tous tenants), chercher explicitement `avl_io_389`
     (+ autres avl_io_* odométriques) dans readings/list.
  2. Faire 2 LECTURES espacées (SLEEP_S) pour amorcer la preuve de cumulativité.
  3. Relever : valeur, timestamp, âge, évolution entre 2 lectures, unité, modèle réel.
  4. Vérifier si le verdict précédent "0/14 FMC003" était incomplet (car il ne cherchait
     pas les avl_io_*).

STATUT PAR VÉHICULE (aucun "validé" sans preuve) :
  OEM_MILEAGE_LIVE                              (avl_389 présent + récent + a augmenté entre 2 lectures)
  OEM_MILEAGE_STALE                             (présent mais timestamp ancien > RECENT_DAYS)
  OEM_MILEAGE_PRESENT_NOT_YET_PROVEN_CUMULATIVE (présent/récent mais pas d'augmentation observée ici)
  NO_OEM_MILEAGE                                (avl_389 absent)

Usage :
  docker exec -e PYTHONPATH=/app -w /app journal_backend python3 /tmp/d2_oem_mileage_reaudit.py
RAW -> /tmp/d2_oem_mileage_reaudit_raw.json
"""
import asyncio
import json
import copy
from datetime import datetime, timedelta

import httpx

import app.tenant_context as tc
from app.tenant_context import set_current_tenant, reset_current_tenant, refresh_tenant_cache
from app.db import init_db
from app import navixy_client as nc

TARGET_MODELS = ("FMC003", "FMC130")
FOCUS_TRACKER = 3467714          # tracker dont il faut lire le source.model reel
RAW_OUT = "/tmp/d2_oem_mileage_reaudit_raw.json"
RECENT_DAYS = 30
SLEEP_S = 90                     # attente entre les 2 lectures (preuve d'incrementation amorcee)

# AVL odometriques recherches (noms Navixy generiques). 389 = OBD OEM Total Mileage (km).
AVL_ODO_NAMES = ["avl_io_389"]   # cible principale
# heuristique complementaire : tout input contenant 'mileage'/'odometer'/'distance' OU avl_io_*
GENERIC_ODO_HINTS = ["mileage", "odometer", "odo", "total_distance", "vehicle_distance"]

# resolve_model() INLINE (le conteneur VPS peut ne pas embarquer app.odometer_capability).
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


def _age_days(ts, now):
    dt = _parse_ts(ts)
    return None if not dt else round((now - dt).total_seconds() / 86400.0, 2)


def _iter_inputs(readings):
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            if isinstance(it, dict):
                yield grp, it


def _extract_oem_and_odo(readings):
    """Retourne (avl389_item, autres_candidats_odo)."""
    avl389 = None
    others = []
    for grp, it in _iter_inputs(readings):
        name = str(it.get("input_name") or it.get("name") or it.get("label") or it.get("field") or "").lower()
        rec = {
            "group": grp, "field": name or None, "value": it.get("value"),
            "units": it.get("units_type") or it.get("units") or it.get("unit"),
            "timestamp": it.get("update_time") or it.get("time"), "sensor_id": it.get("sensor_id"),
        }
        if name in AVL_ODO_NAMES or name == "avl_io_389":
            avl389 = rec
        elif name.startswith("avl_io_") or any(h in name for h in GENERIC_ODO_HINTS):
            others.append(rec)
    return avl389, others


def _navixy_gps_odometer(counters):
    for coll in ("list", "counters"):
        for it in (counters.get(coll) or []):
            if isinstance(it, dict) and str(it.get("type")) == "odometer":
                return {"value": it.get("value"), "timestamp": it.get("update_time")}
    return None


async def audit_vehicle(entry, now):
    tid = entry.get("id")
    label = entry.get("label")
    model_code = (entry.get("source") or {}).get("model")
    model = resolve_model(model_code)

    r1 = await raw("tracker/readings/list", {"tracker_id": tid})
    counters = await raw("tracker/get_counters", {"tracker_id": tid})
    avl1, others = _extract_oem_and_odo(r1)
    gps_odo = _navixy_gps_odometer(counters)

    return {
        "TRACKER_ID": tid, "VEHICLE": label, "MODEL_REAL": model_code, "MODEL": model,
        "avl389_first": avl1,
        "other_odo_candidates": others,
        "navixy_gps_odometer": gps_odo,  # EXCLU comme source privee
    }


def _finalize(row, avl2, now):
    """Combine lecture 1 (row['avl389_first']) et lecture 2 (avl2) -> statut."""
    a1 = row.get("avl389_first")
    present = bool(a1 and a1.get("value") not in (None, ""))
    row["AVL389_PRESENT"] = "YES" if present else "NO"
    if not present:
        row["STATUS"] = "NO_OEM_MILEAGE"
        row["VALUE"] = None
        row["UNIT"] = "n/a"
        row["LIVE"] = "N/A"
        row["CUMULATIVE"] = "N/A"
        return row

    v1 = a1.get("value")
    ts1 = a1.get("timestamp")
    age = _age_days(ts1, now)
    recent = (age is not None and age <= RECENT_DAYS)
    row["VALUE"] = v1
    row["UNIT"] = a1.get("units") or "km (AVL389 doc)"
    row["TIMESTAMP"] = ts1
    row["AGE_DAYS"] = age

    # comparaison 2e lecture
    v2 = avl2.get("value") if avl2 else None
    ts2 = avl2.get("timestamp") if avl2 else None
    row["VALUE_2ND"] = v2
    row["TIMESTAMP_2ND"] = ts2
    increased = None
    try:
        if v1 is not None and v2 is not None:
            increased = float(v2) > float(v1)
    except Exception:
        increased = None
    row["INCREASED_BETWEEN_READS"] = ("YES" if increased else
                                      "NO" if increased is False else "UNKNOWN")

    row["LIVE"] = "YES" if recent else ("TO_VERIFY" if age is None else "NO")
    row["CUMULATIVE"] = ("YES" if increased else
                         "TO_VERIFY" if increased is None else "NOT_OBSERVED")

    if not recent and age is not None:
        row["STATUS"] = "OEM_MILEAGE_STALE"
    elif increased:
        row["STATUS"] = "OEM_MILEAGE_LIVE"
    else:
        row["STATUS"] = "OEM_MILEAGE_PRESENT_NOT_YET_PROVEN_CUMULATIVE"
    return row


async def run():
    db = init_db()
    await refresh_tenant_cache(db)
    tenants = dict(getattr(tc, "_tenant_cache", {}) or {})
    if not tenants:
        rows = await db.tenants.find({}, {"_id": 0}).to_list(1000)
        tenants = {t["id"]: t for t in rows}
    now = datetime.utcnow()

    raw_dump = {"focus_tracker_model": None, "tenants": [], "vehicles": []}
    all_rows = []
    focus_seen = False

    print("\n" + "=" * 78, flush=True)
    print("RE-AUDIT OEM MILEAGE (AVL 389) — READ-ONLY (FMC003 + FMC130, multi-tenant)", flush=True)
    print("=" * 78, flush=True)

    for tid_tenant, tdoc in tenants.items():
        if not tdoc.get("navixy_hash"):
            continue
        tname = tdoc.get("name", tid_tenant)
        tok = set_current_tenant(tid_tenant)
        try:
            try:
                trackers = await nc.list_trackers()
            except Exception as e:
                print(f"\n[TENANT {tname}] list_trackers ERREUR {type(e).__name__} — ignore.", flush=True)
                continue

            # 0) modele reel du tracker focus s'il est dans ce tenant
            for t in trackers:
                if t.get("id") == FOCUS_TRACKER:
                    mc = (t.get("source") or {}).get("model")
                    raw_dump["focus_tracker_model"] = {"tenant": tname, "model": mc,
                                                       "resolved": resolve_model(mc),
                                                       "label": t.get("label")}
                    focus_seen = True
                    print(f"\n[FOCUS] tracker {FOCUS_TRACKER} @ {tname} : source.model={mc!r} "
                          f"-> {resolve_model(mc)} (label={t.get('label')!r})", flush=True)

            targets = [t for t in trackers
                       if resolve_model((t.get("source") or {}).get("model")) in TARGET_MODELS]
            print(f"[TENANT {tname}] {len(trackers)} tracker(s), {len(targets)} FMC003/FMC130.", flush=True)
            raw_dump["tenants"].append({"tenant": tname, "targets": len(targets)})

            # LECTURE 1
            for entry in targets:
                row = await audit_vehicle(entry, now)
                all_rows.append(row)
        finally:
            reset_current_tenant(tok)

    if not focus_seen:
        print(f"\n[FOCUS] tracker {FOCUS_TRACKER} INTROUVABLE dans les tenants scannes.", flush=True)

    # LECTURE 2 (apres attente) — uniquement pour ceux qui ont avl389 present (economie d'appels)
    with_avl = [r for r in all_rows if (r.get("avl389_first") and
                                        r["avl389_first"].get("value") not in (None, ""))]
    print(f"\n{len(with_avl)} vehicule(s) avec avl_io_389 present en lecture 1. "
          f"2e lecture dans {SLEEP_S}s pour amorcer la preuve d'incrementation...", flush=True)
    if with_avl:
        await asyncio.sleep(SLEEP_S)
        now2 = datetime.utcnow()
        # regrouper par tenant pour re-poser le contexte
        by_tenant = {}
        for tid_tenant, tdoc in tenants.items():
            if not tdoc.get("navixy_hash"):
                continue
            by_tenant[tdoc.get("name", tid_tenant)] = tid_tenant
        for r in with_avl:
            # retrouver le tenant du vehicule : re-scan simple par tid
            done = False
            for tname, tid_tenant in by_tenant.items():
                tok = set_current_tenant(tid_tenant)
                try:
                    rd2 = await raw("tracker/readings/list", {"tracker_id": r["TRACKER_ID"]})
                    if isinstance(rd2, dict) and rd2.get("success"):
                        a2, _ = _extract_oem_and_odo(rd2)
                        if a2:
                            _finalize(r, a2, now2)
                            done = True
                            break
                finally:
                    reset_current_tenant(tok)
            if not done:
                _finalize(r, None, now2)

    # finaliser ceux sans avl389
    for r in all_rows:
        if "STATUS" not in r:
            _finalize(r, None, now)

    # ---- AFFICHAGE ----
    for r in all_rows:
        raw_dump["vehicles"].append(_scrub(copy.deepcopy(r)))
        gps = r.get("navixy_gps_odometer")
        gps_s = (f"{gps['value']} @ {gps['timestamp']}" if gps else "n/a")
        print("\n  " + "-" * 70, flush=True)
        print(f"    TRACKER_ID              = {r['TRACKER_ID']}", flush=True)
        print(f"    VEHICLE                 = {r.get('VEHICLE')}", flush=True)
        print(f"    MODEL_REAL / MODEL      = {r.get('MODEL_REAL')} / {r.get('MODEL')}", flush=True)
        print(f"    AVL389_PRESENT          = {r.get('AVL389_PRESENT')}", flush=True)
        if r.get("AVL389_PRESENT") == "YES":
            print(f"    VALUE                   = {r.get('VALUE')} {r.get('UNIT')}", flush=True)
            print(f"    TIMESTAMP / AGE_DAYS    = {r.get('TIMESTAMP')} / {r.get('AGE_DAYS')}", flush=True)
            print(f"    VALUE_2ND / INCREASED   = {r.get('VALUE_2ND')} / {r.get('INCREASED_BETWEEN_READS')}", flush=True)
            print(f"    LIVE / CUMULATIVE       = {r.get('LIVE')} / {r.get('CUMULATIVE')}", flush=True)
        if r.get("other_odo_candidates"):
            names = sorted({c["field"] for c in r["other_odo_candidates"] if c.get("field")})
            print(f"    autres avl_io_/odo      = {names}", flush=True)
        print(f"    NAVIXY_GPS_ODOMETER     = {gps_s}  (EXCLU)", flush=True)
        print(f"    STATUS                  = {r.get('STATUS')}", flush=True)

    # ---- RECAP ----
    print("\n" + "=" * 78, flush=True)
    print(f"RECAP — {len(all_rows)} FMC003/FMC130 audite(s)", flush=True)
    print("=" * 78, flush=True)
    by_status = {}
    for r in all_rows:
        by_status.setdefault(r.get("STATUS"), []).append(r["TRACKER_ID"])
    for st, ids in sorted(by_status.items(), key=lambda x: str(x[0])):
        print(f"  {st:<48} : {len(ids)}  {ids}", flush=True)

    n_oem = sum(1 for r in all_rows if r.get("AVL389_PRESENT") == "YES")
    print(f"\n  avl_io_389 PRESENT sur {n_oem} vehicule(s).", flush=True)
    print("  -> Si n_oem > 0 : le verdict precedent '0/14 FMC003' etait INCOMPLET (ne cherchait", flush=True)
    print("     pas les avl_io_*). AVL389 = source VEHICULE/OBD (independante du GNSS).", flush=True)
    print("  RAPPEL terminologie : AVL389=vehicule/OBD ; Teltonika Total Odo(11806=0)=GNSS interne ;", flush=True)
    print("  Navixy odometer counter = GPS plateforme (EXCLU). READ-ONLY, aucun D3.", flush=True)

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  RAW JSON masque -> {RAW_OUT}", flush=True)
    except Exception as e:
        print(f"  (impossible d'ecrire {RAW_OUT}: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
