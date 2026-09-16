#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC READ-ONLY : réponse device 'Privatemode ON/OFF' (FMC130 781479)
======================================================================================
But : PROUVER ce que `history/tracker/list` renvoie réellement autour des commandes
PRIVATE/BUSINESS du pilote, afin de savoir si la réponse device (visible dans la
console Teltonika) est récupérable par le backend — et sous quelle forme
(response.body texte, ou ACK hardware response.success only, ou événement dédié).

Contexte pilote (à ajuster si besoin) :
  tracker_id = 781479
  PRIVATE ~ 2026-09-15 16:54:08 UTC
  BUSINESS ~ 2026-09-15 16:59:03 UTC
  Fenêtre analysée : 16:49 -> 17:04 UTC (T-5 / T+5 autour des deux commandes).

STRICTEMENT READ-ONLY :
  - Seul endpoint appelé : history/tracker/list (lecture).
  - AUCUN envoi de commande, AUCUN write, AUCUN restart, AUCUNE modif .env.
  - Le credential (hash/api_key) N'EST JAMAIS affiché.

Credentials : os.getenv uniquement (NAVIXY_API_KEY puis NAVIXY_HASH), NAVIXY_API_URL.
Exécution (dans le conteneur backend PROD/Preview, ex. journal_backend) :
    docker exec -i journal_backend python - < navixy_device_response_diag_781479.py
Collez toute la sortie ici (aucun secret n'y figure).
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable — exécuter dans le conteneur backend.")
    sys.exit(2)

TRACKER_ID = 781479
# Fenêtre autour des deux commandes du pilote (UTC). Ajuster si vos timestamps diffèrent.
WIN_FROM = datetime(2026, 9, 15, 16, 49, 0, tzinfo=timezone.utc)
WIN_TO = datetime(2026, 9, 15, 17, 4, 0, tzinfo=timezone.utc)
T_PRIVATE = datetime(2026, 9, 15, 16, 54, 8, tzinfo=timezone.utc)
T_BUSINESS = datetime(2026, 9, 15, 16, 59, 3, tzinfo=timezone.utc)


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


def _fmt(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def _parse(v):
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main():
    cred, src = _cred()
    base = (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")
    print("=" * 78)
    print("DIAGNOSTIC RÉPONSE DEVICE — history/tracker/list (READ-ONLY) — tracker 781479")
    print("=" * 78)
    print("Base URL     :", base)
    print("Credential   :", src or "AUCUN", "(valeur jamais affichée)")
    print("Fenêtre UTC  :", _iso_z(WIN_FROM), "->", _iso_z(WIN_TO))
    print("T_PRIVATE    :", _iso_z(T_PRIVATE), "| T_BUSINESS :", _iso_z(T_BUSINESS))
    if not cred:
        print("\nSTOP — aucun credential Navixy dans le runtime. Aucun appel effectué.")
        sys.exit(3)

    body = {"hash": cred, "trackers": [TRACKER_ID],
            "from": _iso_z(WIN_FROM), "to": _iso_z(WIN_TO),
            "iso_datetime": True, "ascending": True, "limit": 500}
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{base}/history/tracker/list", json=body)
            data = r.json() or {}
    except Exception as e:  # noqa: BLE001
        print("\nAPPEL ÉCHOUÉ:", type(e).__name__)
        sys.exit(4)
    if not data.get("success", False):
        print("\nRÉPONSE NON-SUCCESS:", json.dumps(data.get("status"), ensure_ascii=False))
        sys.exit(5)

    rows = [e for e in (data.get("list") or []) if isinstance(e, dict)]
    print(f"\nEntrées reçues : {len(rows)}")
    print("-" * 78)

    # Comptages utiles pour le diagnostic.
    with_command = 0
    body_hits = 0
    ack_success_hits = 0
    event_types = {}

    for e in rows:
        ts = _parse(e.get("time") or e.get("get_time"))
        ev = e.get("event") or e.get("type")
        event_types[ev] = event_types.get(ev, 0) + 1
        extra = e.get("extra") or {}
        cmd = extra.get("command") or {}
        resp = cmd.get("response") or {}
        has_cmd = bool(cmd)
        if has_cmd:
            with_command += 1
        # Détails ligne (aucun secret).
        line = {
            "time": _fmt(ts),
            "event": ev,
            "message": e.get("message"),
            "cmd_name": cmd.get("name"),
            "cmd_param": cmd.get("param"),
            "resp_status": resp.get("status"),
            "resp_body": resp.get("body"),
            "resp_error": resp.get("error"),
            "resp_success": resp.get("success"),
            "full_message": extra.get("full_message"),
        }
        # Marqueurs : texte 'privatemode on/off' présent ?
        hay = " ".join(str(x) for x in (
            resp.get("body"), cmd.get("name"), cmd.get("param"),
            extra.get("full_message"), e.get("message")) if x is not None).lower()
        if ("privatemode on" in hay) or ("privatemode off" in hay) \
                or ("privatemode:1" in hay) or ("privatemode:0" in hay):
            body_hits += 1
            line["MATCH_TEXT"] = True
        if has_cmd and resp.get("success") is True and resp.get("body") is None:
            ack_success_hits += 1
            line["ACK_HARDWARE_SUCCESS_ONLY"] = True
        # N'imprimer en détail que les lignes intéressantes (commande ou marqueur).
        if has_cmd or line.get("MATCH_TEXT"):
            print(json.dumps(line, ensure_ascii=False, default=str))

    print("-" * 78)
    print("SYNTHÈSE :")
    print("  event types (comptage)          :", json.dumps(event_types, ensure_ascii=False))
    print("  entrées avec extra.command      :", with_command)
    print("  correspondances TEXTE ON/OFF    :", body_hits,
          "  <- si >0 : response.body/message exploitable")
    print("  ACK hardware (success only)     :", ack_success_hits,
          "  <- si >0 : preuve = name/param + success True")
    print()
    print("INTERPRÉTATION :")
    if body_hits > 0:
        print("  -> La réponse 'Privatemode ON/OFF' EST récupérable via history (texte).")
        print("     Le matcher texte du backend doit alors la confirmer. Vérifier fenêtre/anti-stale.")
    elif ack_success_hits > 0:
        print("  -> La réponse hardware apparaît en ACK (success only, body vide).")
        print("     Le NOUVEAU matcher ACK (name/param + success True) doit la confirmer.")
    elif with_command > 0:
        print("  -> Des entrées commande existent mais sans texte ni ACK exploitable :")
        print("     inspecter les champs ci-dessus (peut-être un autre champ porte la preuve).")
    else:
        print("  -> AUCUNE entrée commande dans history sur la fenêtre. La preuve device N'EST")
        print("     PAS disponible via history/tracker/list -> s'appuyer sur la télémétrie FMC130")
        print("     (LKP privé / position fraîche post-OFF business). Ne PAS fabriquer DEVICE_RESPONSE.")
    print("\nFIN — collez toute cette sortie dans le chat (aucun secret présent).")


if __name__ == "__main__":
    main()
