"""CAT-01: catalog invariants and branch-scoped assignments."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from barbershop.booking.models import Booking
from barbershop.booking.services import create_booking
from barbershop.catalog.models import Barber, BarberAssignment, Branch, Business, ServiceOffering
from barbershop.catalog.services import update_service_offering
from tests.support.booking import create_booking_scenario


def test_barber_is_global_and_service_uses_exact_money_fields() -> None:
    """Проверить глобальность мастера и точные денежные поля услуги."""
    assert Barber._meta.get_field("id").primary_key

    price = ServiceOffering._meta.get_field("price")
    assert price.max_digits == 10
    assert price.decimal_places == 2
    assert price.to_python("12.30") == Decimal("12.30")
    assert "buffer_before_seconds" not in {field.name for field in ServiceOffering._meta.fields}
    assert "buffer_after_seconds" not in {field.name for field in ServiceOffering._meta.fields}


def test_invalid_timezone_and_non_positive_duration_are_rejected() -> None:
    """Проверить отказ для неверного часового пояса и неположительной длительности."""
    business = Business(name="Example")
    invalid_branch = Branch(business=business, name="Main", timezone="Not/IANA")

    with pytest.raises(ValidationError, match="valid IANA zone"):
        invalid_branch.clean()

    valid_branch = Branch(business=business, name="Main")
    invalid_service = ServiceOffering(
        branch=valid_branch,
        name="Cut",
        price=Decimal("10.00"),
        duration_seconds=0,
    )
    duration_field = ServiceOffering._meta.get_field("duration_seconds")
    with pytest.raises(ValidationError):
        duration_field.clean(invalid_service.duration_seconds, invalid_service)


@pytest.mark.django_db(transaction=True)
def test_assignment_rejects_service_from_another_branch_and_deduplicates() -> None:
    """Проверить область услуги и уникальность назначения мастера."""
    business = Business.objects.create(name="Example")
    branch_a = Branch.objects.create(business=business, name="A")
    branch_b = Branch.objects.create(business=business, name="B")
    barber = Barber.objects.create(display_name="Alex")
    service = ServiceOffering.objects.create(
        branch=branch_b,
        name="Cut",
        price=Decimal("10.00"),
        duration_seconds=1800,
    )

    invalid_assignment = BarberAssignment(
        branch=branch_a,
        barber=barber,
        service=service,
    )
    with pytest.raises(ValidationError, match="belong to the assignment branch"):
        invalid_assignment.full_clean()

    valid_assignment = BarberAssignment.objects.create(
        branch=branch_b,
        barber=barber,
        service=service,
    )
    with pytest.raises(IntegrityError):
        BarberAssignment.objects.create(
            branch=branch_b,
            barber=barber,
            service=service,
        )
    assert valid_assignment.pk is not None


@pytest.mark.django_db(transaction=True)
def test_catalog_change_does_not_rewrite_booking_snapshot() -> None:
    """Проверить неизменность снимка записи после изменения каталога."""
    scenario = create_booking_scenario()
    result = create_booking(scenario.command("catalog-snapshot"))

    update_service_offering(
        scenario.service.id,
        {"name": "New cut", "price": Decimal("25.00"), "duration_seconds": 3600},
    )
    booking = Booking.objects.get(pk=result.booking_id)

    assert booking.service_name == "Cut"
    assert booking.service_price == Decimal("10.00")
    assert booking.duration_seconds == 1800
