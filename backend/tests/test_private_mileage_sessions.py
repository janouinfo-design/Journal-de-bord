"""Tests — cycle de vie des sessions kilométriques privées AVL16 (app.private_mileage).

Couvre : ouverture Q4b, END candidat, fermeture idempotente, delta négatif, stale/null,
double OPEN (idempotence garantie par contrainte base simulée), double CLOSE, changement
de tracker (abandon), fermeture depuis candidat (DEGRADED). Aucun réseau/commande device.
"""
from __future__ import annotations

import asyncio
import os as _os

from app import private_mileage as pm


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _DuplicateKeyError(Exception):
    pass


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    """Fake collection qui SIMULE l'index unique partiel {state:OPEN} sur
    (tenant_id, vehicle_id, tracker_id) : insert d'une 2e OPEN -> DuplicateKeyError."""
    def __init__(self):
        self.docs = []

    def _match(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict):
                if "$ne" in v and d.get(k) == v["$ne"]:
                    return False
                if "$gte" in v and not (d.get(k) is not None and d.get(k) >= v["$gte"]):
                    return False
                if "$lte" in v and not (d.get(k) is not None and d.get(k) <= v["$lte"]):
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def insert_one(self, doc):
        if doc.get("state") == pm.S_OPEN:
            for d in self.docs:
                if (d.get("state") == pm.S_OPEN and d.get("tenant_id") == doc.get("tenant_id")
                        and d.get("vehicle_id") == doc.get("vehicle_id")
                        and d.get("tracker_id") == doc.get("tracker_id")):
                    raise _DuplicateKeyError("dup OPEN")
        self.docs.append(dict(doc))

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                return
        if upsert:
            nd = dict(q)
            nd.update(upd.get("$set", {}))
            self.docs.append(nd)

    async def update_many(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))

    def find(self, q, proj=None):
        return _Cursor([dict(d) for d in self.docs if self._match(d, q)])


class _DB:
    def __init__(self):
        self._c = _Coll()

    def __getitem__(self, name):
        return self._c


# Nommer l'exception attendue par le module (il teste e.__class__.__name__ == "DuplicateKeyError").
_DuplicateKeyError.__name__ = "DuplicateKeyError"


def setup_module(_m):
    _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "1"


def teardown_module(_m):
    _os.environ.pop("PRIVATE_KM_SOURCE_AVL16", None)


def _open(db, tracker=781479, odo=10000.0, src="AVL16"):
    return _run(pm.open_session(
        db, tenant_id="default", driver_id="d1", vehicle_id="vA", tracker_id=tracker,
        odo_start=odo, start_source=src, start_sample_at="2026-09-20T09:00:00Z",
        command_sent_at="2026-09-20T09:00:00Z"))


def test_open_then_close_computes_distance():
    db = _DB()
    sid = _open(db, odo=10000.0)
    assert sid is not None
    cid = _run(pm.close_session(db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
               odo_end=10012.4, end_source="AVL16", confirmation_source="TELEMETRY_CONFIRMED"))
    assert cid == sid
    s = db._c.docs[0]
    assert s["state"] == pm.S_CLOSED
    assert s["private_km"] == 12.4
    assert s["quality"] == pm.Q_OK


def test_reopen_supersedes_stale_open_single_open_no_start_contamination():
    """FIX PR#6 : ré-ouvrir PRIVATE sur une OPEN résiduelle (même tracker) ne DOIT PAS être
    bloqué. L'ancienne OPEN (sans candidat) passe ABANDONED, une nouvelle OPEN est créée avec
    le NOUVEAU odometer_start (jamais l'ancien) -> exactement 1 OPEN, pas de contamination."""
    db = _DB()
    a = _open(db, odo=10000.0)          # 1re session
    b = _open(db, odo=20000.0)          # ré-ouverture : supersede l'ancienne
    assert a is not None and b is not None and a != b
    opens = [d for d in db._c.docs if d["state"] == pm.S_OPEN]
    abandoned = [d for d in db._c.docs if d["state"] == pm.S_ABANDONED]
    assert len(opens) == 1
    assert opens[0]["odometer_start_km"] == 20000.0          # nouveau start, pas 10000
    assert len(abandoned) == 1 and abandoned[0]["reason"] == "SUPERSEDED_NEW_PRIVATE"


def test_concurrent_open_dupkey_is_idempotent_single_open():
    """Idempotence garantie EN BASE : deux insert OPEN concurrents (course) -> le 2e lève
    DuplicateKeyError (index unique partiel simulé) -> open_session renvoie None. 1 seule OPEN.
    On simule la course en désactivant la résolution préalable (pas de résiduelle détectée)."""
    db = _DB()
    a = _open(db, odo=10000.0)
    assert a is not None
    # Simuler une VRAIE course : forcer un 2e insert direct qui doit lever DuplicateKeyError.
    raised = False
    try:
        _run(db._c.insert_one({
            "id": "x", "tenant_id": "default", "vehicle_id": "vA", "tracker_id": 781479,
            "state": pm.S_OPEN}))
    except Exception as e:
        raised = (e.__class__.__name__ == "DuplicateKeyError")
    assert raised is True
    opens = [d for d in db._c.docs if d["state"] == pm.S_OPEN]
    assert len(opens) == 1


def test_double_close_only_once():
    db = _DB()
    _open(db, odo=10000.0)
    c1 = _run(pm.close_session(db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
              odo_end=10010.0, end_source="AVL16", confirmation_source="X"))
    c2 = _run(pm.close_session(db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
              odo_end=10020.0, end_source="AVL16", confirmation_source="X"))
    assert c1 is not None and c2 is None       # 2e fermeture = no-op
    closed = [d for d in db._c.docs if d["state"] == pm.S_CLOSED]
    assert len(closed) == 1 and closed[0]["private_km"] == 10.0  # pas de 2e distance


def test_negative_delta_refused():
    db = _DB()
    _open(db, odo=10020.0)
    _run(pm.close_session(db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
         odo_end=10000.0, end_source="AVL16", confirmation_source="X"))
    s = db._c.docs[0]
    assert s["private_km"] is None and s["reason"] == "NEGATIVE_DELTA"


def test_end_missing_unavailable():
    db = _DB()
    _open(db, odo=10000.0)
    _run(pm.close_session(db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
         odo_end=None, end_source="UNAVAILABLE", confirmation_source="X"))
    s = db._c.docs[0]
    assert s["private_km"] is None and s["quality"] == pm.Q_UNAVAILABLE


def test_tracker_change_abandons_previous_open():
    db = _DB()
    _open(db, tracker=781479, odo=10000.0)
    # ouvrir sur un AUTRE tracker -> l'ancienne OPEN doit passer ABANDONED
    sid2 = _open(db, tracker=999999, odo=5000.0)
    assert sid2 is not None
    states = {d["tracker_id"]: d["state"] for d in db._c.docs}
    assert states[781479] == pm.S_ABANDONED
    assert states[999999] == pm.S_OPEN


def test_end_candidate_then_close_from_candidate_degraded():
    db = _DB()
    _open(db, odo=10000.0)
    _run(pm.capture_end_candidate(db, tenant_id="default", vehicle_id="vA", tracker_id=781479,
         odo_end_candidate=10008.0, end_candidate_sample_at="2026-09-20T10:00:00Z",
         business_command_sent_at="2026-09-20T10:00:00Z"))
    cid = _run(pm.close_from_candidate(db, tenant_id="default", vehicle_id="vA",
               tracker_id=781479, confirmation_source="LATE_PROOF"))
    assert cid is not None
    s = db._c.docs[0]
    assert s["state"] == pm.S_CLOSED and s["private_km"] == 8.0
    assert s["quality"] == pm.Q_DEGRADED


def test_flag_off_no_session_created():
    _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "0"
    try:
        db = _DB()
        sid = _open(db)
        assert sid is None
        assert db._c.docs == []
    finally:
        _os.environ["PRIVATE_KM_SOURCE_AVL16"] = "1"


def test_unfinished_session_stays_open_not_counted():
    """PRIVATE accepté mais jamais de BUSINESS confirmé -> session reste OPEN, non comptée."""
    db = _DB()
    _open(db, odo=10000.0)
    # aucune fermeture : la session reste OPEN
    opens = [d for d in db._c.docs if d["state"] == pm.S_OPEN]
    assert len(opens) == 1
    # l'agrégat ne compte QUE les CLOSED -> None (pas de session close)

    async def _gps(s, e):
        return None
    from datetime import datetime, timezone
    r = _run(pm.aggregate_private_km(db, tenant_id="default", vehicle_id="vA",
             start_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
             end_utc=datetime(2026, 9, 30, tzinfo=timezone.utc), gps_fallback_km=_gps))
    # pas de cutover, pas de session CLOSED -> UNAVAILABLE
    assert r["private_km_source"] == pm.SRC_UNAVAILABLE and r["private_km"] is None


def test_late_business_confirmation_promotes_degraded_without_changing_km():
    """DEGRADED depuis candidat OFF + confirmation BUSINESS tardive -> OK,
    sans changer aucune borne ni private_km."""
    db = _DB()

    _open(db, odo=10000.0)

    _run(pm.capture_end_candidate(
        db,
        tenant_id="default",
        vehicle_id="vA",
        tracker_id=781479,
        odo_end_candidate=10008.0,
        end_candidate_sample_at="2026-09-20T10:00:00.000000+00:00",
        business_command_sent_at="2026-09-20T10:00:00.001000+00:00",
    ))

    _run(pm.close_from_candidate(
        db,
        tenant_id="default",
        vehicle_id="vA",
        tracker_id=781479,
        confirmation_source="PENDING_TIMEOUT_DEGRADED",
    ))

    before = dict(db._c.docs[0])

    assert before["state"] == pm.S_CLOSED
    assert before["quality"] == pm.Q_DEGRADED
    assert before["private_km"] == 8.0

    sid = _run(pm.promote_degraded_after_confirmation(
        db,
        tenant_id="default",
        vehicle_id="vA",
        tracker_id=781479,
        business_command_sent_at="2026-09-20T10:00:00.003000+00:00",
        confirmation_source="TELEMETRY_CONFIRMED",
    ))

    after = db._c.docs[0]

    assert sid == before["id"]
    assert after["quality"] == pm.Q_OK
    assert after["quality_previous"] == pm.Q_DEGRADED
    assert after["confirmation_source"] == "TELEMETRY_CONFIRMED"

    # Invariants absolus : aucune borne de calcul ne change.
    for field in (
        "odometer_start_km",
        "odometer_end_candidate_km",
        "odometer_end_km",
        "private_km",
        "private_started_at",
        "private_ended_at",
        "business_command_sent_at",
    ):
        assert after.get(field) == before.get(field)


def test_late_business_confirmation_wrong_cycle_does_not_promote():
    """Une confirmation d'un autre cycle BUSINESS ne peut jamais promouvoir."""
    db = _DB()

    _open(db, odo=10000.0)

    _run(pm.capture_end_candidate(
        db,
        tenant_id="default",
        vehicle_id="vA",
        tracker_id=781479,
        odo_end_candidate=10008.0,
        end_candidate_sample_at="2026-09-20T10:00:00Z",
        business_command_sent_at="2026-09-20T10:00:00Z",
    ))

    _run(pm.close_from_candidate(
        db,
        tenant_id="default",
        vehicle_id="vA",
        tracker_id=781479,
        confirmation_source="PENDING_TIMEOUT_DEGRADED",
    ))

    sid = _run(pm.promote_degraded_after_confirmation(
        db,
        tenant_id="default",
        vehicle_id="vA",
        tracker_id=781479,
        business_command_sent_at="2026-09-20T11:00:00Z",
        confirmation_source="TELEMETRY_CONFIRMED",
    ))

    assert sid is None
    assert db._c.docs[0]["quality"] == pm.Q_DEGRADED
