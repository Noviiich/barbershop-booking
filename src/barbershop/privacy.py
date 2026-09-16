"""Idempotent privacy housekeeping; policy approval remains an operational gate."""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from barbershop.idempotency.models import CommandReceipt, PrivacyRedaction, ReceiptState
from barbershop.identity.models import BookingManagementToken


@transaction.atomic  # type: ignore[untyped-decorator]
def redact_expired_receipts(now: datetime | None = None) -> int:
    """Replace expired replay bodies with tombstones, preserving dedup identity."""
    moment = now or timezone.now()
    receipts = CommandReceipt.objects.select_for_update().filter(
        state=ReceiptState.COMPLETED, response_expires_at__lte=moment
    )
    count = 0
    for receipt in receipts:
        receipt.state = ReceiptState.TOMBSTONE
        receipt.result_code = ""
        receipt.response = None
        receipt.response_expires_at = None
        receipt.completed_at = None
        receipt.save(
            update_fields=[
                "state",
                "result_code",
                "response",
                "response_expires_at",
                "completed_at",
            ]
        )
        PrivacyRedaction.objects.get_or_create(receipt=receipt)
        count += 1
    return count


@transaction.atomic  # type: ignore[untyped-decorator]
def revoke_old_management_tokens(now: datetime | None = None, *, retention_days: int = 90) -> int:
    """Remove encrypted guest capabilities after the approved retention window."""
    moment = now or timezone.now()
    cutoff = moment - timedelta(days=retention_days)
    deleted, _ = BookingManagementToken.objects.filter(created_at__lt=cutoff).delete()
    return int(deleted)
