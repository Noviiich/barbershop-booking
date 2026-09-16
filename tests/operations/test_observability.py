"""OBS-01: alert state and logs retain no client or booking data."""

from datetime import timedelta
from time import perf_counter

import pytest
from django.utils import timezone

from barbershop.booking.services import create_booking
from barbershop.journal.models import DeliveryState, OutboxEvent
from barbershop.observability import alerts, metrics, operation_log, record
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_alerts_and_json_logs_are_pii_safe(caplog: pytest.LogCaptureFixture) -> None:
    metrics.clear()
    caplog.set_level("INFO", logger="barbershop.operations")
    scenario = create_booking_scenario()
    event = scenario.command("observability").correlation_id
    del event
    record("auth.failure")
    operation_log("create", perf_counter(), outcome="conflict", trace_id="trace-fixture")
    assert "AUTH_FAILURE" in alerts()
    assert "trace-fixture" in caplog.text
    assert str(scenario.branch.id) not in caplog.text


@pytest.mark.django_db(transaction=True)
def test_overdue_outbox_backlog_alerts() -> None:
    scenario = create_booking_scenario()
    create_booking(scenario.command("overdue"))
    event = OutboxEvent.objects.get()
    DeliveryState.objects.create(
        event=event,
        destination="TEST",
        available_at=timezone.now() - timedelta(minutes=6),
    )
    assert "OUTBOX_BACKLOG_OVER_5M" in alerts()
