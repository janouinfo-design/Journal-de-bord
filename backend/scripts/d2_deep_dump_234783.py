"""DEEP-DUMP READ-ONLY — localiser avl_io_389 (OEM mileage) sur compte 234783.

Cible 3 trackers du compte 234783 :
  3467714 Manchester (avl_io_389=165000 vu dans l'UI mais absent de readings/list),
  3467693 Dakar, 3467717 Gilan (ont 'obd_custom_odometer').

But : trouver DANS QUEL CANAL Navixy expose avl_io_389 / l'odometre OEM
(get_state.state.additional, inputs bruts, sensor/list, etc.) + fraicheur.

READ-ONLY strict. Credential via env AUDIT_NAVIXY_HASH (jamais dans le fichier).
Aucune ecriture, aucun D3.

USAGE :
  docker exec -e AUDIT_NAVIXY_HASH="<NOUVELLE_CLE_234783>" \
    journal_backend python3 /tmp/d2_deep_dump_234783.py
RAW -> /tmp/d2_deep_dump_234783_raw.json
"""
import asyncio
import json
import os
import copy
from datetime import datetime

import httpx

TRACKERS = [3467714, 3467693, 3467717]
RAW_OUT = "/tmp/d2_deep_dump_234783_raw.json"
NEEDLES = ["389", "165000", "odometer", "mileage", "odo", "distance"]

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
        raise SystemExit("ABORT: AUDIT_NAVIXY_HASH absent (fournir la cle du compte 234783 via -e).")
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


def _walk(obj, path=""):
    """Genere (chemin, cle, valeur) pour chaque noeud scalaire/dict-cle de la structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            newp = f"{path}.{k}" if path else str(k)
            yield (newp, str(k), v)
            yield from _walk(v, newp)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            newp = f"{path}[{i}]"
            yield from _walk(v, newp)


def _find_hits(blob, label):
    """Cherche les NEEDLES dans les cles ET valeurs de la structure."""
    hits = []
    for pth, key, val in _walk(blob):
        ks = str(key).lower()
        vs = str(val).lower() if not isinstance(val, (dict, list)) else ""
        for n in NEEDLES:
            if n in ks or (vs and n in vs):
                # on ne garde que les feuilles (val scalaire) pour la lisibilite
                if not isinstance(val, (dict, list)):
                    hits.append({"endpoint": label, "path": pth, "key": key, "value": val, "needle": n})
                break
    return hits


async def dump_tracker(tid):
    print("\n" + "=" * 74, flush=True)
    print(f"DEEP-DUMP tracker {tid}", flush=True)
    print("=" * 74, flush=True)

    endpoints = {
        "get_state": await raw("tracker/get_state", {"tracker_id": tid}),
        "readings_list": await raw("tracker/readings/list", {"tracker_id": tid}),
        "get_counters": await raw("tracker/get_counters", {"tracker_id": tid}),
        "sensor_list": await raw("tracker/sensor/list", {"tracker_id": tid}),
    }

    all_hits = []
    for label, blob in endpoints.items():
        if isinstance(blob, dict) and (blob.get("success") is True or "state" in blob or "list" in blob
                                       or "inputs" in blob):
            hits = _find_hits(blob, label)
            all_hits.extend(hits)
            print(f"\n  [{label}] {len(hits)} correspondance(s) odo/mileage/389 :", flush=True)
            for h in hits:
                print(f"    - {h['path']} = {h['value']!r}  (match '{h['needle']}')", flush=True)
        else:
            st = (blob.get("status") or {}) if isinstance(blob, dict) else {}
            print(f"\n  [{label}] indisponible : {st.get('description') or blob}", flush=True)

    if not all_hits:
        print("\n  AUCUNE correspondance 389/odometer/mileage dans les 4 endpoints.", flush=True)

    return {"tracker_id": tid, "endpoints": _scrub(copy.deepcopy(endpoints)), "hits": all_hits}


async def run():
    h = _hash()  # valide la presence de la cle avant tout
    info = await raw("user/get_info", {})
    ok = isinstance(info, dict) and info.get("success") is True
    print(f"[AUTH] success={ok}", flush=True)
    if not ok:
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return

    raw_dump = {"generated_utc": datetime.utcnow().isoformat(), "trackers": []}
    for tid in TRACKERS:
        raw_dump["trackers"].append(await dump_tracker(tid))

    try:
        with open(RAW_OUT, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  RAW complet masque -> {RAW_OUT}", flush=True)
        print("  (Ouvrir ce fichier pour voir la structure exacte autour de avl_io_389.)", flush=True)
    except Exception as e:
        print(f"  (ecriture RAW impossible: {type(e).__name__})", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
