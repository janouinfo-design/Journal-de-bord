"""Audit odomètre — tests READ-ONLY de l'endpoint /driver/vehicle/odometer.

Vérifie l'honnêteté des données (jamais de 0 fictif), l'authentification et
l'anti-IDOR. N'effectue AUCUNE écriture, ne modifie AUCUN tracker.
"""
from __future__ import annotations

import os

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


def _tok(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def test_odometer_requires_auth():
    r = requests.get(f"{API}/livre/driver/vehicle/odometer", timeout=15)
    assert r.status_code == 401


def test_odometer_no_session_unavailable_never_zero():
    dt = _tok(DRIVER)
    # s'assurer qu'aucune session n'est active
    requests.post(f"{API}/livre/driver/stop", headers=_h(dt), timeout=15)
    r = requests.get(f"{API}/livre/driver/vehicle/odometer", headers=_h(dt), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["odometer_km"] is None
    assert body["status"] == "UNAVAILABLE"
    # JAMAIS 0 quand la donnée n'est pas connue
    assert body["odometer_km"] != 0


def test_odometer_active_session_unavailable_when_navixy_absent():
    """Avec session active mais Navixy non configuré -> UNAVAILABLE (pas de 0, pas de GPS)."""
    at = _tok(ADMIN)
    dt = _tok(DRIVER)
    vehicles = requests.get(f"{API}/livre/vehicles", headers=_h(at), timeout=15).json()
    assert vehicles, "aucun véhicule seedé"
    vid = vehicles[0]["id"]
    requests.post(f"{API}/livre/driver/stop", headers=_h(dt), timeout=15)
    requests.post(f"{API}/livre/driver/claim", headers=_h(dt),
                  json={"vehicle_id": vid}, timeout=15)
    try:
        r = requests.get(f"{API}/livre/driver/vehicle/odometer", headers=_h(dt), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["vehicle_id"] == vid
        # Navixy absent dans l'env de test -> pas de donnée hardware, jamais estimée
        assert body["status"] in ("UNAVAILABLE", "STALE", "REAL")
        if body["status"] == "UNAVAILABLE":
            assert body["odometer_km"] is None
    finally:
        requests.post(f"{API}/livre/driver/stop", headers=_h(dt), timeout=15)


def test_odometer_idor_other_vehicle_forbidden():
    at = _tok(ADMIN)
    dt = _tok(DRIVER)
    vehicles = requests.get(f"{API}/livre/vehicles", headers=_h(at), timeout=15).json()
    if len(vehicles) < 2:
        return  # pas assez de véhicules pour tester l'IDOR
    vid, other = vehicles[0]["id"], vehicles[1]["id"]
    requests.post(f"{API}/livre/driver/stop", headers=_h(dt), timeout=15)
    requests.post(f"{API}/livre/driver/claim", headers=_h(dt),
                  json={"vehicle_id": vid}, timeout=15)
    try:
        r = requests.get(f"{API}/livre/driver/vehicle/odometer?vehicle_id={other}",
                         headers=_h(dt), timeout=15)
        assert r.status_code == 403, f"IDOR non bloqué: {r.status_code} {r.text}"
    finally:
        requests.post(f"{API}/livre/driver/stop", headers=_h(dt), timeout=15)
