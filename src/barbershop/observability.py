"""PII-safe in-process metrics and alert evaluation for local operations."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import timedelta
from time import perf_counter
from uuid import uuid4

from django.utils import timezone

from barbershop.journal.models import DeliveryState

logger = logging.getLogger("barbershop.operations")
metrics: Counter[str] = Counter()


def correlation_id() -> str:
    """Return a non-domain trace identifier safe for logs and metrics."""
    return str(uuid4())


def record(name: str, value: int = 1) -> None:
    """Record a bounded metric name; labels deliberately are not supported."""
    metrics[name] += value


def operation_log(operation: str, started_at: float, *, outcome: str, trace_id: str) -> None:
    """Emit one JSON log without payloads, contacts, or booking identifiers."""
    record(f"command.{operation}.{outcome}")
    logger.info(
        json.dumps(
            {
                "operation": operation,
                "outcome": outcome,
                "latency_ms": round((perf_counter() - started_at) * 1000),
                "trace_id": trace_id,
            }
        )
    )


def alerts() -> tuple[str, ...]:
    """Evaluate local backlog and authentication alert conditions."""
    overdue = DeliveryState.objects.filter(
        state__in=[DeliveryState.State.PENDING, DeliveryState.State.PROCESSING],
        available_at__lt=timezone.now() - timedelta(minutes=5),
    ).exists()
    result = ["OUTBOX_BACKLOG_OVER_5M"] if overdue else []
    if metrics["auth.failure"]:
        result.append("AUTH_FAILURE")
    return tuple(result)
