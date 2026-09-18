import asyncio
from types import SimpleNamespace

import app.private_mode_engine as pm


TRACKER = 781479
TENANT = "default"
SENT = "2026-09-11T15:37:30+00:00"


def run(coro):
    # Compatibilité avec les tests legacy du projet qui utilisent ensuite
    # asyncio.get_event_loop().run_until_complete(...).
    # Ne pas utiliser asyncio.run() ici : il ferme la boucle courante sous Python 3.11.
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def capability():
    return SimpleNamespace(
        field_validated=True,
        device_model="FMC130",
        private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
    )


async def no_device_response(*args, **kwargs):
    return []


async def no_samples(*args, **kwargs):
    return []


def base_state():
    return {
        "private_start_odometer_km": 56771.93,
        "private_gps_anchor_lat": 46.5452133,
        "private_gps_anchor_lng": 6.5890816,
    }


def install_gps(monkeypatch, *, lat, lng, updated, moving=False, ignition=False,
                connection_status="active"):
    async def fake_gps(*args, **kwargs):
        return {
            "lat": lat,
            "lng": lng,
            "gps_updated": updated,
            "movement_status": "moving" if moving else "stopped",
            "ignition": ignition,
            "speed": 0,
            "connection_status": connection_status,
        }

    monkeypatch.setattr(pm, "_fetch_gps_state", fake_gps)
    monkeypatch.setattr(pm, "LKP_NOSAMPLE_MIN_DELTA_KM", 0.2)
    monkeypatch.setattr(pm, "LKP_NOSAMPLE_MAX_RADIUS_M", 50.0)


def test_private_confirms_with_zero_samples_odo_progress_and_lkp(monkeypatch):
    # Reproduit le terrain du 11.09 :
    # +0.780 km AVL16, véhicule déjà arrêté lors de la résolution,
    # aucun sample Navixy, position ~quelques mètres de l'ancre.
    install_gps(
        monkeypatch,
        lat=46.5452700,
        lng=6.5892833,
        updated="2026-09-11T15:48:28+00:00",
        moving=False,
        ignition=False,
    )

    async def odo(_tracker):
        return 56772.71

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=no_samples,
        fetch_command_responses=no_device_response,
    ))

    assert state == pm.PRIVATE
    assert source == pm.SRC_TELEMETRY


def test_zero_samples_does_not_confirm_without_minimum_odo_delta(monkeypatch):
    install_gps(
        monkeypatch,
        lat=46.5452700,
        lng=6.5892833,
        updated="2026-09-11T15:48:28+00:00",
    )

    async def odo(_tracker):
        return 56772.00  # +0.07 km seulement

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=no_samples,
        fetch_command_responses=no_device_response,
    ))

    assert state is None
    assert source == pm.SRC_UNCONFIRMED


def test_zero_samples_does_not_confirm_if_position_left_anchor(monkeypatch):
    install_gps(
        monkeypatch,
        lat=46.5500000,
        lng=6.6000000,
        updated="2026-09-11T15:48:28+00:00",
    )

    async def odo(_tracker):
        return 56772.71

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=no_samples,
        fetch_command_responses=no_device_response,
    ))

    assert state is None
    assert source == pm.SRC_UNCONFIRMED


def test_zero_samples_stale_gps_can_confirm_with_large_odo_delta(monkeypatch):
    """Terrain réel : en PRIVATE la dernière position peut rester gelée avec
    gps.updated antérieur à la commande. AVL16 + connexion active + position
    proche de l'ancre constituent alors la preuve fail-closed renforcée."""
    install_gps(
        monkeypatch,
        lat=46.5452700,
        lng=6.5892833,
        updated="2026-09-11T15:30:00+00:00",
        connection_status="active",
    )

    async def odo(_tracker):
        return 56772.71  # +0.78 km > seuil stale renforcé

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=no_samples,
        fetch_command_responses=no_device_response,
    ))

    assert state == pm.PRIVATE
    assert source == pm.SRC_TELEMETRY


def test_zero_samples_stale_gps_rejects_small_odo_delta(monkeypatch):
    install_gps(
        monkeypatch,
        lat=46.5452700,
        lng=6.5892833,
        updated="2026-09-11T15:30:00+00:00",
        connection_status="active",
    )

    async def odo(_tracker):
        return 56772.25  # +0.32 km : > seuil normal 0.2, < seuil stale 0.5

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=no_samples,
        fetch_command_responses=no_device_response,
    ))

    assert state is None
    assert source == pm.SRC_UNCONFIRMED


def test_zero_samples_stale_gps_requires_active_connection(monkeypatch):
    install_gps(
        monkeypatch,
        lat=46.5452700,
        lng=6.5892833,
        updated="2026-09-11T15:30:00+00:00",
        connection_status="offline",
    )

    async def odo(_tracker):
        return 56772.71

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=no_samples,
        fetch_command_responses=no_device_response,
    ))

    assert state is None
    assert source == pm.SRC_UNCONFIRMED


def test_too_few_nonzero_samples_do_not_use_zero_sample_fallback(monkeypatch):
    install_gps(
        monkeypatch,
        lat=46.5452700,
        lng=6.5892833,
        updated="2026-09-11T15:48:28+00:00",
    )

    async def odo(_tracker):
        return 56772.71

    async def one_sample(*args, **kwargs):
        return [{
            "lat": 46.54527,
            "lng": 6.58928,
            "time": "2026-09-11T15:40:00+00:00",
        }]

    state, source = run(pm.telemetry_confirm(
        TENANT,
        TRACKER,
        pm.PRIVATE,
        SENT,
        capability(),
        state_doc=base_state(),
        read_odo_km=odo,
        fetch_samples=one_sample,
        fetch_command_responses=no_device_response,
    ))

    assert state is None
    assert source == pm.SRC_UNCONFIRMED
