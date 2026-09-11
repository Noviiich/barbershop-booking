"""TIME-01: local calendar conversion is explicit about DST edge cases."""

from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from barbershop.schedule.calendar import LocalTimeError, local_to_utc


def test_dst_gap_is_rejected() -> None:
    with pytest.raises(LocalTimeError, match="does not exist"):
        local_to_utc(date(2026, 3, 8), time(2, 30), ZoneInfo("America/New_York"))


def test_dst_fold_requires_explicit_choice() -> None:
    zone = ZoneInfo("America/New_York")
    with pytest.raises(LocalTimeError, match="ambiguous"):
        local_to_utc(date(2026, 11, 1), time(1, 30), zone)

    first = local_to_utc(date(2026, 11, 1), time(1, 30), zone, fold=0)
    second = local_to_utc(date(2026, 11, 1), time(1, 30), zone, fold=1)
    assert second > first


def test_fixed_zone_conversion_is_independent_of_process_timezone() -> None:
    utc = local_to_utc(date(2026, 1, 15), time(10, 0), ZoneInfo("Europe/Moscow"))
    assert utc.isoformat() == "2026-01-15T07:00:00+00:00"
