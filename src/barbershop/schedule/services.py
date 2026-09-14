"""Internal schedule mutations following the project lock protocol."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.db import connection, transaction

from barbershop.booking.models import Booking, BookingStatus
from barbershop.catalog.services import lock_branch_and_barbers
from barbershop.schedule.models import ScheduleException, ScheduleRule
from barbershop.schedule.policy import booking_fits_schedule


class ScheduleConflict(Exception):
    def __init__(self, booking_ids: tuple[UUID, ...]) -> None:
        self.booking_ids = booking_ids
        super().__init__("schedule change conflicts with future bookings")


def _database_now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        value = cursor.fetchone()[0]
    return cast(datetime, value)


def _ensure_future_bookings_fit(branch_id: UUID, barber_id: UUID) -> None:
    bookings = (
        Booking.objects.select_related("branch", "barber")
        .filter(
            branch_id=branch_id,
            barber_id=barber_id,
            start_at__gte=_database_now(),
        )
        .exclude(status=BookingStatus.CANCELLED)
    )
    conflicts = tuple(
        booking.id
        for booking in bookings.order_by("id")
        if not booking_fits_schedule(
            booking.branch,
            booking.barber,
            booking.start_at,
            booking.end_at,
        )
    )
    if conflicts:
        raise ScheduleConflict(conflicts)


@transaction.atomic  # type: ignore[untyped-decorator]
def update_schedule_rule(rule_id: int, changes: Mapping[str, Any]) -> ScheduleRule:
    rule = cast(ScheduleRule, ScheduleRule.objects.select_related("branch").get(pk=rule_id))
    lock_branch_and_barbers(rule.branch_id)
    rule = cast(ScheduleRule, ScheduleRule.objects.select_for_update().get(pk=rule_id))
    allowed = {"weekday", "starts_at", "ends_at", "is_active"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported schedule field: {sorted(unknown)[0]}")
    for field, value in changes.items():
        setattr(rule, field, value)
    rule.full_clean()
    rule.save(update_fields=list(changes))
    _ensure_future_bookings_fit(rule.branch_id, rule.barber_id)
    return rule


@transaction.atomic  # type: ignore[untyped-decorator]
def update_schedule_exception(exception_id: UUID, changes: Mapping[str, Any]) -> ScheduleException:
    exception = cast(
        ScheduleException,
        ScheduleException.objects.select_related("branch").get(pk=exception_id),
    )
    lock_branch_and_barbers(exception.branch_id)
    exception = cast(
        ScheduleException,
        ScheduleException.objects.select_for_update().get(pk=exception_id),
    )
    allowed = {"local_date", "kind", "starts_at", "ends_at", "reason"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported schedule field: {sorted(unknown)[0]}")
    for field, value in changes.items():
        setattr(exception, field, value)
    exception.full_clean()
    exception.save(update_fields=list(changes))
    _ensure_future_bookings_fit(exception.branch_id, exception.barber_id)
    return exception
