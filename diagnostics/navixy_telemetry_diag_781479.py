#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOGITRAK — DIAGNOSTIC TÉLÉMÉTRIE READ-ONLY — confirmation Privé/Pro (FMC130 781479)
====================================================================================
Objet : comprendre POURQUOI le fallback télémétrique ne confirme pas PRIVATE/BUSINESS,
en capturant EXACTEMENT ce que le moteur regarde (tracker/get_state + track/read +
tracker/readings/list). La voie "réponse device" est prouvée indisponible sur ce compte
(history/tracker/list ne contient que des events de règles, pas de command_sent).

À lancer PENDANT/juste APRÈS un cycle réel PRIVÉ->BUSINESS sur 781479, OU en rejouant une
fenêtre récente (paramètres SINCE_MIN ci-dessous).

STRICTEMENT READ-ONLY :
  - Endpoints LUS : tracker/get_state, track/read, tracker/readings/list.
  - AUCUN envoi de commande, AUCUN write, AUCUN restart, AUCUNE modif .env/DB.
  - Le credential (hash/api_key) N'EST JAMAIS affiché.

Seuils reproduits À L'IDENTIQUE du moteur (private_mode_engine) :
  - fraîcheur position "business" : PRIVATE_BUSINESS_GPS_FRESH_MAX_S (def 180 s)
  - rayon "position gelée sur l'ancre" : PRIVATE_LKP_DOMINANT_RADIUS_M (def 25 m)

Exécution :
    docker exec -i journal_backend python - < navixy_telemetry_diag_781479.py
Collez toute la sortie ici (aucun secret / positions arrondies).
"""
import os
import sys
import json
import math
from datetime import datetime, timezone, timedelta

try:
    import httpx
except ImportError:  # pragma: no cover
    print("ERREUR: httpx introuvable — exécuter dans le conteneur backend.")
    sys.exit(2)

TRACKER_ID = 781479
SINCE_MIN = int(os.getenv("DIAG_SINCE_MIN", "40"))     # fenêtre track/read (minutes)
FRESH_MAX_S = int(os.getenv("PRIVATE_BUSINESS_GPS_FRESH_MAX_S", "180"))
LKP_RADIUS_M = float(os.getenv("PRIVATE_LKP_DOMINANT_RADIUS_M", "25"))


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


def _haversine_m(a_lat, a_lng, b_lat, b_lng):
    try:
        r = 6371000.0
        p1, p2 = math.radians(a_lat), math.radians(b_lat)
        dphi = math.radians(b_lat - a_lat)
        dl = math.radians(b_lng - a_lng)
        h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(min(1.0, math.sqrt(h)))
    except (TypeError, ValueError):
        return None


def _round(v, n=5):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return v


def main():
    cred, src = _cred()
    base = (os.getenv("NAVIXY_API_URL") or "https://api.navixy.com/v2").rstrip("/")
    now = datetime.now(timezone.utc)
    print("=" * 78)
    print("DIAGNOSTIC TÉLÉMÉTRIE READ-ONLY — tracker 781479")
    print("=" * 78)
    print("Base URL   :", base)
    print("Credential :", src or "AUCUN", "(valeur jamais affichée)")
    print(f"Maintenant : {_iso_z(now)} | fenêtre track/read : {SINCE_MIN} min")
    print(f"Seuils moteur : FRESH_MAX_S={FRESH_MAX_S}  LKP_RADIUS_M={LKP_RADIUS_M}")
    if not cred:
        print("\nSTOP — aucun credential Navixy dans le runtime.")
        sys.exit(3)

    with httpx.Client(timeout=30) as c:
        # 1) ÉTAT LIVE (ce que _fetch_gps_state lit)
        print("\n--- [1] tracker/get_state (état LIVE) ---")
        try:
            r = c.post(f"{base}/tracker/get_state",
                       json={"hash": cred, "tracker_id": TRACKER_ID})
            st = (r.json() or {}).get("state") or {}
        except Exception as e:  # noqa: BLE001
            print("get_state ÉCHEC:", type(e).__name__); st = {}
        gps = st.get("gps") or {}
        loc = gps.get("location") or {}
        gps_upd = _parse(gps.get("updated"))
        fresh = bool(gps_upd and (now - gps_upd).total_seconds() <= FRESH_MAX_S)
        cur_lat, cur_lng = loc.get("lat"), loc.get("lng")
        print(json.dumps({
            "connection_status": st.get("connection_status"),
            "movement_status": st.get("movement_status"),
            "ignition": st.get("ignition"),
            "gps_updated": gps.get("updated"),
            "gps_fresh(<=%ds)" % FRESH_MAX_S: fresh,
            "speed": gps.get("speed"),
            "lat": _round(cur_lat), "lng": _round(cur_lng),
            "is_zero_00": (cur_lat is not None and cur_lng is not None
                           and abs(cur_lat) < 1e-6 and abs(cur_lng) < 1e-6),
            "last_update": st.get("last_update"),
        }, ensure_ascii=False, default=str))

        # 2) POINTS GPS (track/read) — voir gel / masquage / fraîcheur
        print(f"\n--- [2] track/read ({SINCE_MIN} min) ---")
        try:
            tr = c.post(f"{base}/track/read", json={
                "hash": cred, "tracker_id": TRACKER_ID,
                "from": _iso_z(now - timedelta(minutes=SINCE_MIN)),
                "to": _iso_z(now + timedelta(minutes=2)),
                "iso_datetime": True, "simplify": False, "point_limit": 200,
            })
            pts = (tr.json() or {}).get("list") or []
        except Exception as e:  # noqa: BLE001
            print("track/read ÉCHEC:", type(e).__name__); pts = []
        print("points reçus:", len(pts))
        # distance entre premier et dernier point (bougé ou gelé ?)
        if len(pts) >= 2:
            p0, pN = pts[0], pts[-1]
            d = _haversine_m(p0.get("lat"), p0.get("lng"), pN.get("lat"), pN.get("lng"))
            print("déplacement premier→dernier point (m):", round(d, 1) if d is not None else None)
        for p in pts[-6:]:
            print("  " + json.dumps({
                "t": p.get("get_time") or p.get("time"),
                "lat": _round(p.get("lat")), "lng": _round(p.get("lng")),
                "speed": p.get("speed"), "valid": p.get("valid"),
            }, ensure_ascii=False, default=str))

        # 3) READINGS LIVE (AVL16 & capteurs) — km privés
        print("\n--- [3] tracker/readings/list (capteurs LIVE) ---")
        try:
            rd = c.post(f"{base}/tracker/readings/list",
                        json={"hash": cred, "tracker_id": TRACKER_ID})
            data = rd.json() or {}
        except Exception as e:  # noqa: BLE001
            print("readings ÉCHEC:", type(e).__name__); data = {}
        found = []

        def _walk(o):
            if isinstance(o, dict):
                if any(k in o for k in ("sensor_id", "value", "name", "label", "type")):
                    found.append({"sensor_id": o.get("sensor_id"),
                                  "name": o.get("name") or o.get("label"),
                                  "type": o.get("type"), "value": o.get("value"),
                                  "units": o.get("units"),
                                  "t": o.get("update_time") or o.get("time") or o.get("get_time")})
                for v in o.values():
                    _walk(v)
            elif isinstance(o, list):
                for v in o:
                    _walk(v)
        _walk(data)
        print("lectures capteur:", len(found))
        for f in found:
            print("  " + json.dumps(f, ensure_ascii=False, default=str))
        if not found:
            print("  (aucune lecture exploitable — brut tronqué)")
            print("  " + json.dumps(data, ensure_ascii=False, default=str)[:400])

    # 4) SYNTHÈSE — pourquoi la confirmation aboutit ou non
    print("\n--- SYNTHÈSE (règles moteur) ---")
    print(f"GPS présent            : {'OUI' if gps else 'NON'}")
    print(f"Position fraîche        : {'OUI' if fresh else 'NON'}  (seuil {FRESH_MAX_S}s)")
    print(f"Position 0,0            : {'OUI' if (cur_lat is not None and cur_lng is not None and abs(cur_lat)<1e-6 and abs(cur_lng)<1e-6) else 'NON'}")
    print(f"movement/ignition       : mv={st.get('movement_status')} ign={st.get('ignition')}")
    print("Lecture :")
    print("  * BUSINESS confirmable si : position RÉELLE, FRAÎCHE (<=%ds), NON 0,0," % FRESH_MAX_S)
    print("    NON gelée sur l'ancre privée, et POSTÉRIEURE au OFF.")
    print("  * Si 'Position fraîche = NON' alors que le véhicule a roulé -> le device")
    print("    ne réémet pas de position récente -> fallback business ne peut pas confirmer.")
    print("  * PRIVATE confirmable via LKP (position gelée/masquée + AVL16 qui progresse).")
    print("\nFIN — collez toute cette sortie (aucun secret ; positions arrondies).")


if __name__ == "__main__":
    main()
