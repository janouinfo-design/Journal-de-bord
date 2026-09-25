"""PR26 — récupération tardive PRIVATE par réponse device explicite uniquement.

Régression terrain FMC130 781479 (25.09.2026):
- commande privatemode ON envoyée;
- PENDING dépasse 300 s -> UNKNOWN/TIMEOUT;
- réponse device explicite "Privatemode ON" arrive ~6 min après la commande;
- l'ancien moteur ne retentait plus PRIVATE après timeout.

Règle PR26, fail-closed:
- UNKNOWN/TIMEOUT + requested_target=PRIVATE peut être promu tardivement
  UNIQUEMENT par une réponse device textuelle explicite postérieure à la commande;
- success=true seul, GPS, AVL16, absence de position ou réponse OFF ne suffisent jamais;
- fenêtre bornée par ASYNC_CONFIRM_MAX_S;
- aucune commande device n'est envoyée par le resolver.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from app import private_mode_engine as pm


VEHICLE_ID = "vA"
TRACKER_ID = 781479
TENANT = "default"


def _run(coro):
    """Compat avec les suites legacy qui réutilisent la loop par défaut."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _Coll:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                d.update(update.get("$set", {}))
                return
        if upsert:
            d = dict(query)
            d.update(update.get("$set", {}))
            self.docs.append(d)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


class _DB:
    def __init__(self, state_doc):
        self.private_mode_state = _Coll([state_doc])
        self.audit_log = _Coll()


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _timed_out_private(*, sent=None):
    sent = sent or (datetime.now(timezone.utc) - timedelta(minutes=6))
    return {
        "vehicle_id": VEHICLE_ID,
        "tenant_id": TENANT,
        "tracker_id": TRACKER_ID,
        "state": pm.UNKNOWN,
        "requested_target": pm.PRIVATE,
        "transition_result": pm.TRANSITION_TIMEOUT,
        "confirmation_source": pm.SRC_UNCONFIRMED,
        "command_sent_at": _iso(sent),
        "pending_timeout_at": _iso(sent + timedelta(seconds=pm.PENDING_TIMEOUT_S)),
        "awaiting_async_confirm": False,
        "private_start_odometer_km": 57916.0,
    }


def _device_entry(at, body=None, *, success=None):
    response = {}
    if body is not None:
        response["body"] = body
    if success is not None:
        response["success"] = success
    return {
        "time": _iso(at),
        "extra": {
            "command": {
                "response": response,
            }
        },
    }


def test_late_private_promoted_by_explicit_device_on():
    """Terrain: ON explicite arrive après le timeout -> PRIVATE / CONFIRMED_LATE."""
    sent = datetime.now(timezone.utc) - timedelta(minutes=6)
    db = _DB(_timed_out_private(sent=sent))

    async def _history(tenant_id, tracker_id, since_iso):
        assert tenant_id == TENANT
        assert tracker_id == TRACKER_ID
        assert since_iso == _iso(sent)
        return [_device_entry(sent + timedelta(minutes=5, seconds=58), "Privatemode ON")]

    out = _run(pm.resolve_pending_confirmation(
        db, VEHICLE_ID, TENANT, fetch_command_responses=_history))

    assert out["state"] == pm.PRIVATE
    assert out["requested_target"] is None
    assert out["transition_result"] == pm.TRANSITION_CONFIRMED_LATE
    assert out["confirmation_source"] == pm.SRC_DEVICE_RESPONSE
    assert out["confirmed_at"] is not None


def test_late_private_refuses_success_true_without_device_text():
    """success=true seul signifie commande envoyée, jamais mode confirmé."""
    sent = datetime.now(timezone.utc) - timedelta(minutes=6)
    db = _DB(_timed_out_private(sent=sent))

    async def _history(*_args):
        return [_device_entry(sent + timedelta(minutes=5, seconds=30),
                              body=None, success=True)]

    out = _run(pm.resolve_pending_confirmation(
        db, VEHICLE_ID, TENANT, fetch_command_responses=_history))

    assert out["state"] == pm.UNKNOWN
    assert out["transition_result"] == pm.TRANSITION_TIMEOUT
    assert out["requested_target"] == pm.PRIVATE
    assert out["confirmation_source"] == pm.SRC_UNCONFIRMED


def test_late_private_never_uses_gps_or_avl16(monkeypatch):
    """Après timeout PRIVATE, GPS/AVL16 ne sont jamais consultés comme preuve tardive."""
    sent = datetime.now(timezone.utc) - timedelta(minutes=6)
    db = _DB(_timed_out_private(sent=sent))

    async def _history(*_args):
        return []

    async def _gps_forbidden(*_args, **_kwargs):
        raise AssertionError("late PRIVATE must not use GPS telemetry")

    async def _odo_forbidden(*_args, **_kwargs):
        raise AssertionError("late PRIVATE must not use AVL16")

    monkeypatch.setattr(pm, "_fetch_gps_state", _gps_forbidden)

    out = _run(pm.resolve_pending_confirmation(
        db, VEHICLE_ID, TENANT,
        read_odo_km=_odo_forbidden,
        fetch_command_responses=_history))

    assert out["state"] == pm.UNKNOWN
    assert out["requested_target"] == pm.PRIVATE


def test_late_private_refuses_stale_on_before_command():
    """Une ancienne réponse ON antérieure à la commande courante est rejetée."""
    sent = datetime.now(timezone.utc) - timedelta(minutes=6)
    db = _DB(_timed_out_private(sent=sent))

    async def _history(*_args):
        return [_device_entry(sent - timedelta(minutes=2), "Privatemode ON")]

    out = _run(pm.resolve_pending_confirmation(
        db, VEHICLE_ID, TENANT, fetch_command_responses=_history))

    assert out["state"] == pm.UNKNOWN
    assert out["confirmation_source"] == pm.SRC_UNCONFIRMED


def test_late_private_refuses_explicit_off():
    """La réponse opposée Privatemode OFF ne peut jamais confirmer PRIVATE."""
    sent = datetime.now(timezone.utc) - timedelta(minutes=6)
    db = _DB(_timed_out_private(sent=sent))

    async def _history(*_args):
        return [_device_entry(sent + timedelta(minutes=5), "Privatemode OFF")]

    out = _run(pm.resolve_pending_confirmation(
        db, VEHICLE_ID, TENANT, fetch_command_responses=_history))

    assert out["state"] == pm.UNKNOWN
    assert out["requested_target"] == pm.PRIVATE


def test_late_private_window_expired_does_not_query_history():
    """Hors ASYNC_CONFIRM_MAX_S : aucune recherche history, état reste UNKNOWN."""
    sent = datetime.now(timezone.utc) - timedelta(seconds=pm.ASYNC_CONFIRM_MAX_S + 60)
    db = _DB(_timed_out_private(sent=sent))

    async def _history_forbidden(*_args):
        raise AssertionError("history must not be queried after late-confirm window")

    out = _run(pm.resolve_pending_confirmation(
        db, VEHICLE_ID, TENANT, fetch_command_responses=_history_forbidden))

    assert out["state"] == pm.UNKNOWN
    assert out["transition_result"] == pm.TRANSITION_TIMEOUT
    assert out["requested_target"] == pm.PRIVATE
