#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — ETAPE 1 — DIAGNOSTIC READ-ONLY (schema reel Navixy) — FMC130 781479
==============================================================================
Objet : PROUVER OU SE TROUVE reellement la preuve d'execution "Privatemode ON/OFF"
renvoyee par le device, autour des commandes envoyees par le backend le 18.09.2026,
afin d'adapter correctement le lecteur de confirmation (sans rien inventer).

CONTEXTE (confirme par l'operateur) :
  - DEVICE_WRITE etait ON pendant ce test : les commandes ON/OFF ont ete envoyees
    par le BACKEND (pas par l'Air Console).
  - PRIVATE  : command_sent_at = 2026-09-18T08:43:41.801331Z  (10:43:41 Europe/Zurich)
               Air Console "Privatemode ON" ~ 10:47:59 Europe/Zurich (~08:47:59Z)
  - BUSINESS : command_sent_at = 2026-09-18T09:01:42.580299Z  (11:01:42 Europe/Zurich)
               Air Console "privatemode OFF" ~ 11:03:29 ; reponses "Privatemode OFF"
               ~ 11:03:35 et 11:03:57 Europe/Zurich (~09:03:xxZ)

CE QUE FAIT CE SCRIPT (STRICTEMENT READ-ONLY) :
  1. history/tracker/list sur 2 fenetres larges (T-2min -> T+8min) avec iso_datetime.
     -> IMPRIME LE JSON BRUT COMPLET de chaque entree (aucun filtrage), pour voir la
        vraie structure (ou est le texte device ? extra.command.response.body ?
        message ? un autre champ ? un event dedie ?).
  2. DEEP-SCAN : recherche la sous-chaine "privatemode" (insensible casse) N'IMPORTE OU
     dans l'entree, et imprime le CHEMIN JSON exact + la valeur (preuve du vrai champ).
  3. Sonde tracker/gprs_command/status (READ-ONLY) pour voir si le RESULTAT d'execution
     d'une commande GPRS y est expose (schema reel), en complement de l'historique.

INTERDITS : aucun envoi de commande, aucun write DB/.env, aucun restart, aucun secret
affiche (le hash/api_key n'est JAMAIS imprime), aucune position GPS imprimee.

Credentials : os.getenv uniquement (NAVIXY_API_KEY puis NAVIXY_HASH), NAVIXY_API_URL.

Execution (dans le conteneur backend PROD) :
    docker exec -i journal_backend python - < etape1_navixy_schema_diag_781479.py

Collez toute la sortie ici (aucun secret / aucune position n'y figure).
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable — executer dans le conteneur backend.")
    sys.exit(2)

TRACKER_ID = 781479

# Fenetres larges autour des commandes reelles (T-2min -> T+8min).
PRIVATE_SENT = datetime(2026, 9, 18, 8, 43, 41, tzinfo=timezone.utc)
BUSINESS_SENT = datetime(2026, 9, 18, 9, 1, 42, tzinfo=timezone.utc)
WINDOWS = [
    ("PRIVATE", PRIVATE_SENT - timedelta(minutes=2), PRIVATE_SENT + timedelta(minutes=8), PRIVATE_SENT),
    ("BUSINESS", BUSINESS_SENT - timedelta(minutes=2), BUSINESS_SENT + timedelta(minutes=8), BUSINESS_SENT),
]


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


def _redact(obj):
    """Retire toute valeur ressemblant a un credential avant impression (defense)."""
    SENSITIVE = {"hash", "api_key", "apikey", "token", "password", "secret", "credential"}
    if isinstance(obj, dict):
        return {k: ("<REDACTED>" if str(k).lower() in SENSITIVE else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def _deep_scan(obj, needle="privatemode", path="$"):
    """Retourne [(chemin_json, valeur_str)] ou 'privatemode' apparait (insensible casse)."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += _deep_scan(v, needle, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _deep_scan(v, needle, f"{path}[{i}]")
    else:
        try:
            s = str(obj)
        except Exception:
            s = ""
        if needle in s.lower():
            hits.append((path, s))
    return hits


def _run_history(client, base, cred, label, w_from, w_to, sent):
    print("\n" + "=" * 78)
    print(f"[HISTORY/TRACKER/LIST] FENETRE {label} : {_iso_z(w_from)} -> {_iso_z(w_to)}  (cmd ~ {_iso_z(sent)})")
    print("=" * 78)
    body = {"hash": cred, "trackers": [TRACKER_ID],
            "from": _iso_z(w_from), "to": _iso_z(w_to),
            "iso_datetime": True, "ascending": True, "limit": 500}
    try:
        r = client.post(f"{base}/history/tracker/list", json=body)
        data = r.json() or {}
    except Exception as e:  # noqa: BLE001
        print("APPEL ECHOUE:", type(e).__name__)
        return
    if not data.get("success", False):
        print("NON-SUCCESS:", json.dumps(data.get("status"), ensure_ascii=False))
        return
    rows = [e for e in (data.get("list") or []) if isinstance(e, dict)]
    print(f"Entrees: {len(rows)}")

    # 1) DEEP-SCAN global : ou apparait 'privatemode' ?
    print("\n--- DEEP-SCAN 'privatemode' (chemin JSON exact) ---")
    any_hit = False
    for idx, e in enumerate(rows):
        for pth, val in _deep_scan(e, "privatemode", f"entry[{idx}]"):
            any_hit = True
            et = e.get("time") or e.get("get_time") or e.get("timestamp")
            print(f"  {pth}  @time={et!r}  -> {val!r}")
    if not any_hit:
        print("  (AUCUNE occurrence 'privatemode' dans l'historique de cette fenetre)")

    # 2) JSON BRUT COMPLET des entrees (schema reel) — credentials redactes.
    print("\n--- JSON BRUT COMPLET des entrees (schema reel) ---")
    for idx, e in enumerate(rows):
        print(f"\n  [entry {idx}] keys={sorted(e.keys())}")
        print("  " + json.dumps(_redact(e), ensure_ascii=False, default=str))


def _run_gprs_status(client, base, cred):
    """Sonde tracker/gprs_command/status (READ-ONLY) — schema reel du resultat de commande."""
    print("\n" + "=" * 78)
    print("[TRACKER/GPRS_COMMAND/STATUS] (READ-ONLY) — schema du resultat de commande")
    print("=" * 78)
    # Selon les versions d'API, le champ d'identite est tracker_id (user-api) ou device_id (panel).
    for key in ("tracker_id", "device_id"):
        body = {"hash": cred, key: TRACKER_ID}
        try:
            r = client.post(f"{base}/tracker/gprs_command/status", json=body)
            data = r.json() or {}
        except Exception as e:  # noqa: BLE001
            print(f"  ({key}) APPEL ECHOUE: {type(e).__name__}")
            continue
        ok = data.get("success", False)
        print(f"  ({key}) success={ok}")
        if not ok:
            print("    status:", json.dumps(data.get("status"), ensure_ascii=False))
        else:
            print("    JSON BRUT:", json.dumps(_redact(data), ensure_ascii=False, default=str)[:4000])


def main():
    cred, src = _cred()
    base = (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")
    print("=" * 78)
    print("ETAPE 1 — DIAGNOSTIC SCHEMA NAVIXY (READ-ONLY) — tracker 781479 — 18.09.2026")
    print("=" * 78)
    print("Base URL   :", base)
    print("Credential :", src or "AUCUN", "(valeur jamais affichee)")
    if not cred:
        print("\nSTOP — aucun credential Navixy dans le runtime. Aucun appel effectue.")
        sys.exit(3)
    with httpx.Client(timeout=30) as c:
        for label, wf, wt, sent in WINDOWS:
            _run_history(c, base, cred, label, wf, wt, sent)
        _run_gprs_status(c, base, cred)
    print("\n" + "=" * 78)
    print("FIN — collez TOUTE la sortie (aucun secret / aucune position n'y figure).")
    print("=" * 78)


if __name__ == "__main__":
    main()
