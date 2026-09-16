"""Validated PostgreSQL connection settings without environment-specific helpers."""

from collections.abc import Collection
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


class DatabaseConfigurationError(ValueError):
    """Raised before Django can connect to an unsafe or unsupported database."""


@dataclass(frozen=True)
class ParsedDatabaseUrl:
    name: str
    user: str
    password: str
    host: str
    port: int


def parse_postgres_url(url: str) -> ParsedDatabaseUrl:
    """Разобрать и проверить URL подключения к PostgreSQL."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise DatabaseConfigurationError("Only PostgreSQL URLs are supported")
    if parsed.query or parsed.fragment or not parsed.hostname or not parsed.path.strip("/"):
        raise DatabaseConfigurationError("Database URL must contain only one PostgreSQL database")
    if not parsed.username or parsed.password is None:
        raise DatabaseConfigurationError("Database URL must include credentials")

    try:
        port = parsed.port or 5432
    except ValueError as error:
        raise DatabaseConfigurationError("Database URL has an invalid port") from error

    return ParsedDatabaseUrl(
        name=unquote(parsed.path.removeprefix("/")),
        user=unquote(parsed.username),
        password=unquote(parsed.password),
        host=parsed.hostname,
        port=port,
    )


def database_settings(
    url: str,
    *,
    allowed_hosts: Collection[str] | None = None,
    required_database_suffix: str | None = None,
) -> dict[str, object]:
    """Собрать настройки Django с учётом ограничений целевой базы."""
    parsed = parse_postgres_url(url)
    if allowed_hosts is not None and parsed.host not in allowed_hosts:
        raise DatabaseConfigurationError("Database host is not permitted for this environment")
    if required_database_suffix is not None and not parsed.name.endswith(required_database_suffix):
        raise DatabaseConfigurationError("Database name is not a disposable test target")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.name,
        "USER": parsed.user,
        "PASSWORD": parsed.password,
        "HOST": parsed.host,
        "PORT": parsed.port,
        "OPTIONS": {"options": "-c timezone=UTC"},
    }
