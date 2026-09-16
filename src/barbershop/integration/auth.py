"""Minimal HS256 verifier for the partner's inbound JWTs."""

import base64
import hashlib
import hmac
import json
from typing import Any, cast

from django.conf import settings


class YandexAuthenticationError(ValueError):
    """The bearer token is invalid for this adapter."""


def authenticate(
    authorization: str, *, expected_claims: dict[str, str] | None = None
) -> dict[str, Any]:
    """Verify HS256 signature and the documented partner/object claims."""
    if not authorization.startswith("Bearer ") or not settings.YANDEX_BOOKING_JWT_SECRET:
        raise YandexAuthenticationError
    token = authorization.removeprefix("Bearer ")
    parts = token.split(".")
    if len(parts) != 3:
        raise YandexAuthenticationError
    signed = f"{parts[0]}.{parts[1]}".encode()
    signature = hmac.new(
        settings.YANDEX_BOOKING_JWT_SECRET.encode(), signed, hashlib.sha256
    ).digest()
    try:
        supplied = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        header = json.loads(base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4)))
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError) as error:
        raise YandexAuthenticationError from error
    if not hmac.compare_digest(signature, supplied) or header.get("alg") != "HS256":
        raise YandexAuthenticationError
    if payload.get("sub") != settings.YANDEX_BOOKING_PARTNER_NAME or "iat" in payload:
        raise YandexAuthenticationError
    for name, value in (expected_claims or {}).items():
        if payload.get(name) != value:
            raise YandexAuthenticationError
    return cast(dict[str, Any], payload)
