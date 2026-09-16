"""Persistent identity and result of one idempotent command."""

import uuid

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


class ReceiptState(models.TextChoices):  # type: ignore[misc]
    PROCESSING = "PROCESSING", "Processing"
    COMPLETED = "COMPLETED", "Completed"
    TOMBSTONE = "TOMBSTONE", "Tombstone"


class CommandReceipt(models.Model):  # type: ignore[misc]
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    scope_digest = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}$", "scope digest must be SHA-256")],
    )
    operation = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    fingerprint_version = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    fingerprint = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}$", "fingerprint must be SHA-256")],
    )
    state = models.CharField(max_length=16, choices=ReceiptState.choices)
    result_code = models.CharField(max_length=64, blank=True)
    response = models.JSONField(null=True, blank=True)
    response_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope_digest", "operation", "idempotency_key"],
                name="idempotency_scope_operation_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(fingerprint_version__gte=1),
                name="idempotency_fingerprint_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=ReceiptState.values),
                name="idempotency_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state=ReceiptState.COMPLETED,
                        response__isnull=False,
                        response_expires_at__isnull=False,
                        completed_at__isnull=False,
                    )
                    | models.Q(
                        state__in=[ReceiptState.PROCESSING, ReceiptState.TOMBSTONE],
                        response__isnull=True,
                    )
                ),
                name="idempotency_state_result_consistent",
            ),
        ]

    def __str__(self) -> str:
        """Вернуть составную идентичность идемпотентной команды."""
        return f"{self.scope_digest}:{self.operation}:{self.idempotency_key}"


class PrivacyRedaction(models.Model):  # type: ignore[misc]
    """Durable proof that a replay body was removed and must stay removed after restore."""

    receipt = models.OneToOneField(
        CommandReceipt, on_delete=models.PROTECT, related_name="redaction"
    )
    reason = models.CharField(max_length=64, default="RESPONSE_RETENTION_EXPIRED")
    redacted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.receipt_id)
