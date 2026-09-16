"""OUT-02: leased delivery safely recovers from failures and late owners."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from typing import cast

import pytest
from django.db import close_old_connections
from django.utils import timezone

from barbershop.journal.delivery import DeliveryTransportError, acknowledge, claim_next, deliver_one
from barbershop.journal.models import DeliveryState, OutboxEvent
from tests.integration.test_outbox import _create_booking


def _event() -> OutboxEvent:
    booking = _create_booking()
    return cast(
        OutboxEvent,
        OutboxEvent.objects.create(
            booking=booking,
            booking_version=1,
            event_kind="BOOKING_CREATED",
            schema_version=1,
            payload={"booking_id": str(booking.id), "status": "CONFIRMED", "version": 1},
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_expired_lease_is_reclaimed_and_old_owner_cannot_acknowledge() -> None:
    event = _event()
    first = claim_next("TEST")
    assert first is not None and first.event.id == event.id
    DeliveryState.objects.filter(pk=first.delivery_id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )

    recovered = claim_next("TEST")
    assert recovered is not None and recovered.delivery_id == first.delivery_id
    assert recovered.owner_token != first.owner_token
    assert not acknowledge(first.delivery_id, first.owner_token)
    assert acknowledge(recovered.delivery_id, recovered.owner_token)


@pytest.mark.django_db(transaction=True)
def test_transport_failure_retries_without_changing_outbox_event() -> None:
    event = _event()

    assert deliver_one("TEST", lambda _: (_ for _ in ()).throw(DeliveryTransportError("down")))
    delivery = DeliveryState.objects.get(event=event, destination="TEST")
    assert delivery.state == DeliveryState.State.PENDING
    assert delivery.last_error == "down"
    assert OutboxEvent.objects.get(pk=event.id).event_kind == "BOOKING_CREATED"

    DeliveryState.objects.filter(pk=delivery.id).update(available_at=timezone.now())
    received: list[str] = []
    assert deliver_one("TEST", lambda item: received.append(str(item.id)))
    delivery.refresh_from_db()
    assert received == [str(event.id)]
    assert delivery.state == DeliveryState.State.DELIVERED


@pytest.mark.django_db(transaction=True)
def test_two_workers_claim_distinct_events_with_independent_connections() -> None:
    """Проверить, что SKIP LOCKED не отдаёт одно событие двум worker."""
    first = _event()
    OutboxEvent.objects.create(
        booking=first.booking,
        booking_version=2,
        event_kind="BOOKING_RESCHEDULED",
        schema_version=1,
        payload={"booking_id": str(first.booking_id), "status": "CONFIRMED", "version": 2},
    )
    ready = Barrier(2)

    def claim() -> int:
        close_old_connections()
        try:
            ready.wait(timeout=10)
            claimed = claim_next("TEST")
            assert claimed is not None
            return cast(int, claimed.delivery_id)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(claim)
        second_future = executor.submit(claim)
        deliveries = [first_future.result(timeout=20), second_future.result(timeout=20)]

    assert len(set(deliveries)) == 2
