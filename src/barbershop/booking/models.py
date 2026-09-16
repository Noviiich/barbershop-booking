"""Physical booking invariant, guarded by PostgreSQL range exclusion."""

import uuid
from decimal import Decimal

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Func

from barbershop.catalog.models import Barber, Branch, ServiceOffering


class SecondsInterval(Func):  # type: ignore[misc]
    """PostgreSQL interval built from an integer number of seconds."""

    function = "make_interval"
    template = "%(function)s(secs => %(expressions)s)"


class BookingStatus(models.TextChoices):  # type: ignore[misc]
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"
    NO_SHOW = "NO_SHOW", "No show"


class Booking(models.Model):  # type: ignore[misc]
    """An immutable-resource visit with service snapshots and a DB-maintained occupied range."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="bookings")
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="bookings")
    service = models.ForeignKey(ServiceOffering, on_delete=models.PROTECT, related_name="bookings")
    status = models.CharField(max_length=16, choices=BookingStatus.choices)
    version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    service_name = models.CharField(max_length=200)
    service_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(
        max_length=3,
        validators=[RegexValidator(r"^[A-Z]{3}$", "currency must be an ISO-like uppercase code")],
    )
    duration_seconds = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    branch_timezone = models.CharField(max_length=64)
    occupied_range = DateTimeRangeField(editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="booking_version_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__gt=F("start_at")),
                name="booking_service_interval_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at=F("start_at") + SecondsInterval(F("duration_seconds"))),
                name="booking_service_interval_matches_duration",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_seconds__gt=0),
                name="booking_duration_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=BookingStatus.values),
                name="booking_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(service_price__gte=0), name="booking_price_nonnegative"
            ),
            ExclusionConstraint(
                name="booking_barber_occupied_range_excludes_overlap",
                expressions=[("barber", "="), ("occupied_range", "&&")],
                condition=~models.Q(status=BookingStatus.CANCELLED),
            ),
        ]

    def __str__(self) -> str:
        """Вернуть идентификатор записи для административного представления."""
        return str(self.id)

    def clean(self) -> None:
        """Проверить согласованность интервала, длительности и филиала услуги."""
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "must be after start_at"})
        if self.duration_seconds and self.start_at and self.end_at:
            elapsed_seconds = int((self.end_at - self.start_at).total_seconds())
            if elapsed_seconds != self.duration_seconds:
                raise ValidationError({"duration_seconds": "must match the service interval"})
        if self.service_id and self.branch_id and self.service.branch_id != self.branch_id:
            raise ValidationError({"service": "service must belong to the booking branch"})
