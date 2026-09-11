"""OUT-01: outbox events are unique and immutable."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction

from barbershop.booking.models import Booking
from barbershop.catalog.models import Barber, Branch, Business, ServiceOffering
from barbershop.journal.models import OutboxEvent


def _create_booking() -> Booking:
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


def test_payload_rejects_raw_or_contact_fields() -> None:
    event = OutboxEvent(payload={"booking_id": "id", "phone": "+79990000000"})
    with pytest.raises(ValidationError, match="unsupported payload key"):
        event.clean()


@pytest.mark.django_db(transaction=True)
def test_event_is_unique_and_database_rejects_mutation() -> None:
    booking = _create_booking()
    event = OutboxEvent.objects.create(
        booking=booking,
        booking_version=1,
        event_kind="BOOKING_CREATED",
        schema_version=1,
        payload={"booking_id": str(booking.id), "status": "CONFIRMED", "version": 1},
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        OutboxEvent.objects.create(
            booking=booking,
            booking_version=1,
            event_kind="BOOKING_CREATED",
            schema_version=1,
            payload=event.payload,
        )

    with pytest.raises(DatabaseError), transaction.atomic():
        OutboxEvent.objects.filter(pk=event.pk).update(event_kind="CHANGED")

    event.refresh_from_db()
    assert event.event_kind == "BOOKING_CREATED"
