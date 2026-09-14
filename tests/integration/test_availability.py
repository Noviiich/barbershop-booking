"""AVL-01: availability is a bounded, read-only projection of PostgreSQL state."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from barbershop.booking.availability import (
    MAX_RANGE_DAYS,
    AvailabilityQuery,
    AvailabilityQueryError,
    list_available_slots,
)
from barbershop.booking.models import Booking
from barbershop.booking.services import create_booking
from barbershop.idempotency.models import CommandReceipt
from barbershop.journal.models import AuditEntry, OutboxEvent
from tests.support.booking import BookingScenario, create_booking_scenario


def _query_for_scenario(scenario: BookingScenario) -> AvailabilityQuery:
    local_date = scenario.start_at.astimezone(ZoneInfo(str(scenario.branch.timezone))).date()
    return AvailabilityQuery(
        business_id=scenario.business.id,
        branch_id=scenario.branch.id,
        date_from=local_date,
        date_to=local_date,
        barber_id=scenario.barber.id,
        service_id=scenario.service.id,
    )


@pytest.mark.django_db(transaction=True)
def test_published_slots_fit_schedule_and_are_accepted_without_state_change() -> None:
    scenario = create_booking_scenario()
    query = _query_for_scenario(scenario)

    slots = list_available_slots(query)

    assert slots
    assert scenario.start_at in {slot.start_at for slot in slots}
    assert all(slot.end_at - slot.start_at == timedelta(minutes=30) for slot in slots)
    assert max(slot.end_at for slot in slots).astimezone(ZoneInfo("Europe/Moscow")).hour == 18
    assert Booking.objects.count() == 0
    assert CommandReceipt.objects.count() == 0
    assert AuditEntry.objects.count() == 0
    assert OutboxEvent.objects.count() == 0

    for index, slot in enumerate(slots):
        with transaction.atomic():
            result = create_booking(scenario.command(f"published-{index}", start_at=slot.start_at))
            assert result.result_code == "CREATED"
            transaction.set_rollback(True)


@pytest.mark.django_db(transaction=True)
def test_occupied_candidates_are_removed_and_stale_slot_is_rejected() -> None:
    scenario = create_booking_scenario()
    query = _query_for_scenario(scenario)
    stale_slot = next(
        slot for slot in list_available_slots(query) if slot.start_at == scenario.start_at
    )

    created = create_booking(scenario.command("winner", start_at=stale_slot.start_at))
    remaining = list_available_slots(query)
    stale_result = create_booking(scenario.command("stale", start_at=stale_slot.start_at))

    assert created.result_code == "CREATED"
    assert stale_result.result_code == "SLOT_CONFLICT"
    assert all(
        slot.end_at <= stale_slot.start_at or stale_slot.end_at <= slot.start_at
        for slot in remaining
    )
    assert Booking.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_query_scope_filters_and_bounds_are_enforced() -> None:
    scenario = create_booking_scenario()
    query = _query_for_scenario(scenario)

    assert list_available_slots(replace(query, barber_id=uuid4())) == ()
    assert list_available_slots(replace(query, service_id=scenario.service.id + 1)) == ()
    assert len(list_available_slots(replace(query, limit=2))) == 2

    with pytest.raises(AvailabilityQueryError, match="scope"):
        list_available_slots(replace(query, business_id=uuid4()))
    with pytest.raises(AvailabilityQueryError, match="date_to"):
        list_available_slots(replace(query, date_to=query.date_from - timedelta(days=1)))
    with pytest.raises(AvailabilityQueryError, match="must not exceed"):
        list_available_slots(
            replace(query, date_to=query.date_from + timedelta(days=MAX_RANGE_DAYS))
        )
    with pytest.raises(AvailabilityQueryError, match="limit"):
        list_available_slots(replace(query, limit=0))
