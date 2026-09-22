#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — VALIDATION FONCTIONNELLE PREVIEW (READ-ONLY) — patch 0009
====================================================================
Interroge l'API Preview en LECTURE SEULE pour prouver, en conditions reelles :
  * P0  : GET /driver/private-mode -> allowed / reason (boutons actifs si session).
  * Anti-fake : can_switch=false + can_switch_reason=PRIVATE_MODE_DEVICE_WRITE_DISABLED
                quand DEVICE_WRITE=0 (le mode Prive n'est pas faussement "actif").
  * G   : si state==PRIVATE (cycle ouvert) -> private_distance_km == null.
  * H   : si cycle BUSINESS clos -> private_distance_km conserve (km-summary).

STRICTEMENT READ-ONLY : uniquement /auth/login (obligatoire) + 2 GET.
  - AUCUN POST de bascule (jamais /driver/private-mode en POST).
  - AUCUNE commande device. AUCUN write metier.
  - Le mot de passe n'est lu que via l'ENV (jamais code en dur, jamais affiche).

Credentials via ENV :
  DIAG_DRIVER_EMAIL   (defaut orhan@logitrak.ch)
  DIAG_DRIVER_PWD     (obligatoire — non affiche)
  PREVIEW_API_URL     (defaut http://127.0.0.1:8102  -> backend Preview local VPS)

Execution (sur le VPS, depuis l'hote) :
  DIAG_DRIVER_PWD='***' python3 preview_functional_check_0009.py
  # ou en ciblant l'URL publique Preview :
  PREVIEW_API_URL='https://fmc130-telemetry.preview.emergentagent.com' \
  DIAG_DRIVER_PWD='***' python3 preview_functional_check_0009.py
"""
import os
import sys
import json

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable. Installez-le (pip install httpx) ou lancez dans le conteneur.")
    sys.exit(2)

BASE = (os.getenv("PREVIEW_API_URL") or "http://127.0.0.1:8102").rstrip("/")
EMAIL = (os.getenv("DIAG_DRIVER_EMAIL") or "orhan@logitrak.ch").strip()
PWD = os.getenv("DIAG_DRIVER_PWD") or ""


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def main():
    print("=" * 74)
    print("VALIDATION FONCTIONNELLE PREVIEW (READ-ONLY) — patch 0009")
    print("=" * 74)
    print("API   :", BASE)
    print("Email :", EMAIL, "(mot de passe via ENV, jamais affiche)")
    if not PWD:
        print("\nSTOP — DIAG_DRIVER_PWD non defini. Aucune requete effectuee.")
        sys.exit(3)

    with httpx.Client(timeout=25, follow_redirects=True) as c:
        # --- LOGIN (obligatoire pour un endpoint chauffeur) ---
        try:
            r = c.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PWD})
        except Exception as e:  # noqa: BLE001
            print("LOGIN: appel echoue:", type(e).__name__); sys.exit(2)
        if r.status_code != 200:
            print(f"LOGIN: HTTP {r.status_code} -> {r.text[:200]}")
            print("(401 = identifiants invalides OU lockout temporaire 15 min.)")
            sys.exit(1)
        data = r.json() or {}
        tok = data.get("access_token") or data.get("token") or (data.get("data") or {}).get("access_token")
        if not tok:
            # certains backends posent le token en cookie httpOnly -> on reutilise le client
            tok = None
            print("LOGIN OK (token en cookie de session, reutilise par le client).")
        else:
            print("LOGIN OK (token bearer recupere).")

        headers = _hdr(tok) if tok else {}

        # --- P0 / Anti-fake / G : GET /driver/private-mode ---
        print("\n--- GET /api/livre/driver/private-mode ---")
        rp = c.get(f"{BASE}/api/livre/driver/private-mode", headers=headers)
        print("HTTP", rp.status_code)
        pm = {}
        if rp.status_code == 200:
            pm = rp.json() or {}
            show = {k: pm.get(k) for k in (
                "state", "allowed", "reason", "can_switch", "can_switch_reason",
                "pending", "private_distance_km", "private_odometer_supported",
                "vehicle_id", "vehicle_plate", "tracker_id")}
            print(json.dumps(show, ensure_ascii=False, indent=2))
        else:
            print(rp.text[:300])

        # --- H : GET /driver/km-summary (distance conservee des sessions closes) ---
        print("\n--- GET /api/livre/driver/km-summary?period=month ---")
        rk = c.get(f"{BASE}/api/livre/driver/km-summary", params={"period": "month"}, headers=headers)
        print("HTTP", rk.status_code)
        if rk.status_code == 200:
            print(json.dumps(rk.json(), ensure_ascii=False, indent=2))
        else:
            print(rk.text[:300])

        # --- VERDICTS AUTOMATIQUES ---
        print("\n=== VERDICTS ===")
        state = pm.get("state")
        allowed = pm.get("allowed")
        cs = pm.get("can_switch")
        csr = pm.get("can_switch_reason")
        dist = pm.get("private_distance_km")

        # P0
        if allowed is True:
            print("P0  : allowed=TRUE -> boutons ACTIFS (canToggle=true). OK")
        elif pm.get("reason") == "PRIVATE_MODE_NO_VEHICLE":
            print("P0  : allowed=false / NO_VEHICLE -> le chauffeur doit faire 'Je conduis'"
                  " sur LOGITRAK AUDI (action mobile).")
        else:
            print(f"P0  : allowed={allowed} reason={pm.get('reason')} (voir gate).")

        # Anti-fake (DEVICE_WRITE=0)
        if cs is False and csr == "PRIVATE_MODE_DEVICE_WRITE_DISABLED":
            print("FAKE: can_switch=FALSE + DEVICE_WRITE_DISABLED -> aucune bascule reelle. OK (DEVICE_WRITE=0).")
        elif cs is False:
            print(f"FAKE: can_switch=FALSE (reason={csr}).")
        else:
            print(f"FAKE: can_switch={cs} (attendu FALSE si DEVICE_WRITE=0).")

        # G : PRIVATE ouvert -> distance None
        if state == "PRIVATE":
            print("G   : state=PRIVATE -> private_distance_km =", dist,
                  "(ATTENDU None/null)." if dist is None else "(!!! DEVRAIT ETRE None)")
        else:
            print(f"G   : state={state} (non PRIVATE) -> G non applicable ici.")

    print("\n" + "=" * 74)
    print("FIN — collez la sortie. (Aucun secret, aucune position, aucun write.)")
    print("=" * 74)


if __name__ == "__main__":
    main()
