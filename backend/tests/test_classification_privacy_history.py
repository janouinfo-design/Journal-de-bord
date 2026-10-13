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
