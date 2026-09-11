"""IDEM-01: durable replay, mismatch, scope, rollback and expiry."""

from datetime import timedelta
from uuid import uuid4

import pytest

from barbershop.catalog.models import Business
from barbershop.idempotency.models import CommandReceipt
from barbershop.idempotency.services import (
    CommandScope,
    IdempotencyConflict,
    IdempotencyResultExpired,
    execute_idempotent,
    replace_result_with_tombstone,
)


def _scope(*, principal_id: str = "user-1") -> CommandScope:
    return CommandScope(
        business_id=uuid4(),
        principal_kind="USER",
        principal_id=principal_id,
        channel="OWN_WEB",
    )


@pytest.mark.django_db(transaction=True)
def test_same_command_replays_one_effect_and_mismatch_conflicts() -> None:
    scope = _scope()

    def effect() -> tuple[str, dict[str, object]]:
        business = Business.objects.create(name="effect")
        return "CREATED", {"effect_id": str(business.pk)}

    first = execute_idempotent(
        scope=scope,
        operation="TEST_EFFECT",
        idempotency_key="key-1",
        payload={"value": 1},
        effect=effect,
    )
    replay = execute_idempotent(
        scope=scope,
        operation="TEST_EFFECT",
        idempotency_key="key-1",
        payload={"value": 1},
        effect=effect,
    )

    assert not first.replayed
    assert replay.replayed
    assert replay.response == first.response
    assert Business.objects.filter(name="effect").count() == 1

    with pytest.raises(IdempotencyConflict):
        execute_idempotent(
            scope=scope,
            operation="TEST_EFFECT",
            idempotency_key="key-1",
            payload={"value": 2},
            effect=effect,
        )


@pytest.mark.django_db(transaction=True)
def test_scope_isolation_does_not_reveal_another_result() -> None:
    shared_business_id = uuid4()
    calls = 0

    def effect() -> tuple[str, dict[str, object]]:
        nonlocal calls
        calls += 1
        return "OK", {"call": calls}

    for principal_id in ("user-1", "user-2"):
        result = execute_idempotent(
            scope=CommandScope(
                business_id=shared_business_id,
                principal_kind="USER",
                principal_id=principal_id,
                channel="OWN_WEB",
            ),
            operation="TEST_EFFECT",
            idempotency_key="shared-key",
            payload={"value": 1},
            effect=effect,
        )
        assert not result.replayed

    assert calls == 2
    assert CommandReceipt.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_transient_rollback_leaves_no_receipt_and_retry_can_run() -> None:
    scope = _scope()

    def failing_effect() -> tuple[str, dict[str, object]]:
        Business.objects.create(name="rolled-back")
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        execute_idempotent(
            scope=scope,
            operation="TEST_EFFECT",
            idempotency_key="retry-key",
            payload={"value": 1},
            effect=failing_effect,
        )

    assert CommandReceipt.objects.count() == 0
    assert Business.objects.filter(name="rolled-back").count() == 0

    result = execute_idempotent(
        scope=scope,
        operation="TEST_EFFECT",
        idempotency_key="retry-key",
        payload={"value": 1},
        effect=lambda: ("OK", {"retried": True}),
    )
    assert not result.replayed


@pytest.mark.django_db(transaction=True)
def test_tombstone_and_expired_result_never_execute_again() -> None:
    scope = _scope()
    calls = 0

    def effect() -> tuple[str, dict[str, object]]:
        nonlocal calls
        calls += 1
        return "OK", {"call": calls}

    execute_idempotent(
        scope=scope,
        operation="TEST_EFFECT",
        idempotency_key="tombstone-key",
        payload={"value": 1},
        effect=effect,
    )
    receipt = CommandReceipt.objects.get(idempotency_key="tombstone-key")
    replace_result_with_tombstone(receipt.id)

    with pytest.raises(IdempotencyResultExpired):
        execute_idempotent(
            scope=scope,
            operation="TEST_EFFECT",
            idempotency_key="tombstone-key",
            payload={"value": 1},
            effect=effect,
        )

    execute_idempotent(
        scope=scope,
        operation="TEST_EFFECT",
        idempotency_key="expired-key",
        payload={"value": 1},
        effect=effect,
        response_retention=timedelta(seconds=-1),
    )
    with pytest.raises(IdempotencyResultExpired):
        execute_idempotent(
            scope=scope,
            operation="TEST_EFFECT",
            idempotency_key="expired-key",
            payload={"value": 1},
            effect=effect,
        )

    assert calls == 2
