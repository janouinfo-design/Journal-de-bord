"""
Tests — VOLET 2 : resolver multi-source MODERNE (`resolve_driver_for_trip`).

Invariant testé : « V2 == V1 sauf autorité moderne PROUVÉE ».
Catégories couvertes : MODERN_SEGMENT, LEGACY_PRE_MODERN, MODERN_GAP_NONE,
NO_RELATION_NONE, CONFLICT_NONE, + tenant absent -> V1 exact.

Également : preuve que `reassign_all_trips()` utilise EXCLUSIVEMENT le resolver V1
(jamais V2), et qu'un trajet manuel historique n'est pas réécrit via l'autorité
moderne (puisque reassign n'appelle QUE V1).

AUCUN id métier (e711/09ce/Audi) n'est "spécial" dans le code applicatif : ce sont
ici de simples identifiants de test, le resolver les traite génériquement.
"""
import asyncio
from app import assignments as A


# ---------------------------------------------------------------------------
# Fake Mongo minimal (en mémoire) — lecture (find/find_one) + update_one (trips).
# ---------------------------------------------------------------------------
class _Cur:
    def __init__(self, items):
        self.items = items

    def sort(self, key=None, direction=1):
        # tri legacy sur from_date dans list_assignments (direction -1) ; ici no-op fidèle
        if key == "from_date":
            self.items = sorted(self.items, key=lambda x: x.get("from_date") or "",
                                reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return list(self.items)

    def __aiter__(self):
        async def gen():
            for it in self.items:
                yield it
        return gen()


class _Coll:
    def __init__(self, docs):
        self.docs = docs

    def _match(self, q, d):
        for k, v in q.items():
            if isinstance(v, dict):
                if "$in" in v:
                    if d.get(k) not in v["$in"]:
                        return False
                # autres opérateurs non utilisés par le resolver
                continue
            if d.get(k) != v:
                return False
        return True

    def find(self, q=None, proj=None):
        q = q or {}
        return _Cur([d for d in self.docs if self._match(q, d)])

    async def find_one(self, q=None, proj=None):
        q = q or {}
        for d in self.docs:
            if self._match(q, d):
                return d
        return None

    async def update_one(self, q, update):
        for d in self.docs:
            if self._match(q, d):
                d.update(update.get("$set", {}))

                class _R:
                    modified_count = 1
                return _R()

        class _R0:
            modified_count = 0
        return _R0()


class _DB:
    def __init__(self, *, assignments=None, events=None, vehicles=None,
                 trips=None, drivers=None):
        self.assignments = _Coll(assignments or [])
        self.vehicle_assignment_events = _Coll(events or [])
        self.vehicles = _Coll(vehicles or [])
        self.trips = _Coll(trips or [])
        self.drivers = _Coll(drivers or [])


def _v2(db, vehicle_id, trip_iso):
    return asyncio.run(A.resolve_driver_for_trip(db, vehicle_id, trip_iso))


# Constantes de test
# NB : le resolver LEGACY V1 (`list_assignments`) filtre sur tenant_id="default"
# EN DUR (legacy mono-tenant, volontairement inchangé en Volet 2). Pour tester un
# vrai "candidat V1", les assignments ET le véhicule doivent donc être en "default"
# (c'est le tenant principal réel de la PROD). V2 déduit le tenant depuis le véhicule.
T = "default"
MS = "2026-09-23T16:13:08+00:00"  # modern_since du chauffeur "modDrv"


def _default_vehicles(*vids, tenant=T):
    return [{"id": v, "tenant_id": tenant} for v in vids]


# ---------------------------------------------------------------------------
# 1) MODERN_SEGMENT — un segment moderne couvrant => driver moderne (témoin "Audi").
# ---------------------------------------------------------------------------
def test_v2_modern_segment_covers_returns_modern_driver():
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "modDrv", "from_vehicle_id": None, "to_vehicle_id": "audi",
         "at": MS},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_RELEASED",
         "driver_id": "modDrv", "from_vehicle_id": "audi", "to_vehicle_id": None,
         "at": "2026-09-24T10:00:00+00:00"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("audi"))
    # trajet dans la fenêtre [MS, 24/09 10:00) -> couvert
    assert _v2(db, "audi", "2026-09-23T18:00:00+00:00") == "modDrv"


def test_v2_modern_segment_end_exclusive():
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "modDrv", "from_vehicle_id": None, "to_vehicle_id": "audi",
         "at": MS},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_RELEASED",
         "driver_id": "modDrv", "from_vehicle_id": "audi", "to_vehicle_id": None,
         "at": "2026-09-24T10:00:00+00:00"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("audi"))
    # trajet EXACTEMENT à end -> NON couvert (fin exclusive). Pas de legacy -> None.
    assert _v2(db, "audi", "2026-09-24T10:00:00+00:00") is None
    # trajet == start -> couvert (début inclusif)
    assert _v2(db, "audi", MS) == "modDrv"


# ---------------------------------------------------------------------------
# 2) MODERN_GAP_NONE — chauffeur sous autorité moderne, legacy pointe encore ce
#    véhicule, mais aucun segment moderne ne couvre => None (cas type "09ce").
# ---------------------------------------------------------------------------
def test_v2_modern_gap_returns_none_after_modern_since():
    # legacy : primary open-ended "modDrv" sur "09ce"
    asgs = [{"tenant_id": T, "vehicle_id": "09ce", "driver_id": "modDrv",
             "from_date": None, "to_date": None, "is_primary": True}]
    # events modernes du chauffeur : il a pris l'AUDI (pas 09ce) -> modern_since connu
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "modDrv", "from_vehicle_id": None, "to_vehicle_id": "audi",
         "at": MS},
    ]
    db = _DB(assignments=asgs, events=events, vehicles=_default_vehicles("09ce", "audi"))
    # trajet 09ce APRÈS modern_since -> MODERN_GAP_NONE -> None (pas de fallback legacy)
    assert _v2(db, "09ce", "2026-10-14T09:00:00+00:00") is None


def test_v2_legacy_pre_modern_before_modern_since_returns_v1():
    asgs = [{"tenant_id": T, "vehicle_id": "09ce", "driver_id": "modDrv",
             "from_date": None, "to_date": None, "is_primary": True}]
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "modDrv", "from_vehicle_id": None, "to_vehicle_id": "audi",
         "at": MS},
    ]
    db = _DB(assignments=asgs, events=events, vehicles=_default_vehicles("09ce", "audi"))
    # trajet 09ce AVANT modern_since -> legacy encore autorisé -> modDrv (== V1)
    assert _v2(db, "09ce", "2026-09-01T09:00:00+00:00") == "modDrv"


# ---------------------------------------------------------------------------
# 3) candidat V1 SANS modern_since -> V1 exact (chauffeur jamais passé moderne).
# ---------------------------------------------------------------------------
def test_v2_v1_candidate_without_modern_since_returns_v1():
    asgs = [{"tenant_id": T, "vehicle_id": "van", "driver_id": "legacyDrv",
             "from_date": None, "to_date": None, "is_primary": True}]
    # events d'un AUTRE chauffeur -> legacyDrv n'a pas de modern_since
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "someoneElse", "from_vehicle_id": None, "to_vehicle_id": "audi",
         "at": MS},
    ]
    db = _DB(assignments=asgs, events=events, vehicles=_default_vehicles("van", "audi"))
    assert _v2(db, "van", "2026-10-14T09:00:00+00:00") == "legacyDrv"


# ---------------------------------------------------------------------------
# 4) NO_RELATION_NONE — ni segment moderne ni candidat legacy -> None (== V1).
# ---------------------------------------------------------------------------
def test_v2_no_relation_returns_none():
    db = _DB(vehicles=_default_vehicles("ghost"))
    assert _v2(db, "ghost", "2026-10-14T09:00:00+00:00") is None


# ---------------------------------------------------------------------------
# 5) CONFLICT_NONE — deux chauffeurs modernes couvrant le même véhicule/instant.
# ---------------------------------------------------------------------------
def test_v2_conflict_two_modern_segments_returns_none():
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvA", "from_vehicle_id": None, "to_vehicle_id": "shared",
         "at": "2026-09-20T08:00:00+00:00"},
        # drvB prend le MÊME véhicule sans release (incohérent historiquement, mais
        # le resolver ne doit pas deviner -> conflit -> None)
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvB", "from_vehicle_id": None, "to_vehicle_id": "shared",
         "at": "2026-09-21T08:00:00+00:00"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("shared"))
    # instant couvert par les deux segments ouverts (drvA open-ended, drvB open-ended)
    assert _v2(db, "shared", "2026-10-01T00:00:00+00:00") is None


# ---------------------------------------------------------------------------
# 6) tenant absent / véhicule inconnu -> V1 EXACT (aucun accès events).
# ---------------------------------------------------------------------------
def test_v2_tenant_absent_falls_back_to_v1_exact():
    asgs = [{"tenant_id": "default", "vehicle_id": "legv", "driver_id": "legacyDrv",
             "from_date": None, "to_date": None, "is_primary": True}]
    # events "default" existent, MAIS le véhicule n'a pas de doc vehicles -> tenant inconnu
    events = [
        {"tenant_id": "default", "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "legacyDrv", "from_vehicle_id": None, "to_vehicle_id": "legv",
         "at": MS},
    ]
    db = _DB(assignments=asgs, events=events, vehicles=[])  # pas de vehicles -> tenant None
    # list_assignments filtre sur tenant_id="default" (legacy) : V1 renvoie legacyDrv.
    # V2 ne doit PAS consulter les events (tenant introuvable) -> V1 exact.
    assert _v2(db, "legv", "2026-10-14T09:00:00+00:00") == "legacyDrv"


# ---------------------------------------------------------------------------
# 7) PREUVE : reassign_all_trips() utilise EXCLUSIVEMENT V1 (jamais V2).
#    On "piège" les deux resolvers et on vérifie lequel est appelé.
# ---------------------------------------------------------------------------
def test_reassign_all_trips_uses_v1_only(monkeypatch):
    calls = {"v1": 0, "v2": 0}

    async def fake_v1(db, vehicle_id, trip_iso):
        calls["v1"] += 1
        return None  # pas de changement

    async def fake_v2(db, vehicle_id, trip_iso):
        calls["v2"] += 1
        return "SHOULD_NOT_BE_USED"

    monkeypatch.setattr(A, "_resolve_driver_for_trip_v1", fake_v1)
    monkeypatch.setattr(A, "resolve_driver_for_trip", fake_v2)

    db = _DB(
        trips=[{"id": "t1", "vehicle_id": "v1", "start_time": "2026-10-01T00:00:00+00:00",
                "driver_id": "orig", "driver_name": "Orig"}],
        drivers=[{"id": "orig", "name": "Orig"}],
    )
    n = asyncio.run(A.reassign_all_trips(db))
    assert calls["v1"] == 1          # V1 appelé
    assert calls["v2"] == 0          # V2 JAMAIS appelé
    assert n == 0                    # aucun changement


# ---------------------------------------------------------------------------
# 8) Trajet manuel historique : reassign (V1) ne lui applique PAS l'autorité
#    moderne. Ici V1 renverrait None (aucune relation) -> trip NON réécrit.
#    (Garantit qu'aucune réécriture moderne ne passe par les routes admin.)
# ---------------------------------------------------------------------------
def test_reassign_does_not_apply_modern_authority_to_manual_trip():
    # Trajet manuel attribué à "manualDrv" ; aucune assignment legacy ne couvre.
    # Des events modernes existent (autorité moderne) MAIS reassign n'utilise que V1,
    # donc V1 -> None -> `new_driver` falsy -> trip NON modifié (driver_id conservé).
    trips = [{"id": "tm", "vehicle_id": "09ce", "start_time": "2026-10-14T09:00:00+00:00",
              "driver_id": "manualDrv", "driver_name": "Manual",
              "auto_classified": False}]
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "modDrv", "from_vehicle_id": None, "to_vehicle_id": "audi",
         "at": MS},
    ]
    db = _DB(events=events, trips=trips, vehicles=_default_vehicles("09ce", "audi"),
             drivers=[{"id": "manualDrv", "name": "Manual"}])
    n = asyncio.run(A.reassign_all_trips(db))
    assert n == 0
    assert db.trips.docs[0]["driver_id"] == "manualDrv"  # inchangé


# ---------------------------------------------------------------------------
# 9) FAIL-CLOSED STRICT (version canonique) — événements anormaux.
#    La reconstruction NE devine JAMAIS : tout événement ambigu met le
#    chauffeur en conflit et neutralise le véhicule (conflict_vehicle_since).
# ---------------------------------------------------------------------------
def test_v2_force_released_marks_conflict_returns_none():
    # VEHICLE_FORCE_RELEASED n'est pas une transition reconstruite -> conflit.
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvF", "from_vehicle_id": None, "to_vehicle_id": "truck",
         "at": "2026-09-20T08:00:00+00:00", "id": "e1"},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_FORCE_RELEASED",
         "driver_id": "drvF", "from_vehicle_id": "truck", "to_vehicle_id": None,
         "at": "2026-09-21T08:00:00+00:00", "id": "e2"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("truck"))
    # trip après le 1er conflit sur 'truck' -> fail-closed None (jamais deviner)
    assert _v2(db, "truck", "2026-09-22T00:00:00+00:00") is None


def test_v2_take_on_open_segment_marks_conflict_returns_none():
    # Deux TAKEN successifs pour le même chauffeur sans release -> conflit driver.
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvT", "from_vehicle_id": None, "to_vehicle_id": "vA",
         "at": "2026-09-20T08:00:00+00:00", "id": "e1"},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvT", "from_vehicle_id": None, "to_vehicle_id": "vB",
         "at": "2026-09-21T08:00:00+00:00", "id": "e2"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("vA", "vB"))
    # le chauffeur est en conflit -> ses segments retirés ; vA neutralisé après conflit
    assert _v2(db, "vA", "2026-09-22T00:00:00+00:00") is None
    assert _v2(db, "vB", "2026-09-22T00:00:00+00:00") is None


def test_v2_release_without_take_marks_conflict():
    # RELEASED sans TAKE préalable -> conflit (séquence incohérente).
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_RELEASED",
         "driver_id": "drvR", "from_vehicle_id": "vX", "to_vehicle_id": None,
         "at": "2026-09-20T08:00:00+00:00", "id": "e1"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("vX"))
    assert _v2(db, "vX", "2026-09-21T00:00:00+00:00") is None


def test_v2_clean_change_reconstructs_two_segments():
    # VEHICLE_CHANGED cohérent : ferme A, ouvre B (deux segments [start,end)).
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvC", "from_vehicle_id": None, "to_vehicle_id": "A",
         "at": "2026-09-20T08:00:00+00:00", "id": "e1"},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_CHANGED",
         "driver_id": "drvC", "from_vehicle_id": "A", "to_vehicle_id": "B",
         "at": "2026-09-20T12:00:00+00:00", "id": "e2"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("A", "B"))
    # A couvert sur [08:00, 12:00)
    assert _v2(db, "A", "2026-09-20T10:00:00+00:00") == "drvC"
    # A NON couvert à 12:00 (fin exclusive) ; pas de legacy -> None
    assert _v2(db, "A", "2026-09-20T12:00:00+00:00") is None
    # B couvert à partir de 12:00 (open-ended)
    assert _v2(db, "B", "2026-09-20T12:00:00+00:00") == "drvC"


def test_v2_invalid_trip_timestamp_returns_v1():
    # trip_start non parsable -> retour V1 exact (pas d'autorité moderne).
    asgs = [{"tenant_id": T, "vehicle_id": "v9", "driver_id": "legacyDrv",
             "from_date": None, "to_date": None, "is_primary": True}]
    db = _DB(assignments=asgs, vehicles=_default_vehicles("v9"))
    assert _v2(db, "v9", "pas-une-date") == "legacyDrv"


# ---------------------------------------------------------------------------
# 10) RÉGRESSION TEMPORELLE DU CONFLIT (bug signalé) :
#     un conflit à l'instant T ne doit PAS invalider rétroactivement une
#     relation moderne déjà prouvée AVANT T. Un segment valide antérieur au
#     conflit DOIT rester couvrant ; seul le >= instant de conflit -> None.
# ---------------------------------------------------------------------------
def test_v2_conflict_does_not_invalidate_prior_valid_segment():
    # Segment PROPRE vX : TAKEN 01/10 -> RELEASED 10/10  => [01/10, 10/10) valide.
    # Puis événement INCOHÉRENT le 20/10 (RELEASE sans TAKE) sur vX => conflit à 20/10.
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvP", "from_vehicle_id": None, "to_vehicle_id": "vX",
         "at": "2026-10-01T08:00:00+00:00", "id": "e1"},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_RELEASED",
         "driver_id": "drvP", "from_vehicle_id": "vX", "to_vehicle_id": None,
         "at": "2026-10-10T08:00:00+00:00", "id": "e2"},
        # incohérence plus tard : RELEASE sans segment ouvert -> conflit à 20/10
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_RELEASED",
         "driver_id": "drvP", "from_vehicle_id": "vX", "to_vehicle_id": None,
         "at": "2026-10-20T08:00:00+00:00", "id": "e3"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("vX"))
    # trajet du 05/10 (AVANT le conflit) : segment valide [01,10) couvre -> drvP CONSERVÉ
    assert _v2(db, "vX", "2026-10-05T12:00:00+00:00") == "drvP"
    # trajet du 09/10 (encore dans le segment valide) -> drvP
    assert _v2(db, "vX", "2026-10-09T23:59:59+00:00") == "drvP"
    # trajet du 25/10 (APRÈS le conflit) -> None (fail-closed à partir du conflit)
    assert _v2(db, "vX", "2026-10-25T00:00:00+00:00") is None


def test_v2_conflict_bounds_open_segment_of_conflicting_driver():
    # Segment OUVERT d'un chauffeur en conflit : TAKEN 01/10 (reste ouvert),
    # puis TAKE-sur-ouvert 20/10 (conflit). Le segment [01/10, None) doit être
    # borné à l'instant du conflit (20/10) -> couvre avant 20/10, None après.
    events = [
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvO", "from_vehicle_id": None, "to_vehicle_id": "vY",
         "at": "2026-10-01T08:00:00+00:00", "id": "e1"},
        {"tenant_id": T, "result": "OK", "type": "VEHICLE_TAKEN",
         "driver_id": "drvO", "from_vehicle_id": None, "to_vehicle_id": "vY",
         "at": "2026-10-20T08:00:00+00:00", "id": "e2"},
    ]
    db = _DB(events=events, vehicles=_default_vehicles("vY"))
    # avant le conflit -> couvert par le segment borné [01,20) -> drvO
    assert _v2(db, "vY", "2026-10-05T00:00:00+00:00") == "drvO"
    # au/après le conflit -> None
    assert _v2(db, "vY", "2026-10-20T08:00:00+00:00") is None
    assert _v2(db, "vY", "2026-10-25T00:00:00+00:00") is None
