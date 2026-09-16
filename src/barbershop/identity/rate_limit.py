"""Database-backed fixed-window limiting for own API mutations."""

from datetime import UTC, datetime
from typing import cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from barbershop.identity.models import ApiRateLimit

MUTATIONS_PER_MINUTE = 20


class RateLimitExceeded(Exception):
    """The caller has exhausted its current API mutation window."""


def _window_start(now: datetime) -> datetime:
    """Свести момент к началу его UTC-минуты для фиксированного окна."""
    return now.astimezone(UTC).replace(second=0, microsecond=0)


@transaction.atomic  # type: ignore[untyped-decorator]
def enforce_mutation_limit(scope_digest: str) -> None:
    """Атомарно увеличить счётчик scope либо сообщить об исчерпанном лимите."""
    window_start = _window_start(timezone.now())
    try:
        counter = cast(
            ApiRateLimit,
            ApiRateLimit.objects.select_for_update().get(
                scope_digest=scope_digest, window_start=window_start
            ),
        )
    except ApiRateLimit.DoesNotExist:
        try:
            ApiRateLimit.objects.create(
                scope_digest=scope_digest, window_start=window_start, count=1
            )
            return
        except IntegrityError:
            counter = cast(
                ApiRateLimit,
                ApiRateLimit.objects.select_for_update().get(
                    scope_digest=scope_digest, window_start=window_start
                ),
            )
    if counter.count >= MUTATIONS_PER_MINUTE:
        raise RateLimitExceeded
    counter.count += 1
    counter.save(update_fields=["count"])
