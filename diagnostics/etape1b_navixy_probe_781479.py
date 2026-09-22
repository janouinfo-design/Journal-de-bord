#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — ETAPE 1b — SONDE READ-ONLY CONCLUSIVE — FMC130 781479
================================================================
history/tracker/list a renvoye 0 entree sur les fenetres du 18.09. Cette sonde
determine DE FACON CONCLUSIVE ou (si quelque part) une preuve d'execution de
commande "Privatemode ON/OFF" est recuperable via l'API Navixy de ce compte.

Tests (STRICTEMENT READ-ONLY) :
  A. history/tracker/list sur TOUTE la journee du 18.09 (00:00->23:59Z) : combien
     d'entrees ? quels TYPES d'evenements existent ? (prouve si l'endpoint stocke
     quoi que ce soit pour ce tracker, et s'il existe des events de commande).
  B. history/list (generique) meme fenetre, si le handler existe.
  C. tracker/batch_get_commands : commandes STOCKEES pour ce tracker + tout champ
     de resultat/reponse d'execution eventuel.

INTERDITS : aucun envoi de commande, aucun write, aucun secret affiche, aucune
position GPS. Redaction auto des credentials.

Execution (conteneur backend PROD) :
    docker exec -i journal_backend python - < etape1b_navixy_probe_781479.py
"""
import os
import sys
import json
from datetime import datetime, timezone

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable — executer dans le conteneur backend.")
    sys.exit(2)

TRACKER_ID = 781479
DAY_FROM = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)
DAY_TO = datetime(2026, 9, 18, 23, 59, 59, tzinfo=timezone.utc)


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
    SENSITIVE = {"hash", "api_key", "apikey", "token", "password", "secret", "credential"}
    if isinstance(obj, dict):
        return {k: ("<REDACTED>" if str(k).lower() in SENSITIVE else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def _deep_scan(obj, needle="privatemode", path="$"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += _deep_scan(v, needle, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _deep_scan(v, needle, f"{path}[{i}]")
    else:
        s = str(obj)
        if needle in s.lower():
            hits.append((path, s))
    return hits


def _post(client, base, path, body):
    try:
        r = client.post(f"{base}/{path}", json=body)
        return r.json() or {}, None
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


def test_A_history_tracker_list(client, base, cred):
    print("\n" + "=" * 78)
    print("A. history/tracker/list — TOUTE la journee 18.09 (types d'evenements)")
    print("=" * 78)
    body = {"hash": cred, "trackers": [TRACKER_ID],
            "from": _iso_z(DAY_FROM), "to": _iso_z(DAY_TO),
            "iso_datetime": True, "ascending": True, "limit": 1000}
    data, err = _post(client, base, "history/tracker/list", body)
    if err:
        print("  APPEL ECHOUE:", err)
        return
    if not data.get("success", False):
        print("  NON-SUCCESS:", json.dumps(data.get("status"), ensure_ascii=False))
        return
    rows = [e for e in (data.get("list") or []) if isinstance(e, dict)]
    print(f"  Entrees sur la journee: {len(rows)}")
    # Recense les types d'evenements
    types = {}
    for e in rows:
        t = e.get("event") or e.get("type") or "(sans type)"
        types[t] = types.get(t, 0) + 1
    print("  Types d'evenements presents:", json.dumps(types, ensure_ascii=False))
    # Toute occurrence 'privatemode' sur la journee ?
    hits = []
    for idx, e in enumerate(rows):
        hits += _deep_scan(e, "privatemode", f"entry[{idx}]")
    print(f"  Occurrences 'privatemode' sur la journee: {len(hits)}")
    for pth, val in hits[:20]:
        print(f"    {pth} -> {val!r}")
    # Montre 2 exemples d'entrees brutes (schema) si presentes
    for e in rows[:2]:
        print("  EXEMPLE ENTREE:", json.dumps(_redact(e), ensure_ascii=False, default=str)[:1500])


def test_B_history_list(client, base, cred):
    print("\n" + "=" * 78)
    print("B. history/list (generique) — meme fenetre")
    print("=" * 78)
    body = {"hash": cred, "tracker_id": TRACKER_ID,
            "from": _iso_z(DAY_FROM), "to": _iso_z(DAY_TO),
            "iso_datetime": True, "count": 1000}
    data, err = _post(client, base, "history/list", body)
    if err:
        print("  APPEL ECHOUE:", err)
        return
    if not data.get("success", False):
        print("  NON-SUCCESS:", json.dumps(data.get("status"), ensure_ascii=False))
        return
    rows = data.get("list") or data.get("events") or []
    print(f"  Entrees: {len(rows)}")
    hits = _deep_scan(rows, "privatemode")
    print(f"  Occurrences 'privatemode': {len(hits)}")
    for pth, val in hits[:20]:
        print(f"    {pth} -> {val!r}")
    if rows[:1]:
        print("  EXEMPLE:", json.dumps(_redact(rows[0]), ensure_ascii=False, default=str)[:1500])


def test_C_batch_get_commands(client, base, cred):
    print("\n" + "=" * 78)
    print("C. tracker/batch_get_commands — commandes stockees + resultat eventuel")
    print("=" * 78)
    body = {"hash": cred, "trackers": [TRACKER_ID]}
    data, err = _post(client, base, "tracker/batch_get_commands", body)
    if err:
        print("  APPEL ECHOUE:", err)
        return
    if not data.get("success", False):
        print("  NON-SUCCESS:", json.dumps(data.get("status"), ensure_ascii=False))
        return
    result = data.get("result") or data.get("value") or {}
    print("  JSON BRUT (redige):", json.dumps(_redact(result), ensure_ascii=False, default=str)[:3000])
    hits = _deep_scan(result, "privatemode")
    print(f"  Occurrences 'privatemode' dans les commandes stockees: {len(hits)}")
    for pth, val in hits[:20]:
        print(f"    {pth} -> {val!r}")


def main():
    cred, src = _cred()
    base = (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")
    print("=" * 78)
    print("ETAPE 1b — SONDE CONCLUSIVE (READ-ONLY) — tracker 781479 — 18.09.2026")
    print("=" * 78)
    print("Base URL   :", base)
    print("Credential :", src or "AUCUN", "(valeur jamais affichee)")
    if not cred:
        print("\nSTOP — aucun credential Navixy dans le runtime. Aucun appel effectue.")
        sys.exit(3)
    with httpx.Client(timeout=40) as c:
        test_A_history_tracker_list(c, base, cred)
        test_B_history_list(c, base, cred)
        test_C_batch_get_commands(c, base, cred)
    print("\n" + "=" * 78)
    print("FIN — collez TOUTE la sortie (aucun secret / aucune position).")
    print("=" * 78)


if __name__ == "__main__":
    main()
