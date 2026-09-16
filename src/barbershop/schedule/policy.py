"""Authoritative schedule evaluation used after locking a barber."""

from datetime import date, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from barbershop.catalog.models import Barber, Branch
from barbershop.schedule.calendar import local_to_utc, rule_interval_utc
from barbershop.schedule.models import ScheduleException, ScheduleRule


def intervals_starting_on(
    branch: Branch,
    barber: Barber,
    local_date: date,
    zone: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    """Получить рабочие интервалы мастера, начинающиеся в локальную дату."""
    exception = cast(
        ScheduleException | None,
        ScheduleException.objects.filter(
            branch=branch,
            barber=barber,
            local_date=local_date,
        ).first(),
    )
    if exception is not None:
        if exception.kind == ScheduleException.Kind.CLOSED:
            return []
        if exception.starts_at is None or exception.ends_at is None:
            return []
        end_date = (
            local_date
            if exception.ends_at > exception.starts_at
            else local_date + timedelta(days=1)
        )
        return [
            (
                local_to_utc(local_date, exception.starts_at, zone),
                local_to_utc(end_date, exception.ends_at, zone),
            )
        ]

    rules = ScheduleRule.objects.filter(
        branch=branch,
        barber=barber,
        weekday=local_date.weekday(),
        is_active=True,
    ).order_by("starts_at", "id")
    return [rule_interval_utc(rule, local_date, zone) for rule in rules]


def booking_fits_schedule(
    branch: Branch,
    barber: Barber,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    """Проверить попадание записи в график с учётом ночных смен прошлого дня."""
    zone = ZoneInfo(str(branch.timezone))
    local_date = start_at.astimezone(zone).date()
    schedule_dates = (local_date - timedelta(days=1), local_date)
    intervals = [
        interval
        for schedule_date in schedule_dates
        for interval in intervals_starting_on(branch, barber, schedule_date, zone)
    ]
    return any(
        interval_start <= start_at and end_at <= interval_end
        for interval_start, interval_end in intervals
    )
