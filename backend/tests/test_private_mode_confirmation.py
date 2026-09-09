"""Tests — confirmation RÉELLE du Mode Privé (PENDING/télémétrie, jamais faux succès/échec).

Couvre : commande envoyée -> PENDING (pas FAILED) ; confirmation télémétrique PRIVATE/BUSINESS ;
timeout -> UNKNOWN ; anti-stale (trame antérieure à la commande) ; profil gated (FMC003) ;
simulation impossible en prod ; idempotence ; cross-tracker/tenant.
Aucun appel réseau réel : télémétrie MOCKÉE via _fetch_gps_state.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

import pytest

from app import private_mode_engine as pm
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER,
    AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


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


FMC003_VC = VehicleOdometerCapability(
    vehicle_id="vA", tracker_id=3657864, device_model="FMC003",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)

FMC130_VC = VehicleOdometerCapability(
    vehicle_id="vB", tracker_id=781479, device_model="FMC130",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)  # validé odo mais PAS terrain privé


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


# ---------- gate profil télémétrie ----------
def test_telemetry_confirm_gated_to_fmc003():
    assert pm._model_supports_telemetry_confirm(FMC003_VC) is True
    # FMC130 : field_validated odo mais profil non habilité à la confirmation télémétrique
    assert pm._model_supports_telemetry_confirm(FMC130_VC) is False
    assert pm._model_supports_telemetry_confirm(None) is False


# ---------- télémétrie : PRIVATE (gel) ----------
def test_telemetry_private_confirmed_by_frozen_position(monkeypatch):
    sent = datetime.now(timezone.utc) - timedelta(seconds=30)
    # position GELÉE (gps_updated antérieur à l'envoi) + véhicule moving -> PRIVATE
    async def fake_state(tenant, tracker):
        return {"connection_status": "active", "movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent - timedelta(seconds=5)), "speed": 34,
                "lat": 46.5, "lng": 6.6}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    state, src = _run(pm.telemetry_confirm("default", 3657864, pm.PRIVATE, _iso(sent), FMC003_VC))
    assert state == pm.PRIVATE and src == pm.SRC_TELEMETRY


def test_telemetry_private_confirmed_by_zero_position(monkeypatch):
    sent = datetime.now(timezone.utc)
    async def fake_state(tenant, tracker):
        return {"connection_status": "active", "movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent), "speed": 20, "lat": 0.0, "lng": 0.0}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    state, src = _run(pm.telemetry_confirm("default", 3657864, pm.PRIVATE, _iso(sent), FMC003_VC))
    assert state == pm.PRIVATE and src == pm.SRC_TELEMETRY


def test_telemetry_private_not_confirmed_when_position_fresh(monkeypatch):
    sent = datetime.now(timezone.utc) - timedelta(seconds=30)
    # position FRAÎCHE (postérieure à l'envoi) + coords réelles -> PAS de masquage prouvé
    async def fake_state(tenant, tracker):
        return {"connection_status": "active", "movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent + timedelta(seconds=10)), "speed": 30,
                "lat": 46.5, "lng": 6.6}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    state, src = _run(pm.telemetry_confirm("default", 3657864, pm.PRIVATE, _iso(sent), FMC003_VC))
    assert state is None and src == pm.SRC_UNCONFIRMED


# ---------- télémétrie : BUSINESS (reprise) ----------
def test_telemetry_business_confirmed_by_position_resumed(monkeypatch):
    sent = datetime.now(timezone.utc) - timedelta(seconds=30)
    async def fake_state(tenant, tracker):
        return {"connection_status": "active", "movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent + timedelta(seconds=15)), "speed": 21,
                "lat": 46.52, "lng": 6.63}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    state, src = _run(pm.telemetry_confirm("default", 3657864, pm.BUSINESS, _iso(sent), FMC003_VC))
    assert state == pm.BUSINESS and src == pm.SRC_TELEMETRY


def test_telemetry_business_not_confirmed_if_stale(monkeypatch):
    sent = datetime.now(timezone.utc)
    # position ANTÉRIEURE à l'envoi -> ne compte pas (anti-stale)
    async def fake_state(tenant, tracker):
        return {"connection_status": "active", "movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent - timedelta(seconds=60)), "speed": 21,
                "lat": 46.52, "lng": 6.63}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    state, src = _run(pm.telemetry_confirm("default", 3657864, pm.BUSINESS, _iso(sent), FMC003_VC))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_telemetry_non_fmc003_never_confirms(monkeypatch):
    sent = datetime.now(timezone.utc)
    async def fake_state(tenant, tracker):
        return {"movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent), "lat": 0.0, "lng": 0.0}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    # FMC130 -> gate refuse la confirmation télémétrique
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _iso(sent), FMC130_VC))
    assert state is None and src == pm.SRC_UNCONFIRMED


# ---------- resolve_pending_confirmation ----------
def _db_pending(target=pm.PRIVATE, sent=None, cap=FMC003_VC, model="telfmb003_fmc003"):
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"}, {"$set": {
        "id": "vA", "tenant_id": "default", "model": model, "navixy_tracker_id": 3657864}}, upsert=True))
    if cap is not None:
        _run(pm.upsert_vehicle_capability(db, cap))
    doc = {"vehicle_id": "vA", "tenant_id": "default", "tracker_id": 3657864,
           "state": pm.PENDING_CONFIRMATION, "requested_target": target,
           "command_sent_at": sent or _iso(datetime.now(timezone.utc))}
    if target == pm.BUSINESS:
        doc["private_start_odometer_km"] = 140325.0
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"}, {"$set": doc}, upsert=True))
    return db


def test_resolve_pending_private_confirmed(monkeypatch):
    sent = datetime.now(timezone.utc) - timedelta(seconds=20)
    db = _db_pending(pm.PRIVATE, sent=_iso(sent))
    async def fake_state(tenant, tracker):
        return {"movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent - timedelta(seconds=5)), "lat": 46.5, "lng": 6.6}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PRIVATE and st["confirmation_source"] == pm.SRC_TELEMETRY


def test_resolve_pending_business_confirmed_with_distance(monkeypatch):
    sent = datetime.now(timezone.utc) - timedelta(seconds=20)
    db = _db_pending(pm.BUSINESS, sent=_iso(sent))
    async def fake_state(tenant, tracker):
        return {"movement_status": "moving", "ignition": True,
                "gps_updated": _iso(sent + timedelta(seconds=10)), "lat": 46.5, "lng": 6.6}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    async def fake_odo(tid):
        return 140326.74
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default", read_odo_km=fake_odo))
    assert st["state"] == pm.BUSINESS
    assert st["private_distance_km"] == round(140326.74 - 140325.0, 3)  # 1.74


def test_resolve_pending_timeout_to_unknown(monkeypatch):
    old = datetime.now(timezone.utc) - timedelta(seconds=pm.PENDING_TIMEOUT_S + 60)
    db = _db_pending(pm.PRIVATE, sent=_iso(old))
    async def fake_state(tenant, tracker):
        # pas de preuve (position fraîche) -> pas de confirmation
        return {"movement_status": "moving", "ignition": True,
                "gps_updated": _iso(datetime.now(timezone.utc)), "lat": 46.5, "lng": 6.6}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.UNKNOWN  # honnête, jamais faux succès


def test_resolve_pending_stays_pending_if_no_proof_before_timeout(monkeypatch):
    recent = datetime.now(timezone.utc) - timedelta(seconds=10)
    db = _db_pending(pm.PRIVATE, sent=_iso(recent))
    async def fake_state(tenant, tracker):
        return {"movement_status": "moving", "ignition": True,
                "gps_updated": _iso(recent + timedelta(seconds=5)), "lat": 46.5, "lng": 6.6}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PENDING_CONFIRMATION  # ni succès, ni échec


def test_resolve_pending_telemetry_unavailable_stays_pending(monkeypatch):
    recent = datetime.now(timezone.utc) - timedelta(seconds=10)
    db = _db_pending(pm.PRIVATE, sent=_iso(recent))
    async def fake_state(tenant, tracker):
        return None  # API indispo
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)
    st = _run(pm.resolve_pending_confirmation(db, "vA", "default"))
    assert st["state"] == pm.PENDING_CONFIRMATION


# ---------- request_mode : envoi réel -> PENDING (pas FAILED) ----------
async def _session_ok(db, drv):
    return {"vehicle_id": "vA", "driver_id": drv}


def _full_pilot_env(monkeypatch):
    monkeypatch.setenv("PRIVATE_MODE_ENABLED", "1")
    monkeypatch.setenv("PRIVATE_MODE_PILOT_TENANTS", "default")
    monkeypatch.setenv("PRIVATE_MODE_PILOT_TRACKERS", "3657864")
    # Ces tests envoient une commande RÉELLE (mock real_send) -> l'écriture device doit
    # être ouverte, sinon fail-fast avant toute transition.
    monkeypatch.setenv("PRIVATE_MODE_DEVICE_WRITE", "1")
    monkeypatch.delenv("PRIVATE_MODE_SIMULATE_CONFIRM", raising=False)
    from app import integrations
    monkeypatch.setattr(integrations, "get_integration_credential",
                        lambda tenant_id=None, provider="NAVIXY":
                        {"credential": "X", "source": "TENANT"} if tenant_id == "default" else None)


def test_request_mode_real_command_goes_pending_not_failed(monkeypatch):
    _full_pilot_env(monkeypatch)
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"}, {"$set": {
        "id": "vA", "tenant_id": "default", "model": "telfmb003_fmc003",
        "navixy_tracker_id": 3657864, "private_mode_pilot": True}}, upsert=True))
    _run(pm.upsert_vehicle_capability(db, FMC003_VC))
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS}}, upsert=True))

    async def real_send(tid, cmd):
        return {"applied": True, "mode": "REAL", "command": cmd, "navixy_command_id": "cmd-1"}
    # confirm par défaut renvoie UNCONFIRMED (pas de simulate)
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               tenant_id="default", send_command=real_send))
    assert res["ok"] is True and res["state"] == pm.PENDING_CONFIRMATION
    assert res.get("pending") is True
    st = _run(pm.get_mode_state(db, "vA"))
    assert st["state"] == pm.PENDING_CONFIRMATION
    assert st.get("command_sent_at") and st.get("requested_target") == pm.PRIVATE
    assert st.get("confirmation_source") == pm.SRC_UNCONFIRMED
    # surtout PAS FAILED
    assert st["state"] != pm.FAILED


def test_production_simulation_impossible(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PRIVATE_MODE_SIMULATE_CONFIRM", "1")
    import importlib
    importlib.reload(pm)
    assert pm.simulate_confirm_enabled() is False
    # restore dev for other tests
    monkeypatch.setenv("APP_ENV", "development")
    importlib.reload(pm)


# ===========================================================================
# STRATÉGIE LAST_KNOWN_POSITION (FMC130 781479) — preuve par POSITION DOMINANTE multi-samples.
# La confidentialité est prouvée par une position stable/répétée sur PLUSIEURS samples pendant
# qu'AVL16 augmente — PAS par une distance à l'ancre. _fetch_gps_state + fetch_samples MOCKÉS.
# ===========================================================================
from app.odometer_capability import CONFIRM_STRATEGY_LAST_KNOWN_POSITION

FMC130_LKP_VC = VehicleOdometerCapability(
    vehicle_id="v130", tracker_id=781479, device_model="FMC130",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", navixy_sensor_id=5577108, scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True, private_increment_verified=True,
    field_validated=True, private_confirmation_strategy=CONFIRM_STRATEGY_LAST_KNOWN_POSITION)

FMC130_NO_STRATEGY_VC = VehicleOdometerCapability(
    vehicle_id="v130", tracker_id=781479, device_model="FMC130",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True, private_increment_verified=True,
    field_validated=True, private_confirmation_strategy=None)

FMC130_NOT_VALIDATED_VC = VehicleOdometerCapability(
    vehicle_id="v130", tracker_id=781479, device_model="FMC130",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    runtime_verified=True, cumulative_verified=True, private_increment_verified=True,
    field_validated=False, private_confirmation_strategy=CONFIRM_STRATEGY_LAST_KNOWN_POSITION)

# Position d'ancre / dominante
_A = (46.5000, 6.6000)


def _now_iso():
    return _iso(datetime.now(timezone.utc))


def _mock_state(monkeypatch, *, lat, lng, gps_updated, moving=True, ignition=True):
    async def fake_state(tenant, tracker):
        return {"connection_status": "active",
                "movement_status": "moving" if moving else "parked",
                "ignition": ignition, "gps_updated": gps_updated,
                "speed": 30 if moving else 0, "lat": lat, "lng": lng}
    monkeypatch.setattr(pm, "_fetch_gps_state", fake_state)


def _mock_samples(points):
    async def fake_samples(tenant, tracker, since):
        return [{"lat": p[0], "lng": p[1], "time": _now_iso()} for p in points]
    return fake_samples


def _odo(seq):
    it = iter(seq)
    async def _r(tid):
        try:
            return next(it)
        except StopIteration:
            return seq[-1]
    return _r


# samples : position dominante stable (masqué) — 8 identiques + 1 écart -> ratio 8/9 = 0.889 (terrain)
DOMINANT_SAMPLES = [_A] * 8 + [(46.5100, 6.6100)]
# samples : véhicule qui roule réellement 50/100/150 m (le GPS suit encore) -> ratio faible
MOVING_SAMPLES = [(46.5000, 6.6000), (46.50045, 6.6000), (46.50090, 6.6000),
                  (46.50135, 6.6000), (46.50180, 6.6000), (46.50225, 6.6000)]  # ~50 m entre points
SINGLE_SAMPLE = [_A]


# --- PRIVATE ---
def test_lkp_not_validated_never_confirms(monkeypatch):
    _mock_state(monkeypatch, lat=_A[0], lng=_A[1], gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_NOT_VALIDATED_VC, state_doc=sd, read_odo_km=_odo([56444.22]),
                      fetch_samples=_mock_samples(DOMINANT_SAMPLES)))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_lkp_no_strategy_never_generalized(monkeypatch):
    _mock_state(monkeypatch, lat=_A[0], lng=_A[1], gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_NO_STRATEGY_VC, state_doc=sd, read_odo_km=_odo([56444.22]),
                      fetch_samples=_mock_samples(DOMINANT_SAMPLES)))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_lkp_private_confirmed_dominant_position_avl16_increases(monkeypatch):
    # position dominante stable multi-samples + AVL16 +1.02 -> PRIVATE confirmé
    _mock_state(monkeypatch, lat=_A[0], lng=_A[1], gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56444.22]),
                      fetch_samples=_mock_samples(DOMINANT_SAMPLES)))
    assert state == pm.PRIVATE and src == pm.SRC_TELEMETRY


def test_lkp_private_false_positive_short_move_rejected(monkeypatch):
    # le véhicule se déplace réellement de 50/100/150 m (GPS suit) -> PAS de masquage prouvé
    _mock_state(monkeypatch, lat=MOVING_SAMPLES[-1][0], lng=MOVING_SAMPLES[-1][1], gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56444.22]),
                      fetch_samples=_mock_samples(MOVING_SAMPLES)))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_lkp_private_single_sample_rejected(monkeypatch):
    # un seul sample stable -> jamais confirmé (exige plusieurs observations)
    _mock_state(monkeypatch, lat=_A[0], lng=_A[1], gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56444.22]),
                      fetch_samples=_mock_samples(SINGLE_SAMPLE)))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_lkp_private_stable_but_avl16_flat_rejected(monkeypatch):
    # position stable mais AVL16 n'augmente pas -> pas de roulage privé -> non confirmé
    _mock_state(monkeypatch, lat=_A[0], lng=_A[1], gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56443.20]),
                      fetch_samples=_mock_samples(DOMINANT_SAMPLES)))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_lkp_private_confirmed_zero_zero_immediate(monkeypatch):
    # coords 0,0 = masquage explicite -> confirmé si AVL16 augmente (sans exiger multi-samples)
    _mock_state(monkeypatch, lat=0.0, lng=0.0, gps_updated=_now_iso())
    sd = {"private_start_odometer_km": 56443.20}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _now_iso(),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56444.22]),
                      fetch_samples=_mock_samples([])))
    assert state == pm.PRIVATE and src == pm.SRC_TELEMETRY


# --- BUSINESS ---
def test_lkp_business_confirmed_short_resume(monkeypatch):
    # reprise GPS réelle même < 200 m : les samples montrent un mouvement -> BUSINESS confirmé
    sent = datetime.now(timezone.utc) - timedelta(seconds=20)
    _mock_state(monkeypatch, lat=MOVING_SAMPLES[-1][0], lng=MOVING_SAMPLES[-1][1],
                gps_updated=_iso(sent + timedelta(seconds=10)))
    sd = {"private_gps_anchor_lat": _A[0], "private_gps_anchor_lng": _A[1]}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(sent),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56444.54]),
                      fetch_samples=_mock_samples(MOVING_SAMPLES)))
    assert state == pm.BUSINESS and src == pm.SRC_TELEMETRY


def test_lkp_business_unconfirmed_if_still_masked(monkeypatch):
    # toujours position dominante stable (pas de reprise) -> pas encore BUSINESS
    sent = datetime.now(timezone.utc) - timedelta(seconds=20)
    _mock_state(monkeypatch, lat=_A[0], lng=_A[1], gps_updated=_iso(sent + timedelta(seconds=10)))
    sd = {"private_gps_anchor_lat": _A[0], "private_gps_anchor_lng": _A[1]}
    state, src = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(sent),
                      FMC130_LKP_VC, state_doc=sd, read_odo_km=_odo([56444.54]),
                      fetch_samples=_mock_samples([_A] * 6)))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_lkp_resolve_pending_business_distance_from_avl16(monkeypatch):
    # distance privée = delta AVL16 uniquement ; ancre nettoyée après BUSINESS
    sent = datetime.now(timezone.utc) - timedelta(seconds=20)
    db = _DB()
    _run(db.vehicles.update_one({"id": "v130"}, {"$set": {
        "id": "v130", "tenant_id": "default", "model": "telfmu130_fmc130",
        "navixy_tracker_id": 781479}}, upsert=True))
    _run(pm.upsert_vehicle_capability(db, FMC130_LKP_VC))
    doc = {"vehicle_id": "v130", "tenant_id": "default", "tracker_id": 781479,
           "state": pm.PENDING_CONFIRMATION, "requested_target": pm.BUSINESS,
           "command_sent_at": _iso(sent), "private_start_odometer_km": 56443.20,
           "private_gps_anchor_lat": _A[0], "private_gps_anchor_lng": _A[1]}
    _run(db.private_mode_state.update_one({"vehicle_id": "v130"}, {"$set": doc}, upsert=True))
    _mock_state(monkeypatch, lat=MOVING_SAMPLES[-1][0], lng=MOVING_SAMPLES[-1][1],
                gps_updated=_iso(sent + timedelta(seconds=10)))
    monkeypatch.setattr(pm, "_fetch_gps_samples", _mock_samples(MOVING_SAMPLES))
    async def fake_odo(tid):
        return 56444.54
    st = _run(pm.resolve_pending_confirmation(db, "v130", "default", read_odo_km=fake_odo))
    assert st["state"] == pm.BUSINESS
    assert st["private_distance_km"] == round(56444.54 - 56443.20, 3)  # 1.34
    assert "private_gps_anchor_lat" not in st and "private_gps_anchor_lng" not in st


# --- Helpers de dominance (unitaires) ---
def test_dominant_position_ratio():
    ratio, dom, total = pm._dominant_position(
        [{"lat": _A[0], "lng": _A[1]} for _ in range(8)] + [{"lat": 46.51, "lng": 6.61}])
    assert total == 9 and dom == 8 and round(ratio, 3) == 0.889


def test_samples_show_movement():
    assert pm._samples_show_movement([{"lat": p[0], "lng": p[1]} for p in MOVING_SAMPLES]) is True
    assert pm._samples_show_movement([{"lat": _A[0], "lng": _A[1]} for _ in range(6)]) is False


# --- garde-fous ---
def test_no_11807_no_deep_sleep_in_commands():
    for cmd in pm._CMD.values():
        assert "11807" not in cmd and "11000" not in cmd


def test_fmc003_frozen_position_unchanged(monkeypatch):
    sent = datetime.now(timezone.utc) - timedelta(seconds=30)
    _mock_state(monkeypatch, lat=46.5, lng=6.6, gps_updated=_iso(sent - timedelta(seconds=5)))
    state, src = _run(pm.telemetry_confirm("default", 3657864, pm.PRIVATE, _iso(sent), FMC003_VC))
    assert state == pm.PRIVATE and src == pm.SRC_TELEMETRY
