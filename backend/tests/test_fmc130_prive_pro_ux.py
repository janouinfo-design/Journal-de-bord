"""Finition UX boutons Privé / Professionnel (FMC130) — sans nouveau test terrain.

Le matériel et le chemin device sont validés (privatemode ON/OFF PASS). Ce module
vérifie UNIQUEMENT la finition applicative demandée :

  1. Après envoi RÉEL, la réponse porte un message honnête :
       PRIVATE  -> « Commande Privé envoyée »
       BUSINESS -> « Commande Professionnel envoyée »
  2. Aucun faux « actif » : un envoi non confirmé reste PENDING_CONFIRMATION
     (jamais PRIVATE/BUSINESS d'office).
  3. Récupération rapide TOUJOURS possible : demander Professionnel pendant un
     PRIVATE en attente est ACCEPTÉ (supersede), pas refusé (transition_in_progress).
  4. Pas de verrou UX de 5 min : double-tap sur la MÊME cible ne renvoie pas de
     commande (idempotent pending), mais ne bloque pas la cible opposée.
  5. Fail-closed préservé : feature OFF / kill switch / DEVICE_WRITE=0 refusent.

Hooks device/odomètre MOCKÉS. Aucun appel réseau, aucune commande device réelle,
aucun secret. DB fake en mémoire.
"""
from __future__ import annotations

import asyncio
import os as _os

from app import private_mode_engine as pm
from app import private_mode_gate as _gate
from app import integrations as _integrations
from app.odometer_capability import (
    VehicleOdometerCapability, SOURCE_TELTONIKA_TOTAL_ODOMETER,
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


_ORIG_GET_CRED = _integrations.get_integration_credential


def setup_module(_m):
    _os.environ["PRIVATE_MODE_ENABLED"] = "1"
    _os.environ["PRIVATE_MODE_PILOT_TENANTS"] = "default"
    _os.environ["PRIVATE_MODE_PILOT_TRACKERS"] = "781479"
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"  # machine à états testée (hooks mockés)

    def _stub(tenant_id=None, provider="NAVIXY"):
        if tenant_id == "default" and provider == "NAVIXY":
            return {"credential": "STUB", "source": "TENANT", "api_url": None}
        return None
    _integrations.get_integration_credential = _stub
    _gate.get_integration_credential = _stub


def teardown_module(_m):
    for k in ("PRIVATE_MODE_ENABLED", "PRIVATE_MODE_PILOT_TENANTS",
              "PRIVATE_MODE_PILOT_TRACKERS", "PRIVATE_MODE_DEVICE_WRITE"):
        _os.environ.pop(k, None)
    _integrations.get_integration_credential = _ORIG_GET_CRED


FIELD_VALIDATED_VC = VehicleOdometerCapability(
    vehicle_id="vA", tracker_id=781479, device_model="FMC130",
    private_distance_source=SOURCE_TELTONIKA_TOTAL_ODOMETER, raw_avl_id=AVL_TOTAL_ODOMETER,
    navixy_input="avl_io_16", scale_status=SCALE_VERIFIED,
    private_confirmation_strategy=pm.CONFIRM_STRATEGY_LAST_KNOWN_POSITION,
    runtime_verified=True, cumulative_verified=True,
    private_increment_verified=True, field_validated=True)


def _db():
    db = _DB()
    _run(db.vehicles.update_one({"id": "vA"},
         {"$set": {"id": "vA", "tenant_id": "default", "model": "telfmu130_fmc130",
                   "navixy_tracker_id": 781479, "plate": "GE-AUDI",
                   "private_mode_pilot": True}}, upsert=True))
    _run(pm.upsert_vehicle_capability(db, FIELD_VALIDATED_VC))
    return db


async def _session_ok(db, driver_id):
    return {"vehicle_id": "vA", "driver_id": driver_id}


def _real_command():
    """Commande RÉELLE (mode REAL) -> déclenche le flux PENDING quand non confirmée."""
    async def _c(tid, cmd):
        assert "privatemode" in cmd and "11000" not in cmd  # jamais Deep Sleep
        return {"applied": True, "mode": "REAL", "command": cmd,
                "navixy_command_id": 4242}
    return _c


def _confirm(state):
    async def _cf(tid, expected):
        return (expected if state == "ok" else None), pm.SRC_TELEMETRY
    return _cf


def _odo(v):
    async def _r(tid):
        return v
    return _r


# --------------------------------------------------------------------------
# 1. Message métier honnête après envoi RÉEL
# --------------------------------------------------------------------------
def test_private_request_message_commande_prive_envoyee():
    db = _db()
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_real_command(), confirm=_confirm("no"),
               read_odo_km=_odo(56000.0), tenant_id="default"))
    assert res["ok"] is True
    assert res["state"] == pm.PENDING_CONFIRMATION      # jamais un faux "actif"
    assert res["message"] == "Commande Privé envoyée"
    assert res["command_label"] == "Privé"


def test_business_request_message_commande_professionnel_envoyee():
    db = _db()
    # part de PRIVATE confirmé pour que BUSINESS ne soit pas idempotent
    _run(db.private_mode_state.update_one({"vehicle_id": "vA"},
         {"$set": {"vehicle_id": "vA", "tenant_id": "default", "state": pm.PRIVATE}},
         upsert=True))
    res = _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
               send_command=_real_command(), confirm=_confirm("no"),
               read_odo_km=_odo(56010.0), tenant_id="default"))
    assert res["ok"] is True
    assert res["state"] == pm.PENDING_CONFIRMATION
    assert res["message"] == "Commande Professionnel envoyée"
    assert res["command_label"] == "Professionnel"


def test_confirmed_immediate_also_carries_message():
    """Confirmation immédiate -> état cible + message « envoyée » (jamais un jargon)."""
    db = _db()
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_real_command(), confirm=_confirm("ok"),
               read_odo_km=_odo(56000.0), tenant_id="default"))
    assert res["ok"] is True and res["state"] == pm.PRIVATE
    assert res["message"] == "Commande Privé envoyée"


# --------------------------------------------------------------------------
# 2. Aucun faux « actif »
# --------------------------------------------------------------------------
def test_pending_never_reports_active_state():
    db = _db()
    res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
               send_command=_real_command(), confirm=_confirm("no"),
               read_odo_km=_odo(56000.0), tenant_id="default"))
    assert res["state"] not in (pm.PRIVATE, pm.BUSINESS)
    st = _run(pm.get_mode_state(db, "vA"))
    assert st["state"] == pm.PENDING_CONFIRMATION


# --------------------------------------------------------------------------
# 3. Récupération rapide (supersede) TOUJOURS possible
# --------------------------------------------------------------------------
def test_business_recovery_allowed_during_private_pending():
    """Professionnel demandé pendant un PRIVATE en attente -> ACCEPTÉ (supersede)."""
    db = _db()
    # 1) PRIVATE -> PENDING
    r1 = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
              send_command=_real_command(), confirm=_confirm("no"),
              read_odo_km=_odo(56000.0), tenant_id="default"))
    assert r1["state"] == pm.PENDING_CONFIRMATION
    # 2) BUSINESS pendant le pending PRIVATE -> doit être accepté, PAS refusé
    r2 = _run(pm.request_mode(db, "d1", pm.BUSINESS, "d1@x", resolve_session=_session_ok,
              send_command=_real_command(), confirm=_confirm("no"),
              read_odo_km=_odo(56000.0), tenant_id="default"))
    assert r2["ok"] is True
    assert r2.get("reason") != _gate.R_TRANSITION_IN_PROGRESS
    assert r2["message"] == "Commande Professionnel envoyée"


def test_same_target_double_tap_is_idempotent_pending_no_respend():
    """Double-tap Privé pendant le pending Privé -> pas de nouvelle commande device."""
    db = _db()
    _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
         send_command=_real_command(), confirm=_confirm("no"),
         read_odo_km=_odo(56000.0), tenant_id="default"))

    def _forbid():
        async def _c(tid, cmd):
            raise AssertionError("aucune commande device ne doit repartir sur double-tap")
        return _c

    r2 = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
              send_command=_forbid(), confirm=_confirm("no"),
              read_odo_km=_odo(56000.0), tenant_id="default"))
    assert r2["ok"] is True
    assert r2["state"] == pm.PENDING_CONFIRMATION
    assert r2["message"] == "Commande Privé envoyée"


# --------------------------------------------------------------------------
# 5. Fail-closed préservé
# --------------------------------------------------------------------------
def test_fail_closed_device_write_disabled():
    db = _db()
    _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "0"
    try:
        def _forbid():
            async def _c(tid, cmd):
                raise AssertionError("aucune commande avec DEVICE_WRITE=0")
            return _c
        res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
                   send_command=_forbid(), confirm=_confirm("ok"),
                   read_odo_km=_odo(56000.0), tenant_id="default"))
        assert res["ok"] is False
        assert res["reason"] == _gate.R_DEVICE_WRITE_DISABLED
        assert res["can_switch"] is False
        # aucun état transitoire créé
        st = _run(pm.get_mode_state(db, "vA"))
        assert st["state"] != pm.PENDING_CONFIRMATION
    finally:
        _os.environ["PRIVATE_MODE_DEVICE_WRITE"] = "1"


def test_fail_closed_feature_disabled():
    db = _db()
    _os.environ["PRIVATE_MODE_ENABLED"] = "0"
    try:
        res = _run(pm.request_mode(db, "d1", pm.PRIVATE, "d1@x", resolve_session=_session_ok,
                   send_command=_real_command(), confirm=_confirm("ok"),
                   read_odo_km=_odo(56000.0), tenant_id="default"))
        assert res["ok"] is False and res["allowed"] is False
        assert res["reason"] == _gate.R_FEATURE_DISABLED
    finally:
        _os.environ["PRIVATE_MODE_ENABLED"] = "1"
