"""D3-B SNAPSHOT CAPTURE (READ-ONLY) — pilote 3657864 FMC003.

PRÉPARATION GATED : ce script NE FAIT QUE LIRE. Il n'envoie AUCUNE commande
(pas de privatemode, pas de setparam, pas de raw_command). Il ne bascule RIEN.
La bascule Business<->Private est une action MANUELLE/opérateur décidée hors de ce script,
sur GO explicite. Ce script sert uniquement à CAPTURER des snapshots horodatés à chaque
phase, et à calculer la distance privée = AVL16_END - AVL16_START à la fin.

PHASES (argument) :
  before | private_start | private_driving | private_end | business_restored | summary

Chaque appel ajoute un snapshot au fichier cumulatif /tmp/d3b_3657864_snapshots.json.
`summary` calcule PRIVATE_DISTANCE = km(private_end) - km(private_start) et affiche le bilan.

Credential via env AUDIT_NAVIXY_HASH (compte 121349). Tracker via env TID (défaut 3657864).

USAGE (exemples, READ-ONLY) :
  docker exec -e AUDIT_NAVIXY_HASH="$KEY3" -e TID=3657864 journal_backend \
    python3 /tmp/d3b_snapshot.py before
  ... (bascule Privé MANUELLE, sur GO) ...
  docker exec -e AUDIT_NAVIXY_HASH="$KEY3" journal_backend python3 /tmp/d3b_snapshot.py private_start
  docker exec -e AUDIT_NAVIXY_HASH="$KEY3" journal_backend python3 /tmp/d3b_snapshot.py private_driving
  docker exec -e AUDIT_NAVIXY_HASH="$KEY3" journal_backend python3 /tmp/d3b_snapshot.py private_end
  ... (retour Professionnel MANUEL) ...
  docker exec -e AUDIT_NAVIXY_HASH="$KEY3" journal_backend python3 /tmp/d3b_snapshot.py business_restored
  docker exec -e AUDIT_NAVIXY_HASH="$KEY3" journal_backend python3 /tmp/d3b_snapshot.py summary
"""
import asyncio
import json
import os
import sys
from datetime import datetime

import httpx

TID = int(os.environ.get("TID", "3657864"))
STORE = "/tmp/d3b_3657864_snapshots.json"
PHASES = ("before", "private_start", "private_driving", "private_end",
          "business_restored", "summary")
AVL16_INPUTS = {"avl_io_16", "hw_mileage"}
ODO_SENSOR_NAME_HINTS = ("odo total", "odometer", "odometre", "odo")


def _base_url():
    return os.environ.get("AUDIT_NAVIXY_URL", "https://api.navixy.com/v2").rstrip("/")


def _hash():
    h = os.environ.get("AUDIT_NAVIXY_HASH", "").strip()
    if not h:
        raise SystemExit("ABORT: AUDIT_NAVIXY_HASH absent (cle du compte via -e).")
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


def _find_avl16(readings):
    for grp in ("inputs", "virtual_sensors", "sensors", "counters", "states"):
        for it in (readings.get(grp) or []):
            nm = str(it.get("input_name") or it.get("name") or it.get("field") or "").lower()
            if nm in AVL16_INPUTS:
                return {"value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time") or it.get("time")}
    # fallback par nom de sensor odométrique
    for grp in ("inputs", "virtual_sensors", "sensors"):
        for it in (readings.get(grp) or []):
            label = str(it.get("label") or it.get("name") or "").lower()
            if any(h in label for h in ODO_SENSOR_NAME_HINTS):
                return {"value": it.get("value"),
                        "units": it.get("units_type") or it.get("units"),
                        "timestamp": it.get("update_time") or it.get("time")}
    return None


def _gps_masked_from_point(lat, lng):
    """Retourne True si la position (lat,lng) est réellement à 0,0 (masquée),
    False si coordonnées réelles, None si indéterminable."""
    if lat is None or lng is None:
        return None
    try:
        return abs(float(lat)) < 1e-6 and abs(float(lng)) < 1e-6
    except (TypeError, ValueError):
        return None


async def _last_gps_point():
    """Position TRANSMISE = state.gps.location.{lat,lng}. Retourne (lat,lng,ts)."""
    st = ((await raw("tracker/get_state", {"tracker_id": TID})) or {}).get("state") or {}
    gps = st.get("gps") or {}
    loc = gps.get("location") or {}
    if isinstance(loc, dict) and (loc.get("lat") is not None or loc.get("lng") is not None):
        return loc.get("lat"), loc.get("lng"), gps.get("updated")
    return None, None, gps.get("updated")


def _parse(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(ts)[:19], fmt)
        except Exception:
            continue
    return None


def _masking_verdict(lat, lng, gps_ts, avl_ts, moving, ignition):
    """Masquage détecté si :
      - position à 0,0 (Data Sent As Zero), OU
      - position GELÉE : gps figé alors que l'activité continue (AVL16 bien plus récent que le GPS,
        véhicule moving/ignition) -> le device ne transmet plus de nouvelles positions = masqué.
    Retourne ('MASKED'|'NOT_MASKED'|'INCONCLUSIVE', raison)."""
    # cas 0,0
    try:
        if lat is not None and lng is not None and abs(float(lat)) < 1e-6 and abs(float(lng)) < 1e-6:
            return "MASKED", "coords 0,0 (Data Sent As Zero)"
    except (TypeError, ValueError):
        pass
    g = _parse(gps_ts)
    a = _parse(avl_ts)
    # position gelée : AVL16 nettement plus récent que la position GPS, alors qu'on roule
    if g and a:
        gap = (a - g).total_seconds()
        if gap >= 120 and (moving or ignition):
            return "MASKED", (f"position GELEE: GPS figé depuis {int(gap)}s alors que AVL16 est frais "
                              f"et vehicule actif -> plus de position transmise = masqué")
    if lat is not None and lng is not None:
        # coords réelles ET récentes (gap faible) -> non masqué
        if g and a and (a - g).total_seconds() < 120:
            return "NOT_MASKED", "coords réelles récentes"
        return "NOT_MASKED", "coords réelles (fraîcheur indéterminée)"
    return "INCONCLUSIVE", "position indéterminable"


async def capture(phase):
    now = datetime.utcnow().isoformat()
    state = await raw("tracker/get_state", {"tracker_id": TID})
    readings = await raw("tracker/readings/list", {"tracker_id": TID})
    counters = await raw("tracker/get_counters", {"tracker_id": TID})

    st = (state or {}).get("state") or {}
    gps = st.get("gps") or {}
    avl16 = _find_avl16(readings)
    gps_odo = None
    for it in (counters.get("list") or []):
        if str(it.get("type")) == "odometer":
            gps_odo = it.get("value")

    lat, lng, pt_ts = await _last_gps_point()
    moving = st.get("movement_status") == "moving"
    ignition = bool(st.get("ignition"))
    avl_ts = avl16.get("timestamp") if avl16 else None
    verdict, reason = _masking_verdict(lat, lng, pt_ts, avl_ts, moving, ignition)

    snap = {
        "phase": phase,
        "captured_utc": now,
        "tracker_online": st.get("connection_status") in ("active", "idle"),
        "connection_status": st.get("connection_status"),
        "masking_verdict": verdict,              # MASKED | NOT_MASKED | INCONCLUSIVE
        "masking_reason": reason,
        "gps_has_position": (lat is not None and lng is not None),
        "gps_point_ts": pt_ts,
        "gps_signal_level": gps.get("signal_level"),
        "gps_speed": gps.get("speed"),
        "avl16_km": avl16.get("value") if avl16 else None,
        "avl16_timestamp": avl_ts,
        "navixy_platform_odometer": gps_odo,
        "ignition": ignition,
        "moving": moving,
    }
    return snap


def _load():
    if os.path.exists(STORE):
        try:
            return json.load(open(STORE))
        except Exception:
            return {"snapshots": []}
    return {"snapshots": []}


def _save(data):
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _print_snap(s):
    print(f"  phase              = {s['phase']}", flush=True)
    print(f"  captured_utc       = {s['captured_utc']}", flush=True)
    print(f"  tracker_online     = {s['tracker_online']} ({s['connection_status']})", flush=True)
    print(f"  MASKING_VERDICT    = {s.get('masking_verdict')}", flush=True)
    print(f"    -> {s.get('masking_reason')}", flush=True)
    print(f"  gps position ts    = {s.get('gps_point_ts')}   signal/speed={s.get('gps_signal_level')}/{s.get('gps_speed')}", flush=True)
    print(f"  AVL16_KM           = {s['avl16_km']}   @ {s['avl16_timestamp']}", flush=True)
    print(f"  ignition / moving  = {s['ignition']} / {s['moving']}", flush=True)
    print(f"  navixy_gps_odo(REF)= {s['navixy_platform_odometer']} (EXCLU du calcul prive)", flush=True)


async def run(phase):
    _ = _hash()
    info = await raw("user/get_info", {})
    if not (isinstance(info, dict) and info.get("success")):
        st = (info.get("status") or {}) if isinstance(info, dict) else {}
        print(f"[AUTH] echec: {st.get('description') or info} — rien fait.", flush=True)
        return
    data = _load()

    if phase == "summary":
        snaps = {s["phase"]: s for s in data.get("snapshots", [])}
        ps = snaps.get("private_start")
        pe = snaps.get("private_end")
        print("\n" + "=" * 60, flush=True)
        print("D3-B SUMMARY (READ-ONLY) — tracker %d" % TID, flush=True)
        print("=" * 60, flush=True)
        for ph in ("before", "private_start", "private_driving", "private_end", "business_restored"):
            s = snaps.get(ph)
            print(f"[{ph}] " + ("absent" if not s else
                  f"online={s['tracker_online']} MASKING={s.get('masking_verdict')} "
                  f"AVL16={s['avl16_km']}"), flush=True)
        dist = None
        if ps and pe and _isnum(ps.get("avl16_km")) and _isnum(pe.get("avl16_km")):
            dist = round(float(pe["avl16_km"]) - float(ps["avl16_km"]), 3)
        print("\n  PRIVATE_DISTANCE_KM (AVL16_end - AVL16_start) =",
              dist if dist is not None else "N/A (relevés manquants)", flush=True)
        if dist is not None:
            print("  INCREMENT =", "OK (Y>X)" if dist > 0 else
                  ("INCONCLUSIVE (delta nul — rouler plus)" if dist == 0 else "ANOMALIE (Y<X)"),
                  flush=True)
        pm = [snaps.get(p, {}).get("masking_verdict") for p in ("private_start", "private_end")]
        br = snaps.get("business_restored", {}).get("masking_verdict")
        print("  MASKING pendant prive (start/end) =", pm, "-> PASS si MASKED", flush=True)
        print("  MASKING au retour Business        =", br, "-> attendu NOT_MASKED (GPS revenu)", flush=True)
        print("\n  NOTE: verdict PASS/FAIL selon protocole D3-B (§G) — jugé par l'operateur/agent.", flush=True)
        print("  Aucune bascule/ecriture faite par ce script.", flush=True)
        return

    snap = await capture(phase)
    data.setdefault("snapshots", []).append(snap)
    _save(data)
    print(f"\n===== SNAPSHOT [{phase}] (READ-ONLY) =====", flush=True)
    _print_snap(snap)
    print(f"  -> ajoute a {STORE}", flush=True)
    print("  (Aucune commande envoyee. Aucune bascule. Aucun privatemode.)", flush=True)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "before"
    if phase not in PHASES:
        print(f"usage: d3b_snapshot.py [{' | '.join(PHASES)}]")
        return
    asyncio.run(run(phase))


if __name__ == "__main__":
    main()
