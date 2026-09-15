"""Correctif confirmation BUSINESS FMC130 781479 — reprise position valide à l'arrêt.

Terrain réel : après 'privatemode OFF', Location valid=yes, Speed=0 (véhicule à l'arrêt),
Satellites=14 -> l'état restait PENDING jusqu'au timeout car la preuve exigeait un MOUVEMENT.
Fix : une position GPS RÉELLE, FRAÎCHE et NON masquée réémise APRÈS l'envoi OFF confirme la
reprise BUSINESS (fail-closed : gelée sur l'ancre / périmée / 0,0 -> jamais confirmé).

Approche B : DB fake + hooks mockés. Aucun réseau, aucune commande device, aucun secret.
"""
from __future__ import annotations

import asyncio
import os as _os
from datetime import datetime, timezone, timedelta

from app import private_mode_engine as pm
from app import private_mode_gate as _gate
from app import integrations as _integrations
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER, AVL_TOTAL_ODOMETER, SCALE_VERIFIED,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _cap():
    return VehicleOdometerCapability(
        vehicle_id="vA", tracker_id=781479, device_model="FMC130",
        private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
        navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
        private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
        runtime_verified=True, cumulative_verified=True,
        private_increment_verified=True, field_validated=True)


def setup_module(_m):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "781479"

    def _stub(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT", "api_url": None}
        return None
    setup_module._orig = _integrations.get_integration_credential
    _integrations.get_integration_credential = _stub
    _gate.get_integration_credential = _stub


def teardown_module(_m):
    for k in ("PRIVATE_MODE_ENABLED", "PRIVATE_MODE_PILOT_TENANTS", "PRIVATE_MODE_PILOT_TRACKERS"):
        _os.environ.pop(k, None)
    _integrations.get_integration_credential = setup_module._orig


def _iso(dt):
    return dt.isoformat()


def _mk(monkeypatch, *, gps, samples=None, cmd_responses=None):
    async def _g(tenant_id, tracker_id):
        return gps
    async def _s(tenant_id, tracker_id, since):
        return samples or []
    async def _r(tenant_id, tracker_id, since):
        return cmd_responses or []
    monkeypatch.setattr(pm, "_fetch_gps_state", _g)
    monkeypatch.setattr(pm, "_fetch_gps_samples", _s)
    monkeypatch.setattr(pm, "_fetch_command_responses", _r)


NOW = datetime.now(timezone.utc)
SENT = NOW - timedelta(seconds=30)          # commande OFF envoyée il y a 30 s
FRESH = _iso(NOW - timedelta(seconds=10))   # position réémise il y a 10 s (fraîche, > sent)
STALE = _iso(NOW - timedelta(seconds=600))  # position périmée (> fenêtre 180 s)
ANCHOR = {"private_gps_anchor_lat": 46.5000, "private_gps_anchor_lng": 6.6000}


def test_business_confirmed_valid_fresh_position_at_standstill(monkeypatch):
    """OFF + position valide fraîche NON masquée à l'arrêt (speed=0) -> BUSINESS confirmé."""
    _mk(monkeypatch, gps={"lat": 46.6000, "lng": 6.7000, "movement_status": "parked",
                          "ignition": False, "gps_updated": FRESH, "speed": 0})
    st, src = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(SENT), _cap(),
                   state_doc=ANCHOR))
    assert st == pm.BUSINESS and src == pm.SRC_TELEMETRY


def test_business_refused_if_position_frozen_on_anchor(monkeypatch):
    """Position TOUJOURS gelée sur l'ancre privée (masquée) -> pas de BUSINESS (fail-closed)."""
    _mk(monkeypatch, gps={"lat": 46.50000, "lng": 6.60000, "movement_status": "parked",
                          "ignition": False, "gps_updated": FRESH, "speed": 0})
    st, _ = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(SENT), _cap(),
                 state_doc=ANCHOR))
    assert st is None  # encore sur l'ancre -> considéré masqué -> pas de faux BUSINESS


def test_business_refused_if_position_stale(monkeypatch):
    """Position périmée (hors fenêtre de fraîcheur) -> pas de BUSINESS."""
    _mk(monkeypatch, gps={"lat": 46.6000, "lng": 6.7000, "movement_status": "parked",
                          "ignition": False, "gps_updated": STALE, "speed": 0})
    # gps_updated est ANTÉRIEUR à sent -> la garde gps_upd>sent bloque déjà ; on force gps_upd>sent mais périmé :
    # ici STALE < SENT donc gps_upd>sent est faux -> None (double sécurité). On teste aussi le cas fresh<sent séparément.
    st, _ = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(SENT), _cap(),
                 state_doc=ANCHOR))
    assert st is None


def test_business_refused_if_zero_position(monkeypatch):
    """Position 0,0 (masquée) après OFF -> jamais BUSINESS."""
    _mk(monkeypatch, gps={"lat": 0.0, "lng": 0.0, "movement_status": "parked",
                          "ignition": False, "gps_updated": FRESH})
    st, _ = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(SENT), _cap(),
                 state_doc=ANCHOR))
    assert st is None


def test_business_still_confirmed_by_movement(monkeypatch):
    """Non-régression : reprise par mouvement réel (samples) confirme toujours BUSINESS."""
    _mk(monkeypatch, gps={"lat": 46.6, "lng": 6.7, "movement_status": "moving",
                          "ignition": True, "gps_updated": FRESH},
        samples=[{"lat": 46.5, "lng": 6.6}, {"lat": 46.7, "lng": 6.9}])  # déplacement
    st, src = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(SENT), _cap(),
                   state_doc=ANCHOR))
    assert st == pm.BUSINESS and src == pm.SRC_TELEMETRY


def test_business_refused_if_frame_not_after_command(monkeypatch):
    """Trame GPS antérieure à l'envoi OFF -> jamais BUSINESS (anti-stale)."""
    before = _iso(SENT - timedelta(seconds=60))
    _mk(monkeypatch, gps={"lat": 46.6, "lng": 6.7, "movement_status": "parked",
                          "ignition": False, "gps_updated": before})
    st, _ = _run(pm.telemetry_confirm("default", 781479, pm.BUSINESS, _iso(SENT), _cap(),
                 state_doc=ANCHOR))
    assert st is None


def test_private_unchanged_no_false_success(monkeypatch):
    """PRIVATE : sans preuve (pas de device response, GPS suit encore), reste non confirmé."""
    async def _r(t, k, s): return []
    monkeypatch.setattr(pm, "_fetch_command_responses", _r)
    _mk(monkeypatch, gps={"lat": 46.6, "lng": 6.7, "movement_status": "moving",
                          "ignition": True, "gps_updated": FRESH},
        samples=[{"lat": 46.60, "lng": 6.70}, {"lat": 46.70, "lng": 6.90},
                 {"lat": 46.80, "lng": 7.00}, {"lat": 46.90, "lng": 7.10},
                 {"lat": 47.00, "lng": 7.20}])  # positions qui bougent -> pas masqué
    async def _odo(_t): return 56000.0  # pas d'augmentation vs start
    st, _ = _run(pm.telemetry_confirm("default", 781479, pm.PRIVATE, _iso(SENT), _cap(),
                 state_doc={"private_start_odometer_km": 56000.0, **ANCHOR}, read_odo_km=_odo))
    assert st is None  # aucun faux PRIVATE
