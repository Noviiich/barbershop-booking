"""CON-02: cancellation and replacement creation serialize on the barber."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from barbershop.booking.cancellation import CancelBookingResult, cancel_booking
from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.services import CreateBookingResult, create_booking
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_cancel_and_create_preserve_a_valid_serialized_outcome() -> None:
    """Проверить сериализуемый результат одновременных отмены и создания."""
    scenario = create_booking_scenario()
    original = create_booking(scenario.command("original"))
    assert original.booking_id is not None
    original_id = original.booking_id
    ready = Barrier(2)

    def cancel() -> CancelBookingResult:
        """Отменить исходную запись через независимое соединение."""
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return cancel_booking(
                scenario.cancel_command("cancel-race", original_id),
                deadline_seconds=15,
                lock_timeout_seconds=10,
                statement_timeout_seconds=12,
            )
        finally:
            close_old_connections()

    def create() -> CreateBookingResult:
        """Попытаться создать заменяющую запись через независимое соединение."""
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return create_booking(
                scenario.command("replacement"),
                deadline_seconds=15,
                lock_timeout_seconds=10,
                statement_timeout_seconds=12,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        cancel_future = executor.submit(cancel)
        create_future = executor.submit(create)
        cancel_result = cancel_future.result(timeout=20)
        create_result = create_future.result(timeout=20)

    original_booking = Booking.objects.get(pk=original_id)
    active = Booking.objects.exclude(status=BookingStatus.CANCELLED)

    assert cancel_result.result_code == "CANCELLED"
    assert original_booking.status == BookingStatus.CANCELLED
    assert create_result.result_code in {"CREATED", "SLOT_CONFLICT"}
    assert active.count() == (1 if create_result.result_code == "CREATED" else 0)
    if create_result.result_code == "CREATED":
        assert active.get().id == create_result.booking_id
