"""SCH-01: schedule persistence validates branch scope and exception shape."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from barbershop.booking.services import create_booking
from barbershop.catalog.models import Barber, BarberAssignment, Branch, Business, ServiceOffering
from barbershop.schedule.models import ScheduleException, ScheduleRule
from barbershop.schedule.services import ScheduleConflict, update_schedule_rule
from tests.support.booking import create_booking_scenario


def test_schedule_rule_rejects_empty_interval_without_database() -> None:
    """Проверить отказ для пустого интервала правила без обращения к базе."""
    rule = ScheduleRule(weekday=0, starts_at=time(10), ends_at=time(10))
    with pytest.raises(ValidationError, match="must not be empty"):
        rule.clean()


def test_closed_exception_has_no_interval() -> None:
    """Проверить отсутствие интервала у исключения закрытия."""
    exception = ScheduleException(
        local_date=date(2026, 1, 15),
        kind=ScheduleException.Kind.CLOSED,
        starts_at=time(10),
    )
    with pytest.raises(ValidationError):
        exception.clean()


@pytest.mark.django_db(transaction=True)
def test_schedule_rule_requires_a_branch_assignment() -> None:
    """Проверить требование назначения мастера в филиал для правила."""
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


@pytest.mark.django_db(transaction=True)
def test_schedule_cannot_be_shortened_over_future_booking() -> None:
    """Проверить запрет сокращения графика поверх будущей записи."""
    scenario = create_booking_scenario()
    booking = create_booking(scenario.command("schedule-conflict"))

    with pytest.raises(ScheduleConflict) as error:
        update_schedule_rule(scenario.rule.id, {"ends_at": time(10, 15)})

    scenario.rule.refresh_from_db()
    assert scenario.rule.ends_at == time(18)
    assert error.value.booking_ids == (booking.booking_id,)
