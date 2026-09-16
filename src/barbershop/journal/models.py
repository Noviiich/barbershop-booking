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
        """Вернуть запись, версию и операцию аудита."""
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
        """Вернуть запись, версию и вид исходящего события."""
        return f"{self.booking_id}:{self.booking_version}:{self.event_kind}"

    def clean(self) -> None:
        """Проверить тип и разрешённые поля полезной нагрузки события."""
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "payload must be an object"})
        unknown_keys = set(self.payload) - self.ALLOWED_PAYLOAD_KEYS
        if unknown_keys:
            raise ValidationError(
                {"payload": f"unsupported payload key: {sorted(unknown_keys)[0]}"}
            )


class DeliveryState(models.Model):  # type: ignore[misc]
    """Per-destination delivery lease; it never changes Booking lifecycle."""

    class State(models.TextChoices):  # type: ignore[misc]
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        DELIVERED = "DELIVERED", "Delivered"
        PARKED = "PARKED", "Parked"

    event = models.ForeignKey(OutboxEvent, on_delete=models.PROTECT, related_name="deliveries")
    destination = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    owner_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "destination"], name="journal_delivery_event_destination_unique"
            )
        ]

    def __str__(self) -> str:
        """Вернуть событие и получатель его доставки."""
        return f"{self.event_id}:{self.destination}"
