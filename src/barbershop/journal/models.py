"""Immutable records created alongside a booking mutation."""

import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from barbershop.booking.models import Booking


class ActorKind(models.TextChoices):  # type: ignore[misc]
    USER = "USER", "User"
    INTEGRATION = "INTEGRATION", "Integration"
    SYSTEM = "SYSTEM", "System"


class AuditEntry(models.Model):  # type: ignore[misc]
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="audit_entries")
    booking_version = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    operation = models.CharField(max_length=64)
    actor_kind = models.CharField(max_length=16, choices=ActorKind.choices)
    actor_id = models.CharField(max_length=64, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    correlation_id = models.UUIDField()
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "booking_version"],
                name="journal_audit_booking_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(booking_version__gte=1),
                name="journal_audit_booking_version_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.booking_id}:{self.booking_version}:{self.operation}"


class OutboxEvent(models.Model):  # type: ignore[misc]
    ALLOWED_PAYLOAD_KEYS = frozenset({"booking_id", "status", "version"})

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="outbox_events")
    booking_version = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    event_kind = models.CharField(max_length=64)
    schema_version = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    payload = models.JSONField()
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "booking_version", "event_kind"],
                name="journal_outbox_booking_version_kind_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(booking_version__gte=1),
                name="journal_outbox_booking_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__gte=1),
                name="journal_outbox_schema_version_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.booking_id}:{self.booking_version}:{self.event_kind}"

    def clean(self) -> None:
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "payload must be an object"})
        unknown_keys = set(self.payload) - self.ALLOWED_PAYLOAD_KEYS
        if unknown_keys:
            raise ValidationError(
                {"payload": f"unsupported payload key: {sorted(unknown_keys)[0]}"}
            )
