"""Tests Phase 2 — bascule Privé/Professionnel (backend autoritaire).

Couvre la machine à états, la gate par tracker, l'idempotence, la distance AVL16,
la rédaction de position en PRIVATE, la non-généralisation, l'absence de Deep Sleep.
Les hooks device/odomètre sont MOCKÉS (aucun appel Navixy réel).
"""
from __future__ import annotations

import asyncio
import pytest

from app import private_mode_engine as pm
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER, SOURCE_NAVIXY_GPS_CALCULATED,
    AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


# --------- Faux DB minimal en mémoire (async) ---------
class _Coll:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            nd = dict(q)
            nd.update(upd.get("$set", {}))
            self.docs.append(nd)

    async def insert_one(self, d):
        self.docs.append(dict(d))


class _DB:
    def __init__(self):
        self.vehicles = _Coll()
        self.private_mode_state = _Coll()
        self.vehicle_private_capabilities = _Coll()
        self.audit_log = _Coll()
        self.feature_flags = _Coll()
        self.tenants = _Coll()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --------- Setup pilote pour la gate centrale (fail-closed) ---------
# La gate exige : feature ON + tenant allowlisté + véhicule pilote + capability
# field_validated + intégration Navixy dispo. On configure ces conditions via env
# + un stub d'intégration (aucun secret réel, aucun appel réseau).
import os as _os  # noqa: E402
from app import private_mode_gate as _gate  # noqa: E402
from app import integrations as _integrations  # noqa: E402

_ORIG_GET_CRED = _integrations.get_integration_credential


def setup_module(_module):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "3657864"
    # Stub intégration : credential présent pour 'default' uniquement (fail-closed ailleurs).
    def _stub_cred(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT", "api_url": None}
        return None
    _integrations.get_integration_credential = _stub_cred
    _gate.get_integration_credential = _stub_cred  # au cas où importé par référence


def teardown_module(_module):
    for k in ("PRIVATE_MODE_ENABLED", "PRIVATE_MODE_PILOT_TENANTS", "PRIVATE_MODE_PILOT_TRACKERS"):
        _os.environ.pop(k, None)
    _integrations.get_integration_credential = _ORIG_GET_CRED


# --------- Fixtures / helpers ---------
FIELD_VALIDATED_VC = VehicleOdometerCapability(
    vehicle_id="vA", tracker_id=3657864, device_model="FMC003",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)


def _db_with_vehicle(tracker_id=3657864, model="telfmb003_fmc003", capability=None):
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"},
         {"$set": {"id": "vA", "tenant_id": "default", "model": model,
                   "navixy_tracker_id": tracker_id, "plate": "GE-TEST",
                   "private_mode_pilot": True}}, upsert=True))
    if capability is not None:
        _run(pm.upsert_vehicle_capability(db, capability))
    return db


async def _session_ok(db, driver_id):
    return {"vehicle_id": "vA", "driver_id": driver_id}


def _mock_command(applied=True):
    async def _c(tid, cmd):
        assert "privatemode" in cmd and "11000" not in cmd  # jamais Deep Sleep
        return {"applied": applied, "mode": "MOCK", "command": cmd}
    return _c


def _mock_confirm(state):
    async def _cf(tid, expected):
        return (expected if state == "ok" else None), "MOCK"
    return _cf


def _mock_odo(seq):
    it = iter(seq)

    async def _r(tid):
        try:
            return next(it)
        except StopIteration:
            return seq[-1]
    return _r


# --------- Tests ---------
def test_gate_blocks_non_validated_tracker():
    """Tracker inconnu (ni Mongo ni registre pilote) -> refus (pas de commande)."""
    db = _db_with_vehicle(tracker_id=999999, capability=None)  # 999999 non validé
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x",
               resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([100.0])))
    assert res["ok"] is False
    assert res["allowed"] is False
    # La gate centrale refuse au niveau hardware (capability non field_validated).
    assert res["reason"] == _gate.R_NOT_SUPPORTED


def test_business_to_private_confirmed():
    """BUSINESS -> PRIVATE_REQUESTED -> PRIVATE seulement après confirmation."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x",
               resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([140000.0])))
    assert res["ok"] is True
    assert res["state"] == pm.PRIVATE
    st = _run(pm.get_mode_state(db, "vA"))
    assert st["state"] == pm.PRIVATE
    assert st["private_start_odometer_km"] == 140000.0


def test_not_confirmed_stays_requested_or_failed():
    """Sans confirmation device -> PAS de passage optimiste à PRIVATE."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x",
               resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("no"),
               read_odo_km=_mock_odo([140000.0])))
    assert res["ok"] is False
    assert res["state"] != pm.PRIVATE  # jamais PRIVATE sans confirmation


def test_private_distance_via_avl16_only():
    """Distance privée = AVL16_end - AVL16_start (pas de GPS). Cycle complet."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    # entrée privé (odo start = 140000)
    _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
         send_command=_mock_command(), confirm=_mock_confirm("ok"),
         read_odo_km=_mock_odo([140000.0])))
    # retour business (odo end = 140005.5) -> distance = 5.5
    res = _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([140005.5])))
    assert res["ok"] is True
    assert res["state"] == pm.BUSINESS
    assert res["private_distance_km"] == 5.5


def test_private_distance_unavailable_if_no_odometer():
    """Odomètre indisponible -> distance UNAVAILABLE, jamais inventée."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))
    _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
         send_command=_mock_command(), confirm=_mock_confirm("ok"),
         read_odo_km=_mock_odo([None])))
    res = _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([None])))
    assert res.get("private_distance_km") is None
    assert res.get("distance_status") == "UNAVAILABLE"


def test_idempotent_same_mode():
    """Demander PRIVATE alors que déjà PRIVATE -> no-op (aucune commande)."""
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.PRIVATE}}, upsert=True))
    calls = {"n": 0}

    async def _cmd(tid, c):
        calls["n"] += 1
        return {"applied": True, "mode": "MOCK"}
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_cmd, confirm=_mock_confirm("ok"), read_odo_km=_mock_odo([1])))
    assert res["ok"] is True and res.get("idempotent") is True
    assert calls["n"] == 0  # aucune commande device renvoyée


def test_no_active_vehicle():
    db = _db_with_vehicle(capability=FIELD_VALIDATED_VC)

    async def _no_sess(_db, _d):
        return None
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_no_sess))
    assert res["ok"] is False and res["reason"] == "no_active_vehicle"


def test_redact_private_location():
    """En PRIVATE : toute position neutralisée ; jamais 0,0 comme donnée métier."""
    obj = {"vehicle_id": "vA", "private_distance_km": 5.5,
           "lat": 46.5, "lng": 6.5, "address": "Lausanne",
           "gps": {"lat": 46.5, "lng": 6.5}, "polyline": "abc"}
    red = pm.redact_private_location(obj, pm.PRIVATE)
    assert red["lat"] is None and red["lng"] is None and red["address"] is None
    assert red["polyline"] is None and red["gps"] is None  # bloc gps entier masqué (plus sûr)
    assert red["private_distance_km"] == 5.5  # champ métier conservé
    # en BUSINESS : rien n'est masqué
    assert pm.redact_private_location(obj, pm.BUSINESS)["lat"] == 46.5


def test_private_trip_dto_has_no_position():
    doc = {"vehicle_id": "vA", "driver_id": "d1", "private_start_time": "t0",
           "private_end_time": "t1", "private_start_odometer_km": 100.0,
           "private_end_odometer_km": 106.0, "private_distance_km": 6.0,
           "odometer_source": SOURCE_TELTONIKA_TOTAL_ODOMETER, "state": pm.PRIVATE,
           "lat": 46.5, "lng": 6.5}
    dto = pm.private_trip_dto(doc)
    for forbidden in ("lat", "lng", "latitude", "longitude", "address", "polyline", "gps"):
        assert forbidden not in dto
    assert dto["private_distance_km"] == 6.0
    assert dto["odometer_source"] == SOURCE_TELTONIKA_TOTAL_ODOMETER


def test_gps_source_never_allowed_for_private_distance():
    """Une capability sur source GPS Navixy -> gate refuse (jamais de distance GPS privée)."""
    vc_gps = VehicleOdometerCapability(
        vehicle_id="vA", tracker_id=3657864, device_model="FMC003",
        private_distance_source=SOURCE_NAVIXY_GPS_CALCULATED, raw_avl_id=16,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    db = _db_with_vehicle(capability=vc_gps)
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_mock_command(), confirm=_mock_confirm("ok"),
               read_odo_km=_mock_odo([1])))
    assert res["ok"] is False and res["allowed"] is False


def test_deep_sleep_never_used():
    """Le mapping de commandes n'utilise jamais Deep Sleep 11000."""
    assert "11000" not in pm._CMD[pm.PRIVATE]
    assert "11000" not in pm._CMD[pm.BUSINESS]
    assert pm._CMD[pm.PRIVATE] == "privatemode ON"
    assert pm._CMD[pm.BUSINESS] == "privatemode OFF"


def test_device_write_gated_by_default(monkeypatch):
    """Par défaut, l'envoi device réel est désactivé (simulation)."""
    monkeypatch.delenv("PRIVATE_MODE_DEVICE_WRITE", raising=False)
    assert pm.device_write_enabled() is False
    monkeypatch.setenv("PRIVATE_MODE_DEVICE_WRITE", "1")
    assert pm.device_write_enabled() is True


# --------- Phase B : tests de non-fuite de localisation (privacy web) ---------
def test_trip_is_private_uses_business_marker_not_coords():
    """Un trajet est privé via marqueur métier explicite, JAMAIS via lat==0."""
    assert pm.trip_is_private({"private_mode": True}) is True
    assert pm.trip_is_private({"mode_status": "PRIVATE"}) is True
    assert pm.trip_is_private({"privacy": "private"}) is True
    # coords à 0,0 SANS marqueur -> PAS considéré privé (pas de déduction par coords)
    assert pm.trip_is_private({"start_lat": 0, "start_lng": 0}) is False
    assert pm.trip_is_private({"classification": "professional"}) is False


def test_redact_private_trip_removes_all_location_keeps_business():
    """Trajet privé : toute localisation retirée (None), champs métier conservés, jamais 0,0."""
    trip = {
        "id": "t1", "vehicle_id": "vA", "driver_id": "d1", "private_mode": True,
        "start_time": "t0", "end_time": "t1", "distance_km": 5.5,
        "start_lat": 46.5, "start_lng": 6.5, "end_lat": 46.6, "end_lng": 6.6,
        "start_address": "Lausanne", "end_address": "Genève", "polyline": "abc",
        "start_zone_type": "office",
    }
    red = pm.redact_private_trip(trip)
    for k in ("start_lat", "start_lng", "end_lat", "end_lng",
              "start_address", "end_address", "polyline", "start_zone_type"):
        assert red[k] is None, f"{k} doit être masqué"
    # jamais 0,0 (None, pas une coordonnée artificielle)
    assert red["start_lat"] != 0 and red["start_lng"] != 0 or red["start_lat"] is None
    # champs métier conservés
    assert red["vehicle_id"] == "vA" and red["driver_id"] == "d1"
    assert red["distance_km"] == 5.5 and red["start_time"] == "t0"
    assert red["private_redacted"] is True


def test_redact_private_trip_no_op_on_business_trip():
    """Un trajet Business (non privé) n'est PAS masqué (non-régression)."""
    trip = {"id": "t2", "classification": "professional", "start_lat": 46.5,
            "start_lng": 6.5, "start_address": "Lausanne"}
    red = pm.redact_private_trip(trip)
    assert red["start_lat"] == 46.5 and red["start_address"] == "Lausanne"
    assert "private_redacted" not in red


def test_business_private_business_segments_preserved():
    """Cycle BUSINESS->PRIVATE->BUSINESS : segments Business intacts, segment PRIVATE sans GPS,
    aucune interpolation (le segment privé ne contient simplement pas de coords)."""
    seg_b1 = {"id": "b1", "classification": "professional", "start_lat": 46.5, "start_lng": 6.5}
    seg_p = {"id": "p1", "private_mode": True, "start_lat": 46.55, "start_lng": 6.55,
             "distance_km": 3.0}
    seg_b2 = {"id": "b2", "classification": "professional", "start_lat": 46.6, "start_lng": 6.6}
    out = [pm.redact_private_trip(s) for s in (seg_b1, seg_p, seg_b2)]
    # Business conservés
    assert out[0]["start_lat"] == 46.5 and out[2]["start_lat"] == 46.6
    # Private sans coords, mais distance conservée
    assert out[1]["start_lat"] is None and out[1]["start_lng"] is None
    assert out[1]["distance_km"] == 3.0



# ===========================================================================
# Phase 3 — HARDENING de la rédaction PRIVATE (variantes + récursif).
# Objectif : PRIVATE_REDACTION_HARDENING = PASS / BUSINESS_NON_REGRESSION = PASS
# ===========================================================================
def test_redact_private_field_variants():
    """Les variantes de champs de localisation sont bien nullifiées en PRIVATE."""
    trip = {
        "id": "v1", "private_mode": True, "distance_km": 4.2,
        "latitude": 46.5, "longitude": 6.5, "lat": 46.5, "lon": 6.5, "lng": 6.5,
        "start_location": {"lat": 46.5, "lng": 6.5}, "end_location": {"lat": 46.6, "lng": 6.6},
        "coordinates": [6.5, 46.5], "address": "Rue X", "polyline": "abc",
        "route": [1, 2], "points": [[6.5, 46.5]],
    }
    red = pm.redact_private_trip(trip)
    for k in ("latitude", "longitude", "lat", "lon", "lng", "start_location",
              "end_location", "coordinates", "address", "polyline", "route", "points"):
        assert red[k] is None, f"{k} doit être nullifié"
    # champ métier conservé, jamais 0,0
    assert red["distance_km"] == 4.2
    assert red["private_redacted"] is True


def test_redact_private_nested_location_recursive():
    """Une position IMBRIQUÉE dans un champ métier est retirée récursivement (jamais 0,0)."""
    trip = {
        "id": "n1", "mode_status": "PRIVATE", "distance_km": 7.7,
        "meta": {  # champ métier contenant par erreur une position imbriquée
            "note": "ok",
            "last_position": {"lat": 46.5, "lng": 6.5},
            "waypoints": [{"lat": 46.5, "lng": 6.5}, {"lat": 46.6, "lng": 6.6}],
        },
        "segments": [
            {"label": "a", "start_location": {"lat": 46.5, "lng": 6.5}},
        ],
    }
    red = pm.redact_private_trip(trip)
    # métier conservé
    assert red["distance_km"] == 7.7
    assert red["meta"]["note"] == "ok"
    # positions imbriquées retirées (None), jamais 0,0
    assert red["meta"]["last_position"] is None
    # waypoints n'est pas une clé location -> parcouru; les lat/lng internes nullifiés
    assert red["meta"]["waypoints"][0]["lat"] is None
    assert red["meta"]["waypoints"][0]["lng"] is None
    assert red["meta"]["waypoints"][1]["lat"] is None
    # segment: start_location nullifié, label métier conservé
    assert red["segments"][0]["label"] == "a"
    assert red["segments"][0]["start_location"] is None


def test_business_trip_nested_data_not_touched():
    """NON-RÉGRESSION : un trajet Business garde toutes ses données, même imbriquées."""
    trip = {
        "id": "b9", "classification": "professional", "distance_km": 12.0,
        "start_lat": 46.5, "start_lng": 6.5,
        "meta": {"last_position": {"lat": 46.5, "lng": 6.5}, "note": "ok"},
    }
    red = pm.redact_private_trip(trip)
    # aucun masquage sur un trajet Business
    assert red["start_lat"] == 46.5 and red["start_lng"] == 6.5
    assert red["meta"]["last_position"]["lat"] == 46.5
    assert "private_redacted" not in red


def test_redact_never_introduces_zero_zero():
    """La rédaction ne remplace JAMAIS une position par 0,0 (toujours None)."""
    trip = {"id": "z1", "private_mode": True, "start_lat": 46.5, "start_lng": 6.5,
            "end_lat": 46.6, "end_lng": 6.6}
    red = pm.redact_private_trip(trip)
    for k in ("start_lat", "start_lng", "end_lat", "end_lng"):
        assert red[k] is None
        assert red[k] != 0
