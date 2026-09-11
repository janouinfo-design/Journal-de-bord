"""Correctif confirmation PRIVATE FMC130 — resolve_pending_confirmation (Approche B).

Vérifie que :
  A) PRIVATE + start odo + AVL16 live supérieur + position dominante -> PRIVATE confirmé.
  B) AVL16 live indisponible -> reste PENDING (avant timeout).
  C) AVL16 live égal/inférieur -> pas de fausse confirmation.
  D) timeout sans preuve -> UNKNOWN (jamais previous_state), historique conservé.
  E) confirmation BUSINESS existante non régressée.
  F) resolve_pending_confirmation ne déclenche AUCUNE commande device.
  G) l'injection read_odo_km existante continue de fonctionner.

DB fake + AVL16 canonique (read_live_avl16_km) MOCKÉ. Aucun réseau, aucun secret,
aucune écriture PROD, aucune commande device.
"""
from __future__ import annotations

import asyncio
import os as _os

from app import private_mode_engine as pm
from app import private_mode_gate as _gate
from app import integrations as _integrations
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER, AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


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


def _db_fmc130():
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"},
         {"$set": {"id": "vA", "tenant_id": "default", "model": "telfmb130_fmc130",
                   "navixy_tracker_id": 781479, "plate": "LOGITRAK AUDI",
                   "private_mode_pilot": True}}, upsert=True))
    vc = VehicleOdometerCapability(
        vehicle_id="vA", tracker_id=781479, device_model="FMC130",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
        private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    _run(pm.upsert_vehicle_capability(db, vc))
    return db


def _make_pending(db, previous_state, requested, sent_iso, start_odo=None):
    st = {"vehicle_id": "vA", "state": pm.PENDING_CONFIRMATION,
          "previous_state": previous_state, "requested_target": requested,
          "last_command": "setparam privatemode:1", "command_sent_at": sent_iso,
          "tracker_id": 781479, "tenant_id": "default"}
    if start_odo is not None:
        st["private_start_odometer_km"] = start_odo
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"}, {"$set": st}, upsert=True))


def setup_module(_m):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "781479"
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "0"  # WRITE reste 0 (aucune commande device)

    def _stub_cred(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT", "api_url": None}
        return None
    setup_module._orig = _integrations.get_integration_credential
    _integrations.get_integration_credential = _stub_cred
    _gate.get_integration_credential = _stub_cred


def teardown_module(_m):
    for k in ("PRIVATE_MODE_ENABLED", "PRIVATE_MODE_PILOT_TENANTS",
              "PRIVATE_MODE_PILOT_TRACKERS", "PRIVATE_MODE_DEVICE_WRITE"):
        _os.environ.pop(k, None)
    _integrations.get_integration_credential = setup_module._orig


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _mock_live_avl16(monkeypatch, value_km, reason=None):
    async def _reader(_db, *, tenant_id, vehicle_id):
        return {"value_km": value_km, "reason": reason}
    monkeypatch.setattr("app.odometer_calibration.read_live_avl16_km", _reader)


def _mock_gps(monkeypatch, state):
    async def _g(tenant_id, tracker_id):
        return state
    monkeypatch.setattr(pm, "_fetch_gps_state", _g)


def _mock_samples(monkeypatch, samples):
    async def _s(tenant_id, tracker_id, since):
        return samples
    monkeypatch.setattr(pm, "_fetch_gps_samples", _s)


def _forbid_gps_writes():
    # aucune commande device n'existe dans resolve_pending_confirmation ; on documente l'invariant.
    pass


# ===========================================================================
# A) PRIVATE confirmé : AVL16 live > start + position dominante
# ===========================================================================
def test_A_private_confirmed_live_avl16_and_dominant(monkeypatch):
    db = _db_fmc130()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, _now_iso(), start_odo=56000.0)
    _mock_live_avl16(monkeypatch, 56010.0)      # AVL16 live PROD > start
    _mock_gps(monkeypatch, {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                            "ignition": True, "gps_updated": _now_iso()})
    _mock_samples(monkeypatch, [{"lat": 46.5, "lng": 6.6}] * 6)  # position dominante stable
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PRIVATE
    assert st["transition_result"] == pm.TRANSITION_CONFIRMED


# ===========================================================================
# B) AVL16 live indisponible -> reste PENDING (avant timeout)
# ===========================================================================
def test_B_live_avl16_unavailable_stays_pending(monkeypatch):
    db = _db_fmc130()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, _now_iso(), start_odo=56000.0)
    _mock_live_avl16(monkeypatch, None, reason="NAVIXY_UNAVAILABLE")  # indispo
    _mock_gps(monkeypatch, {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                            "ignition": True, "gps_updated": _now_iso()})
    _mock_samples(monkeypatch, [{"lat": 46.5, "lng": 6.6}] * 6)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PENDING_CONFIRMATION  # pas de preuve odo -> reste pending


# ===========================================================================
# C) AVL16 live égal/inférieur -> pas de fausse confirmation
# ===========================================================================
def test_C_live_avl16_not_increasing_no_false_confirm(monkeypatch):
    db = _db_fmc130()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, _now_iso(), start_odo=56000.0)
    _mock_live_avl16(monkeypatch, 56000.0)      # égal -> pas d'augmentation
    _mock_gps(monkeypatch, {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                            "ignition": True, "gps_updated": _now_iso()})
    _mock_samples(monkeypatch, [{"lat": 46.5, "lng": 6.6}] * 6)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PENDING_CONFIRMATION  # jamais PRIVATE sans progression odo


# ===========================================================================
# D) timeout sans preuve -> UNKNOWN (jamais previous_state)
# ===========================================================================
def test_D_timeout_without_proof_becomes_unknown(monkeypatch):
    db = _db_fmc130()
    old = "2000-01-01T00:00:00+00:00"
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, old, start_odo=56000.0)
    _mock_live_avl16(monkeypatch, None, reason="NAVIXY_UNAVAILABLE")
    _mock_gps(monkeypatch, None)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.UNKNOWN                       # jamais faux BUSINESS
    assert st["transition_result"] == pm.TRANSITION_TIMEOUT
    assert st["previous_state"] == pm.BUSINESS             # historique conservé
    assert st["requested_target"] == pm.PRIVATE
    assert st["last_command"] == "setparam privatemode:1"
    assert st["command_sent_at"] == old
    assert st.get("pending_timeout_at")


# ===========================================================================
# E) BUSINESS confirmation existante non régressée
# ===========================================================================
def test_E_business_confirmation_not_regressed(monkeypatch):
    db = _db_fmc130()
    _make_pending(db, pm.PRIVATE, pm.BUSINESS, _now_iso(), start_odo=56000.0)
    _mock_live_avl16(monkeypatch, 56012.0)
    # BUSINESS : trame postérieure à l'envoi OFF + coords réelles + reprise mouvement
    _mock_gps(monkeypatch, {"lat": 46.9, "lng": 7.0, "movement_status": "moving",
                            "ignition": True, "gps_updated": _now_iso()})
    _mock_samples(monkeypatch, [{"lat": 46.5, "lng": 6.6}, {"lat": 46.9, "lng": 7.0}])  # déplacement
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.BUSINESS
    assert st["transition_result"] == pm.TRANSITION_CONFIRMED


# ===========================================================================
# F) aucune commande device déclenchée par resolve_pending_confirmation
# ===========================================================================
def test_F_no_device_command_triggered(monkeypatch):
    db = _db_fmc130()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, _now_iso(), start_odo=56000.0)
    _mock_live_avl16(monkeypatch, 56010.0)
    _mock_gps(monkeypatch, {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                            "ignition": True, "gps_updated": _now_iso()})
    _mock_samples(monkeypatch, [{"lat": 46.5, "lng": 6.6}] * 6)
    # Si un envoi device était tenté, ce hook ferait échouer le test.
    async def _boom(tid, cmd):
        raise AssertionError("resolve_pending_confirmation ne doit envoyer AUCUNE commande device")
    monkeypatch.setattr(pm, "_default_send_command", _boom)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PRIVATE  # confirmé par télémétrie READ-ONLY, sans commande


# ===========================================================================
# G) l'injection read_odo_km existante continue de fonctionner
# ===========================================================================
def test_G_injection_read_odo_km_still_works(monkeypatch):
    db = _db_fmc130()
    _make_pending(db, pm.BUSINESS, pm.PRIVATE, _now_iso(), start_odo=56000.0)
    # read_live_avl16_km ne doit PAS être appelé quand read_odo_km est injecté.
    async def _must_not_call(_db, *, tenant_id, vehicle_id):
        raise AssertionError("read_live_avl16_km ne doit pas être appelé si read_odo_km injecté")
    monkeypatch.setattr("app.odometer_calibration.read_live_avl16_km", _must_not_call)
    _mock_gps(monkeypatch, {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                            "ignition": True, "gps_updated": _now_iso()})
    _mock_samples(monkeypatch, [{"lat": 46.5, "lng": 6.6}] * 6)

    async def _injected(_t):
        return 56010.0  # injection de test
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default", read_odo_km=_injected))
    assert st["state"] == pm.PRIVATE
