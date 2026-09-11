"""Persisted weekly rules and dated local-calendar exceptions."""

import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models

from barbershop.catalog.models import Barber, Branch


class ScheduleRule(models.Model):  # type: ignore[misc]
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="schedule_rules")
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="schedule_rules")
    weekday = models.PositiveSmallIntegerField()
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "barber", "weekday", "starts_at", "ends_at"],
                name="schedule_rule_branch_barber_slot_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0) & models.Q(weekday__lte=6),
                name="schedule_rule_weekday_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.branch_id}:{self.barber_id}:{self.weekday}:{self.starts_at}-{self.ends_at}"

    def clean(self) -> None:
        if self.starts_at == self.ends_at:
            raise ValidationError("schedule interval must not be empty")
        if (
            self.branch_id
            and self.barber_id
            and not Barber.objects.filter(
                id=self.barber_id, assignments__branch_id=self.branch_id
            ).exists()
        ):
            raise ValidationError({"barber": "barber is not assigned to the branch"})


class ScheduleException(models.Model):  # type: ignore[misc]
    class Kind(models.TextChoices):  # type: ignore[misc]
        CLOSED = "CLOSED", "Closed"
        REPLACEMENT = "REPLACEMENT", "Replacement"

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="schedule_exceptions")
    barber = models.ForeignKey(Barber, on_delete=models.PROTECT, related_name="schedule_exceptions")
    local_date = models.DateField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    starts_at = models.TimeField(null=True, blank=True)
    ends_at = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "barber", "local_date"],
                name="schedule_exception_branch_barber_date_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="CLOSED", starts_at__isnull=True, ends_at__isnull=True)
                    | models.Q(
                        kind="REPLACEMENT",
                        starts_at__isnull=False,
                        ends_at__isnull=False,
                    )
                ),
                name="schedule_exception_kind_times_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.branch_id}:{self.barber_id}:{self.local_date}:{self.kind}"

    def clean(self) -> None:
        if self.local_date is None or not isinstance(self.local_date, date):
            raise ValidationError({"local_date": "a local calendar date is required"})
        if self.kind == self.Kind.CLOSED and (self.starts_at or self.ends_at):
            raise ValidationError("closed exception cannot have an interval")
        if self.kind == self.Kind.REPLACEMENT and (self.starts_at is None or self.ends_at is None):
            raise ValidationError("replacement exception requires an interval")
        if self.kind == self.Kind.REPLACEMENT and self.starts_at == self.ends_at:
            raise ValidationError("replacement interval must not be empty")
        if (
            self.branch_id
            and self.barber_id
            and not Barber.objects.filter(
                id=self.barber_id, assignments__branch_id=self.branch_id
            ).exists()
        ):
            raise ValidationError({"barber": "barber is not assigned to the branch"})
