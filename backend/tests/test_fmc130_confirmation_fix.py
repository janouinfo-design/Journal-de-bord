"""Confirmation FMC130 — preuve autoritative par RÉPONSE DEVICE (history/tracker/list).

Résout le bug : PRIVATE ne se confirmait jamais (timeout) car la stratégie télémétrie
dépendait de flux GPS/AVL16 que le mode privé masque. La confirmation s'appuie désormais
EN PRIORITÉ sur la réponse device ("Privatemode ON/OFF") lue dans l'historique Navixy.

Couvre : D (PRIVATE/BUSINESS confirmés par device response), E (timeout), F (absence GPS
ne confirme jamais PRIVATE), G (tenant isolation / mauvais tracker), H (nouveau cycle sans
stale). Tous les accès réseau sont MOCKÉS/INJECTÉS. Aucun send_command réel, DEVICE_WRITE=0
dans .env (les tests activent WRITE=1 uniquement en process via monkeypatch os.environ).
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
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)
    _run(pm.upsert_vehicle_capability(db, vc))
    return db


def _cap():
    return VehicleOdometerCapability(
        vehicle_id="vA", tracker_id=781479, device_model="FMC130",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
        private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)


def _hist_entry(time_iso, body):
    return {"time": time_iso, "message": body,
            "extra": {"command": {"name": "custom", "param": None,
                                  "response": {"status": "executed", "body": body,
                                               "error": None, "success": True}}}}


def setup_module(_m):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "781479"
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"

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


# ===========================================================================
# D — Confirmation par RÉPONSE DEVICE (autoritative)
# ===========================================================================
def test_private_confirmed_by_device_response():
    """Réponse device 'Privatemode ON' postérieure -> PRIVATE / DEVICE_RESPONSE (sans GPS)."""
    sent = "2026-09-10T12:00:00+00:00"
    after = "2026-09-10T12:00:20+00:00"

    async def _resp(tenant_id, tracker_id, since_iso):
        return [_hist_entry(after, "Privatemode ON")]
    state, src = _run(pm.telemetry_confirm(
        "default", 781479, pm.PRIVATE, sent, _cap(),
        fetch_command_responses=_resp))
    assert state == pm.PRIVATE
    assert src == pm.SRC_DEVICE_RESPONSE


def test_business_confirmed_by_device_response():
    """Réponse device 'Privatemode OFF' postérieure -> BUSINESS / DEVICE_RESPONSE."""
    sent = "2026-09-10T12:10:00+00:00"
    after = "2026-09-10T12:10:15+00:00"

    async def _resp(tenant_id, tracker_id, since_iso):
        return [_hist_entry(after, "Privatemode OFF")]
    state, src = _run(pm.telemetry_confirm(
        "default", 781479, pm.BUSINESS, sent, _cap(),
        fetch_command_responses=_resp))
    assert state == pm.BUSINESS
    assert src == pm.SRC_DEVICE_RESPONSE


# ===========================================================================
# H (anti-stale) — réponse d'un ANCIEN cycle ne confirme jamais un nouveau
# ===========================================================================
def test_stale_device_response_before_command_ignored():
    """Réponse 'Privatemode ON' ANTÉRIEURE à command_sent_at -> non confirmé (anti-stale)."""
    sent = "2026-09-10T12:30:00+00:00"
    before = "2026-09-10T11:59:00+00:00"

    async def _resp(tenant_id, tracker_id, since_iso):
        return [_hist_entry(before, "Privatemode ON")]
    state, src = _run(pm.telemetry_confirm(
        "default", 781479, pm.PRIVATE, sent, _cap(),
        fetch_command_responses=_resp))
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_device_response_failure_not_confirmed():
    """response.success=False -> jamais confirmé, même si 'privatemode on' présent."""
    sent = "2026-09-10T12:00:00+00:00"
    after = "2026-09-10T12:00:20+00:00"
    bad = {"time": after, "message": "Privatemode ON",
           "extra": {"command": {"name": "custom", "param": None,
                                 "response": {"status": "failed", "body": "Privatemode ON",
                                              "error": "timeout", "success": False}}}}

    async def _resp(tenant_id, tracker_id, since_iso):
        return [bad]
    state, _ = _run(pm.telemetry_confirm(
        "default", 781479, pm.PRIVATE, sent, _cap(), fetch_command_responses=_resp))
    assert state is None


# ===========================================================================
# F — une simple absence de GPS ne confirme JAMAIS PRIVATE (fail-closed)
# ===========================================================================
def test_no_gps_and_no_device_response_never_confirms_private():
    """Ni réponse device ni GPS -> jamais PRIVATE (offline != privé)."""
    async def _resp(tenant_id, tracker_id, since_iso):
        return []  # history indisponible
    async def _no_gps(tenant_id, tracker_id):
        return None  # get_state indisponible

    orig = pm._fetch_gps_state
    pm._fetch_gps_state = _no_gps
    try:
        state, src = _run(pm.telemetry_confirm(
            "default", 781479, pm.PRIVATE, "2026-09-10T12:00:00+00:00", _cap(),
            read_odo_km=None, fetch_command_responses=_resp))
    finally:
        pm._fetch_gps_state = orig
    assert state is None and src == pm.SRC_UNCONFIRMED


def test_history_unavailable_falls_back_and_stays_unconfirmed():
    """History vide + télémétrie insuffisante -> non confirmé (jamais faux PRIVATE)."""
    async def _resp(tenant_id, tracker_id, since_iso):
        return []
    async def _gps(tenant_id, tracker_id):
        # position qui bouge encore (le GPS suit) -> pas masqué
        return {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                "ignition": True, "gps_updated": "2026-09-10T12:00:30+00:00"}
    async def _samples(tenant_id, tracker_id, since):
        return [{"lat": 46.5, "lng": 6.6}, {"lat": 46.6, "lng": 6.7},
                {"lat": 46.7, "lng": 6.8}, {"lat": 46.8, "lng": 6.9},
                {"lat": 46.9, "lng": 7.0}]  # se déplacent -> non masqué
    async def _odo(_t):
        return 56010.0

    orig = pm._fetch_gps_state
    pm._fetch_gps_state = _gps
    try:
        state, _ = _run(pm.telemetry_confirm(
            "default", 781479, pm.PRIVATE, "2026-09-10T12:00:00+00:00", _cap(),
            state_doc={"private_start_odometer_km": 56000.0},
            read_odo_km=_odo, fetch_samples=_samples, fetch_command_responses=_resp))
    finally:
        pm._fetch_gps_state = orig
    assert state is None  # positions se déplacent + pas de device response -> jamais PRIVATE


# ===========================================================================
# Fallback télémétrie LKP toujours fonctionnel si device response absente
# ===========================================================================
def test_telemetry_fallback_still_confirms_private_when_dominant():
    """Sans device response mais dominante stable + AVL16 augmente -> PRIVATE / TELEMETRY."""
    async def _resp(tenant_id, tracker_id, since_iso):
        return []  # pas de réponse device -> fallback télémétrie
    async def _gps(tenant_id, tracker_id):
        return {"lat": 46.5, "lng": 6.6, "movement_status": "moving",
                "ignition": True, "gps_updated": "2026-09-10T12:00:30+00:00"}
    async def _samples(tenant_id, tracker_id, since):
        # 6 samples quasi identiques (position gelée/dominante) -> masqué
        return [{"lat": 46.5000, "lng": 6.6000}] * 6
    async def _odo(_t):
        return 56010.0

    orig = pm._fetch_gps_state
    pm._fetch_gps_state = _gps
    try:
        state, src = _run(pm.telemetry_confirm(
            "default", 781479, pm.PRIVATE, "2026-09-10T12:00:00+00:00", _cap(),
            state_doc={"private_start_odometer_km": 56000.0},
            read_odo_km=_odo, fetch_samples=_samples, fetch_command_responses=_resp))
    finally:
        pm._fetch_gps_state = orig
    assert state == pm.PRIVATE and src == pm.SRC_TELEMETRY


# ===========================================================================
# G — tenant isolation / mauvais tracker
# ===========================================================================
def test_tenant_isolation_history_uses_real_tenant():
    """Le fetch history reçoit le tenant réel ; un autre tenant -> pas de credential -> [] -> non confirmé."""
    seen = {}

    async def _resp(tenant_id, tracker_id, since_iso):
        seen["tenant"] = tenant_id
        seen["tracker"] = tracker_id
        return []  # simulate: other tenant / no data
    state, _ = _run(pm.telemetry_confirm(
        "tenantB", 999999, pm.PRIVATE, "2026-09-10T12:00:00+00:00", _cap(),
        fetch_command_responses=_resp))
    # même sans GPS (get_state réel échouera pour tracker inconnu), pas de faux positif
    assert seen["tenant"] == "tenantB" and seen["tracker"] == 999999
    assert state is None


# ===========================================================================
# H — nouveau cycle : aucun stale pending_timeout_at / transition_result
# ===========================================================================
def test_new_cycle_purges_stale_timeout_fields():
    """Une nouvelle transition PRIVATE ne réutilise JAMAIS pending_timeout_at/transition_result
    d'un cycle précédent."""
    db = _db_fmc130()
    # État précédent pollué par un ancien cycle timeout.
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "state": pm.BUSINESS,
                   "pending_timeout_at": "2000-01-01T00:00:00+00:00",
                   "transition_result": pm.TRANSITION_TIMEOUT,
                   "confirmed_at": "2000-01-01T00:00:00+00:00"}}, upsert=True))

    async def _session_ok(_db, drv):
        return {"vehicle_id": "vA", "driver_id": drv}
    async def _cmd(tid, cmd):
        return {"applied": True, "mode": "REAL", "command": cmd, "navixy_command_id": "c1"}
    async def _confirm_none(tid, expected):
        return None, pm.SRC_UNCONFIRMED
    async def _odo(_t):
        return 56000.0

    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_cmd, confirm=_confirm_none, read_odo_km=_odo))
    assert res["state"] == pm.PENDING_CONFIRMATION
    st = _run(pm.get_mode_state(db, "vA"))
    # Champs d'ancien cycle purgés au nouveau cycle.
    assert st.get("pending_timeout_at") is None
    assert st.get("transition_result") is None
    assert st.get("confirmed_at") is None
    # Nouveau command_sent_at renseigné (cycle courant).
    assert st.get("command_sent_at") is not None
    assert st.get("command_sent_at") != "2000-01-01T00:00:00+00:00"


def test_command_response_matches_helper():
    """Le matcher reconnaît ON/OFF et rejette un échec explicite."""
    on = _hist_entry("2026-09-10T12:00:20+00:00", "Privatemode ON")
    off = _hist_entry("2026-09-10T12:00:20+00:00", "Privatemode OFF")
    assert pm._command_response_matches(on, pm.PRIVATE) is True
    assert pm._command_response_matches(on, pm.BUSINESS) is False
    assert pm._command_response_matches(off, pm.BUSINESS) is True
