"""DB-01: PostgreSQL is the final guard for occupied booking intervals."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.db import IntegrityError

from barbershop.booking.models import Booking
from barbershop.catalog.models import Barber, Branch, Business, ServiceOffering


def test_booking_model_declares_protected_range_and_partial_exclusion() -> None:
    """Проверить декларацию диапазона занятости и частичного исключения."""
    constraints = {constraint.name: constraint for constraint in Booking._meta.constraints}
    exclusion = constraints["booking_barber_occupied_range_excludes_overlap"]

    assert exclusion.expressions == [("barber", "="), ("occupied_range", "&&")]
    assert exclusion.condition is not None
    assert not Booking._meta.get_field("occupied_range").editable
    field_names = {field.name for field in Booking._meta.fields}
    assert "buffer_before_seconds" not in field_names
    assert "buffer_after_seconds" not in field_names


@pytest.mark.django_db(transaction=True)
def test_postgres_exclusion_allows_neighbours_and_cancelled_but_rejects_overlap() -> None:
    """Проверить допуск соседних и отменённых записей при запрете пересечений."""
    business = Business.objects.create(name="Example")
    branch = Branch.objects.create(business=business, name="Main")
    barber = Barber.objects.create(display_name="Alex")
    service = ServiceOffering.objects.create(
        branch=branch,
        name="Cut",
        price=Decimal("10.00"),
        duration_seconds=1800,
    )
    start = datetime(2026, 1, 15, 10, tzinfo=UTC)

    def create(start_at: datetime, status: str = "CONFIRMED") -> Booking:
        """Создать запись с заданным началом и статусом."""
        return cast(
            Booking,
            Booking.objects.create(
                branch=branch,
                barber=barber,
                service=service,
                status=status,
                start_at=start_at,
                end_at=start_at + timedelta(minutes=30),
                service_name="Cut",
                service_price=Decimal("10.00"),
                currency="RUB",
                duration_seconds=1800,
                branch_timezone="Europe/Moscow",
            ),
        )

    create(start)
    create(start + timedelta(minutes=30))
    with pytest.raises(IntegrityError):
        create(start + timedelta(minutes=15))
    create(start + timedelta(minutes=15), "CANCELLED")
