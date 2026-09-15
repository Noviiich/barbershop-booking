"""Single transactional command service for moving a confirmed booking."""

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from django.db import IntegrityError, OperationalError, connection, transaction

from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.services import (
    EXCLUSION_CONSTRAINT,
    RETRYABLE_SQLSTATES,
    TIMEOUT_SQLSTATES,
    BookingRetryableError,
    BookingRuleViolation,
    _constraint_name,
    database_now,
    validate_booking_start,
)
from barbershop.catalog.models import Barber, Branch
from barbershop.idempotency.services import CommandResult, CommandScope, execute_idempotent
from barbershop.journal.services import append_booking_change
from barbershop.schedule.policy import booking_fits_schedule


class ReschedulingRuleViolation(Exception):
    """The reschedule command is malformed or outside its trusted scope."""


@dataclass(frozen=True)
class RescheduleBookingCommand:
    scope: CommandScope
    idempotency_key: str
    booking_id: UUID
    expected_version: int
    start_at: datetime
    correlation_id: UUID


@dataclass(frozen=True)
class RescheduleBookingResult:
    result_code: str
    booking_id: UUID
    version: int
    no_op: bool
    replayed: bool


def _validate_command(command: RescheduleBookingCommand) -> None:
    if command.expected_version < 1:
        raise ReschedulingRuleViolation("expected_version must be positive")
    if command.start_at.tzinfo is None or command.start_at.utcoffset() is None:
        raise ReschedulingRuleViolation("start_at must be timezone-aware")


def _authorize_target(command: RescheduleBookingCommand) -> None:
    if command.scope.target_id != command.booking_id:
        raise ReschedulingRuleViolation("booking is outside command target scope")
    try:
        booking = cast(
            Booking,
            Booking.objects.select_related("branch")
            .only("id", "branch__business_id")
            .get(pk=command.booking_id),
        )
    except Booking.DoesNotExist as error:
        raise ReschedulingRuleViolation("booking is outside command scope") from error
    if booking.branch.business_id != command.scope.business_id:
        raise ReschedulingRuleViolation("booking is outside command scope")


def _set_timeouts(lock_timeout_seconds: float, statement_timeout_seconds: float) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            [f"{int(lock_timeout_seconds * 1000)}ms"],
        )
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            [f"{int(statement_timeout_seconds * 1000)}ms"],
        )


def _reschedule_effect(
    command: RescheduleBookingCommand,
    *,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> tuple[str, dict[str, object]]:
    _set_timeouts(lock_timeout_seconds, statement_timeout_seconds)
    initial = cast(Booking, Booking.objects.only("barber_id").get(pk=command.booking_id))
    barber = cast(Barber, Barber.objects.select_for_update().get(pk=initial.barber_id))
    booking = cast(
        Booking,
        Booking.objects.select_for_update().select_related("branch").get(pk=command.booking_id),
    )
    if (
        booking.branch.business_id != command.scope.business_id
        or command.scope.target_id != booking.id
    ):
        raise ReschedulingRuleViolation("booking is outside command scope")
    if booking.status != BookingStatus.CONFIRMED:
        return "STATE_CONFLICT", {
            "booking_id": str(booking.id),
            "error": "STATE_CONFLICT",
            "version": booking.version,
        }
    if booking.version != command.expected_version:
        return "VERSION_CONFLICT", {
            "booking_id": str(booking.id),
            "error": "VERSION_CONFLICT",
            "version": booking.version,
        }
    if command.start_at.astimezone(UTC) == booking.start_at:
        return "RESCHEDULED", {
            "booking_id": str(booking.id),
            "status": booking.status,
            "version": booking.version,
            "no_op": True,
        }

    branch = cast(Branch, booking.branch)
    now = database_now()
    if now >= booking.start_at:
        return "RESCHEDULE_CLOSED", {
            "booking_id": str(booking.id),
            "error": "RESCHEDULE_CLOSED",
            "version": booking.version,
        }
    try:
        validate_booking_start(branch, command.start_at, now)
    except BookingRuleViolation:
        return "TIME_RULE_VIOLATION", {
            "booking_id": str(booking.id),
            "error": "TIME_RULE_VIOLATION",
            "version": booking.version,
        }

    start_at = command.start_at.astimezone(UTC)
    end_at = start_at + timedelta(seconds=int(booking.duration_seconds))
    if not booking_fits_schedule(branch, barber, start_at, end_at):
        return "TIME_RULE_VIOLATION", {
            "booking_id": str(booking.id),
            "error": "TIME_RULE_VIOLATION",
            "version": booking.version,
        }
    booking.start_at = start_at
    booking.end_at = end_at
    booking.version += 1
    try:
        with transaction.atomic():
            booking.save(update_fields=["start_at", "end_at", "version"])
    except IntegrityError as error:
        if _constraint_name(error) == EXCLUSION_CONSTRAINT:
            return "SLOT_CONFLICT", {
                "booking_id": str(booking.id),
                "error": "SLOT_CONFLICT",
                "version": command.expected_version,
            }
        raise
    append_booking_change(
        booking,
        operation="BOOKING_RESCHEDULED",
        event_kind="BOOKING_RESCHEDULED",
        actor_kind=command.scope.principal_kind,
        actor_id=command.scope.principal_id,
        correlation_id=command.correlation_id,
    )
    return "RESCHEDULED", {
        "booking_id": str(booking.id),
        "status": booking.status,
        "version": booking.version,
        "no_op": False,
    }


def _execute_once(
    command: RescheduleBookingCommand,
    *,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> CommandResult:
    payload: dict[str, object] = {
        "booking_id": str(command.booking_id),
        "expected_version": command.expected_version,
        "start_at": command.start_at.isoformat(),
    }
    return cast(
        CommandResult,
        execute_idempotent(
            scope=command.scope,
            operation="RESCHEDULE_BOOKING",
            idempotency_key=command.idempotency_key,
            payload=payload,
            effect=lambda: _reschedule_effect(
                command,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            ),
        ),
    )


def reschedule_booking(
    command: RescheduleBookingCommand,
    *,
    deadline_seconds: float = 4.0,
    lock_timeout_seconds: float = 1.0,
    statement_timeout_seconds: float = 2.0,
) -> RescheduleBookingResult:
    """Move one confirmed booking, retaining its service and catalog snapshots."""
    _validate_command(command)
    _authorize_target(command)
    deadline = time.monotonic() + deadline_seconds
    for attempt in range(3):
        try:
            result = _execute_once(
                command,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            )
            booking_id_raw = result.response.get("booking_id")
            version_raw = result.response.get("version")
            return RescheduleBookingResult(
                result_code=result.result_code,
                booking_id=(
                    UUID(booking_id_raw) if isinstance(booking_id_raw, str) else command.booking_id
                ),
                version=version_raw if isinstance(version_raw, int) else command.expected_version,
                no_op=result.response.get("no_op") is True,
                replayed=result.replayed,
            )
        except OperationalError as error:
            sqlstate = getattr(error.__cause__, "sqlstate", None)
            if sqlstate in RETRYABLE_SQLSTATES and attempt < 2 and time.monotonic() < deadline:
                time.sleep(min(random.uniform(0.005, 0.025), max(0.0, deadline - time.monotonic())))
                continue
            if sqlstate in RETRYABLE_SQLSTATES | TIMEOUT_SQLSTATES:
                raise BookingRetryableError("reschedule transaction should be retried") from error
            raise
    raise BookingRetryableError("reschedule transaction retry budget exhausted")
