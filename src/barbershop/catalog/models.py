"""Catalog models; booking and schedule state are deliberately out of scope."""

import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


class Business(models.Model):  # type: ignore[misc]
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        """Вернуть название компании для административного представления."""
        return str(self.name)


class Branch(models.Model):  # type: ignore[misc]
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="branches")
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="Europe/Moscow")
    horizon_days = models.PositiveSmallIntegerField(default=60)
    min_lead_minutes = models.PositiveIntegerField(default=30)
    grid_minutes = models.PositiveSmallIntegerField(default=15)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"], name="catalog_branch_business_name_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(horizon_days__gt=0), name="catalog_branch_horizon_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(grid_minutes__gt=0), name="catalog_branch_grid_positive"
            ),
        ]

    def __str__(self) -> str:
        """Вернуть название филиала вместе с идентификатором компании."""
        return f"{self.business_id}:{self.name}"

    def clean(self) -> None:
        """Проверить, что часовой пояс филиала существует в базе IANA."""
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValidationError({"timezone": "timezone must be a valid IANA zone"}) from error


class Barber(models.Model):  # type: ignore[misc]
    """Globally identified resource; branch access is represented by assignments."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    display_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        """Вернуть отображаемое имя мастера."""
        return str(self.display_name)


class ServiceOffering(models.Model):  # type: ignore[misc]
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="services")
    name = models.CharField(max_length=200)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    currency = models.CharField(
        max_length=3,
        default="RUB",
        validators=[RegexValidator(r"^[A-Z]{3}$", "currency must be an ISO-like uppercase code")],
    )
    duration_seconds = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"], name="catalog_service_branch_name_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0), name="catalog_service_price_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(duration_seconds__gt=0),
                name="catalog_service_duration_positive",
            ),
        ]

    def __str__(self) -> str:
        """Вернуть название услуги вместе с идентификатором филиала."""
        return f"{self.branch_id}:{self.name}"


class BarberAssignment(models.Model):  # type: ignore[misc]
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="assignments")
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="assignments")
    service = models.ForeignKey(
        ServiceOffering, on_delete=models.PROTECT, related_name="barber_assignments"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "barber", "service"],
                name="catalog_assignment_branch_barber_service_unique",
            )
        ]

    def __str__(self) -> str:
        """Вернуть составной идентификатор назначения мастера на услугу."""
        return f"{self.branch_id}:{self.barber_id}:{self.service_id}"

    def clean(self) -> None:
        """Проверить принадлежность услуги филиалу назначения."""
        if self.service_id and self.branch_id and self.service.branch_id != self.branch_id:
            raise ValidationError({"service": "service must belong to the assignment branch"})
