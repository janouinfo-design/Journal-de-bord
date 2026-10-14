"""
Tests — resolve_driver_for_trip : règle d'identité time-aware + FAIL-CLOSED.

Garde-fou : la résolution ne repose QUE sur des relations valides (fenêtre datée
couvrant le trajet, ou primary). Jamais de repli arbitraire sur asgs[0].
Les noms/plaques/emails ne doivent JAMAIS intervenir (test ne les utilise pas).
"""
import asyncio
from app import assignments as A


class _FakeColl:
    def __init__(self, docs): self.docs = docs
    def find(self, q=None, proj=None):
        q = q or {}
        def _match(d):
            for k, v in q.items():
                if isinstance(v, dict):
                    continue
                if d.get(k) != v:
                    return False
            return True
        res = [d for d in self.docs if _match(d)]
        class _Cur:
            def __init__(s, items): s.items = items
            def sort(s, *a, **k):
                s.items = sorted(s.items, key=lambda x: x.get("from_date") or "", reverse=True)
                return s
            def to_list(s, n):
                async def g(): return list(s.items)
                return g()
        return _Cur(res)


class _FakeDB:
    def __init__(self, assignments): self.assignments = _FakeColl(assignments)


def _run(assignments, vehicle_id, trip_iso):
    # Les docs de test reçoivent tenant_id=default (comme en base) pour matcher
    # le filtre de list_assignments ({tenant_id, vehicle_id}).
    # Volet 2 : ce fichier valide le RESOLVER LEGACY V1 (comportement historique
    # INCHANGÉ). On cible donc explicitement `_resolve_driver_for_trip_v1`, qui est
    # la fonction utilisée par `reassign_all_trips()`. Le resolver moderne V2
    # (`resolve_driver_for_trip`) est testé séparément dans test_resolve_driver_v2.py.
    docs = [{**a, "tenant_id": "default"} for a in assignments]
    db = _FakeDB(docs)
    return asyncio.run(A._resolve_driver_for_trip_v1(db, vehicle_id, trip_iso))


def test_fail_closed_no_window_no_primary_returns_none():
    # Affectation existante NON-primary mais hors fenêtre + AUCUN primary -> None.
    asg = [{"vehicle_id": "v1", "driver_id": "dOLD", "is_primary": False,
            "from_date": "2026-01-01T00:00:00+00:00", "to_date": "2026-01-31T00:00:00+00:00"}]
    # trajet en octobre, hors fenêtre janvier, pas de primary
    assert _run(asg, "v1", "2026-10-06T15:21:30+00:00") is None


def test_dated_window_match_wins():
    asg = [{"vehicle_id": "v1", "driver_id": "dWIN", "is_primary": False,
            "from_date": "2026-10-01T00:00:00+00:00", "to_date": None}]
    assert _run(asg, "v1", "2026-10-06T15:21:30+00:00") == "dWIN"


def test_primary_used_when_no_dated_window():
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": None, "to_date": None}]
    assert _run(asg, "v1", "2026-10-06T15:21:30+00:00") == "dPRIM"


def test_dated_window_overrides_primary():
    asg = [
        {"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
         "from_date": None, "to_date": None},
        {"vehicle_id": "v1", "driver_id": "dWIN", "is_primary": False,
         "from_date": "2026-10-05T00:00:00+00:00", "to_date": "2026-10-10T00:00:00+00:00"},
    ]
    assert _run(asg, "v1", "2026-10-06T15:21:30+00:00") == "dWIN"


def test_no_assignment_returns_none():
    assert _run([], "v1", "2026-10-06T15:21:30+00:00") is None


def test_never_falls_back_to_first_arbitrary():
    # Deux affectations non-primary HORS fenêtre, aucun primary -> None (jamais asgs[0]).
    asg = [
        {"vehicle_id": "v1", "driver_id": "dA", "is_primary": False,
         "from_date": "2026-01-01T00:00:00+00:00", "to_date": "2026-01-31T00:00:00+00:00"},
        {"vehicle_id": "v1", "driver_id": "dB", "is_primary": False,
         "from_date": "2026-02-01T00:00:00+00:00", "to_date": "2026-02-28T00:00:00+00:00"},
    ]
    assert _run(asg, "v1", "2026-10-06T15:21:30+00:00") is None


# ---------------------------------------------------------------------------
# VOLET 1 — primary TIME-AWARE, convention [start, end) (fin EXCLUSIVE).
# ---------------------------------------------------------------------------

def test_v1_primary_open_ended_covers_everything_unchanged():
    # Régression : primary open-ended (from/to=None) couvre TOUT -> inchangé.
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": None, "to_date": None}]
    assert _run(asg, "v1", "1999-01-01T00:00:00+00:00") == "dPRIM"
    assert _run(asg, "v1", "2099-12-31T23:59:59+00:00") == "dPRIM"


def test_v1_primary_bounded_trip_before_from_not_covered():
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": "2026-06-01T00:00:00+00:00",
            "to_date": "2026-06-30T00:00:00+00:00"}]
    # trajet AVANT from_date -> non couvert -> fail-closed None
    assert _run(asg, "v1", "2026-05-31T23:59:59+00:00") is None


def test_v1_primary_bounded_trip_equals_from_inclusive_covered():
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": "2026-06-01T00:00:00+00:00",
            "to_date": "2026-06-30T00:00:00+00:00"}]
    # trajet == from_date -> début INCLUSIF -> couvert
    assert _run(asg, "v1", "2026-06-01T00:00:00+00:00") == "dPRIM"


def test_v1_primary_bounded_trip_inside_window_covered():
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": "2026-06-01T00:00:00+00:00",
            "to_date": "2026-06-30T00:00:00+00:00"}]
    assert _run(asg, "v1", "2026-06-15T12:00:00+00:00") == "dPRIM"


def test_v1_primary_bounded_trip_equals_to_exclusive_not_covered():
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": "2026-06-01T00:00:00+00:00",
            "to_date": "2026-06-30T00:00:00+00:00"}]
    # trajet == to_date -> fin EXCLUSIVE -> NON couvert -> None
    assert _run(asg, "v1", "2026-06-30T00:00:00+00:00") is None


def test_v1_primary_bounded_trip_after_to_not_covered():
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": "2026-06-01T00:00:00+00:00",
            "to_date": "2026-06-30T00:00:00+00:00"}]
    assert _run(asg, "v1", "2026-07-01T00:00:00+00:00") is None


def test_v1_primary_half_open_only_from_set_covers_future():
    # from défini, to=None -> couvre de from (inclus) à +infini.
    asg = [{"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
            "from_date": "2026-06-01T00:00:00+00:00", "to_date": None}]
    assert _run(asg, "v1", "2026-05-31T23:59:59+00:00") is None
    assert _run(asg, "v1", "2026-06-01T00:00:00+00:00") == "dPRIM"
    assert _run(asg, "v1", "2030-01-01T00:00:00+00:00") == "dPRIM"


def test_v1_dated_window_still_overrides_bounded_primary():
    # Une affectation datée non-primary couvrante prime toujours sur le primary.
    asg = [
        {"vehicle_id": "v1", "driver_id": "dPRIM", "is_primary": True,
         "from_date": None, "to_date": None},
        {"vehicle_id": "v1", "driver_id": "dWIN", "is_primary": False,
         "from_date": "2026-06-01T00:00:00+00:00", "to_date": "2026-06-30T00:00:00+00:00"},
    ]
    assert _run(asg, "v1", "2026-06-10T00:00:00+00:00") == "dWIN"
