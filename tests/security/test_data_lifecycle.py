"""SEC-01: privacy housekeeping removes replay bodies without reopening commands."""

from datetime import timedelta

import pytest
from django.utils import timezone

from barbershop.booking.services import create_booking
from barbershop.idempotency.models import CommandReceipt, PrivacyRedaction, ReceiptState
from barbershop.privacy import redact_expired_receipts
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_expired_receipt_is_redacted_to_a_tombstone() -> None:
    scenario = create_booking_scenario()
    create_booking(scenario.command("privacy"))
    receipt = CommandReceipt.objects.get(idempotency_key="privacy")
    CommandReceipt.objects.filter(pk=receipt.pk).update(
        response_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert redact_expired_receipts() == 1
    receipt.refresh_from_db()
    assert receipt.state == ReceiptState.TOMBSTONE
    assert receipt.response is None
    assert PrivacyRedaction.objects.filter(receipt=receipt).exists()
    assert redact_expired_receipts() == 0
