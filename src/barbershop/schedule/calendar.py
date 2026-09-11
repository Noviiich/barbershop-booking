"""Timezone-safe conversion of local schedule intervals to UTC."""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from barbershop.schedule.models import ScheduleRule


class LocalTimeError(ValueError):
    """The local timestamp is missing or ambiguous in its IANA timezone."""


def local_to_utc(
    local_date: date, local_time: time, zone: ZoneInfo, *, fold: int | None = None
) -> datetime:
    """Convert a local wall time, rejecting DST gaps and implicit folds."""
    naive = datetime.combine(local_date, local_time)
    candidates = []
    for candidate_fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=candidate_fold)
        utc_value = aware.astimezone(UTC)
        if utc_value.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.append((candidate_fold, utc_value))
    if len(candidates) == 2 and candidates[0][1] == candidates[1][1]:
        candidates = candidates[:1]
    if not candidates:
        raise LocalTimeError("local time does not exist in timezone")
    if len(candidates) > 1:
        if fold is None:
            raise LocalTimeError("local time is ambiguous; explicit fold is required")
        for candidate_fold, value in candidates:
            if candidate_fold == fold:
                return value
        raise LocalTimeError("fold must be 0 or 1")
    if fold is not None and candidates[0][0] != fold:
        raise LocalTimeError("fold does not match the local timestamp")
    return candidates[0][1]


def rule_interval_utc(
    rule: ScheduleRule, local_date: date, zone: ZoneInfo
) -> tuple[datetime, datetime]:
    """Return one weekly rule interval; an end not after start crosses midnight."""
    end_date = local_date if rule.ends_at > rule.starts_at else local_date + timedelta(days=1)
    start = local_to_utc(local_date, rule.starts_at, zone)
    end = local_to_utc(end_date, rule.ends_at, zone)
    if end <= start:
        raise LocalTimeError("schedule interval is not positive in UTC")
    return start, end


def intervals_for_date(
    rules: Iterable[ScheduleRule], local_date: date, zone: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """Build sorted UTC intervals for one branch-local calendar date."""
    intervals = [
        rule_interval_utc(rule, local_date, zone)
        for rule in rules
        if rule.weekday == local_date.weekday()
    ]
    return sorted(intervals)
