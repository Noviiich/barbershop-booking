"""SCH-01: schedule persistence validates branch scope and exception shape."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from barbershop.catalog.models import Barber, BarberAssignment, Branch, Business, ServiceOffering
from barbershop.schedule.models import ScheduleException, ScheduleRule


def test_schedule_rule_rejects_empty_interval_without_database() -> None:
    rule = ScheduleRule(weekday=0, starts_at=time(10), ends_at=time(10))
    with pytest.raises(ValidationError, match="must not be empty"):
        rule.clean()


def test_closed_exception_has_no_interval() -> None:
    exception = ScheduleException(
        local_date=date(2026, 1, 15),
        kind=ScheduleException.Kind.CLOSED,
        starts_at=time(10),
    )
    with pytest.raises(ValidationError):
        exception.clean()


@pytest.mark.django_db(transaction=True)
def test_schedule_rule_requires_a_branch_assignment() -> None:
    business = Business.objects.create(name="Example")
    branch = Branch.objects.create(business=business, name="Main")
    barber = Barber.objects.create(display_name="Alex")
    service = ServiceOffering.objects.create(
        branch=branch,
        name="Cut",
        price=Decimal("10.00"),
        duration_seconds=1800,
    )
    rule = ScheduleRule(
        branch=branch,
        barber=barber,
        weekday=0,
        starts_at=time(9),
        ends_at=time(17),
    )
    with pytest.raises(ValidationError, match="not assigned"):
        rule.full_clean()
    BarberAssignment.objects.create(branch=branch, barber=barber, service=service)
    rule.full_clean()
