"""
Tests — stratégie de classification 'privacy_history_strict' (logique pure).

Règles validées avec le client :
- preuve mode CONFIRMÉE BUSINESS/PRIVATE <= 2 h avant le départ -> classement (HAUTE) ;
- preuve trop ancienne (> 2 h) -> None (À classer) ;
- aucune preuve avant le départ -> None ;
- changement de mode CONFIRMÉ pendant le trajet -> None (traitement spécial) ;
- aucun fallback horaire.
"""
from app.rules import classify_by_mode_history, PRIVACY_FRESH_MAX_S


def trip(start, end=None):
    return {"start_time": start, "end_time": end}


def ev(ts, state):
    return {"ts": ts, "state": state}


def test_business_confirmed_1s_before_start_is_professional():
    # Cas réel 13.10 : BUSINESS confirmé 06:09:42, trajet 06:09:43.
    events = [ev("2026-10-13T06:09:42+00:00", "BUSINESS")]
    t = trip("2026-10-13T06:09:43+00:00", "2026-10-13T06:15:00+00:00")
    assert classify_by_mode_history(t, events) == "professional"


def test_business_confirmed_11min_before_is_professional():
    events = [ev("2026-10-13T06:09:42+00:00", "BUSINESS")]
    t = trip("2026-10-13T06:20:21+00:00", "2026-10-13T06:25:00+00:00")
    assert classify_by_mode_history(t, events) == "professional"


def test_private_confirmed_before_is_personal():
    events = [ev("2026-10-13T06:00:00+00:00", "PRIVATE")]
    t = trip("2026-10-13T06:30:00+00:00", "2026-10-13T06:45:00+00:00")
    assert classify_by_mode_history(t, events) == "personal"


def test_proof_too_old_is_none():
    # Dernier état confirmé = 29.09 ; trajet le 06.10 -> > 2 h -> À classer.
    events = [ev("2026-09-29T12:39:00+00:00", "BUSINESS")]
    t = trip("2026-10-06T15:21:30+00:00", "2026-10-06T15:40:00+00:00")
    assert classify_by_mode_history(t, events) is None


def test_no_proof_before_start_is_none():
    # Preuve PRIVATE seulement APRÈS le départ -> pas de preuve au départ.
    events = [ev("2026-10-12T13:15:53+00:00", "PRIVATE")]
    t = trip("2026-10-12T13:10:59+00:00", "2026-10-12T14:20:00+00:00")
    assert classify_by_mode_history(t, events) is None


def test_mode_change_during_trip_is_none():
    # BUSINESS avant le départ MAIS PRIVATE confirmé PENDANT le trajet -> À classer.
    events = [
        ev("2026-10-12T12:00:00+00:00", "BUSINESS"),
        ev("2026-10-12T13:15:53+00:00", "PRIVATE"),
    ]
    t = trip("2026-10-12T13:10:59+00:00", "2026-10-12T14:20:00+00:00")
    assert classify_by_mode_history(t, events) is None


def test_exactly_2h_boundary_is_classified():
    events = [ev("2026-10-13T06:00:00+00:00", "BUSINESS")]
    t = trip("2026-10-13T08:00:00+00:00")  # exactement 2h
    assert classify_by_mode_history(t, events) == "professional"


def test_just_over_2h_is_none():
    events = [ev("2026-10-13T06:00:00+00:00", "BUSINESS")]
    t = trip("2026-10-13T08:00:01+00:00")  # 2h + 1s
    assert classify_by_mode_history(t, events) is None


def test_empty_events_is_none():
    assert classify_by_mode_history(trip("2026-10-13T06:09:43+00:00"), []) is None


def test_invalid_start_is_none():
    assert classify_by_mode_history(trip(None), [ev("2026-10-13T06:00:00+00:00", "BUSINESS")]) is None


def test_latest_confirmed_before_wins():
    # Plusieurs états : on prend le DERNIER avant le départ.
    events = [
        ev("2026-10-13T05:00:00+00:00", "PRIVATE"),
        ev("2026-10-13T06:09:42+00:00", "BUSINESS"),  # le plus récent avant 06:20
    ]
    t = trip("2026-10-13T06:20:21+00:00", "2026-10-13T06:25:00+00:00")
    assert classify_by_mode_history(t, events) == "professional"


def test_fresh_threshold_is_2h():
    assert PRIVACY_FRESH_MAX_S == 2 * 3600


# --- Tests anti-régression de _apply_privacy_history_strict (DB simulée) ---
import asyncio
from app import rules as rules_mod


class _FakeCursor:
    def __init__(self, docs): self._docs = list(docs)
    def sort(self, *a, **k): return self
    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.updates = []
        self.inserted = []
    def find(self, query=None, proj=None):
        # filtre minimal : auto_classified != False
        q = query or {}
        res = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$ne" in v:
                    if d.get(k) == v["$ne"]:
                        ok = False
                elif isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok:
                res.append(d)
        return _FakeCursor(res)
    async def find_one(self, query=None, proj=None):
        cur = self.find(query, proj)
        async for d in cur:
            return d
        return None
    async def update_one(self, q, upd):
        self.updates.append((q, upd))
        for d in self.docs:
            if d.get("id") == q.get("id"):
                d.update(upd["$set"])
    async def insert_one(self, doc):
        self.inserted.append(doc)


class _FakeDB:
    def __init__(self, trips, vehicles=None, events=None, schedules=None):
        self.trips = _FakeColl(trips)
        self.vehicles = _FakeColl(vehicles or [])
        self.audit_log = _FakeColl(events or [])
        self.schedules = _FakeColl(schedules or [{"driver_id": None, "days": []}])
    # _confirmed_mode_events lit db.audit_log.find(...).sort(...)


def _run_strict(trips, vehicles=None, audit=None, settings=None):
    db = _FakeDB(trips, vehicles, audit)
    s = settings or {"id": "default", "classification_mode": "privacy_history_strict"}
    updated = asyncio.run(rules_mod._apply_privacy_history_strict(db, s))
    return db, updated


def test_strict_NEVER_overwrites_existing_with_none():
    # Trajet déjà 'professional', AUCUNE preuve mode -> DOIT rester 'professional'.
    trips = [{
        "id": "t1", "vehicle_id": "v1", "classification": "professional",
        "auto_classified": True, "start_time": "2026-10-06T15:21:30+00:00",
        "end_time": "2026-10-06T15:40:00+00:00",
    }]
    db, updated = _run_strict(trips, vehicles=[{"id": "v1"}], audit=[])
    assert db.trips.docs[0]["classification"] == "professional"  # PRÉSERVÉ
    assert updated == 0
    assert db.trips.updates == []  # aucune écriture


def test_strict_NEVER_overwrites_personal_with_none():
    trips = [{
        "id": "t2", "vehicle_id": "v1", "classification": "personal",
        "auto_classified": True, "start_time": "2026-10-06T15:21:30+00:00",
    }]
    db, updated = _run_strict(trips, vehicles=[{"id": "v1"}], audit=[])
    assert db.trips.docs[0]["classification"] == "personal"  # PRÉSERVÉ
    assert updated == 0


def test_strict_classifies_none_when_fresh_proof():
    # None + preuve BUSINESS fraîche (1 min avant) -> professional.
    trips = [{
        "id": "t3", "vehicle_id": "v1", "classification": None,
        "auto_classified": True, "start_time": "2026-10-13T06:10:00+00:00",
        "end_time": "2026-10-13T06:15:00+00:00",
    }]
    audit = [{"scope": "private_mode", "vehicle_id": "v1",
              "ts": "2026-10-13T06:09:00+00:00",
              "resulting_state": "BUSINESS", "result": "confirmed_async"}]
    db, updated = _run_strict(trips, vehicles=[{"id": "v1"}], audit=audit)
    assert db.trips.docs[0]["classification"] == "professional"
    assert updated == 1


def test_strict_corrects_existing_on_fresh_contradictory_proof():
    # 'personal' erroné + preuve BUSINESS fraîche -> corrigé en professional.
    trips = [{
        "id": "t4", "vehicle_id": "v1", "classification": "personal",
        "auto_classified": True, "start_time": "2026-10-13T06:20:21+00:00",
        "end_time": "2026-10-13T06:25:00+00:00",
    }]
    audit = [{"scope": "private_mode", "vehicle_id": "v1",
              "ts": "2026-10-13T06:09:42+00:00",
              "resulting_state": "BUSINESS", "result": "confirmed_async"}]
    db, updated = _run_strict(trips, vehicles=[{"id": "v1"}], audit=audit)
    assert db.trips.docs[0]["classification"] == "professional"
    assert updated == 1


def test_strict_never_touches_manual():
    # manuel (auto_classified=False) -> jamais traité (exclu du find).
    trips = [{
        "id": "t5", "vehicle_id": "v1", "classification": "professional",
        "auto_classified": False, "start_time": "2026-10-13T06:20:21+00:00",
    }]
    db, updated = _run_strict(trips, vehicles=[{"id": "v1"}], audit=[])
    assert db.trips.docs[0]["classification"] == "professional"
    assert updated == 0


# --- Tests de SCOPE : _effective_strategy + apply_rules_to_all par véhicule ---
def test_effective_strategy_vehicle_override_wins():
    # override véhicule privacy -> privacy, même si tenant legacy.
    veh = {"id": "audi", "classification_mode": "privacy_history_strict"}
    assert rules_mod._effective_strategy(veh, {"classification_mode": "legacy"}) == "privacy_history_strict"


def test_effective_strategy_vehicle_legacy_overrides_tenant_privacy():
    # override véhicule legacy -> legacy, même si tenant privacy.
    veh = {"id": "x", "classification_mode": "legacy"}
    assert rules_mod._effective_strategy(veh, {"classification_mode": "privacy_history_strict"}) == "legacy"


def test_effective_strategy_fallback_tenant_then_legacy():
    assert rules_mod._effective_strategy({"id": "x"}, {"classification_mode": "legacy"}) == "legacy"
    assert rules_mod._effective_strategy({"id": "x"}, {}) == "legacy"
    assert rules_mod._effective_strategy({"id": "x"}, {"classification_mode": "privacy_history_strict"}) == "privacy_history_strict"


def test_strict_scope_limits_to_given_vehicles():
    # 2 véhicules : AUDI (privacy) + OTHER. Le moteur strict ne doit toucher QU'AUDI.
    trips = [
        {"id": "ta", "vehicle_id": "audi", "classification": "professional",
         "auto_classified": True, "start_time": "2026-10-06T15:00:00+00:00"},
        {"id": "to", "vehicle_id": "other", "classification": "professional",
         "auto_classified": True, "start_time": "2026-10-06T15:00:00+00:00"},
    ]
    db = _FakeDB(trips, vehicles=[{"id": "audi"}, {"id": "other"}], events=[])
    # Scope limité à 'audi' : 'other' ne doit PAS être parcouru.
    updated = asyncio.run(rules_mod._apply_privacy_history_strict(
        db, {"classification_mode": "privacy_history_strict"}, vehicle_ids={"audi"}))
    # Aucune preuve -> audi conservé 'professional' ; other jamais touché.
    assert db.trips.docs[0]["classification"] == "professional"  # audi préservé
    assert db.trips.docs[1]["classification"] == "professional"  # other intact
    assert updated == 0
    # Aucune écriture sur 'other'
    assert all(q.get("id") != "to" for q, _ in db.trips.updates)


# --- Tests V3 : isolation multi-tenant (fail-safe + scope tenant) ---
def test_apply_rules_refuses_without_tenant_context():
    """apply_rules_to_all SANS contexte tenant -> REFUSE (return 0, aucune écriture)."""
    from app.tenant_context import get_tenant_id, reset_current_tenant, set_current_tenant
    # S'assurer qu'aucun tenant n'est posé.
    trips = [{"id": "x", "vehicle_id": "v", "classification": "professional",
              "auto_classified": True, "start_time": "2026-10-06T15:00:00+00:00"}]
    db = _FakeDB(trips, vehicles=[{"id": "v"}], events=[])
    # Contexte sans tenant (None).
    assert get_tenant_id() in (None, "")  # défaut
    updated = asyncio.run(rules_mod.apply_rules_to_all(db))
    assert updated == 0
    assert db.trips.updates == []  # RIEN n'a été écrit (fail-safe)


def test_apply_rules_scopes_to_current_tenant():
    """Avec un tenant posé, les requêtes sont filtrées par tenant_id (défense en profondeur)."""
    from app.tenant_context import set_current_tenant, reset_current_tenant
    seen = []

    class _SpyColl(_FakeColl):
        def find(self, query=None, proj=None):
            seen.append(dict(query or {}))
            return super().find(query, proj)
        async def find_one(self, query=None, proj=None):
            seen.append(dict(query or {}))
            return await super().find_one(query, proj)

    class _SpyDB:
        def __init__(self):
            self.settings = _SpyColl([{"id": "default", "tenant_id": "T1", "classification_mode": "legacy"}])
            self.vehicles = _SpyColl([{"id": "v1", "tenant_id": "T1"}])
            self.trips = _SpyColl([])
            self.schedules = _SpyColl([{"driver_id": None, "tenant_id": "T1", "days": []}])
            self.audit_log = _SpyColl([])

    token = set_current_tenant("T1")
    try:
        asyncio.run(rules_mod.apply_rules_to_all(_SpyDB()))
    finally:
        reset_current_tenant(token)

    # Au moins une requête settings/vehicles porte explicitement tenant_id=T1.
    assert any(f.get("tenant_id") == "T1" for f in seen), seen


