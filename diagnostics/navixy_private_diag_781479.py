#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC NAVIXY *READ-ONLY* — Confirmation mode PRIVE (FMC130)
===========================================================================
Objet : capturer, autour d'un evenement "privatemode ON" reel, TOUT ce qui
reste reellement observable via l'API Navixy quand le vehicule est a l'arret,
afin de determiner s'il existe une preuve fiable de PRIVE (fail-closed).

Tracker  : 781479  (LOGITRAK AUDI)
T0       : 2026-09-14 15:04:59 UTC   (POST PRIVATE accepte / privatemode ON)
Timeout  : 2026-09-14 15:10:07 UTC   (pending_timeout -> UNKNOWN)
Fenetre  : 2026-09-14 14:59:59 UTC  ->  2026-09-14 15:14:59 UTC (T-5 / T+10)

CORRECTIF TIMEZONE (v2)
-----------------------
Le 1er diagnostic etait inconclusif car `track/read` recevait une fenetre au
format 'YYYY-MM-DD HH:MM:SS' SANS offset. Navixy interprete ce format dans la
TIMEZONE DU COMPTE (Europe/Zurich = UTC+2 en DST septembre). La fenetre UTC
14:59:59->15:14:59 etait donc lue comme heure LOCALE -> reellement ~12:59->13:14
UTC, a cote de l'evenement (0 point pertinent).

Correction : `track/read` ET `history/tracker/list` envoient desormais des
instants ISO 8601 UTC avec offset explicite (...Z) + `iso_datetime: true`,
ce qui rend la fenetre NON AMBIGUE (meme correctif que le backend prod).
Un repli en heure locale (ACCOUNT_TZ_OFFSET_HOURS) est prevu et documente
au cas ou un endpoint ignorerait `iso_datetime`.

STRICTEMENT READ-ONLY :
  - Endpoints appeles : tracker/get_state, history/tracker/list,
                        track/read, tracker/readings/list
  - AUCUN envoi de commande (device/raw_command), AUCUN write, AUCUN restart,
    AUCUNE modification de .env, AUCUN deploiement.
  - Les secrets (hash / api_key) NE SONT JAMAIS affiches ni journalises.

Credentials : lus uniquement depuis l'environnement du conteneur (os.getenv).
  Priorite : NAVIXY_API_KEY  puis  NAVIXY_HASH.
  Base URL : NAVIXY_API_URL (defaut https://api.navixy.com/v2).

--------------------------------------------------------------------------
EXECUTION SUR LE VPS (dans l'environnement du backend, ex. conteneur
journal_backend qui possede deja NAVIXY_API_URL / NAVIXY_HASH) :

    docker exec -i journal_backend python - < navixy_private_diag_781479.py

  ou, si le fichier est copie dans le conteneur :

    docker exec -it journal_backend python /chemin/navixy_private_diag_781479.py

Le script n'ecrit rien sur disque : il imprime uniquement sur stdout.
Collez l'integralite de la sortie dans le chat pour analyse.
--------------------------------------------------------------------------
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

try:
    import httpx  # deja present dans l'env backend
except ImportError:  # pragma: no cover
    print("ERREUR: le module httpx est introuvable dans cet environnement.")
    print("Executez ce script DANS le conteneur backend (journal_backend), "
          "qui possede httpx + les variables NAVIXY_*.")
    sys.exit(2)


# ============================ CONFIG FIGEE ================================
TRACKER_ID = 781479
T0 = datetime(2026, 9, 14, 15, 4, 59, tzinfo=timezone.utc)     # PRIVATE accepte
T_TIMEOUT = datetime(2026, 9, 14, 15, 10, 7, tzinfo=timezone.utc)  # pending_timeout
WIN_FROM = datetime(2026, 9, 14, 14, 59, 59, tzinfo=timezone.utc)  # T-5min
WIN_TO = datetime(2026, 9, 14, 15, 14, 59, tzinfo=timezone.utc)    # T+10min

HTTP_TIMEOUT = 30.0
TRACK_POINT_LIMIT = 1000
HISTORY_LIMIT = 500

# Timezone du compte Navixy (repli uniquement). Europe/Zurich = UTC+2 en DST
# (14 sept 2026 est en heure d'ete). Sert a construire une fenetre en HEURE LOCALE
# si jamais un endpoint ignore `iso_datetime`. Par defaut on privilegie ISO+Z.
ACCOUNT_TZ_OFFSET_HOURS = 2


# ============================ HELPERS ====================================
def _resolve_credential():
    """Renvoie (credential, source_label) SANS jamais retourner/afficher la valeur brute.
    Priorite NAVIXY_API_KEY puis NAVIXY_HASH. STOP si aucun."""
    api_key = (os.getenv("NAVIXY_API_KEY") or "").strip()
    if api_key:
        return api_key, "NAVIXY_API_KEY"
    legacy = (os.getenv("NAVIXY_HASH") or "").strip()
    if legacy:
        return legacy, "NAVIXY_HASH"
    return None, None


def _base_url():
    return (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")


def _fmt_iso(dt: datetime) -> str:
    """ISO 8601 UTC avec offset explicite -> instant NON ambigu (Navixy iso_datetime)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_plain(dt: datetime) -> str:
    """'YYYY-MM-DD HH:MM:SS' en HEURE LOCALE DU COMPTE (repli si iso_datetime ignore).
    ATTENTION : sans offset, Navixy lit ce format dans la timezone du compte."""
    local = dt.astimezone(timezone.utc) + timedelta(hours=ACCOUNT_TZ_OFFSET_HOURS)
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(v):
    """Parse un timestamp Navixy (ISO avec offset, 'YYYY-MM-DD HH:MM:SS', ou epoch).
    Renvoie un datetime timezone-aware (UTC) ou None. Aucune supposition risquee."""
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
    # ISO 8601
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    # 'YYYY-MM-DD HH:MM:SS' SANS offset -> HEURE LOCALE DU COMPTE (Navixy).
    # On la convertit en UTC via ACCOUNT_TZ_OFFSET_HOURS (jamais suppose UTC).
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc) - timedelta(hours=ACCOUNT_TZ_OFFSET_HOURS)
        return dt
    except ValueError:
        return None


def _phase(dt):
    """Classe un instant dans la sequence BEFORE / T0 / DURING / TIMEOUT / AFTER."""
    if dt is None:
        return "??"
    if dt < T0:
        return "BEFORE"
    if dt < T0 + timedelta(seconds=2):
        return "~T0"
    if dt < T_TIMEOUT:
        return "DURING"
    if dt < T_TIMEOUT + timedelta(seconds=2):
        return "~TIMEOUT"
    return "AFTER"


def _post(client, base, path, payload, cred):
    """POST READ-ONLY. Injecte hash en memoire. Ne journalise JAMAIS le hash.
    Renvoie (ok, data_or_error_dict)."""
    body = {"hash": cred, **payload}
    try:
        r = client.post(f"{base}/{path.lstrip('/')}", json=body, timeout=HTTP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        return False, {"transport_error": type(e).__name__, "detail": str(e)[:200]}
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return False, {"http_status": r.status_code, "non_json_body": r.text[:300]}
    if r.status_code != 200 or not data.get("success", False):
        # On renvoie le status Navixy (jamais le hash — il n'y figure pas).
        return False, {"http_status": r.status_code, "navixy_status": data.get("status"),
                       "success": data.get("success")}
    return True, data


def _hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _sub(title):
    print("\n--- " + title + " " + "-" * max(0, 70 - len(title)))


# ============================ MAIN =======================================
def main():
    cred, cred_src = _resolve_credential()
    base = _base_url()

    _hr("LOGITRAK — DIAGNOSTIC NAVIXY READ-ONLY (mode PRIVE / tracker 781479)")
    print(f"Genere le      : {_fmt_iso(datetime.now(timezone.utc))}")
    print(f"Base URL       : {base}")
    print(f"Credential src : {cred_src or 'AUCUN'}   (valeur JAMAIS affichee)")
    print(f"Tracker        : {TRACKER_ID}")
    print(f"T0 PRIVATE     : {_fmt_iso(T0)}")
    print(f"T timeout      : {_fmt_iso(T_TIMEOUT)}")
    print(f"Fenetre        : {_fmt_iso(WIN_FROM)}  ->  {_fmt_iso(WIN_TO)}")
    print("NOTE TZ        : requetes en ISO 8601 UTC (...Z) + iso_datetime=true -> fenetre NON "
          "ambigue.\n                 Timestamps sans offset renvoyes par Navixy = heure LOCALE "
          f"compte (UTC+{ACCOUNT_TZ_OFFSET_HOURS}), reconvertis en UTC.")

    if not cred:
        _hr("STOP — CREDENTIAL NAVIXY ABSENT DU RUNTIME")
        print("Ni NAVIXY_API_KEY ni NAVIXY_HASH ne sont presents dans l'environnement.")
        print("Executez ce script DANS le conteneur backend (journal_backend), qui "
              "possede ces variables.")
        print("Aucun appel API n'a ete effectue.")
        sys.exit(3)

    client = httpx.Client(timeout=HTTP_TIMEOUT)

    # ---------------------------------------------------------------
    # 0. ETAT COURANT (get_state) — reference "maintenant"
    # ---------------------------------------------------------------
    _hr("[1/4] tracker/get_state  (etat LIVE courant — reference)")
    ok, data = _post(client, base, "tracker/get_state",
                     {"tracker_id": TRACKER_ID}, cred)
    current_state = {}
    if ok:
        st = data.get("state") or {}
        current_state = st
        gps = st.get("gps") or {}
        loc = gps.get("location") or {}
        print(json.dumps({
            "connection_status": st.get("connection_status"),
            "movement_status": st.get("movement_status"),
            "ignition": st.get("ignition"),
            "last_update": st.get("last_update"),
            "gps_updated": gps.get("updated"),
            "gps_signal_level": gps.get("signal_level"),
            "speed": gps.get("speed"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "gsm_signal": (st.get("gsm") or {}).get("signal_level")
            if isinstance(st.get("gsm"), dict) else st.get("gsm_level"),
            "inputs": st.get("inputs"),
            "battery_level": st.get("battery_level"),
        }, indent=2, ensure_ascii=False, default=str))
        print("\n[get_state] cles disponibles au niveau racine 'state':")
        print("  " + ", ".join(sorted(st.keys())))
    else:
        print("get_state INDISPONIBLE:", json.dumps(data, ensure_ascii=False, default=str))

    # ---------------------------------------------------------------
    # 1. HISTORIQUE (history/tracker/list) — iso_datetime pour instants UTC surs
    #    C'est ici que peut apparaitre la REPONSE DEVICE "Privatemode ON".
    # ---------------------------------------------------------------
    _hr("[2/4] history/tracker/list  (evenements + REPONSES DEVICE, iso_datetime=True)")
    ok, data = _post(client, base, "history/tracker/list", {
        "trackers": [TRACKER_ID],
        "from": _fmt_iso(WIN_FROM),
        "to": _fmt_iso(WIN_TO),
        "ascending": True,
        "limit": HISTORY_LIMIT,
        "iso_datetime": True,
    }, cred)

    device_response_private_found = False
    device_response_after_t0 = False
    history_rows = []
    if ok:
        history_rows = data.get("list") or []
        print(f"Entrees recues : {len(history_rows)}")
        for e in history_rows:
            if not isinstance(e, dict):
                continue
            ts = _parse_ts(e.get("time") or e.get("get_time") or e.get("timestamp"))
            extra = e.get("extra") or {}
            cmd = extra.get("command") or {}
            resp = cmd.get("response") or {}
            body_txt = resp.get("body")
            phase = _phase(ts)
            line = {
                "phase": phase,
                "time": _fmt_iso(ts) if ts else e.get("time"),
                "event": e.get("event") or e.get("type"),
                "message": e.get("message"),
                "cmd_name": cmd.get("name"),
                "cmd_param": cmd.get("param"),
                "resp_body": body_txt,
                "resp_success": resp.get("success"),
                "resp_error": resp.get("error"),
            }
            print("  " + json.dumps(line, ensure_ascii=False, default=str))
            hay = " ".join(str(x) for x in (
                body_txt, cmd.get("name"), cmd.get("param"),
                extra.get("full_message"), e.get("message")) if x is not None).lower()
            if ("privatemode on" in hay) or ("privatemode:1" in hay) or ("private mode on" in hay):
                device_response_private_found = True
                if ts and ts > T0:
                    device_response_after_t0 = True
        if not history_rows:
            print("  (aucune entree d'historique dans la fenetre)")
    else:
        print("history/tracker/list INDISPONIBLE:",
              json.dumps(data, ensure_ascii=False, default=str))

    # ---------------------------------------------------------------
    # 2. POINTS GPS BRUTS (track/read) — voir si GPS gele/masque/0,0/frais
    # ---------------------------------------------------------------
    _hr("[3/4] track/read  (points GPS bruts dans la fenetre, ISO+Z, iso_datetime=True)")
    ok, data = _post(client, base, "track/read", {
        "tracker_id": TRACKER_ID,
        "from": _fmt_iso(WIN_FROM),
        "to": _fmt_iso(WIN_TO),
        "iso_datetime": True,
        "simplify": False,
        "point_limit": TRACK_POINT_LIMIT,
    }, cred)

    pts_before = pts_during = pts_after = 0
    last_before = last_during = None
    if ok:
        pts = data.get("list") or []
        print(f"Points recus   : {len(pts)}")
        for p in pts:
            if not isinstance(p, dict):
                continue
            ts = _parse_ts(p.get("get_time") or p.get("time"))
            ph = _phase(ts)
            if ph == "BEFORE":
                pts_before += 1
                last_before = p
            elif ph in ("~T0", "DURING", "~TIMEOUT"):
                pts_during += 1
                last_during = p
            elif ph == "AFTER":
                pts_after += 1
        # Echantillon lisible : dernier avant T0 + tous ceux "DURING"
        def _pp(p):
            ts = _parse_ts(p.get("get_time") or p.get("time"))
            return {"phase": _phase(ts),
                    "time": _fmt_iso(ts) if ts else p.get("get_time"),
                    "lat": p.get("lat"), "lng": p.get("lng"),
                    "speed": p.get("speed"), "satellites": p.get("satellites"),
                    "valid": p.get("valid")}
        _sub("dernier point AVANT T0")
        print("  " + (json.dumps(_pp(last_before), ensure_ascii=False, default=str)
                      if last_before else "(aucun)"))
        _sub("points PENDANT PRIVE (T0 -> timeout)")
        shown = 0
        for p in pts:
            if not isinstance(p, dict):
                continue
            ts = _parse_ts(p.get("get_time") or p.get("time"))
            if _phase(ts) in ("~T0", "DURING", "~TIMEOUT"):
                print("  " + json.dumps(_pp(p), ensure_ascii=False, default=str))
                shown += 1
        if shown == 0:
            print("  (AUCUN point GPS transmis pendant la periode PRIVE)")
        print(f"\nResume points  : BEFORE={pts_before}  DURING={pts_during}  AFTER={pts_after}")
    else:
        print("track/read INDISPONIBLE:", json.dumps(data, ensure_ascii=False, default=str))

    # ---------------------------------------------------------------
    # 3. READINGS LIVE (tracker/readings/list) — capteurs/AVL courants
    #    NB: c'est un instantane LIVE (non historise sur une fenetre).
    # ---------------------------------------------------------------
    _hr("[4/4] tracker/readings/list  (capteurs LIVE — instantane, AVL16 & autres)")
    ok, data = _post(client, base, "tracker/readings/list",
                     {"tracker_id": TRACKER_ID}, cred)
    if ok:
        # Aplatir toutes les entrees porteuses de sensor_id/value/name.
        found = []

        def _walk(obj):
            if isinstance(obj, dict):
                if any(k in obj for k in ("sensor_id", "value", "name", "label", "type")):
                    found.append({
                        "sensor_id": obj.get("sensor_id"),
                        "name": obj.get("name") or obj.get("label"),
                        "type": obj.get("type"),
                        "value": obj.get("value"),
                        "units": obj.get("units"),
                        "time": obj.get("update_time") or obj.get("time")
                        or obj.get("get_time") or obj.get("timestamp"),
                    })
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    _walk(v)

        _walk(data)
        print(f"Lectures capteur : {len(found)}")
        for f in found:
            print("  " + json.dumps(f, ensure_ascii=False, default=str))
        if not found:
            print("  (aucune lecture de capteur exploitable)")
            print("  Brut:", json.dumps(data, ensure_ascii=False, default=str)[:600])
    else:
        print("readings/list INDISPONIBLE:", json.dumps(data, ensure_ascii=False, default=str))

    client.close()

    # ---------------------------------------------------------------
    # SYNTHESE DIAGNOSTIC (YES/NO) — aide a la formulation de la regle
    # ---------------------------------------------------------------
    _hr("SYNTHESE DIAGNOSTIC (a interpreter — READ-ONLY, aucune ecriture faite)")
    gps = (current_state.get("gps") or {}) if current_state else {}
    conn = current_state.get("connection_status") if current_state else None
    print(f"TRACKER STILL CONNECTED (now)      : {conn or 'INCONNU'}")
    print(f"IGNITION AVAILABLE (get_state)     : "
          f"{'YES' if (current_state.get('ignition') is not None) else 'NO'}")
    print(f"GPS FIELD PRESENT (get_state)      : {'YES' if gps else 'NO'}")
    print(f"GPS POINTS DURING PRIVATE          : {pts_during} "
          f"({'presents' if pts_during else 'AUCUN — GPS gele/absent pendant PRIVE'})")
    print(f"GPS POINTS AFTER TIMEOUT           : {pts_after}")
    print(f"DEVICE RESPONSE 'privatemode ON'   : "
          f"{'YES' if device_response_private_found else 'NO'} (dans history/tracker/list)")
    print(f"  -> POSTERIEUR A T0 (fiable)      : {'YES' if device_response_after_t0 else 'NO'}")
    print(f"HISTORY ENTRIES IN WINDOW          : {len(history_rows)}")
    print("\nLecture attendue :")
    print("  * Si DEVICE RESPONSE 'privatemode ON' = YES et POSTERIEUR A T0 = YES :")
    print("      -> preuve PRIMAIRE fiable (DEVICE_RESPONSE) => regle PRIVATE possible.")
    print("  * Sinon, examiner si un signal telemetrique change de facon nette")
    print("      APRES T0 (ex: GPS masque/0,0 apparaissant seulement apres T0).")
    print("  * Si RIEN ne change de maniere nette ET correlee apres T0 :")
    print("      -> SAFE PRIVATE CONFIRMATION RULE POSSIBLE: NO (rester fail-closed).")
    print("\nFIN — collez toute cette sortie dans le chat pour analyse.")


if __name__ == "__main__":
    main()
