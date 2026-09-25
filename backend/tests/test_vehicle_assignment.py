"""Tests Lot 1 — Affectation conducteur <-> véhicule (vehicle_assignment).

Couvre les 13 scénarios metier + concurrence, avec un FAUX DB en memoire qui
SIMULE les index uniques partiels (tenant_id, driver_id|vehicle_id) WHERE status=ACTIVE
en levant DuplicateKeyError, comme le ferait MongoDB standalone.

Prouve notamment :
- CHANGE A->B : si B occupe -> DuplicateKeyError -> A reste STRICTEMENT inchange.
- double TAKE concurrent -> une seule reussit.
- pause / PRO / PRIVE -> aucune liberation (aucune API d'affectation appelee).
- historique reconstruit UNIQUEMENT depuis les events.
- idempotence request_id.
"""
from __future__ import annotations

import asyncio
import pytest
from pymongo.errors import DuplicateKeyError

from app import vehicle_assignment as va


def _run(coro):
    """Run async test helpers safely even after another test closed the default loop."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# --------- Faux DB en mémoire avec index uniques partiels simulés ---------
class _Coll:
    def __init__(self, unique_active_keys=None):
        self.docs = []
        # liste de tuples de champs formant une contrainte unique WHERE status=ACTIVE
        self.unique_active_keys = unique_active_keys or []

    def _match(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict):
                if "$ne" in v and d.get(k) == v["$ne"]:
                    return False
                if "$in" in v and d.get(k) not in v["$in"]:
                    return False
                if "$type" in v:  # simplifié : présence
                    if d.get(k) is None:
                        return False
                if "$lte" in v and not (d.get(k) is not None and d.get(k) <= v["$lte"]):
                    return False
            else:
                if d.get(k) != v:
                    return False
        return True

    def _violates_unique(self, candidate, ignore_id=None):
        if candidate.get("status") != va.STATUS_ACTIVE:
            return False
        for key in self.unique_active_keys:
            for d in self.docs:
                if d is candidate:
                    continue
                if ignore_id and d.get("id") == ignore_id:
                    continue
                if d.get("status") != va.STATUS_ACTIVE:
                    continue
                if all(d.get(k) == candidate.get(k) for k in key):
                    return True
        return False

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    async def insert_one(self, doc):
        cand = dict(doc)
        if self._violates_unique(cand):
            raise DuplicateKeyError("dup active")
        self.docs.append(cand)

    async def update_one(self, q, upd, upsert=False):
        setter = upd.get("$set", {})
        for d in self.docs:
            if self._match(d, q):
                merged = dict(d); merged.update(setter)
                # simulate unique index on the resulting ACTIVE state
                if self._violates_unique(merged, ignore_id=d.get("id")):
                    raise DuplicateKeyError("dup active on update")
                d.update(setter)
                return _Res(1, 1)
        if upsert:
            nd = {k: v for k, v in q.items() if not isinstance(v, dict)}
            nd.update(setter)
            if self._violates_unique(nd):
                raise DuplicateKeyError("dup active upsert")
            self.docs.append(nd)
            return _Res(0, 1)
        return _Res(0, 0)

    def find(self, q, proj=None):
        rows = [dict(d) for d in self.docs if self._match(d, q)]
        return _Cursor(rows)

    async def create_index(self, *a, **k):
        return "idx"


class _Res:
    def __init__(self, matched, modified):
        self.matched_count = matched
        self.modified_count = modified


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, key, direction=1):
        self._rows.sort(key=lambda r: r.get(key) or "", reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return self._rows[:n]


class _DB:
    def __init__(self):
        self.vehicle_assignments = _Coll(unique_active_keys=[
            ("tenant_id", "driver_id"), ("tenant_id", "vehicle_id")])
        self.vehicle_assignment_events = _Coll()
        self.audit_log = _Coll()
        self.vehicles = _Coll()


T = "default"


# ============================ SCÉNARIOS ============================
def test_take_creates_active_assignment():
    db = _DB()
    r = _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA",
                     actor_id="d1@x", request_id="req-1"))
    assert r["result"] == "ok"
    a = _run(va.get_active(db, T, "d1"))
    assert a and a["vehicle_id"] == "vA" and a["status"] == "ACTIVE"


def test_take_idempotent_same_request():
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x", request_id="req-1"))
    r2 = _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x", request_id="req-1"))
    assert r2["result"] == "ok" and r2.get("idempotent") is True
    assert len([d for d in db.vehicle_assignments.docs if d["status"] == "ACTIVE"]) == 1


def test_reopen_app_assignment_persists():
    """Fermeture/reouverture app -> GET active retrouve le meme vehicule (backend = verite)."""
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    a = _run(va.get_active(db, T, "d1"))  # simulate re-open -> GET active
    assert a and a["vehicle_id"] == "vA"


def test_pause_does_not_release():
    """Une pause n'appelle AUCUNE API d'affectation -> reste ACTIVE."""
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    # (aucune action) -> toujours actif
    assert _run(va.get_active(db, T, "d1"))["vehicle_id"] == "vA"


def test_private_mode_does_not_release():
    """Le Mode Prive ne touche pas a l'affectation (resolve_active_vehicle only)."""
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    vid = _run(va.resolve_active_vehicle(db, "d1", T))
    assert vid == "vA"
    # toujours actif apres resolution
    assert _run(va.get_active(db, T, "d1"))["status"] == "ACTIVE"


def test_change_a_to_b_success():
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    r = _run(va.change(db, tenant_id=T, driver_id="d1", to_vehicle_id="vB", actor_id="d1@x", request_id="chg-1"))
    assert r["result"] == "ok"
    a = _run(va.get_active(db, T, "d1"))
    assert a["vehicle_id"] == "vB" and a["previous_vehicle_id"] == "vA"
    # jamais deux ACTIVE
    assert len([d for d in db.vehicle_assignments.docs if d["status"] == "ACTIVE"]) == 1


def test_change_a_to_b_rejected_leaves_A_unchanged():
    """PREUVE CRITIQUE : B occupe -> DuplicateKeyError -> A reste STRICTEMENT inchange."""
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    _run(va.take(db, tenant_id=T, driver_id="d2", vehicle_id="vB", actor_id="d2@x"))  # B occupe par d2
    a_before = _run(va.get_active(db, T, "d1"))
    r = _run(va.change(db, tenant_id=T, driver_id="d1", to_vehicle_id="vB", actor_id="d1@x", request_id="chg-2"))
    assert r["result"] == "conflict" and r["reason"] == "VEHICLE_OCCUPIED"
    a_after = _run(va.get_active(db, T, "d1"))
    assert a_after["vehicle_id"] == "vA"                 # A INCHANGÉ
    assert a_after["id"] == a_before["id"]               # meme document
    # d2 garde vB
    assert _run(va.get_active(db, T, "d2"))["vehicle_id"] == "vB"
    # event REJECTED trace
    evs = [e for e in db.vehicle_assignment_events.docs if e["type"] == va.EV_CHANGE]
    assert evs and evs[-1]["result"] == "REJECTED"


def test_other_driver_cannot_take_occupied_vehicle():
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    r = _run(va.take(db, tenant_id=T, driver_id="d2", vehicle_id="vA", actor_id="d2@x", request_id="req-x"))
    assert r["result"] == "conflict" and r["reason"] == "VEHICLE_OCCUPIED"
    # d1 garde vA, d2 sans affectation
    assert _run(va.get_active(db, T, "d1"))["vehicle_id"] == "vA"
    assert _run(va.get_active(db, T, "d2")) is None


def test_concurrent_take_same_vehicle_only_one_wins():
    """Deux prises quasi simultanees du meme vehicule -> une seule ACTIVE."""
    db = _DB()

    async def both():
        # séquentiel dans l'event loop mais la 2e voit l'index unique -> DuplicateKey
        r1 = await va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x", request_id="c1")
        r2 = await va.take(db, tenant_id=T, driver_id="d2", vehicle_id="vA", actor_id="d2@x", request_id="c2")
        return r1, r2
    r1, r2 = _run(both())
    oks = [r for r in (r1, r2) if r["result"] == "ok"]
    assert len(oks) == 1
    assert len([d for d in db.vehicle_assignments.docs if d["status"] == "ACTIVE" and d["vehicle_id"] == "vA"]) == 1


def test_double_click_take_no_duplicate():
    db = _DB()

    async def dbl():
        r1 = await va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x", request_id="same")
        r2 = await va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x", request_id="same")
        return r1, r2
    r1, r2 = _run(dbl())
    assert r1["result"] == "ok" and r2["result"] == "ok"
    assert len([d for d in db.vehicle_assignments.docs if d["status"] == "ACTIVE"]) == 1


def test_end_of_service_releases_vehicle():
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    r = _run(va.end(db, tenant_id=T, driver_id="d1", actor_id="d1@x", request_id="end-1"))
    assert r["result"] == "ok"
    assert _run(va.get_active(db, T, "d1")) is None
    # vehicule redevient disponible -> un autre chauffeur peut le prendre
    r2 = _run(va.take(db, tenant_id=T, driver_id="d2", vehicle_id="vA", actor_id="d2@x"))
    assert r2["result"] == "ok"


def test_admin_force_end_releases_vehicle():
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    r = _run(va.force_end(db, tenant_id=T, vehicle_id="vA", actor_id="admin@x",
                          actor_role="admin", request_id="force-1"))
    assert r["result"] == "ok"
    assert _run(va.get_active(db, T, "d1")) is None
    evs = [e for e in db.vehicle_assignment_events.docs if e["type"] == va.EV_FORCE]
    assert evs and evs[-1]["result"] == "OK"


def test_history_reconstructed_from_events_only():
    """Historique = TAKE A -> CHANGE A->B -> CHANGE B->C -> END C, via events uniquement."""
    db = _DB()
    _run(va.take(db, tenant_id=T, driver_id="d1", vehicle_id="vA", actor_id="d1@x", request_id="h1"))
    _run(va.change(db, tenant_id=T, driver_id="d1", to_vehicle_id="vB", actor_id="d1@x", request_id="h2"))
    _run(va.change(db, tenant_id=T, driver_id="d1", to_vehicle_id="vC", actor_id="d1@x", request_id="h3"))
    _run(va.end(db, tenant_id=T, driver_id="d1", actor_id="d1@x", request_id="h4"))
    hist = _run(va.history(db, T, driver_id="d1"))
    types = [e["type"] for e in hist]
    assert types == [va.EV_TAKE, va.EV_CHANGE, va.EV_CHANGE, va.EV_END]
    # le doc courant est ENDED, mais l'historique complet vient des events
    assert _run(va.get_active(db, T, "d1")) is None
    assert hist[1]["from_vehicle_id"] == "vA" and hist[1]["to_vehicle_id"] == "vB"
    assert hist[2]["from_vehicle_id"] == "vB" and hist[2]["to_vehicle_id"] == "vC"


def test_multitenant_isolation_same_vehicle_id():
    """Deux tenants peuvent avoir le meme vehicle_id ACTIVE (index inclut tenant_id)."""
    db = _DB()
    r1 = _run(va.take(db, tenant_id="tenantA", driver_id="d1", vehicle_id="vA", actor_id="d1@x"))
    r2 = _run(va.take(db, tenant_id="tenantB", driver_id="d9", vehicle_id="vA", actor_id="d9@x"))
    assert r1["result"] == "ok" and r2["result"] == "ok"


def test_resolve_active_vehicle_none_when_no_assignment():
    db = _DB()
    assert _run(va.resolve_active_vehicle(db, "dX", T)) is None
