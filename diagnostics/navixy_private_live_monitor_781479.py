#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — MONITEUR LIVE NAVIXY *READ-ONLY* — Preuve mode PRIVE (FMC130 781479)
================================================================================
Objet : observer EN DIRECT ce qui change reellement quand le tracker 781479
recoit "privatemode ON", afin d'identifier une preuve POSITIVE et POSTERIEURE
au clic (fail-closed). A lancer AVANT le prochain test PRIVATE reel.

Tracker pilote : 781479  (LOGITRAK AUDI)   Tenant : default

STRICTEMENT READ-ONLY :
  - Endpoints LUS : tracker/get_state, tracker/readings/list,
                    history/tracker/list, track/read
  - AUCUN envoi de commande (raw_command/send_command), AUCUN write,
    AUCUN restart, AUCUNE modif .env, AUCUN deploy, AUCUNE modif backend.
  - Le credential (hash / api_key) N'EST JAMAIS affiche ni journalise.

TIMEZONE :
  - Requetes en ISO 8601 UTC (...Z) + iso_datetime=true -> non ambigu.
  - Les timestamps NAIFS renvoyes par Navixy sont traites comme HEURE LOCALE
    Europe/Zurich (offset DST auto via zoneinfo, repli +2h) puis normalises UTC.
  - On n'assume JAMAIS UTC sans offset explicite.

DEROULE DU TEST (l'operateur controle T0) :
  1. Lancer le script (il commence la phase BEFORE, ~1 min).
  2. Quand le script indique "PRET — appuyez sur Entree PUIS cliquez PRIVATE",
     appuyer sur Entree AU MOMENT du clic PRIVATE dans l'app -> marque T0.
  3. Le script continue en AFTER_PRIVATE (~5 min) puis imprime la synthese.
  (Si aucune touche n'est pressee, un T0 minute de repli est utilise.)

Credentials : os.getenv uniquement. Priorite NAVIXY_API_KEY puis NAVIXY_HASH.
Base URL : NAVIXY_API_URL (defaut https://api.navixy.com/v2).
--------------------------------------------------------------------------
EXECUTION (VPS, depuis /opt/apps/journal-logitrak) :

    docker exec -it journal_backend python - < navixy_private_live_monitor_781479.py

  ( -it obligatoire : le script attend l'appui Entree pour marquer T0 )

Le script n'ecrit rien sur disque : sortie stdout uniquement.
Collez toute la sortie dans le chat pour analyse.
--------------------------------------------------------------------------
"""

import os
import sys
import json
import select
import time
from datetime import datetime, timezone, timedelta

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable. Executez ce script DANS le conteneur "
          "journal_backend (httpx + NAVIXY_* presents).")
    sys.exit(2)

# Zone du compte pour normaliser les timestamps NAIFS (repli +2h si zoneinfo absent).
try:
    from zoneinfo import ZoneInfo
    _ACCOUNT_TZ = ZoneInfo("Europe/Zurich")
except Exception:  # pragma: no cover
    _ACCOUNT_TZ = None
_ACCOUNT_TZ_FALLBACK_HOURS = 2


# ============================ CONFIG =====================================
TRACKER_ID = 781479
AVL16_SENSOR_ID = 5577108          # sensor AVL16 attendu (mis en evidence)
BEFORE_SECONDS = 60                # ~1 min avant clic PRIVATE
AFTER_SECONDS = 300                # ~5 min apres clic PRIVATE
SAMPLE_EVERY_S = 3                 # cadence d'echantillonnage (2-5 s)
HTTP_TIMEOUT = 15.0
HISTORY_LOOKBACK_MIN = 10          # fenetre glissante pour history/tracker/list
TRACK_LOOKBACK_MIN = 10            # fenetre glissante pour track/read
GPS_FRESH_MAX_S = 180              # "frais" si gps.updated < 3 min


# ============================ HELPERS ====================================
def _resolve_credential():
    api_key = (os.getenv("NAVIXY_API_KEY") or "").strip()
    if api_key:
        return api_key, "NAVIXY_API_KEY"
    legacy = (os.getenv("NAVIXY_HASH") or "").strip()
    if legacy:
        return legacy, "NAVIXY_HASH"
    return None, None


def _base_url():
    return (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")


def _fmt_iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(v):
    """Timestamp Navixy -> datetime UTC aware. Naif = HEURE LOCALE compte (jamais UTC)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        # naif -> heure locale compte
        if _ACCOUNT_TZ is not None:
            return dt.replace(tzinfo=_ACCOUNT_TZ).astimezone(timezone.utc)
        return (dt.replace(tzinfo=timezone.utc)
                - timedelta(hours=_ACCOUNT_TZ_FALLBACK_HOURS))
    except ValueError:
        pass
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        if _ACCOUNT_TZ is not None:
            return dt.replace(tzinfo=_ACCOUNT_TZ).astimezone(timezone.utc)
        return (dt.replace(tzinfo=timezone.utc)
                - timedelta(hours=_ACCOUNT_TZ_FALLBACK_HOURS))
    except ValueError:
        return None


def _post(client, base, path, payload, cred):
    body = {"hash": cred, **payload}
    try:
        r = client.post(f"{base}/{path.lstrip('/')}", json=body, timeout=HTTP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        return False, {"transport_error": type(e).__name__}
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return False, {"http_status": r.status_code}
    if r.status_code != 200 or not data.get("success", False):
        return False, {"http_status": r.status_code, "navixy_status": data.get("status")}
    return True, data


def _hr(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78, flush=True)


# ============================ LECTEURS READ-ONLY =========================
def read_state(client, base, cred):
    ok, data = _post(client, base, "tracker/get_state", {"tracker_id": TRACKER_ID}, cred)
    if not ok:
        return {"available": False, "error": data}
    st = data.get("state") or {}
    gps = st.get("gps") or {}
    loc = gps.get("location") or {}
    gsm = st.get("gsm")
    gsm_sig = gsm.get("signal_level") if isinstance(gsm, dict) else st.get("gsm_level")
    gps_upd = _parse_ts(gps.get("updated"))
    return {
        "available": True,
        "connection_status": st.get("connection_status"),
        "movement_status": st.get("movement_status"),
        "ignition": st.get("ignition"),
        "last_update": _fmt_iso(_parse_ts(st.get("last_update"))),
        "gps_updated": _fmt_iso(gps_upd),
        "gps_fresh": (gps_upd is not None
                      and (_now() - gps_upd).total_seconds() <= GPS_FRESH_MAX_S),
        "gps_signal_level": gps.get("signal_level"),
        "speed": gps.get("speed"),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "gsm_signal": gsm_sig,
        "inputs": st.get("inputs"),
        "battery": st.get("battery_level"),
    }


def read_avl16(client, base, cred):
    ok, data = _post(client, base, "tracker/readings/list", {"tracker_id": TRACKER_ID}, cred)
    if not ok:
        return {"available": False, "error": data}
    hit = None

    def _walk(o):
        nonlocal hit
        if isinstance(o, dict):
            sid = o.get("sensor_id")
            try:
                sid = int(sid) if sid is not None else None
            except (TypeError, ValueError):
                sid = None
            if sid == AVL16_SENSOR_ID and "value" in o:
                hit = {"sensor_id": sid, "value": o.get("value"),
                       "name": o.get("name") or o.get("label"),
                       "time": _fmt_iso(_parse_ts(o.get("update_time") or o.get("time")
                                                  or o.get("timestamp")))}
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(data)
    if hit is None:
        return {"available": False, "reason": "AVL16_NOT_IN_READINGS"}
    return {"available": True, **hit}


def read_history(client, base, cred):
    now = _now()
    ok, data = _post(client, base, "history/tracker/list", {
        "trackers": [TRACKER_ID],
        "from": _fmt_iso(now - timedelta(minutes=HISTORY_LOOKBACK_MIN)),
        "to": _fmt_iso(now + timedelta(minutes=1)),
        "ascending": True, "limit": 200, "iso_datetime": True,
    }, cred)
    if not ok:
        return {"available": False, "error": data, "rows": []}
    rows = []
    for e in (data.get("list") or []):
        if not isinstance(e, dict):
            continue
        extra = e.get("extra") or {}
        cmd = extra.get("command") or {}
        resp = cmd.get("response") or {}
        rows.append({
            "time": _fmt_iso(_parse_ts(e.get("time") or e.get("get_time"))),
            "event": e.get("event") or e.get("type"),
            "message": e.get("message"),
            "cmd_name": cmd.get("name"),
            "cmd_param": cmd.get("param"),
            "resp_body": resp.get("body"),
            "resp_success": resp.get("success"),
            "resp_error": resp.get("error"),
        })
    return {"available": True, "rows": rows}


def read_track_last(client, base, cred):
    now = _now()
    ok, data = _post(client, base, "track/read", {
        "tracker_id": TRACKER_ID,
        "from": _fmt_iso(now - timedelta(minutes=TRACK_LOOKBACK_MIN)),
        "to": _fmt_iso(now + timedelta(minutes=1)),
        "iso_datetime": True, "simplify": False, "point_limit": 500,
    }, cred)
    if not ok:
        return {"available": False, "error": data}
    pts = data.get("list") or []
    if not pts:
        return {"available": True, "count": 0, "last": None}
    last = pts[-1] if isinstance(pts[-1], dict) else {}
    return {"available": True, "count": len(pts), "last": {
        "time": _fmt_iso(_parse_ts(last.get("get_time") or last.get("time"))),
        "lat": last.get("lat"), "lng": last.get("lng"),
        "speed": last.get("speed"), "satellites": last.get("satellites"),
        "valid": last.get("valid"),
    }}


# ============================ DETECTION DEVICE RESPONSE ===================
def _hist_has_private_on(rows, after_iso):
    """Cherche une reponse device 'privatemode ON' POSTERIEURE a after_iso (T0)."""
    after = _parse_ts(after_iso) if after_iso else None
    for r in rows:
        hay = " ".join(str(x) for x in (
            r.get("resp_body"), r.get("cmd_name"), r.get("cmd_param"),
            r.get("message")) if x is not None).lower()
        if r.get("resp_success") is False:
            continue
        if isinstance(r.get("resp_error"), str) and r["resp_error"].strip():
            continue
        if ("privatemode on" in hay) or ("privatemode:1" in hay) or ("private mode on" in hay):
            rts = _parse_ts(r.get("time"))
            if after is None or (rts is not None and rts > after):
                return True, r
    return False, None


# ============================ BOUCLE PRINCIPALE ==========================
def _wait_or_enter(seconds):
    """Attend `seconds`, mais retourne immediatement True si l'operateur presse Entree.
    Utilise select sur stdin (non bloquant). En l'absence de TTY -> attente simple."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            r, _, _ = select.select([sys.stdin], [], [], 0.25)
            if r:
                sys.stdin.readline()
                return True
        except Exception:  # pas de stdin exploitable
            time.sleep(0.25)
    return False


def main():
    cred, cred_src = _resolve_credential()
    base = _base_url()

    _hr("LOGITRAK — MONITEUR LIVE PRIVE (READ-ONLY) — tracker 781479")
    print(f"Debut       : {_fmt_iso(_now())}")
    print(f"Base URL    : {base}")
    print(f"Credential  : {cred_src or 'AUCUN'}  (valeur JAMAIS affichee)")
    print(f"Cadence     : {SAMPLE_EVERY_S}s | BEFORE {BEFORE_SECONDS}s | AFTER {AFTER_SECONDS}s")
    print(f"AVL16 sensor: {AVL16_SENSOR_ID}")
    print(f"TZ compte   : {'Europe/Zurich (zoneinfo)' if _ACCOUNT_TZ else f'repli +{_ACCOUNT_TZ_FALLBACK_HOURS}h'}")

    if not cred:
        _hr("STOP — CREDENTIAL NAVIXY ABSENT DU RUNTIME")
        print("Ni NAVIXY_API_KEY ni NAVIXY_HASH presents. Aucun appel effectue.")
        sys.exit(3)

    client = httpx.Client(timeout=HTTP_TIMEOUT)
    samples = []          # historique des echantillons (phase, t, state, avl16, track)
    t0 = None             # instant du clic PRIVATE (marque par l'operateur)
    prev = None           # echantillon precedent (pour deltas)

    def snapshot(phase):
        nonlocal prev
        s = {
            "phase": phase,
            "t": _fmt_iso(_now()),
            "state": read_state(client, base, cred),
            "avl16": read_avl16(client, base, cred),
            "track": read_track_last(client, base, cred),
        }
        # deltas vs precedent
        deltas = []
        if prev is not None:
            ps, cs = prev.get("state", {}), s.get("state", {})
            for k in ("connection_status", "movement_status", "ignition",
                      "gps_updated", "speed", "lat", "lng", "gsm_signal"):
                if ps.get(k) != cs.get(k):
                    deltas.append(f"{k}: {ps.get(k)} -> {cs.get(k)}")
            pa, ca = prev.get("avl16", {}), s.get("avl16", {})
            if pa.get("value") != ca.get("value"):
                deltas.append(f"AVL16.value: {pa.get('value')} -> {ca.get('value')}")
        s["deltas"] = deltas
        st = s["state"]
        av = s["avl16"]
        line = (f"[{phase}] {s['t']} conn={st.get('connection_status')} "
                f"ign={st.get('ignition')} mv={st.get('movement_status')} "
                f"spd={st.get('speed')} gpsfresh={st.get('gps_fresh')} "
                f"gps_upd={st.get('gps_updated')} lat={st.get('lat')} lng={st.get('lng')} "
                f"gsm={st.get('gsm_signal')} avl16={av.get('value') if av.get('available') else 'NA'}")
        print(line, flush=True)
        if deltas:
            print("     Δ " + " | ".join(deltas), flush=True)
        prev = s
        samples.append(s)
        return s

    # ---- PHASE BEFORE ----
    _hr(f"PHASE BEFORE (~{BEFORE_SECONDS}s) — etat de reference AVANT PRIVATE")
    before_end = time.time() + BEFORE_SECONDS
    while time.time() < before_end:
        snapshot("BEFORE")
        time.sleep(SAMPLE_EVERY_S)

    # ---- MARQUAGE T0 ----
    _hr("PRET — appuyez sur Entree PUIS cliquez PRIVATE dans l'app (marque T0)")
    print(">>> (repli automatique dans 60s si aucune touche) <<<", flush=True)
    _wait_or_enter(60)
    t0 = _now()
    print(f"*** T0 PRIVATE marque : {_fmt_iso(t0)} ***", flush=True)
    snapshot("T0")

    # ---- PHASE AFTER ----
    _hr(f"PHASE AFTER_PRIVATE (~{AFTER_SECONDS}s) — observation post-clic")
    after_end = time.time() + AFTER_SECONDS
    while time.time() < after_end:
        snapshot("AFTER_PRIVATE")
        time.sleep(SAMPLE_EVERY_S)

    # ---- HISTORY FINAL (device response) ----
    _hr("HISTORY FINAL — recherche reponse device 'Privatemode ON' (posterieure a T0)")
    hist = read_history(client, base, cred)
    if hist.get("available"):
        for r in hist["rows"]:
            if r.get("resp_body") or r.get("cmd_name") or r.get("event"):
                print("  " + json.dumps(r, ensure_ascii=False, default=str), flush=True)
    else:
        print("  history INDISPONIBLE:", json.dumps(hist.get("error"), default=str))
    found_on, found_row = _hist_has_private_on(hist.get("rows", []), _fmt_iso(t0))
    client.close()

    # ============================ SYNTHESE ===============================
    before = [s for s in samples if s["phase"] == "BEFORE"]
    after = [s for s in samples if s["phase"] in ("T0", "AFTER_PRIVATE")]

    def _last(lst, path, default=None):
        for s in reversed(lst):
            cur = s
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and cur is not None:
                return cur
        return default

    conn_after = _last(after, ["state", "connection_status"])
    gsm_after = _last(after, ["state", "gsm_signal"])
    ign_after = _last(after, ["state", "ignition"])
    gps_fresh_after = any(s["state"].get("gps_fresh") for s in after if s["state"].get("available"))
    avl_before_vals = [s["avl16"].get("value") for s in before
                       if s["avl16"].get("available")]
    avl_after_vals = [s["avl16"].get("value") for s in after
                      if s["avl16"].get("available")]
    avl_available_after = len(avl_after_vals) > 0
    avl_changed_after = (len(set([str(v) for v in (avl_before_vals + avl_after_vals)])) > 1
                         and len(avl_after_vals) > 0)

    # GPS gele/fige : positions identiques et non fraiches apres T0
    latlng_after = [(s["state"].get("lat"), s["state"].get("lng")) for s in after
                    if s["state"].get("available")]
    gps_frozen = (len(set(map(str, latlng_after))) <= 1 and not gps_fresh_after
                  and len(latlng_after) > 1)

    _hr("SYNTHESE DIAGNOSTIC LIVE (READ-ONLY — aucune ecriture effectuee)")
    print(f"T0 PRIVATE                          : {_fmt_iso(t0)}")
    print(f"Echantillons BEFORE / AFTER         : {len(before)} / {len(after)}")
    print(f"TRACKER CONNECTED AFTER PRIVATE     : "
          f"{'YES' if conn_after in ('active', 'online', True) or conn_after else 'NO'} ({conn_after})")
    print(f"GSM AVAILABLE AFTER PRIVATE         : {'YES' if gsm_after is not None else 'NO'} ({gsm_after})")
    print(f"IGNITION AVAILABLE AFTER PRIVATE    : {'YES' if ign_after is not None else 'NO'} ({ign_after})")
    print(f"GPS AVAILABLE (fresh) AFTER PRIVATE : {'YES' if gps_fresh_after else 'NO'}")
    print(f"GPS MASKED/FROZEN AFTER PRIVATE     : {'YES' if gps_frozen else 'NO'}")
    print(f"AVL16 AVAILABLE AFTER PRIVATE       : {'YES' if avl_available_after else 'NO'}")
    print(f"AVL16 CHANGED AFTER PRIVATE         : {'YES' if avl_changed_after else 'NO'} "
          f"(before={avl_before_vals[-3:]} after={avl_after_vals[:3]}...)")
    print(f"DEVICE RESPONSE 'Privatemode ON'    : {'YES' if found_on else 'NO'}")
    if found_on and found_row:
        print("   -> " + json.dumps(found_row, ensure_ascii=False, default=str))

    print("\n--- CONCLUSION (a valider) " + "-" * 50)
    if found_on:
        print("BEST PRIVATE CONFIRMATION SIGNAL     : DEVICE_RESPONSE 'Privatemode ON' "
              "(history/tracker/list, posterieur a T0)")
        print("SAFE PRIVATE CONFIRMATION RULE POSSIBLE: YES (preuve device explicite)")
        print("FALSE POSITIVE RISK                 : FAIBLE (message device + anti-stale > T0)")
    else:
        print("BEST PRIVATE CONFIRMATION SIGNAL     : AUCUNE preuve device observee.")
        print("   Examiner un eventuel signal telemetrique change NET & POSTERIEUR a T0 "
              "(ci-dessus).")
        print("SAFE PRIVATE CONFIRMATION RULE POSSIBLE: NO (rester fail-closed) — "
              "sauf preuve positive claire ci-dessus")
        print("FALSE POSITIVE RISK                 : ELEVE si on confirme sur "
              "absence GPS / immobilite / envoi seul")
    print("\nRAPPEL FAIL-CLOSED : ne JAMAIS confirmer PRIVATE sur GPS absent, "
          "position figee, AVL16 absent, tracker connecte, vehicule immobile, "
          "ou commande envoyee. Preuve POSITIVE posterieure au clic exigee.")
    print("\nFIN — collez toute cette sortie dans le chat.", flush=True)


if __name__ == "__main__":
    main()
