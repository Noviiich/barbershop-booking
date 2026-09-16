"""Primary-DB projections for the documented Yandex read operations."""

from datetime import date
from typing import cast
from zoneinfo import ZoneInfo

from barbershop.booking.availability import AvailabilityQuery, list_available_slots
from barbershop.integration.models import YandexBranchMapping, YandexConnection


class YandexReadError(ValueError):
    """A mapped object is absent or outside the connection's scope."""


def branch_for(connection: YandexConnection, company_id: str) -> YandexBranchMapping:
    try:
        return cast(
            YandexBranchMapping,
            YandexBranchMapping.objects.select_related("branch").get(
                connection=connection, external_id=company_id
            ),
        )
    except YandexBranchMapping.DoesNotExist as error:
        raise YandexReadError from error


def feed(connection: YandexConnection, cursor: str | None, count: int) -> dict[str, object]:
    mappings = list(
        YandexBranchMapping.objects.select_related("branch")
        .filter(connection=connection, external_id__gt=cursor or "")
        .order_by("external_id")[: count + 1]
    )
    page, extra = mappings[:count], mappings[count:]
    return {
        "companies": [
            {
                "id": item.external_id,
                "permalink": item.permalink,
                "name": item.branch.name,
                "address": item.address,
                "coordinates": {"lat": float(item.latitude), "lon": float(item.longitude)},
            }
            for item in page
        ],
        "pagination": {
            "cursor": page[-1].external_id if extra and page else None,
            "hasMore": bool(extra),
        },
    }


def services(mapping: YandexBranchMapping) -> dict[str, object]:
    rows = (
        mapping.connection.services.select_related("service")
        .filter(service__branch=mapping.branch, service__is_active=True)
        .order_by("external_id")
    )
    return {
        "services": [
            {
                "id": row.external_id,
                "title": row.service.name,
                "price": {
                    "currencyCode": row.service.currency,
                    "range": [float(row.service.price), float(row.service.price)],
                },
                "durationSeconds": row.service.duration_seconds,
            }
            for row in rows
        ]
    }


def resources(mapping: YandexBranchMapping) -> dict[str, object]:
    rows = (
        mapping.connection.barbers.select_related("barber")
        .filter(
            barber__assignments__branch=mapping.branch,
            barber__assignments__is_active=True,
            barber__is_active=True,
        )
        .distinct()
        .order_by("external_id")
    )
    return {
        "resources": [
            {"id": row.external_id, "title": row.barber.display_name, "description": "Барбер"}
            for row in rows
        ]
    }


def slots(
    mapping: YandexBranchMapping, service_ids: list[str], resource_id: str | None, local_date: date
) -> dict[str, object]:
    service_map = mapping.connection.services.filter(
        service__branch=mapping.branch, external_id__in=service_ids
    )
    local_service_ids = list(service_map.values_list("service_id", flat=True))
    if len(local_service_ids) != len(set(service_ids)):
        raise YandexReadError
    barber_id = None
    if resource_id:
        try:
            barber_id = mapping.connection.barbers.get(external_id=resource_id).barber_id
        except mapping.connection.barbers.model.DoesNotExist as error:
            raise YandexReadError from error
    values = list_available_slots(
        AvailabilityQuery(
            mapping.branch.business_id,
            mapping.branch_id,
            local_date,
            local_date,
            barber_id,
            local_service_ids[0] if len(local_service_ids) == 1 else None,
            500,
        )
    )
    zone = ZoneInfo(str(mapping.branch.timezone))
    return {
        "availableTimeSlots": [
            {"datetime": slot.start_at.astimezone(zone).isoformat()}
            for slot in values
            if slot.service_id in local_service_ids
        ]
    }
