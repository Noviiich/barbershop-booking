"""Transactional helper for claiming and replaying durable command receipts."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from barbershop.idempotency.models import CommandReceipt, ReceiptState


class IdempotencyConflict(Exception):
    """The key already identifies a command with different content."""


class IdempotencyResultExpired(Exception):
    """The command identity remains, but its replay result is no longer available."""


@dataclass(frozen=True)
class CommandScope:
    business_id: UUID
    principal_kind: str
    principal_id: str
    channel: str
    target_id: UUID | None = None

    def digest(self) -> str:
        """Вычислить устойчивый хеш области действия команды."""
        encoded = _canonical_json(
            {
                "business_id": str(self.business_id),
                "channel": self.channel,
                "principal_id": self.principal_id,
                "principal_kind": self.principal_kind,
                "target_id": str(self.target_id) if self.target_id else None,
            }
        )
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CommandResult:
    result_code: str
    response: dict[str, object]
    replayed: bool


def _canonical_json(value: Mapping[str, object]) -> bytes:
    """Сериализовать значение в каноническое представление JSON."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def command_fingerprint(
    operation: str,
    payload: Mapping[str, object],
    *,
    version: int = 1,
) -> str:
    """Вычислить отпечаток операции, версии и её полезной нагрузки."""
    canonical = _canonical_json(
        {"operation": operation, "payload": dict(payload), "version": version}
    )
    return hashlib.sha256(canonical).hexdigest()


@transaction.atomic  # type: ignore[untyped-decorator]
def execute_idempotent(
    *,
    scope: CommandScope,
    operation: str,
    idempotency_key: str,
    payload: Mapping[str, object],
    effect: Callable[[], tuple[str, dict[str, object]]],
    response_retention: timedelta = timedelta(days=30),
) -> CommandResult:
    """Выполнить эффект и сохранить результат повтора в той же транзакции."""
    fingerprint_version = 1
    fingerprint = command_fingerprint(operation, payload, version=fingerprint_version)
    scope_digest = scope.digest()
    try:
        with transaction.atomic():
            receipt = cast(
                CommandReceipt,
                CommandReceipt.objects.create(
                    scope_digest=scope_digest,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    fingerprint_version=fingerprint_version,
                    fingerprint=fingerprint,
                    state=ReceiptState.PROCESSING,
                ),
            )
        created = True
    except IntegrityError:
        receipt = cast(
            CommandReceipt,
            CommandReceipt.objects.select_for_update().get(
                scope_digest=scope_digest,
                operation=operation,
                idempotency_key=idempotency_key,
            ),
        )
        created = False

    if not created:
        if receipt.fingerprint_version != fingerprint_version or receipt.fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key was used with another command")
        if receipt.state == ReceiptState.TOMBSTONE:
            raise IdempotencyResultExpired("idempotency result was removed")
        now = timezone.now()
        if receipt.response_expires_at is None or receipt.response_expires_at <= now:
            raise IdempotencyResultExpired("idempotency result has expired")
        return CommandResult(
            result_code=str(receipt.result_code),
            response=cast(dict[str, object], receipt.response),
            replayed=True,
        )

    result_code, response = effect()
    completed_at = timezone.now()
    receipt.state = ReceiptState.COMPLETED
    receipt.result_code = result_code
    receipt.response = response
    receipt.completed_at = completed_at
    receipt.response_expires_at = completed_at + response_retention
    receipt.full_clean()
    receipt.save(
        update_fields=[
            "state",
            "result_code",
            "response",
            "completed_at",
            "response_expires_at",
        ]
    )
    return CommandResult(result_code=result_code, response=response, replayed=False)


@transaction.atomic  # type: ignore[untyped-decorator]
def replace_result_with_tombstone(receipt_id: UUID) -> None:
    """Удалить тело результата повтора, сохранив постоянную идентичность команды."""
    receipt = cast(
        CommandReceipt,
        CommandReceipt.objects.select_for_update().get(pk=receipt_id),
    )
    receipt.state = ReceiptState.TOMBSTONE
    receipt.result_code = ""
    receipt.response = None
    receipt.response_expires_at = None
    receipt.completed_at = None
    receipt.full_clean()
    receipt.save(
        update_fields=[
            "state",
            "result_code",
            "response",
            "response_expires_at",
            "completed_at",
        ]
    )
