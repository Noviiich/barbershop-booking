"""Internal schedule mutations following the project lock protocol."""

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from django.db import transaction

from barbershop.catalog.services import lock_branch_and_barbers
from barbershop.schedule.models import ScheduleException, ScheduleRule


@transaction.atomic  # type: ignore[untyped-decorator]
def update_schedule_rule(rule_id: int, changes: Mapping[str, Any]) -> ScheduleRule:
    rule = cast(ScheduleRule, ScheduleRule.objects.select_related("branch").get(pk=rule_id))
    lock_branch_and_barbers(rule.branch_id)
    rule = cast(ScheduleRule, ScheduleRule.objects.select_for_update().get(pk=rule_id))
    allowed = {"weekday", "starts_at", "ends_at", "is_active"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported schedule field: {sorted(unknown)[0]}")
    for field, value in changes.items():
        setattr(rule, field, value)
    rule.full_clean()
    rule.save(update_fields=list(changes))
    return rule


@transaction.atomic  # type: ignore[untyped-decorator]
def update_schedule_exception(exception_id: UUID, changes: Mapping[str, Any]) -> ScheduleException:
    exception = cast(
        ScheduleException,
        ScheduleException.objects.select_related("branch").get(pk=exception_id),
    )
    lock_branch_and_barbers(exception.branch_id)
    exception = cast(
        ScheduleException,
        ScheduleException.objects.select_for_update().get(pk=exception_id),
    )
    allowed = {"local_date", "kind", "starts_at", "ends_at", "reason"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"unsupported schedule field: {sorted(unknown)[0]}")
    for field, value in changes.items():
        setattr(exception, field, value)
    exception.full_clean()
    exception.save(update_fields=list(changes))
    return exception
