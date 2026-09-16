"""YAN-01: mapped Yandex reads are authenticated, scoped and disabled by default."""

import base64
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.test import Client, override_settings

from barbershop.catalog.models import BarberAssignment
from barbershop.integration.models import (
    YandexBarberMapping,
    YandexBranchMapping,
    YandexConnection,
    YandexServiceMapping,
)
from tests.support.booking import create_booking_scenario


def _token(payload: dict[str, str], secret: str = "contract-secret") -> str:
    def encode(value: dict[str, str]) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")

    header, body = encode({"alg": "HS256", "typ": "JWT"}), encode(payload)
    signature = hmac.new(secret.encode(), header + b"." + body, hashlib.sha256).digest()
    return (
        "Bearer "
        + b".".join((header, body, base64.urlsafe_b64encode(signature).rstrip(b"="))).decode()
    )


@pytest.mark.django_db(transaction=True)
def test_reads_are_disabled_then_return_only_mapped_primary_data() -> None:
    scenario = create_booking_scenario()
    connection = YandexConnection.objects.create(
        business=scenario.business,
        partner_name="partner-fixture",
        catalog_read_enabled=True,
        availability_read_enabled=True,
    )
    YandexBranchMapping.objects.create(
        connection=connection,
        branch=scenario.branch,
        external_id="company-1",
        permalink="123",
        address="Fixture address",
        latitude=Decimal("55.750000"),
        longitude=Decimal("37.610000"),
    )
    YandexServiceMapping.objects.create(
        connection=connection, service=scenario.service, external_id="service-1"
    )
    YandexBarberMapping.objects.create(
        connection=connection, barber=scenario.barber, external_id="barber-1"
    )
    client = Client()
    assert client.get("/companies/feed").status_code == 404

    with override_settings(
        YANDEX_BOOKING_READ_ENABLED=True,
        YANDEX_BOOKING_JWT_SECRET="contract-secret",
        YANDEX_BOOKING_PARTNER_NAME="partner-fixture",
    ):
        feed_response = client.get(
            "/companies/feed?count=1", HTTP_AUTHORIZATION=_token({"sub": "partner-fixture"})
        )
        services_response = client.get(
            "/companies/company-1/services",
            HTTP_AUTHORIZATION=_token({"sub": "partner-fixture", "companyId": "company-1"}),
        )
        slots_response = client.get(
            "/companies/company-1/available_time_slots?serviceIds[]=service-1&resourceId=barber-1&date="
            + scenario.start_at.astimezone().date().isoformat(),
            HTTP_AUTHORIZATION=_token({"sub": "partner-fixture", "companyId": "company-1"}),
        )
        denied = client.get(
            "/companies/company-1/services",
            HTTP_AUTHORIZATION=_token({"sub": "partner-fixture", "companyId": "other"}),
        )

    assert feed_response.status_code == 200
    assert feed_response.json()["companies"][0]["id"] == "company-1"
    assert services_response.json()["services"][0]["durationSeconds"] == 1800
    assert slots_response.status_code == 200
    assert slots_response.json()["availableTimeSlots"]
    assert denied.status_code == 404
    assert BarberAssignment.objects.count() == 1
