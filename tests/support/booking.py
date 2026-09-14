"""PostgreSQL booking scenario used by command-service tests."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.utils import timezone

from barbershop.booking.services import CreateBookingCommand
from barbershop.catalog.models import Barber, BarberAssignment, Branch, Business, ServiceOffering
from barbershop.idempotency.services import CommandScope
from barbershop.schedule.calendar import local_to_utc
from barbershop.schedule.models import ScheduleRule


@dataclass(frozen=True)
class BookingScenario:
    business: Business
    branch: Branch
    barber: Barber
    service: ServiceOffering
    rule: ScheduleRule
    start_at: datetime

    def command(self, key: str, *, start_at: datetime | None = None) -> CreateBookingCommand:
        return CreateBookingCommand(
            scope=CommandScope(
                business_id=self.business.id,
                principal_kind="SYSTEM",
                principal_id="test-system",
                channel="TEST",
            ),
            idempotency_key=key,
            branch_id=self.branch.id,
            barber_id=self.barber.id,
            service_id=self.service.id,
            start_at=start_at or self.start_at,
            correlation_id=uuid4(),
        )


def create_booking_scenario() -> BookingScenario:
    business = cast(Business, Business.objects.create(name="Example"))
    branch = cast(
        Branch,
        Branch.objects.create(
            business=business,
            name="Main",
            timezone="Europe/Moscow",
            horizon_days=60,
            min_lead_minutes=30,
            grid_minutes=15,
        ),
    )
    barber = cast(Barber, Barber.objects.create(display_name="Alex"))
    service = cast(
        ServiceOffering,
        ServiceOffering.objects.create(
            branch=branch,
            name="Cut",
            price=Decimal("10.00"),
            currency="RUB",
            duration_seconds=1800,
        ),
    )
    BarberAssignment.objects.create(branch=branch, barber=barber, service=service)
    zone = ZoneInfo("Europe/Moscow")
    local_date = timezone.now().astimezone(zone).date() + timedelta(days=3)
    rule = cast(
        ScheduleRule,
        ScheduleRule.objects.create(
            branch=branch,
            barber=barber,
            weekday=local_date.weekday(),
            starts_at=time(9),
            ends_at=time(18),
        ),
    )
    start_at = local_to_utc(local_date, time(10), zone)
    return BookingScenario(business, branch, barber, service, rule, start_at)
