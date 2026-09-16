"""MOVE-01: moving a booking is versioned, atomic, and idempotent."""

from datetime import timedelta

import pytest

from barbershop.booking.models import Booking
from barbershop.booking.rescheduling import reschedule_booking
from barbershop.booking.services import create_booking
from barbershop.journal.models import AuditEntry, OutboxEvent
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_reschedule_updates_the_interval_and_replays_without_new_journal_rows() -> None:
    """Проверить перенос интервала и повтор без новых журнальных строк."""
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create"))
    assert created.booking_id is not None
    new_start = scenario.start_at + timedelta(hours=1)
    command = scenario.reschedule_command("move", created.booking_id, start_at=new_start)

    result = reschedule_booking(command)
    replay = reschedule_booking(command)
    booking = Booking.objects.get(pk=created.booking_id)

    assert result.result_code == "RESCHEDULED"
    assert result.version == 2
    assert not result.no_op
    assert replay.replayed
    assert booking.start_at == new_start
    assert booking.end_at == new_start + timedelta(seconds=scenario.service.duration_seconds)
    assert booking.version == 2
    assert AuditEntry.objects.filter(booking=booking).count() == 2
    assert OutboxEvent.objects.filter(booking=booking).count() == 2


@pytest.mark.django_db(transaction=True)
def test_conflicting_new_slot_keeps_the_original_interval_and_version() -> None:
    """Проверить сохранение интервала и версии при конфликте нового слота."""
    scenario = create_booking_scenario()
    original = create_booking(scenario.command("original"))
    occupied = create_booking(
        scenario.command("occupied", start_at=scenario.start_at + timedelta(hours=1))
    )
    assert original.booking_id is not None
    assert occupied.booking_id is not None

    result = reschedule_booking(
        scenario.reschedule_command(
            "conflicting-move", original.booking_id, start_at=scenario.start_at + timedelta(hours=1)
        )
    )
    booking = Booking.objects.get(pk=original.booking_id)

    assert result.result_code == "SLOT_CONFLICT"
    assert booking.start_at == scenario.start_at
    assert booking.version == 1
    assert AuditEntry.objects.filter(booking=booking).count() == 1
    assert OutboxEvent.objects.filter(booking=booking).count() == 1


@pytest.mark.django_db(transaction=True)
def test_same_time_is_a_version_checked_no_op() -> None:
    """Проверить перенос на то же время как no-op с контролем версии."""
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-no-op"))
    assert created.booking_id is not None

    result = reschedule_booking(
        scenario.reschedule_command("same-time", created.booking_id, start_at=scenario.start_at)
    )
    booking = Booking.objects.get(pk=created.booking_id)

    assert result.result_code == "RESCHEDULED"
    assert result.no_op
    assert booking.version == 1
    assert AuditEntry.objects.filter(booking=booking).count() == 1
