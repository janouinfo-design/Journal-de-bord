#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC READ-ONLY : réponse device ON/OFF vs anti-stale (FMC130 781479)
======================================================================================
But (test terrain 18.09.2026) : PROUVER le format réel des entrées history/tracker/list
autour des commandes PRIVATE/BUSINESS, et notamment DANS QUEL CHAMP l'horodatage arrive
(`time` vs `get_time` vs autre), afin d'expliquer pourquoi le backend est resté
UNCONFIRMED/TIMEOUT alors que Air Console a affiché "Privatemode ON/OFF".

Fenêtres analysées (UTC) :
  PRIVATE  : 2026-09-18 08:43:00Z -> 08:49:30Z   (cmd envoyée 08:43:41.8Z)
  BUSINESS : 2026-09-18 09:01:00Z -> 09:07:30Z   (cmd envoyée 09:01:42.6Z)

STRICTEMENT READ-ONLY :
  - Seul endpoint appelé : history/tracker/list (lecture).
  - AUCUN envoi de commande, AUCUN write, AUCUN restart, AUCUNE modif .env/DB.
  - Le credential (hash/api_key) N'EST JAMAIS affiché. AUCUNE position GPS affichée.

Credentials : os.getenv uniquement (NAVIXY_API_KEY puis NAVIXY_HASH), NAVIXY_API_URL.
Exécution (dans le conteneur backend PROD, ex. journal_backend) :
    docker exec -i journal_backend python - < navixy_confirmation_diag_781479_0918.py
Collez toute la sortie ici (aucun secret n'y figure).
"""
import os
import sys
import json
from datetime import datetime, timezone

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable — exécuter dans le conteneur backend.")
    sys.exit(2)

TRACKER_ID = 781479
WINDOWS = [
    ("PRIVATE", datetime(2026, 9, 18, 8, 43, 0, tzinfo=timezone.utc),
     datetime(2026, 9, 18, 8, 49, 30, tzinfo=timezone.utc),
     datetime(2026, 9, 18, 8, 43, 41, tzinfo=timezone.utc)),
    ("BUSINESS", datetime(2026, 9, 18, 9, 1, 0, tzinfo=timezone.utc),
     datetime(2026, 9, 18, 9, 7, 30, tzinfo=timezone.utc),
     datetime(2026, 9, 18, 9, 1, 42, tzinfo=timezone.utc)),
]
# Formes recherchées par le matcher (mêmes que le backend).
WANT = {"PRIVATE": ("privatemode on", "privatemode:1", "private mode on"),
        "BUSINESS": ("privatemode off", "privatemode:0", "private mode off")}


def _cred():
    k = (os.getenv("NAVIXY_API_KEY") or "").strip()
    if k:
        return k, "NAVIXY_API_KEY"
    lg = (os.getenv("NAVIXY_HASH") or "").strip()
    if lg:
        return lg, "NAVIXY_HASH"
    return None, None


def _iso_z(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v):
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = datetime.strptime(s[:19], fmt)
                break
            except ValueError:
                d = None
        if d is None:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _match(entry, mode):
    """Réplique de la logique matcher (texte + ACK hardware), pour afficher la décision."""
    extra = entry.get("extra") or {}
    cmd = extra.get("command") or {}
    resp = cmd.get("response") or {}
    if resp.get("success") is False:
        return "NO(success=False)"
    if isinstance(resp.get("error"), str) and resp.get("error").strip():
        return "NO(error)"
    text = " ".join(str(x) for x in (resp.get("body"), extra.get("full_message"),
                                     entry.get("message")) if x is not None).lower()
    if any(w in text for w in WANT[mode]):
        return "YES(text)"
    if resp.get("success") is True:
        np = " ".join(str(x) for x in (cmd.get("name"), cmd.get("param")) if x is not None).lower()
        if any(w in np for w in WANT[mode]):
            return "YES(hardware_ack)"
    return "NO"


def _run_window(client, base, cred, label, w_from, w_to, sent):
    print("\n" + "=" * 78)
    print(f"FENÊTRE {label} : {_iso_z(w_from)} -> {_iso_z(w_to)}  (cmd ~ {_iso_z(sent)})")
    print("=" * 78)
    body = {"hash": cred, "trackers": [TRACKER_ID],
            "from": _iso_z(w_from), "to": _iso_z(w_to),
            "iso_datetime": True, "ascending": True, "limit": 500}
    try:
        r = client.post(f"{base}/history/tracker/list", json=body)
        data = r.json() or {}
    except Exception as e:  # noqa: BLE001
        print("APPEL ÉCHOUÉ:", type(e).__name__)
        return
    if not data.get("success", False):
        print("NON-SUCCESS:", json.dumps(data.get("status"), ensure_ascii=False))
        return
    rows = [e for e in (data.get("list") or []) if isinstance(e, dict)]
    print(f"Entrées: {len(rows)}")
    if rows:
        # Quels champs de temps existent au niveau racine de l'entrée ?
        keys_seen = set()
        for e in rows:
            keys_seen |= set(k for k in e.keys())
        time_fields = [k for k in ("time", "get_time", "timestamp", "event_time") if k in keys_seen]
        print("CHAMPS DE TEMPS présents au niveau entrée :", time_fields or "(AUCUN parmi time/get_time/timestamp/event_time)")
    for e in rows:
        extra = e.get("extra") or {}
        cmd = extra.get("command") or {}
        resp = cmd.get("response") or {}
        t_time = e.get("time")
        t_get = e.get("get_time")
        # instant utilisé par le backend ACTUEL (time seul) vs multi-champ
        et_backend = _parse(t_time)
        et_multi = _parse(t_time or t_get or e.get("timestamp") or e.get("event_time"))
        post = (et_multi is not None and et_multi >= sent)
        line = {
            "event": e.get("event") or e.get("type"),
            "time": t_time, "get_time": t_get,
            "has_command": bool(cmd),
            "cmd_name": cmd.get("name"), "cmd_param": cmd.get("param"),
            "resp_status": resp.get("status"), "resp_success": resp.get("success"),
            "resp_body": resp.get("body"),
            "has_message": bool(e.get("message")),
            "has_full_message": bool(extra.get("full_message")),
            "BACKEND_time_parsed": _iso_z(et_backend) if et_backend else None,
            "MULTI_time_parsed": _iso_z(et_multi) if et_multi else None,
            "POST_COMMAND(multi)": post,
            "MATCH": _match(e, label),
        }
        # N'imprime que les entrées avec commande OU un match potentiel (bruit réduit).
        if cmd or line["MATCH"].startswith("YES"):
            print("  " + json.dumps(line, ensure_ascii=False, default=str))

    print("-" * 78)
    print("LECTURE :")
    print("  * Si des entrées ont MATCH=YES mais BACKEND_time_parsed=null alors que")
    print("    MULTI_time_parsed est renseigné -> le backend rejette à tort (il ne lit que 'time').")
    print("  * Si le temps est dans get_time et pas dans time -> ROOT CAUSE confirmée.")


def main():
    cred, src = _cred()
    base = (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")
    print("=" * 78)
    print("DIAGNOSTIC CONFIRMATION ON/OFF (READ-ONLY) — tracker 781479 — 18.09.2026")
    print("=" * 78)
    print("Base URL   :", base)
    print("Credential :", src or "AUCUN", "(valeur jamais affichée)")
    if not cred:
        print("\nSTOP — aucun credential Navixy dans le runtime. Aucun appel effectué.")
        sys.exit(3)
    with httpx.Client(timeout=30) as c:
        for label, wf, wt, sent in WINDOWS:
            _run_window(c, base, cred, label, wf, wt, sent)
    print("\nFIN — collez toute cette sortie (aucun secret / aucune position).")


if __name__ == "__main__":
    main()
