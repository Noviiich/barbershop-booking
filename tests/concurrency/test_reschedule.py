"""MOVE-01 concurrency checks with independent PostgreSQL connections."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID

import pytest
from django.db import close_old_connections

from barbershop.booking.cancellation import cancel_booking
from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.rescheduling import RescheduleBookingResult, reschedule_booking
from barbershop.booking.services import CreateBookingResult, create_booking
from tests.support.booking import BookingScenario, create_booking_scenario


def _move(
    scenario: BookingScenario,
    key: str,
    booking_id: UUID,
    start_offset: timedelta,
    ready: Barrier,
) -> RescheduleBookingResult:
    close_old_connections()
    try:
        ready.wait(timeout=10)
        return reschedule_booking(
            scenario.reschedule_command(
                key,
                booking_id,
                start_at=scenario.start_at + start_offset,
            ),
            deadline_seconds=15,
            lock_timeout_seconds=10,
            statement_timeout_seconds=12,
        )
    finally:
        close_old_connections()


@pytest.mark.django_db(transaction=True)
def test_two_reschedules_of_one_version_have_one_winner() -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("original"))
    assert created.booking_id is not None
    booking_id = created.booking_id
    ready = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_move, scenario, "move-one", booking_id, timedelta(hours=1), ready)
        second = executor.submit(_move, scenario, "move-two", booking_id, timedelta(hours=2), ready)
        results = [first.result(timeout=20), second.result(timeout=20)]

    booking = Booking.objects.get(pk=booking_id)
    assert sorted(result.result_code for result in results) == ["RESCHEDULED", "VERSION_CONFLICT"]
    assert booking.version == 2
    assert booking.start_at in {
        scenario.start_at + timedelta(hours=1),
        scenario.start_at + timedelta(hours=2),
    }


@pytest.mark.django_db(transaction=True)
def test_reschedule_and_create_for_new_slot_leave_one_valid_occupant() -> None:
    scenario = create_booking_scenario()
    original = create_booking(scenario.command("original"))
    assert original.booking_id is not None
    booking_id = original.booking_id
    new_start = scenario.start_at + timedelta(hours=1)
    ready = Barrier(2)

    def move() -> RescheduleBookingResult:
        return _move(scenario, "move", booking_id, timedelta(hours=1), ready)

    def create() -> CreateBookingResult:
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return create_booking(
                scenario.command("new-booking", start_at=new_start),
                deadline_seconds=15,
                lock_timeout_seconds=10,
                statement_timeout_seconds=12,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        move_future = executor.submit(move)
        create_future = executor.submit(create)
        move_result = move_future.result(timeout=20)
        create_result = create_future.result(timeout=20)

    original_booking = Booking.objects.get(pk=booking_id)
    if move_result.result_code == "RESCHEDULED":
        assert create_result.result_code == "SLOT_CONFLICT"
        assert original_booking.start_at == new_start
    else:
        assert move_result.result_code == "SLOT_CONFLICT"
        assert create_result.result_code == "CREATED"
        assert original_booking.start_at == scenario.start_at


@pytest.mark.django_db(transaction=True)
def test_reschedule_and_cancel_do_not_overwrite_each_other() -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("original"))
    assert created.booking_id is not None
    booking_id = created.booking_id
    ready = Barrier(2)

    def move() -> RescheduleBookingResult:
        return _move(scenario, "move", booking_id, timedelta(hours=1), ready)

    def cancel() -> str:
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return cancel_booking(
                scenario.cancel_command("cancel", booking_id),
                deadline_seconds=15,
                lock_timeout_seconds=10,
                statement_timeout_seconds=12,
            ).result_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        move_future = executor.submit(move)
        cancel_future = executor.submit(cancel)
        move_result = move_future.result(timeout=20)
        cancel_result = cancel_future.result(timeout=20)

    booking = Booking.objects.get(pk=booking_id)
    assert (move_result.result_code, cancel_result) in {
        ("RESCHEDULED", "VERSION_CONFLICT"),
        ("STATE_CONFLICT", "CANCELLED"),
    }
    assert (booking.status, booking.version) in {
        (BookingStatus.CONFIRMED, 2),
        (BookingStatus.CANCELLED, 2),
    }
