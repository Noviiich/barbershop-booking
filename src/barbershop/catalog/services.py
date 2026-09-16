"""Internal catalog commands with the project-wide Branch → Barber lock order."""

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from django.db import transaction

from barbershop.catalog.models import Barber, BarberAssignment, Branch, ServiceOffering


def lock_branch_and_barbers(branch_id: UUID) -> Branch:
    """Заблокировать филиал, затем связанных мастеров в устойчивом порядке."""
    branch = cast(Branch, Branch.objects.select_for_update().get(pk=branch_id))
    barber_ids = (
        BarberAssignment.objects.filter(branch_id=branch_id)
        .order_by("barber_id")
        .values_list("barber_id", flat=True)
        .distinct()
    )
    list(Barber.objects.select_for_update().filter(id__in=barber_ids).order_by("id"))
    return branch


@transaction.atomic  # type: ignore[untyped-decorator]
def update_service_offering(service_id: int, changes: Mapping[str, Any]) -> ServiceOffering:
    """Обновить услугу после блокировки филиала и связанных мастеров."""
    service = cast(
        ServiceOffering, ServiceOffering.objects.select_related("branch").get(pk=service_id)
    )
    lock_branch_and_barbers(service.branch_id)
    service = cast(ServiceOffering, ServiceOffering.objects.select_for_update().get(pk=service_id))
    allowed_fields = {
        "name",
        "price",
        "currency",
        "duration_seconds",
        "is_active",
    }
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValueError(f"unsupported service field: {field}")
        setattr(service, field, value)
    service.full_clean()
    service.save(update_fields=list(changes))
    return service
