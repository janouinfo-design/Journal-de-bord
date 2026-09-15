from datetime import datetime, timezone

from app import navixy_sync as ns


def test_fmt_converts_utc_to_zurich_summer():
    dt = datetime(
        2026, 9, 14, 8, 34, 14,
        tzinfo=timezone.utc,
    )

    assert ns._fmt(dt) == "2026-09-14 10:34:14"


def test_fmt_converts_utc_to_zurich_winter():
    dt = datetime(
        2026, 1, 14, 9, 34, 14,
        tzinfo=timezone.utc,
    )

    assert ns._fmt(dt) == "2026-01-14 10:34:14"


def test_normalize_navixy_summer_to_utc():
    assert ns._normalize_navixy_date(
        "2026-09-14 10:34:14"
    ) == "2026-09-14T08:34:14+00:00"


def test_normalize_navixy_winter_to_utc():
    assert ns._normalize_navixy_date(
        "2026-01-14 10:34:14"
    ) == "2026-01-14T09:34:14+00:00"


def test_normalize_explicit_utc_is_not_shifted():
    assert ns._normalize_navixy_date(
        "2026-09-14T08:34:14+00:00"
    ) == "2026-09-14T08:34:14+00:00"
