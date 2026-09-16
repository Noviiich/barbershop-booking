"""API-01: guest booking transport delegates to transactional services."""

import json

import pytest
from django.test import Client

from barbershop.idempotency.models import CommandReceipt
from barbershop.identity.models import BookingManagementToken
from tests.support.booking import create_booking_scenario


@pytest.mark.django_db(transaction=True)
def test_guest_create_replay_and_management_scope() -> None:
    scenario = create_booking_scenario()
    client = Client()
    payload = {
        "branch_id": str(scenario.branch.id),
        "barber_id": str(scenario.barber.id),
        "service_id": scenario.service.id,
        "start_at": scenario.start_at.isoformat(),
    }
    headers = {"HTTP_IDEMPOTENCY_KEY": "guest-create"}

    created = client.post("/api/v1/bookings/", data=json.dumps(payload), content_type="application/json", **headers)
    replay = client.post("/api/v1/bookings/", data=json.dumps(payload), content_type="application/json", **headers)

    assert created.status_code == 201
    assert replay.status_code == 201
    assert created["Cache-Control"] == "no-store"
    assert created.json()["booking_id"] == replay.json()["booking_id"]
    assert created.json()["management_token"] == replay.json()["management_token"]
    assert not BookingManagementToken.objects.filter(
        token_hash=created.json()["management_token"]
    ).exists()
    receipt = CommandReceipt.objects.get(idempotency_key="guest-create")
    assert "management_token_encrypted" in receipt.response
    assert created.json()["management_token"] not in str(receipt.response)

    booking_id = created.json()["booking_id"]
    token = created.json()["management_token"]
    accessible = client.get(f"/api/v1/bookings/{booking_id}/", HTTP_AUTHORIZATION=f"Booking {token}")
    other_client = Client()
    denied = other_client.get(f"/api/v1/bookings/{booking_id}/", HTTP_AUTHORIZATION=f"Booking {token}")

    assert accessible.status_code == 200
    assert denied.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_guest_mutation_requires_key_and_matching_token() -> None:
    scenario = create_booking_scenario()
    client = Client()
    payload = {
        "branch_id": str(scenario.branch.id),
        "barber_id": str(scenario.barber.id),
        "service_id": scenario.service.id,
        "start_at": scenario.start_at.isoformat(),
    }
    created = client.post(
        "/api/v1/bookings/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="create-for-cancel",
    )
    booking_id = created.json()["booking_id"]
    token = created.json()["management_token"]

    missing_key = client.post(
        f"/api/v1/bookings/{booking_id}/cancel/",
        data=json.dumps({"expected_version": 1}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Booking {token}",
    )
    cancelled = client.post(
        f"/api/v1/bookings/{booking_id}/cancel/",
        data=json.dumps({"expected_version": 1}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Booking {token}",
        HTTP_IDEMPOTENCY_KEY="guest-cancel",
    )

    assert missing_key.status_code == 400
    assert cancelled.status_code == 200
    assert cancelled.json()["code"] == "CANCELLED"
