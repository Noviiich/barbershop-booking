"""Generic leased outbox delivery with no knowledge of external contracts."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from threading import Event
from typing import cast
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from barbershop.journal.models import DeliveryState, OutboxEvent
from barbershop.observability import record

LEASE_SECONDS = 30
MAX_ATTEMPTS = 20


@dataclass(frozen=True)
class ClaimedDelivery:
    delivery_id: int
    owner_token: UUID
    event: OutboxEvent


class DeliveryTransportError(Exception):
    """A retryable failure reported by the generic test transport."""


@transaction.atomic  # type: ignore[untyped-decorator]
def claim_next(destination: str) -> ClaimedDelivery | None:
    """Claim one ready delivery with SKIP LOCKED and commit before transport I/O."""
    now = timezone.now()
    DeliveryState.objects.bulk_create(
        [
            DeliveryState(event=event, destination=destination, available_at=now)
            for event in OutboxEvent.objects.order_by("occurred_at", "id")
        ],
        ignore_conflicts=True,
    )
    delivery = (
        DeliveryState.objects.select_for_update(skip_locked=True)
        .select_related("event")
        .filter(destination=destination)
        .filter(
            Q(state=DeliveryState.State.PENDING, available_at__lte=now)
            | Q(state=DeliveryState.State.PROCESSING, lease_expires_at__lte=now)
        )
        .order_by("available_at", "id")
        .first()
    )
    if delivery is None:
        return None
    token = uuid4()
    delivery.state = DeliveryState.State.PROCESSING
    delivery.owner_token = token
    delivery.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    delivery.attempts += 1
    delivery.save(update_fields=["state", "owner_token", "lease_expires_at", "attempts"])
    record("outbox.lease.claimed")
    return ClaimedDelivery(delivery.id, token, cast(OutboxEvent, delivery.event))


@transaction.atomic  # type: ignore[untyped-decorator]
def acknowledge(delivery_id: int, owner_token: UUID) -> bool:
    """Fence a success acknowledgement to the owner of the current lease."""
    now = timezone.now()
    updated = DeliveryState.objects.filter(
        pk=delivery_id,
        state=DeliveryState.State.PROCESSING,
        owner_token=owner_token,
        lease_expires_at__gt=now,
    ).update(
        state=DeliveryState.State.DELIVERED,
        delivered_at=now,
        owner_token=None,
        lease_expires_at=None,
        last_error="",
    )
    return bool(updated == 1)


@transaction.atomic  # type: ignore[untyped-decorator]
def fail(delivery_id: int, owner_token: UUID, error: str) -> bool:
    """Release the current lease with bounded exponential retry or parking."""
    delivery = (
        DeliveryState.objects.select_for_update()
        .filter(pk=delivery_id, state=DeliveryState.State.PROCESSING, owner_token=owner_token)
        .first()
    )
    if delivery is None:
        return False
    now = timezone.now()
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.state = DeliveryState.State.PARKED
        delivery.available_at = now
    else:
        delivery.state = DeliveryState.State.PENDING
        delivery.available_at = now + timedelta(seconds=min(300, 2 ** min(delivery.attempts, 8)))
    delivery.owner_token = None
    delivery.lease_expires_at = None
    delivery.last_error = error[:200]
    delivery.save()
    record("outbox.parked" if delivery.state == DeliveryState.State.PARKED else "outbox.retry")
    return True


def deliver_one(destination: str, transport: Callable[[OutboxEvent], None]) -> bool:
    """Send one claimed event outside transactions, then fence its acknowledgement."""
    claim = claim_next(destination)
    if claim is None:
        return False
    try:
        transport(claim.event)
    except DeliveryTransportError as error:
        fail(claim.delivery_id, claim.owner_token, str(error))
    else:
        acknowledge(claim.delivery_id, claim.owner_token)
    return True


def run_worker(
    destination: str,
    transport: Callable[[OutboxEvent], None],
    stop: Event,
    *,
    poll_interval_seconds: float = 0.25,
) -> None:
    """Run a stoppable worker process loop; network I/O remains outside DB transactions."""
    while not stop.is_set():
        if not deliver_one(destination, transport):
            stop.wait(poll_interval_seconds)
