"""Single transactional command service for creating bookings."""

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import IntegrityError, OperationalError, connection, transaction

from barbershop.booking.models import Booking, BookingStatus
from barbershop.catalog.models import Barber, BarberAssignment, Branch, ServiceOffering
from barbershop.idempotency.services import CommandResult, CommandScope, execute_idempotent
from barbershop.journal.services import append_booking_change
from barbershop.schedule.policy import booking_fits_schedule

EXCLUSION_CONSTRAINT = "booking_barber_occupied_range_excludes_overlap"
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})
TIMEOUT_SQLSTATES = frozenset({"55P03", "57014"})


class BookingRuleViolation(Exception):
    """The requested visit is outside the current catalog or calendar policy."""


class BookingRetryableError(Exception):
    """The transaction could not finish within its lock/deadline budget."""


@dataclass(frozen=True)
class CreateBookingCommand:
    scope: CommandScope
    idempotency_key: str
    branch_id: UUID
    barber_id: UUID
    service_id: int
    start_at: datetime
    correlation_id: UUID


@dataclass(frozen=True)
class CreateBookingResult:
    result_code: str
    booking_id: UUID | None
    version: int | None
    replayed: bool


def database_now() -> datetime:
    """Получить текущее время непосредственно от основной базы данных."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        value = cursor.fetchone()[0]
    return cast(datetime, value)


def _constraint_name(error: IntegrityError) -> str | None:
    """Извлечь имя нарушенного ограничения из ошибки PostgreSQL."""
    cause = error.__cause__
    diagnostic = getattr(cause, "diag", None)
    return cast(str | None, getattr(diagnostic, "constraint_name", None))


def validate_booking_start(branch: Branch, start_at: datetime, now: datetime) -> None:
    """Проверить начало записи по часовому поясу, горизонту и сетке филиала."""
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise BookingRuleViolation("start_at must be timezone-aware")
    zone = ZoneInfo(str(branch.timezone))
    local_start = start_at.astimezone(zone)
    local_now = now.astimezone(zone)
    if start_at < now + timedelta(minutes=int(branch.min_lead_minutes)):
        raise BookingRuleViolation("start_at violates minimum lead time")
    if local_start.date() > local_now.date() + timedelta(days=int(branch.horizon_days)):
        raise BookingRuleViolation("start_at is outside booking horizon")
    seconds_from_midnight = local_start.hour * 3600 + local_start.minute * 60 + local_start.second
    if local_start.microsecond or seconds_from_midnight % (int(branch.grid_minutes) * 60):
        raise BookingRuleViolation("start_at is outside the branch grid")


def _create_effect(
    command: CreateBookingCommand,
    *,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> tuple[str, dict[str, object]]:
    """Создать запись и журнальные события внутри текущей транзакции команды."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            [f"{int(lock_timeout_seconds * 1000)}ms"],
        )
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            [f"{int(statement_timeout_seconds * 1000)}ms"],
        )

    barber = cast(
        Barber,
        Barber.objects.select_for_update().get(pk=command.barber_id),
    )
    now = database_now()
    branch = cast(
        Branch,
        Branch.objects.select_related("business").get(pk=command.branch_id),
    )
    if branch.business_id != command.scope.business_id:
        raise BookingRuleViolation("branch is outside command scope")
    service = cast(
        ServiceOffering,
        ServiceOffering.objects.get(pk=command.service_id, branch=branch, is_active=True),
    )
    if not barber.is_active:
        raise BookingRuleViolation("barber is inactive")
    if not BarberAssignment.objects.filter(
        branch=branch,
        barber=barber,
        service=service,
        is_active=True,
    ).exists():
        raise BookingRuleViolation("barber is not assigned to the service")

    validate_booking_start(branch, command.start_at, now)
    start_at = command.start_at.astimezone(UTC)
    end_at = start_at + timedelta(seconds=int(service.duration_seconds))
    if not booking_fits_schedule(branch, barber, start_at, end_at):
        raise BookingRuleViolation("booking does not fit the working schedule")

    try:
        with transaction.atomic():
            booking = cast(
                Booking,
                Booking.objects.create(
                    branch=branch,
                    barber=barber,
                    service=service,
                    status=BookingStatus.CONFIRMED,
                    version=1,
                    start_at=start_at,
                    end_at=end_at,
                    service_name=service.name,
                    service_price=cast(Decimal, service.price),
                    currency=service.currency,
                    duration_seconds=service.duration_seconds,
                    branch_timezone=branch.timezone,
                ),
            )
    except IntegrityError as error:
        if _constraint_name(error) == EXCLUSION_CONSTRAINT:
            return "SLOT_CONFLICT", {"error": "SLOT_CONFLICT"}
        raise

    append_booking_change(
        booking,
        operation="BOOKING_CREATED",
        event_kind="BOOKING_CREATED",
        actor_kind=command.scope.principal_kind,
        actor_id=command.scope.principal_id,
        correlation_id=command.correlation_id,
    )
    return "CREATED", {
        "booking_id": str(booking.id),
        "status": "CONFIRMED",
        "version": 1,
    }


def _execute_once(
    command: CreateBookingCommand,
    *,
    lock_timeout_seconds: float,
    statement_timeout_seconds: float,
) -> CommandResult:
    """Однократно выполнить идемпотентную команду создания записи."""
    payload: dict[str, object] = {
        "barber_id": str(command.barber_id),
        "branch_id": str(command.branch_id),
        "service_id": command.service_id,
        "start_at": command.start_at.isoformat(),
    }
    return cast(
        CommandResult,
        execute_idempotent(
            scope=command.scope,
            operation="CREATE_BOOKING",
            idempotency_key=command.idempotency_key,
            payload=payload,
            effect=lambda: _create_effect(
                command,
                lock_timeout_seconds=lock_timeout_seconds,
                statement_timeout_seconds=statement_timeout_seconds,
            ),
        ),
    )


def create_booking(
    command: CreateBookingCommand,
    *,
    deadline_seconds: float = 4.0,
    lock_timeout_seconds: float = 1.0,
    statement_timeout_seconds: float = 2.0,
) -> CreateBookingResult:
    """Создать или повторить запись, перезапуская только всю транзакцию целиком."""
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
            return CreateBookingResult(
                result_code=result.result_code,
                booking_id=UUID(booking_id_raw) if isinstance(booking_id_raw, str) else None,
                version=version_raw if isinstance(version_raw, int) else None,
                replayed=result.replayed,
            )
        except OperationalError as error:
            sqlstate = getattr(error.__cause__, "sqlstate", None)
            if sqlstate in RETRYABLE_SQLSTATES and attempt < 2 and time.monotonic() < deadline:
                time.sleep(min(random.uniform(0.005, 0.025), max(0.0, deadline - time.monotonic())))
                continue
            if sqlstate in RETRYABLE_SQLSTATES | TIMEOUT_SQLSTATES:
                raise BookingRetryableError("booking transaction should be retried") from error
            raise
    raise BookingRetryableError("booking transaction retry budget exhausted")
