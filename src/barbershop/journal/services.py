"""Atomic append helper shared by future booking commands."""

from typing import cast
from uuid import UUID

from django.db import transaction

from barbershop.booking.models import Booking
from barbershop.journal.models import AuditEntry, OutboxEvent


def append_booking_change(
    booking: Booking,
    *,
    operation: str,
    event_kind: str,
    actor_kind: str,
    actor_id: str,
    correlation_id: UUID,
    reason_code: str = "",
) -> tuple[AuditEntry, OutboxEvent]:
    """Append audit/outbox rows inside the caller's booking transaction."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("booking journal must be appended inside transaction.atomic")
    if booking.pk is None:
        raise ValueError("booking must be persisted before its journal entries")

    audit = cast(
        AuditEntry,
        AuditEntry.objects.create(
            booking=booking,
            booking_version=booking.version,
            operation=operation,
            actor_kind=actor_kind,
            actor_id=actor_id,
            reason_code=reason_code,
            correlation_id=correlation_id,
        ),
    )
    event = OutboxEvent(
        booking=booking,
        booking_version=booking.version,
        event_kind=event_kind,
        schema_version=1,
        payload={
            "booking_id": str(booking.pk),
            "status": booking.status,
            "version": booking.version,
        },
    )
    event.full_clean()
    event.save(force_insert=True)
    return audit, event
