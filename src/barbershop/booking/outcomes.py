"""Transactional terminal-outcome commands for confirmed bookings."""

import random
import time
from dataclasses import dataclass
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
from barbershop.identity.policy import AccessAction, Principal, authorize
from barbershop.journal.services import append_booking_change


class OutcomeRuleViolation(Exception):
    """The outcome command is malformed or outside its trusted scope."""


COMPLETED_STATUS = cast(str, BookingStatus.COMPLETED)
NO_SHOW_STATUS = cast(str, BookingStatus.NO_SHOW)


@dataclass(frozen=True)
class BookingOutcomeCommand:
    scope: CommandScope
    principal: Principal
    idempotency_key: str
    booking_id: UUID
    expected_version: int
    correlation_id: UUID


CompleteBookingCommand = BookingOutcomeCommand
MarkNoShowCommand = BookingOutcomeCommand


@dataclass(frozen=True)
class BookingOutcomeResult:
    result_code: str
    booking_id: UUID
    version: int
    no_op: bool
    replayed: bool


def _validate_command(command: BookingOutcomeCommand) -> None:
    """Проверить версию команды и соответствие scope доверенному сотруднику."""
    if command.expected_version < 1:
        raise OutcomeRuleViolation("expected_version must be positive")
    if command.scope.principal_id != str(command.principal.user_id):
        raise OutcomeRuleViolation("command scope does not match trusted principal")


def _authorize_target(command: BookingOutcomeCommand) -> None:
    """Проверить принадлежность записи бизнесу и право отметить её исход."""
    if command.scope.target_id != command.booking_id:
        raise OutcomeRuleViolation("booking is outside command target scope")
    try:
        booking = cast(
            Booking,
            Booking.objects.select_related("branch")
            .only("id", "branch_id", "branch__business_id")
            .get(pk=command.booking_id),
        )
    except Booking.DoesNotExist as error:
        raise OutcomeRuleViolation("booking is outside command scope") from error
    if booking.branch.business_id != command.scope.business_id:
        raise OutcomeRuleViolation("booking is outside command scope")
    authorize(command.principal, AccessAction.MARK_OUTCOME, booking.branch_id)


def _set_timeouts(lock_timeout_seconds: float, statement_timeout_seconds: float) -> None:
    """Установить локальные тайм-ауты ожидания блокировки и SQL-запросов."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            [f"{int(lock_timeout_seconds * 1000)}ms"],
        )
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            [f"{int(statement_timeout_seconds * 1000)}ms"],
        )


def _outcome_effect(
    command: BookingOutcomeCommand,
    *,
    target_status: str,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> tuple[str, dict[str, object]]:
    """Выполнить смену terminal-статуса под блокировками мастера и записи."""
    _set_timeouts(lock_timeout_seconds, statement_timeout_seconds)
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
        raise OutcomeRuleViolation("booking is outside command scope")
    authorize(command.principal, AccessAction.MARK_OUTCOME, booking.branch_id)

    result_code = "COMPLETED" if target_status == COMPLETED_STATUS else "NO_SHOW"
    if booking.status == target_status:
        return result_code, {
            "booking_id": str(booking.id),
            "status": target_status,
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
    if database_now() < booking.end_at:
        return "OUTCOME_TOO_EARLY", {
            "booking_id": str(booking.id),
            "error": "OUTCOME_TOO_EARLY",
            "version": booking.version,
        }

    booking.status = target_status
    booking.version += 1
    booking.save(update_fields=["status", "version"])
    append_booking_change(
        booking,
        operation=f"BOOKING_{result_code}",
        event_kind=f"BOOKING_{result_code}",
        actor_kind=command.scope.principal_kind,
        actor_id=command.scope.principal_id,
        correlation_id=command.correlation_id,
    )
    return result_code, {
        "booking_id": str(booking.id),
        "status": target_status,
        "version": booking.version,
        "no_op": False,
    }


def _execute_once(
    command: BookingOutcomeCommand,
    *,
    target_status: str,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> CommandResult:
    """Запустить одну идемпотентную транзакцию и сохранить её результат."""
    result_code = "COMPLETE_BOOKING" if target_status == COMPLETED_STATUS else "MARK_NO_SHOW"
    payload: dict[str, object] = {
        "booking_id": str(command.booking_id),
        "expected_version": command.expected_version,
    }
    return cast(
        CommandResult,
        execute_idempotent(
            scope=command.scope,
            operation=result_code,
            idempotency_key=command.idempotency_key,
            payload=payload,
            effect=lambda: _outcome_effect(
                command,
                target_status=target_status,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            ),
        ),
    )


def _record_outcome(
    command: BookingOutcomeCommand,
    *,
    target_status: str,
    deadline_seconds: float,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> BookingOutcomeResult:
    """Проверить доступ, выполнить команду исхода и повторить transient-сбой."""
    _validate_command(command)
    _authorize_target(command)
    deadline = time.monotonic() + deadline_seconds
    for attempt in range(3):
        try:
            result = _execute_once(
                command,
                target_status=target_status,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            )
            booking_id_raw = result.response.get("booking_id")
            version_raw = result.response.get("version")
            return BookingOutcomeResult(
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
                raise BookingRetryableError("outcome transaction should be retried") from error
            raise
    raise BookingRetryableError("outcome transaction retry budget exhausted")


def complete_booking(
    command: CompleteBookingCommand,
    *,
    deadline_seconds: float = 4.0,
    lock_timeout_seconds: float = 1.0,
    statement_timeout_seconds: float = 2.0,
) -> BookingOutcomeResult:
    """Отметить подтверждённую запись выполненной после планового окончания."""
    return _record_outcome(
        command,
        target_status=COMPLETED_STATUS,
        deadline_seconds=deadline_seconds,
        lock_timeout_seconds=lock_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
    )


def mark_no_show(
    command: MarkNoShowCommand,
    *,
    deadline_seconds: float = 4.0,
    lock_timeout_seconds: float = 1.0,
    statement_timeout_seconds: float = 2.0,
) -> BookingOutcomeResult:
    """Отметить подтверждённую запись как неявку после планового окончания."""
    return _record_outcome(
        command,
        target_status=NO_SHOW_STATUS,
        deadline_seconds=deadline_seconds,
        lock_timeout_seconds=lock_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
    )
