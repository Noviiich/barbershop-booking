"""LIFE-01: cancellation is versioned, idempotent, and releases its interval."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from barbershop.booking.availability import AvailabilityQuery, list_available_slots
from barbershop.booking.cancellation import CancellationRuleViolation, cancel_booking
from barbershop.booking.models import Booking, BookingStatus
from barbershop.booking.services import create_booking
from barbershop.idempotency.models import CommandReceipt
from barbershop.journal.models import AuditEntry, OutboxEvent
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_cancel_releases_slot_and_replays_without_new_effects() -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create"))
    assert created.booking_id is not None
    command = scenario.cancel_command("cancel", created.booking_id, reason_code="CUSTOMER_REQUEST")

    result = cancel_booking(command)
    replay = cancel_booking(command)
    no_op = cancel_booking(
        scenario.cancel_command("cancel-again", created.booking_id, expected_version=1)
    )

    booking = Booking.objects.get(pk=created.booking_id)
    audit = AuditEntry.objects.get(booking=booking, booking_version=2)
    local_date = booking.start_at.astimezone(ZoneInfo(str(scenario.branch.timezone))).date()
    slots = list_available_slots(
        AvailabilityQuery(
            business_id=scenario.business.id,
            branch_id=scenario.branch.id,
            date_from=local_date,
            date_to=local_date,
            barber_id=scenario.barber.id,
            service_id=scenario.service.id,
        )
    )

    assert result.result_code == "CANCELLED"
    assert result.version == 2
    assert not result.no_op
    assert replay.replayed and replay.version == 2
    assert no_op.no_op and no_op.version == 2
    assert booking.status == BookingStatus.CANCELLED
    assert audit.reason_code == "CUSTOMER_REQUEST"
    assert scenario.start_at in {slot.start_at for slot in slots}
    assert AuditEntry.objects.filter(booking=booking).count() == 2
    assert OutboxEvent.objects.filter(booking=booking).count() == 2


@pytest.mark.django_db(transaction=True)
def test_version_state_and_scope_conflicts_do_not_change_booking() -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-conflicts"))
    assert created.booking_id is not None

    version_conflict = cancel_booking(
        scenario.cancel_command("wrong-version", created.booking_id, expected_version=2)
    )
    wrong_scope = scenario.cancel_command("wrong-scope", created.booking_id)
    wrong_scope = replace(
        wrong_scope,
        scope=replace(wrong_scope.scope, business_id=uuid4()),
    )
    with pytest.raises(CancellationRuleViolation, match="scope"):
        cancel_booking(wrong_scope)

    booking = Booking.objects.get(pk=created.booking_id)
    booking.status = BookingStatus.COMPLETED
    booking.save(update_fields=["status"])
    state_conflict = cancel_booking(
        scenario.cancel_command("wrong-state", created.booking_id, expected_version=1)
    )

    assert version_conflict.result_code == "VERSION_CONFLICT"
    assert state_conflict.result_code == "STATE_CONFLICT"
    assert Booking.objects.get(pk=created.booking_id).version == 1
    assert not CommandReceipt.objects.filter(idempotency_key="wrong-scope").exists()
    assert AuditEntry.objects.filter(booking_id=created.booking_id).count() == 1
    assert OutboxEvent.objects.filter(booking_id=created.booking_id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_cancellation_window_and_trusted_override_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-window"))
    assert created.booking_id is not None
    monkeypatch.setattr(
        "barbershop.booking.cancellation.database_now",
        lambda: scenario.start_at - timedelta(hours=1),
    )

    closed = cancel_booking(scenario.cancel_command("closed", created.booking_id))
    override = scenario.cancel_command(
        "override",
        created.booking_id,
        override=True,
        reason_code="STAFF_OVERRIDE",
    )
    with pytest.raises(CancellationRuleViolation, match="staff authority"):
        cancel_booking(override)
    accepted = cancel_booking(override, allow_override=True)

    assert closed.result_code == "CANCELLATION_CLOSED"
    assert accepted.result_code == "CANCELLED"
    assert not CommandReceipt.objects.filter(
        idempotency_key="override",
        state="PROCESSING",
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_override_cannot_cancel_after_start(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-started"))
    assert created.booking_id is not None
    monkeypatch.setattr(
        "barbershop.booking.cancellation.database_now",
        lambda: scenario.start_at + timedelta(seconds=1),
    )

    result = cancel_booking(
        scenario.cancel_command(
            "started",
            created.booking_id,
            override=True,
            reason_code="STAFF_OVERRIDE",
        ),
        allow_override=True,
    )

    assert result.result_code == "CANCELLATION_CLOSED"
    assert Booking.objects.get(pk=created.booking_id).status == BookingStatus.CONFIRMED


@pytest.mark.django_db(transaction=True)
def test_customer_can_cancel_at_exact_two_hour_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-boundary"))
    assert created.booking_id is not None
    monkeypatch.setattr(
        "barbershop.booking.cancellation.database_now",
        lambda: scenario.start_at - timedelta(hours=2),
    )

    result = cancel_booking(scenario.cancel_command("boundary", created.booking_id))

    assert result.result_code == "CANCELLED"


@pytest.mark.django_db(transaction=True)
def test_journal_failure_rolls_back_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = create_booking_scenario()
    created = create_booking(scenario.command("create-rollback"))
    assert created.booking_id is not None

    def fail_journal(*args: object, **kwargs: object) -> None:
        raise RuntimeError("failpoint after cancellation")

    monkeypatch.setattr("barbershop.booking.cancellation.append_booking_change", fail_journal)
    with pytest.raises(RuntimeError, match="failpoint"):
        cancel_booking(scenario.cancel_command("cancel-rollback", created.booking_id))

    booking = Booking.objects.get(pk=created.booking_id)
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.version == 1
    assert not CommandReceipt.objects.filter(idempotency_key="cancel-rollback").exists()
    assert AuditEntry.objects.filter(booking=booking).count() == 1
    assert OutboxEvent.objects.filter(booking=booking).count() == 1
