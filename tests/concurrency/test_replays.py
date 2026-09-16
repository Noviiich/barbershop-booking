"""IDEM-01: concurrent attempts share one PostgreSQL receipt."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from django.db import close_old_connections

from barbershop.catalog.models import Business
from barbershop.idempotency.models import CommandReceipt
from barbershop.idempotency.services import CommandResult, CommandScope, execute_idempotent


@pytest.mark.django_db(transaction=True)
def test_concurrent_replay_executes_effect_once() -> None:
    """Проверить однократное выполнение эффекта при конкурентном повторе."""
    scope = CommandScope(
        business_id=uuid4(),
        principal_kind="USER",
        principal_id="user-1",
        channel="OWN_WEB",
    )
    ready = Barrier(2)

    def run() -> CommandResult:
        """Выполнить команду через отдельное соединение с базой."""
        close_old_connections()
        try:
            ready.wait(timeout=5)

            def effect() -> tuple[str, dict[str, object]]:
                """Создать наблюдаемый побочный эффект тестовой команды."""
                business = Business.objects.create(name="concurrent-effect")
                return "CREATED", {"effect_id": str(business.pk)}

            return cast(
                CommandResult,
                execute_idempotent(
                    scope=scope,
                    operation="TEST_EFFECT",
                    idempotency_key="concurrent-key",
                    payload={"value": 1},
                    effect=effect,
                ),
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(), range(2)))

    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].response == results[1].response
    assert Business.objects.filter(name="concurrent-effect").count() == 1
    assert CommandReceipt.objects.count() == 1
