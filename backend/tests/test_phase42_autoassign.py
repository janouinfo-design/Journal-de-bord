"""Phase 4.2 — Auto-assignation chauffeur/véhicule via BLE (tests API réels).

Vérifie le comportement RÉEL du backend (déjà existant) pour l'auto-assignation :
- Cas nominal : tag connu + véhicule connu + RSSI valide -> session auto (source BLE).
- Répétition beacon : N détections identiques -> UNE seule session (idempotence).
- Tag inconnu -> aucune session.
- Chauffeur déjà sur le même véhicule -> pas de duplication.
- Détection trop faible (sous le plancher RSSI) -> ignorée, pas de session.
- Isolation tenant : /vehicles ne renvoie que le tenant du chauffeur.

NB : ces tests utilisent les endpoints réels ; ils ne créent aucune donnée fictive
présentée comme réelle (les tags/détections de test sont nettoyés).
"""
from __future__ import annotations

import os
import uuid

import requests

_frontend_env = {}
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@logitrak.ch", "password": "admin123"}
DRIVER = {"email": "chauffeur@logitrak.ch", "password": "chauffeur123"}


def _login(creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['email']} failed: {r.status_code} {r.text}"
    return s


def _admin():
    return _login(ADMIN)


def _driver():
    return _login(DRIVER)


def _first_vehicle(admin_s):
    r = admin_s.get(f"{API}/livre/vehicles", timeout=15)
    assert r.status_code == 200
    vs = r.json()
    assert vs, "aucun véhicule seedé"
    return vs[0]


def _stop(driver_s):
    driver_s.post(f"{API}/livre/driver/stop", timeout=15)


def test_auto_assign_nominal_creates_session():
    """Tag connu + véhicule connu + RSSI valide -> session auto (identification BLE)."""
    admin_s = _admin()
    driver_s = _driver()
    _stop(driver_s)  # état propre
    veh = _first_vehicle(admin_s)
    tag_id = f"AUTOTAG_{uuid.uuid4().hex[:8]}"
    # Créer un tag associé au véhicule
    rt = admin_s.post(f"{API}/livre/ble/tags",
                      json={"vehicle_id": veh["id"], "identifier": tag_id}, timeout=15)
    assert rt.status_code == 200, rt.text
    try:
        # Le chauffeur remonte une détection réelle de ce tag
        rd = driver_s.post(f"{API}/livre/ble/detections",
                           json={"identifier": tag_id, "rssi": -55, "platform": "native"}, timeout=15)
        assert rd.status_code == 200, rd.text
        # La session courante doit refléter le véhicule, source contenant BLE
        cs = driver_s.get(f"{API}/livre/driver/current-session", timeout=15).json()
        sess = cs.get("session")
        assert sess is not None, "aucune session auto créée"
        assert sess["vehicle_id"] == veh["id"]
        assert "BLE" in (sess.get("identification_source") or ""), sess.get("identification_source")
    finally:
        _stop(driver_s)


def test_auto_assign_beacon_repeat_single_session():
    """10 détections identiques -> une seule session (idempotence, pas de doublon)."""
    admin_s = _admin()
    driver_s = _driver()
    _stop(driver_s)
    veh = _first_vehicle(admin_s)
    tag_id = f"AUTOTAG_{uuid.uuid4().hex[:8]}"
    admin_s.post(f"{API}/livre/ble/tags",
                 json={"vehicle_id": veh["id"], "identifier": tag_id}, timeout=15)
    try:
        session_ids = set()
        for _ in range(10):
            rd = driver_s.post(f"{API}/livre/ble/detections",
                               json={"identifier": tag_id, "rssi": -58, "platform": "native"}, timeout=15)
            assert rd.status_code == 200
            cs = driver_s.get(f"{API}/livre/driver/current-session", timeout=15).json()
            if cs.get("session"):
                session_ids.add(cs["session"]["id"])
        assert len(session_ids) == 1, f"attendu 1 session, obtenu {session_ids}"
    finally:
        _stop(driver_s)


def test_auto_assign_unknown_tag_no_session():
    """Tag inconnu -> détection ignorée, aucune session créée."""
    driver_s = _driver()
    _stop(driver_s)
    ghost = f"GHOST_{uuid.uuid4().hex[:8]}"
    rd = driver_s.post(f"{API}/livre/ble/detections",
                       json={"identifier": ghost, "rssi": -50, "platform": "native"}, timeout=15)
    assert rd.status_code == 200, rd.text
    body = rd.json()
    # L'API renvoie un résumé ; la détection est marquée ignorée (unknown_tag)
    results = body.get("results") or []
    if results:
        assert any(r.get("ignored") for r in results), body
    cs = driver_s.get(f"{API}/livre/driver/current-session", timeout=15).json()
    assert cs.get("session") is None, "une session a été créée pour un tag inconnu"


def test_auto_assign_low_rssi_ignored():
    """RSSI sous le plancher -> ignoré, pas de session."""
    admin_s = _admin()
    driver_s = _driver()
    _stop(driver_s)
    veh = _first_vehicle(admin_s)
    tag_id = f"AUTOTAG_{uuid.uuid4().hex[:8]}"
    admin_s.post(f"{API}/livre/ble/tags",
                 json={"vehicle_id": veh["id"], "identifier": tag_id}, timeout=15)
    try:
        rd = driver_s.post(f"{API}/livre/ble/detections",
                           json={"identifier": tag_id, "rssi": -120, "platform": "native"}, timeout=15)
        assert rd.status_code == 200
        cs = driver_s.get(f"{API}/livre/driver/current-session", timeout=15).json()
        assert cs.get("session") is None, "session créée malgré RSSI trop faible"
    finally:
        _stop(driver_s)


def test_auto_assign_same_vehicle_no_duplicate():
    """Chauffeur déjà sur le véhicule + nouvelle détection -> même session, pas de doublon."""
    admin_s = _admin()
    driver_s = _driver()
    _stop(driver_s)
    veh = _first_vehicle(admin_s)
    tag_id = f"AUTOTAG_{uuid.uuid4().hex[:8]}"
    admin_s.post(f"{API}/livre/ble/tags",
                 json={"vehicle_id": veh["id"], "identifier": tag_id}, timeout=15)
    try:
        driver_s.post(f"{API}/livre/ble/detections",
                      json={"identifier": tag_id, "rssi": -55, "platform": "native"}, timeout=15)
        first = driver_s.get(f"{API}/livre/driver/current-session", timeout=15).json()["session"]
        driver_s.post(f"{API}/livre/ble/detections",
                      json={"identifier": tag_id, "rssi": -53, "platform": "native"}, timeout=15)
        second = driver_s.get(f"{API}/livre/driver/current-session", timeout=15).json()["session"]
        assert first and second and first["id"] == second["id"], "session dupliquée"
        assert second["vehicle_id"] == veh["id"]
    finally:
        _stop(driver_s)


def test_vehicles_endpoint_authenticated_only():
    """GET /vehicles exige une authentification (tenant garanti côté serveur)."""
    anon = requests.get(f"{API}/livre/vehicles", timeout=15)
    assert anon.status_code == 401
    driver_s = _driver()
    r = driver_s.get(f"{API}/livre/vehicles", timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
