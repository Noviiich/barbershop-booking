"""Single transactional command service for cancelling bookings."""

import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.db import OperationalError, connection

from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.services import (
    RETRYABLE_SQLSTATES,
    TIMEOUT_SQLSTATES,
    BookingRetryableError,
    database_now,
)
from barbershop.catalog.models import Barber
from barbershop.idempotency.services import CommandResult, CommandScope, execute_idempotent
from barbershop.journal.services import append_booking_change

CANCELLATION_WINDOW = timedelta(hours=2)


class CancellationRuleViolation(Exception):
    """The cancellation command is malformed or outside its trusted scope."""


@dataclass(frozen=True)
class CancelBookingCommand:
    scope: CommandScope
    idempotency_key: str
    booking_id: UUID
    expected_version: int
    correlation_id: UUID
    reason_code: str = ""
    override: bool = False


@dataclass(frozen=True)
class CancelBookingResult:
    result_code: str
    booking_id: UUID
    version: int
    no_op: bool
    replayed: bool


def _normalize_reason(command: CancelBookingCommand) -> str:
    """Нормализовать причину отмены и проверить обязательные поля команды."""
    reason_code = command.reason_code.strip()
    if len(reason_code) > 64:
        raise CancellationRuleViolation("reason_code must not exceed 64 characters")
    if command.override and not reason_code:
        raise CancellationRuleViolation("override cancellation requires a reason_code")
    if command.expected_version < 1:
        raise CancellationRuleViolation("expected_version must be positive")
    return reason_code


def _authorize_target(command: CancelBookingCommand) -> None:
    """Убедиться, что запись принадлежит области действия команды."""
    if command.scope.target_id != command.booking_id:
        raise CancellationRuleViolation("booking is outside command target scope")
    try:
        booking = cast(
            Booking,
            Booking.objects.select_related("branch")
            .only("id", "branch__business_id")
            .get(pk=command.booking_id),
        )
    except Booking.DoesNotExist as error:
        raise CancellationRuleViolation("booking is outside command scope") from error
    if booking.branch.business_id != command.scope.business_id:
        raise CancellationRuleViolation("booking is outside command scope")


def _cancel_effect(
    command: CancelBookingCommand,
    *,
    reason_code: str,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> tuple[str, dict[str, object]]:
    """Отменить заблокированную запись и атомарно сохранить журнальные события."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            [f"{int(lock_timeout_seconds * 1000)}ms"],
        )
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            [f"{int(statement_timeout_seconds * 1000)}ms"],
        )

    initial = cast(Booking, Booking.objects.only("barber_id").get(pk=command.booking_id))
    Barber.objects.select_for_update().get(pk=initial.barber_id)
    booking = cast(
        Booking,
        Booking.objects.select_for_update().select_related("branch").get(pk=command.booking_id),
    )
    if (
        booking.branch.business_id != command.scope.business_id
        or command.scope.target_id != booking.id
    ):
        raise CancellationRuleViolation("booking is outside command scope")

    if booking.status == BookingStatus.CANCELLED:
        return "CANCELLED", {
            "booking_id": str(booking.id),
            "status": BookingStatus.CANCELLED,
            "version": booking.version,
            "no_op": True,
        }
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

    now = database_now()
    if now >= booking.start_at:
        return "CANCELLATION_CLOSED", {
            "booking_id": str(booking.id),
            "error": "CANCELLATION_CLOSED",
            "version": booking.version,
        }
    if not command.override and booking.start_at - now < CANCELLATION_WINDOW:
        return "CANCELLATION_CLOSED", {
            "booking_id": str(booking.id),
            "error": "CANCELLATION_CLOSED",
            "version": booking.version,
        }

    booking.status = BookingStatus.CANCELLED
    booking.version += 1
    booking.save(update_fields=["status", "version"])
    append_booking_change(
        booking,
        operation="BOOKING_CANCELLED",
        event_kind="BOOKING_CANCELLED",
        actor_kind=command.scope.principal_kind,
        actor_id=command.scope.principal_id,
        correlation_id=command.correlation_id,
        reason_code=reason_code,
    )
    return "CANCELLED", {
        "booking_id": str(booking.id),
        "status": BookingStatus.CANCELLED,
        "version": booking.version,
        "no_op": False,
    }


def _execute_once(
    command: CancelBookingCommand,
    *,
    reason_code: str,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> CommandResult:
    """Однократно выполнить идемпотентную команду отмены записи."""
    payload: dict[str, object] = {
        "booking_id": str(command.booking_id),
        "expected_version": command.expected_version,
        "override": command.override,
        "reason_code": reason_code,
    }
    return cast(
        CommandResult,
        execute_idempotent(
            scope=command.scope,
            operation="CANCEL_BOOKING",
            idempotency_key=command.idempotency_key,
            payload=payload,
            effect=lambda: _cancel_effect(
                command,
                reason_code=reason_code,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            ),
        ),
    )


def cancel_booking(
    command: CancelBookingCommand,
    *,
    allow_override: bool = False,
    deadline_seconds: float = 4.0,
    lock_timeout_seconds: float = 1.0,
    statement_timeout_seconds: float = 2.0,
) -> CancelBookingResult:
    """Отменить или повторить отмену записи, не ожидая внешней доставки."""
    reason_code = _normalize_reason(command)
    if command.override and not allow_override:
        raise CancellationRuleViolation("trusted staff authority is required for override")
    _authorize_target(command)
    deadline = time.monotonic() + deadline_seconds
    for attempt in range(3):
        try:
            result = _execute_once(
                command,
                reason_code=reason_code,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            )
            booking_id_raw = result.response.get("booking_id")
            version_raw = result.response.get("version")
            return CancelBookingResult(
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
                raise BookingRetryableError("cancellation transaction should be retried") from error
            raise
    raise BookingRetryableError("cancellation transaction retry budget exhausted")
