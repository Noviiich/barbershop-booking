"""Issue and validate session-bound, encrypted booking management capabilities."""

import hashlib
import secrets
from dataclasses import dataclass
from typing import cast

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from barbershop.identity.models import BookingManagementToken


class ManagementTokenError(PermissionError):
    """The management capability is missing, malformed, or not valid here."""


@dataclass(frozen=True)
class IssuedManagementToken:
    raw: str
    token_hash: str
    encrypted: str


def _fernet() -> Fernet:
    """Получить настроенный ключ шифрования capability без fallback в production."""
    try:
        return Fernet(settings.MANAGEMENT_TOKEN_ENCRYPTION_KEY)
    except (AttributeError, TypeError, ValueError) as error:
        raise ManagementTokenError("management token encryption is unavailable") from error


def issue_management_token() -> IssuedManagementToken:
    """Сгенерировать секрет для клиента и его хеш/шифротекст для БД."""
    raw = secrets.token_urlsafe(32)
    return IssuedManagementToken(
        raw=raw,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        encrypted=_fernet().encrypt(raw.encode()).decode(),
    )


def authorize_management_token(
    *,
    booking_id: object,
    raw_token: str | None,
    session_key: str,
) -> BookingManagementToken:
    """Проверить capability записи и привязку украденного секрета к сессии гостя."""
    if not raw_token:
        raise ManagementTokenError("booking management token is required")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    try:
        grant = BookingManagementToken.objects.select_related("booking").get(
            booking_id=booking_id,
            token_hash=token_hash,
            guest_session_key=session_key,
        )
    except BookingManagementToken.DoesNotExist as error:
        raise ManagementTokenError("booking management token is invalid") from error
    return cast(BookingManagementToken, grant)


def decrypt_management_token(encrypted: str) -> str:
    """Расшифровать сохранённый секрет только для его исходной гостевой сессии."""
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as error:
        raise ManagementTokenError("stored management token is invalid") from error
