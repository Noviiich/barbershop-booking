"""Read-only availability derived from the primary PostgreSQL database."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.services import (
    BookingRuleViolation,
    database_now,
    validate_booking_start,
)
from barbershop.catalog.models import BarberAssignment, Branch
from barbershop.schedule.calendar import LocalTimeError, local_to_utc
from barbershop.schedule.policy import intervals_starting_on

PRIMARY_DB_ALIAS = "default"
MAX_RANGE_DAYS = 31
MAX_RESULTS = 500


class AvailabilityQueryError(ValueError):
    """The requested branch, range, or filter is not available to this scope."""


@dataclass(frozen=True)
class AvailabilityQuery:
    business_id: UUID
    branch_id: UUID
    date_from: date
    date_to: date
    barber_id: UUID | None = None
    service_id: int | None = None
    limit: int = 100


@dataclass(frozen=True, order=True)
class AvailableSlot:
    start_at: datetime
    barber_id: UUID
    service_id: int
    end_at: datetime


def _query_branch(query: AvailabilityQuery, now: datetime) -> Branch:
    if query.date_to < query.date_from:
        raise AvailabilityQueryError("date_to must not be before date_from")
    if (query.date_to - query.date_from).days + 1 > MAX_RANGE_DAYS:
        raise AvailabilityQueryError(f"date range must not exceed {MAX_RANGE_DAYS} days")
    if not 1 <= query.limit <= MAX_RESULTS:
        raise AvailabilityQueryError(f"limit must be between 1 and {MAX_RESULTS}")
    try:
        branch = cast(
            Branch,
            Branch.objects.using(PRIMARY_DB_ALIAS).get(
                pk=query.branch_id,
                business_id=query.business_id,
            ),
        )
    except Branch.DoesNotExist as error:
        raise AvailabilityQueryError("branch is outside query scope") from error
    local_today = now.astimezone(ZoneInfo(str(branch.timezone))).date()
    if query.date_to > local_today + timedelta(days=int(branch.horizon_days)):
        raise AvailabilityQueryError("date range is outside booking horizon")
    return branch


def _local_dates(date_from: date, date_to: date) -> list[date]:
    return [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]


def _schedule_intervals(
    branch: Branch,
    assignment: BarberAssignment,
    local_date: date,
    zone: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for schedule_date in (local_date - timedelta(days=1), local_date):
        try:
            intervals.extend(intervals_starting_on(branch, assignment.barber, schedule_date, zone))
        except LocalTimeError:
            # A dated exception must disambiguate a DST-affected regular calendar.
            continue
    return intervals


def _candidate_starts(
    local_date: date,
    zone: ZoneInfo,
    grid_minutes: int,
) -> list[datetime]:
    starts: list[datetime] = []
    local_value = datetime.combine(local_date, time.min)
    local_end = local_value + timedelta(days=1)
    while local_value < local_end:
        with suppress(LocalTimeError):
            starts.append(local_to_utc(local_date, local_value.time(), zone))
        local_value += timedelta(minutes=grid_minutes)
    return starts


def list_available_slots(query: AvailabilityQuery) -> tuple[AvailableSlot, ...]:
    """Return bounded slot candidates; this function never reserves a resource."""
    now = database_now()
    branch = _query_branch(query, now)
    assignments = (
        BarberAssignment.objects.using(PRIMARY_DB_ALIAS)
        .select_related("barber", "service")
        .filter(
            branch=branch,
            is_active=True,
            barber__is_active=True,
            service__is_active=True,
        )
        .order_by("barber_id", "service_id")
    )
    if query.barber_id is not None:
        assignments = assignments.filter(barber_id=query.barber_id)
    if query.service_id is not None:
        assignments = assignments.filter(service_id=query.service_id)

    zone = ZoneInfo(str(branch.timezone))
    candidates: list[AvailableSlot] = []
    for assignment in assignments:
        for local_date in _local_dates(query.date_from, query.date_to):
            intervals = _schedule_intervals(branch, assignment, local_date, zone)
            for start_at in _candidate_starts(local_date, zone, int(branch.grid_minutes)):
                try:
                    validate_booking_start(branch, start_at, now)
                except BookingRuleViolation:
                    continue
                end_at = start_at + timedelta(seconds=int(assignment.service.duration_seconds))
                if any(
                    interval_start <= start_at and end_at <= interval_end
                    for interval_start, interval_end in intervals
                ):
                    candidates.append(
                        AvailableSlot(
                            start_at=start_at.astimezone(UTC),
                            barber_id=assignment.barber_id,
                            service_id=assignment.service_id,
                            end_at=end_at.astimezone(UTC),
                        )
                    )

    if not candidates:
        return ()
    first_start = min(slot.start_at for slot in candidates)
    last_end = max(slot.end_at for slot in candidates)
    barber_ids = {slot.barber_id for slot in candidates}
    occupied = list(
        Booking.objects.using(PRIMARY_DB_ALIAS)
        .filter(
            barber_id__in=barber_ids,
            start_at__lt=last_end,
            end_at__gt=first_start,
        )
        .exclude(status=BookingStatus.CANCELLED)
        .values_list("barber_id", "start_at", "end_at")
    )
    available = [
        slot
        for slot in candidates
        if not any(
            barber_id == slot.barber_id
            and occupied_start < slot.end_at
            and slot.start_at < occupied_end
            for barber_id, occupied_start, occupied_end in occupied
        )
    ]
    return tuple(sorted(available)[: query.limit])
