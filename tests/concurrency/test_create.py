"""CON-01: concurrent creates cannot double-book one global barber."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from barbershop.booking.models import Booking
from barbershop.booking.services import CreateBookingResult, create_booking
from barbershop.idempotency.models import CommandReceipt
from barbershop.journal.models import AuditEntry, OutboxEvent
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_twenty_competing_commands_have_one_success() -> None:
    scenario = create_booking_scenario()
    ready = Barrier(20)

    def run(index: int) -> CreateBookingResult:
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return create_booking(
                scenario.command(f"create-{index}"),
                deadline_seconds=15,
                lock_timeout_seconds=10,
                statement_timeout_seconds=12,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(run, range(20)))

    assert [result.result_code for result in results].count("CREATED") == 1
    assert [result.result_code for result in results].count("SLOT_CONFLICT") == 19
    assert Booking.objects.count() == 1
    assert AuditEntry.objects.count() == 1
    assert OutboxEvent.objects.count() == 1
    assert CommandReceipt.objects.count() == 20
