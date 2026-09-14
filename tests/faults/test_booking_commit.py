"""TX-01: failures roll back every mandatory create effect."""

import pytest

from barbershop.booking.models import Booking
from barbershop.booking.services import create_booking
from barbershop.idempotency.models import CommandReceipt
from barbershop.journal.models import AuditEntry, OutboxEvent
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_failure_after_booking_insert_rolls_back_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = create_booking_scenario()

    def fail_journal(*args: object, **kwargs: object) -> None:
        raise RuntimeError("failpoint after booking")

    monkeypatch.setattr("barbershop.booking.services.append_booking_change", fail_journal)
    with pytest.raises(RuntimeError, match="failpoint"):
        create_booking(scenario.command("rollback-key"))

    assert Booking.objects.count() == 0
    assert AuditEntry.objects.count() == 0
    assert OutboxEvent.objects.count() == 0
    assert CommandReceipt.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_lost_response_replay_returns_original_booking() -> None:
    scenario = create_booking_scenario()
    command = scenario.command("lost-response")

    first = create_booking(command)
    replay = create_booking(command)

    assert first.result_code == "CREATED"
    assert replay.result_code == "CREATED"
    assert replay.replayed
    assert replay.booking_id == first.booking_id
    assert Booking.objects.count() == 1
    assert AuditEntry.objects.count() == 1
    assert OutboxEvent.objects.count() == 1
