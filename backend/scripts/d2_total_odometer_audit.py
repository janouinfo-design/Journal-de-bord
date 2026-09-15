"""D2 — FMC130 TOTAL ODOMETER AUDIT (tracker 781479 UNIQUEMENT).

============================  READ-ONLY STRICT  ============================
Ce script NE FAIT QUE DES LECTURES. Il n'importe NI n'appelle aucune fonction
d'écriture (pas de send_raw_command, pas de counter/value/set, pas de setparam,
pas de privatemode). Aucune modification Navixy / Teltonika / Mongo / config.

Objectif D2 : déterminer si le FMC130 pilote expose à Navixy un compteur
cumulatif indépendant de l'odomètre GPS-calculé (Total Odometer interne
Teltonika / hardware odometer), qui pourra continuer à évoluer quand la
position GPS transmise sera masquée en mode privé (à prouver en D3).

Endpoints Navixy READ-ONLY interrogés :
  1. tracker/get_state        -> état courant + inputs/GPS bruts
  2. tracker/readings/list    -> inputs / sensors / counters réellement reçus
  3. tracker/get_counters     -> compteurs calculés par Navixy (référence)
  + track/list (24-72h)       -> détection de roulage récent (READ-ONLY)

Verrous durs : ne s'exécute QUE sur TENANT/TID ci-dessous ; refuse tout autre
device ou tout modèle != FMC130.

Sécurité d'affichage : masque hash/tokens, IMEI, SIM/ICCID/IMSI, credentials,
et coordonnées GPS exactes. Ne masque AUCUN nom de champ AVL/input/sensor ni
leurs valeurs numériques utiles à l'identification de l'odomètre.

Usage (lecture seule, sûr) :
  docker exec -e PYTHONPATH=/app -w /app journal_backend python3 /tmp/d2_total_odometer_audit.py

Le RAW JSON masqué est aussi sauvegardé dans /tmp/d2_audit_781479_raw.json.
"""
import asyncio
import json
import re
import copy
from datetime import datetime, timedelta

import httpx

from app.tenant_context import set_current_tenant, reset_current_tenant, refresh_tenant_cache
from app.db import init_db
from app import navixy_client as nc

# ---- VERROUS DURS (ne jamais élargir sans nouvelle décision) ----
TENANT = "default"
TID = 781479
EXPECTED_MODEL_TOKEN = "fmc130"          # doit apparaître dans source.model
RAW_OUT = "/tmp/d2_audit_781479_raw.json"

# ---- Candidats "odomètre" recherchés (noms possibles, non exhaustif) ----
ODO_NAME_HINTS = [
    "total_odometer", "total_odo", "totalodometer",
    "hw_mileage", "hardware_mileage", "hw_odometer", "hardware_odometer",
    "vehicle_mileage", "device_mileage", "internal_odometer",
    "can_mileage", "obd_mileage", "can_vehicle_mileage",
    "mileage", "odometer", "odo",
]

# ---- Clés à masquer (secrets / PII) ----
SECRET_KEY_HINTS = [
    "hash", "token", "api_key", "apikey", "password", "secret", "credential",
    "imei", "sim", "iccid", "imsi", "phone", "msisdn", "device_id",
]
GPS_KEY_HINTS = ["lat", "lng", "lon", "latitude", "longitude", "location", "address"]


def _mask_value(key: str, value):
    """Masque une valeur si la clé est sensible. Conserve les noms de champs."""
    kl = str(key).lower()
    if any(h in kl for h in SECRET_KEY_HINTS):
        if value in (None, "", 0):
            return value
        s = str(value)
        return f"***MASKED({len(s)} chars)***"
    if any(kl == h or kl.endswith("_" + h) or kl == h for h in GPS_KEY_HINTS) or kl in GPS_KEY_HINTS:
        # coordonnées GPS exactes non nécessaires pour cette mission
        if value in (None, "", 0):
            return value
        return "***GPS_MASKED***"
    return value


def _scrub(obj):
    """Nettoyage récursif : masque secrets/PII/GPS partout dans la structure."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(h in kl for h in SECRET_KEY_HINTS):
                out[k] = _mask_value(k, v)
            elif kl in GPS_KEY_HINTS or any(kl.endswith("_" + h) for h in GPS_KEY_HINTS):
                out[k] = _mask_value(k, v)
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


async def raw(path, payload):
    """POST READ-ONLY vers Navixy (réutilise base_url + credential du client)."""
    base = nc._base_url()
    h = nc._hash()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{base}/{path}", json={"hash": h, **payload})
        try:
            return r.json()
        except Exception:
            return {"http": r.status_code, "text": r.text[:200]}


async def _guard(trk):
    """Verrou dur : device présent + modèle FMC130, sinon abort."""
    me = next((x for x in trk if x.get("id") == TID), None)
    if not me:
        raise SystemExit(f"ABORT: tracker {TID} introuvable dans tracker/list. Aucune action.")
    model = (me or {}).get("source", {}).get("model", "")
    label = (me or {}).get("label", "")
    if EXPECTED_MODEL_TOKEN not in str(model).lower():
        raise SystemExit(f"ABORT: device {TID} model={model!r} != FMC130 attendu. Aucune action.")
    print(f"[GUARD] tracker={TID} label={label!r} model={model!r} -> OK (FMC130)", flush=True)
    return me


def _iter_readings(rd):
    """Itère (groupe, item) sur tous les groupes de readings/list."""
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (rd.get(grp) or []):
            if isinstance(it, dict):
                yield grp, it


def _extract_odo_candidates(rd, state, counters):
    """Repère tous les champs susceptibles d'être un odomètre/mileage."""
    found = []

    # 1) readings/list : inputs / sensors / counters
    for grp, it in _iter_readings(rd):
        name = str(it.get("input_name") or it.get("name") or it.get("label") or "").lower()
        if any(hint in name for hint in ODO_NAME_HINTS):
            found.append({
                "source": f"readings/list[{grp}]",
                "field": it.get("input_name") or it.get("name") or it.get("label"),
                "value": it.get("value"),
                "units": it.get("units") or it.get("unit"),
                "timestamp": it.get("update_time") or it.get("time"),
            })

    # 2) get_state : parfois inputs/AVL bruts sous state
    st = (state or {}).get("state") or {}
    for k, v in st.items():
        kl = str(k).lower()
        if any(hint in kl for hint in ODO_NAME_HINTS):
            found.append({
                "source": "get_state.state",
                "field": k,
                "value": v,
                "units": None,
                "timestamp": st.get("actual_track_update") or st.get("gps", {}).get("updated"),
            })
    # inputs bruts éventuels
    for grp_key in ("inputs", "additional", "avl", "raw"):
        blk = st.get(grp_key)
        if isinstance(blk, dict):
            for k, v in blk.items():
                if any(hint in str(k).lower() for hint in ODO_NAME_HINTS):
                    found.append({
                        "source": f"get_state.state.{grp_key}",
                        "field": k, "value": v, "units": None, "timestamp": None,
                    })
        elif isinstance(blk, list):
            for it in blk:
                if isinstance(it, dict):
                    nm = str(it.get("name") or it.get("input_name") or "").lower()
                    if any(hint in nm for hint in ODO_NAME_HINTS):
                        found.append({
                            "source": f"get_state.state.{grp_key}[]",
                            "field": it.get("name") or it.get("input_name"),
                            "value": it.get("value"),
                            "units": it.get("units"),
                            "timestamp": it.get("update_time"),
                        })

    # 3) get_counters : odometer Navixy (référence GPS-calculée le plus souvent)
    for coll_key in ("list", "counters"):
        for it in (counters.get(coll_key) or []):
            if isinstance(it, dict):
                found.append({
                    "source": "get_counters (REF Navixy)",
                    "field": it.get("type") or it.get("name"),
                    "value": it.get("value"),
                    "units": it.get("units") or it.get("unit"),
                    "timestamp": it.get("update_time") or it.get("time"),
                })
    return found


async def run():
    db = init_db()
    await refresh_tenant_cache(db)
    tok = set_current_tenant(TENANT)
    raw_dump = {}
    try:
        # Guard
        trk = await nc.list_trackers()
        me = await _guard(trk)
        raw_dump["tracker_list_entry"] = _scrub(copy.deepcopy(me))

        print("\n" + "=" * 70, flush=True)
        print("D2 FMC130 TOTAL ODOMETER AUDIT — READ-ONLY (tracker %d)" % TID, flush=True)
        print("=" * 70, flush=True)

        # 1) get_state
        state = await raw("tracker/get_state", {"tracker_id": TID})
        raw_dump["get_state"] = _scrub(copy.deepcopy(state))

        # 2) readings/list
        readings = await raw("tracker/readings/list", {"tracker_id": TID})
        raw_dump["readings_list"] = _scrub(copy.deepcopy(readings))

        # 3) get_counters
        counters = await raw("tracker/get_counters", {"tracker_id": TID})
        raw_dump["get_counters"] = _scrub(copy.deepcopy(counters))

        # ---- RESUME FILTRE (niveau 1) ----
        print("\n----- [1] RESUME FILTRE : candidats odometre / mileage -----", flush=True)
        candidates = _extract_odo_candidates(readings, state, counters)
        if not candidates:
            print("  Aucun champ contenant odometer/mileage/odo trouve dans les 3 sources.", flush=True)
        for c in candidates:
            print(f"  - [{c['source']}] {c['field']} = {c['value']} "
                  f"{c['units'] or ''} @ {c['timestamp'] or 'n/a'}", flush=True)

        # Etat courant synthetique (GPS masque)
        st = (state or {}).get("state") or {}
        print("\n----- [1b] Etat courant (GPS masque) -----", flush=True)
        print(f"  movement_status = {st.get('movement_status')}", flush=True)
        print(f"  ignition        = {st.get('ignition')}", flush=True)
        print(f"  last_update     = {st.get('actual_track_update') or st.get('last_update')}", flush=True)
        print(f"  gps.updated     = {(st.get('gps') or {}).get('updated')}", flush=True)
        print(f"  connection      = {st.get('connection_status')}", flush=True)

        # Liste brute des noms d'inputs/sensors disponibles (aide au mapping AVL)
        print("\n----- [1c] Inventaire des noms d'inputs/sensors/counters -----", flush=True)
        names = []
        for grp, it in _iter_readings(readings):
            nm = it.get("input_name") or it.get("name") or it.get("label")
            if nm:
                names.append(f"{grp}:{nm}")
        if names:
            for n in sorted(set(names)):
                print(f"  - {n}", flush=True)
        else:
            print("  (readings/list ne renvoie aucun input/sensor nomme)", flush=True)

        # ---- DETECTION ROULAGE RECENT (24-72h) via track/list ----
        print("\n----- [1d] Roulage recent (24-72h, READ-ONLY track/list) -----", flush=True)
        now = datetime.utcnow()
        recent = "INCONCLUSIVE"
        last_move = None
        total_len = None
        for hours in (24, 72):
            d_from = (now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            d_to = now.strftime("%Y-%m-%d %H:%M:%S")
            tl = await raw("track/list", {"tracker_id": TID, "from": d_from, "to": d_to})
            raw_dump[f"track_list_{hours}h"] = _scrub(copy.deepcopy(tl))
            tracks = tl.get("list") or []
            if tracks:
                recent = "YES"
                # somme des longueurs si dispo
                lens = [t.get("length") for t in tracks if isinstance(t.get("length"), (int, float))]
                total_len = sum(lens) if lens else None
                last = tracks[-1]
                last_move = last.get("end_date") or last.get("start_date")
                print(f"  {hours}h: {len(tracks)} track(s), last_move={last_move}, "
                      f"total_length={total_len} (unite Navixy)", flush=True)
                break
            else:
                print(f"  {hours}h: 0 track (pas de mouvement enregistre sur la periode)", flush=True)
        if recent != "YES":
            recent = "NO"

        # ---- CONCLUSIONS ----
        # Cherche un candidat qui ne soit ni l'odometer Navixy REF ni can_mileage mort.
        hw_candidates = [c for c in candidates
                         if "REF Navixy" not in c["source"]
                         and c["value"] not in (None, "", 0)]
        exposed = "NOT_EXPOSED"
        if any("total" in str(c["field"]).lower() or "hw" in str(c["field"]).lower()
               or "hardware" in str(c["field"]).lower() for c in hw_candidates):
            exposed = "EXPOSED"
        elif hw_candidates:
            exposed = "INCONCLUSIVE"  # champs mileage presents mais pas clairement un total hardware

        print("\n" + "=" * 70, flush=True)
        print("CONCLUSIONS D2 (a valider par l'agent apres reception)", flush=True)
        print("=" * 70, flush=True)
        print(f"  RECENT_DRIVING          = {recent}"
              + (f" (last_move={last_move}, total_length={total_len})" if recent == "YES" else ""),
              flush=True)
        print(f"  FMC130_TOTAL_ODOMETER   = {exposed}  (candidats HW non-REF: {len(hw_candidates)})", flush=True)
        print("  ODOMETER_INCREMENT      = PENDING_REAL_DRIVE  "
              "(increment reel a confirmer avec 2 lectures avant/apres roulage)", flush=True)
        print("  NOTE: aucune commande envoyee, aucune ecriture. D3 NON lance.", flush=True)

        # ---- RAW JSON complet masque ----
        try:
            with open(RAW_OUT, "w", encoding="utf-8") as f:
                json.dump(raw_dump, f, ensure_ascii=False, indent=2, default=str)
            size = len(json.dumps(raw_dump, default=str))
            print(f"\n----- [2] RAW JSON masque sauvegarde -> {RAW_OUT} ({size} chars) -----", flush=True)
            if size <= 12000:
                print(json.dumps(raw_dump, ensure_ascii=False, indent=2, default=str), flush=True)
            else:
                print("  (RAW volumineux : voir le fichier ci-dessus. Extraits pertinents deja affiches.)",
                      flush=True)
                # afficher seulement readings_list + get_counters (les plus utiles)
                for key in ("readings_list", "get_counters"):
                    print(f"\n  --- {key} ---", flush=True)
                    print(json.dumps(raw_dump.get(key, {}), ensure_ascii=False, indent=2, default=str)[:6000],
                          flush=True)
        except Exception as e:
            print(f"  (impossible d'ecrire {RAW_OUT}: {type(e).__name__})", flush=True)

    finally:
        reset_current_tenant(tok)


if __name__ == "__main__":
    asyncio.run(run())
