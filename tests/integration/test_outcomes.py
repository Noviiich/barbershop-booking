"""LIFE-02: terminal booking outcomes are authorized, versioned, and final."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import IntegrityError, close_old_connections

from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.outcomes import (
    BookingOutcomeResult,
    complete_booking,
    mark_no_show,
)
from barbershop.booking.services import create_booking
from barbershop.identity.policy import AccessDenied, Principal
from barbershop.journal.models import AuditEntry, OutboxEvent
from tests.support.booking import create_booking_scenario

OutcomeFunction = Callable[..., BookingOutcomeResult]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("operation", "status", "opposite"),
    [
        (complete_booking, BookingStatus.COMPLETED, mark_no_show),
        (mark_no_show, BookingStatus.NO_SHOW, complete_booking),
    ],
)
def test_terminal_outcomes_are_idempotent_and_cannot_be_rewritten(
    monkeypatch: pytest.MonkeyPatch,
    operation: OutcomeFunction,
    status: str,
    opposite: OutcomeFunction,
) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create"))
    assert created.booking_id is not None
    booking_id = created.booking_id
    monkeypatch.setattr(
        "barbershop.booking.outcomes.database_now",
        lambda: scenario.start_at + timedelta(minutes=30),
    )
    command = scenario.outcome_command("outcome", booking_id)

    result = operation(command)
    replay = operation(command)
    no_op = operation(scenario.outcome_command("same-outcome", booking_id, expected_version=1))
    conflict = opposite(scenario.outcome_command("other-outcome", booking_id, expected_version=2))
    booking = Booking.objects.get(pk=booking_id)

    assert result.result_code == status
    assert result.version == 2
    assert replay.replayed
    assert no_op.no_op and no_op.version == 2
    assert conflict.result_code == "STATE_CONFLICT"
    assert booking.status == status
    assert booking.version == 2
    assert AuditEntry.objects.filter(booking=booking).count() == 2
    assert OutboxEvent.objects.filter(booking=booking).count() == 2


@pytest.mark.django_db(transaction=True)
def test_outcomes_are_rejected_before_end_and_for_another_branch() -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-early"))
    assert created.booking_id is not None
    booking_id = created.booking_id

    too_early = complete_booking(scenario.outcome_command("early", booking_id))
    outsider = Principal(user_id=2, roles=frozenset({"ADMIN"}), branch_ids=frozenset())
    with pytest.raises(AccessDenied):
        mark_no_show(scenario.outcome_command("outsider", booking_id, principal=outsider))

    assert too_early.result_code == "OUTCOME_TOO_EARLY"
    assert Booking.objects.get(pk=booking_id).status == BookingStatus.CONFIRMED
    assert AuditEntry.objects.filter(booking_id=booking_id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_completed_and_no_show_intervals_remain_protected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-history"))
    assert created.booking_id is not None
    booking_id = created.booking_id
    monkeypatch.setattr(
        "barbershop.booking.outcomes.database_now",
        lambda: scenario.start_at + timedelta(minutes=30),
    )
    result = mark_no_show(scenario.outcome_command("no-show", booking_id))
    booking = Booking.objects.get(pk=booking_id)

    assert result.result_code == "NO_SHOW"
    with pytest.raises(IntegrityError):
        Booking.objects.create(
            branch=booking.branch,
            barber=booking.barber,
            service=booking.service,
            status=BookingStatus.CONFIRMED,
            start_at=booking.start_at,
            end_at=booking.end_at,
            service_name=booking.service_name,
            service_price=booking.service_price,
            currency=booking.currency,
            duration_seconds=booking.duration_seconds,
            branch_timezone=booking.branch_timezone,
        )


@pytest.mark.django_db(transaction=True)
def test_competing_terminal_outcomes_have_one_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-race"))
    assert created.booking_id is not None
    booking_id = created.booking_id
    monkeypatch.setattr(
        "barbershop.booking.outcomes.database_now",
        lambda: scenario.start_at + timedelta(minutes=30),
    )
    ready = Barrier(2)

    def run(operation: OutcomeFunction, key: str) -> BookingOutcomeResult:
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return operation(
                scenario.outcome_command(key, booking_id),
                deadline_seconds=15,
                lock_timeout_seconds=10,
                statement_timeout_seconds=12,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        complete_future = executor.submit(run, complete_booking, "complete")
        no_show_future = executor.submit(run, mark_no_show, "no-show")
        results = [complete_future.result(timeout=20), no_show_future.result(timeout=20)]

    booking = Booking.objects.get(pk=booking_id)
    result_codes = sorted(result.result_code for result in results)
    assert result_codes in (["COMPLETED", "STATE_CONFLICT"], ["NO_SHOW", "STATE_CONFLICT"])
    assert booking.status in {BookingStatus.COMPLETED, BookingStatus.NO_SHOW}
    assert booking.version == 2
