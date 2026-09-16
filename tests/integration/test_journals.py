"""AUD-01: booking mutation, audit and event share one transaction."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction

from barbershop.booking.models import Booking
from barbershop.catalog.models import Barber, Branch, Business, ServiceOffering
from barbershop.journal.models import AuditEntry, OutboxEvent
from barbershop.journal.services import append_booking_change


def _create_booking() -> Booking:
    """Создать запись с минимальным набором связанных данных."""
    business = Business.objects.create(name="Example")
    branch = Branch.objects.create(business=business, name="Main")
    barber = Barber.objects.create(display_name="Alex")
    service = ServiceOffering.objects.create(
        branch=branch,
        name="Cut",
        price=Decimal("10.00"),
        duration_seconds=1800,
    )
    start = datetime(2026, 1, 15, 10, tzinfo=UTC)
    return cast(
        Booking,
        Booking.objects.create(
            branch=branch,
            barber=barber,
            service=service,
            status="CONFIRMED",
            start_at=start,
            end_at=start + timedelta(minutes=30),
            service_name="Cut",
            service_price=Decimal("10.00"),
            currency="RUB",
            duration_seconds=1800,
            branch_timezone="Europe/Moscow",
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_rollback_removes_booking_audit_and_outbox() -> None:
    """Проверить удаление записи, аудита и outbox при откате."""

    class ForcedRollback(Exception):
        pass

    with pytest.raises(ForcedRollback), transaction.atomic():
        booking = _create_booking()
        append_booking_change(
            booking,
            operation="BOOKING_CREATED",
            event_kind="BOOKING_CREATED",
            actor_kind="SYSTEM",
            actor_id="system",
            correlation_id=uuid4(),
        )
        raise ForcedRollback

    assert Booking.objects.count() == 0
    assert AuditEntry.objects.count() == 0
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_commit_preserves_matching_booking_version_and_minimal_payload() -> None:
    """Проверить согласованную версию и минимальную нагрузку после commit."""
    with transaction.atomic():
        booking = _create_booking()
        audit, event = append_booking_change(
            booking,
            operation="BOOKING_CREATED",
            event_kind="BOOKING_CREATED",
            actor_kind="SYSTEM",
            actor_id="system",
            correlation_id=uuid4(),
        )

    assert audit.booking_id == booking.id
    assert audit.booking_version == booking.version
    assert event.booking_id == booking.id
    assert event.booking_version == booking.version
    assert event.payload == {
        "booking_id": str(booking.id),
        "status": "CONFIRMED",
        "version": 1,
    }

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEntry.objects.filter(pk=audit.pk).update(operation="CHANGED")
