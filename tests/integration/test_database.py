"""MIG-01: PostgreSQL 17, btree_gist, UTC, and independent transactions."""

import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.db import connection, connections
from django.db.migrations.recorder import MigrationRecorder

from barbershop.database.connection import DatabaseConfigurationError, database_settings
from scripts.migrate_check import check_database_url


def test_test_settings_reject_sqlite_and_nonlocal_production_host() -> None:
    """Проверить запрет SQLite и внешнего production-хоста в тестах."""
    with pytest.raises(DatabaseConfigurationError, match="PostgreSQL"):
        database_settings("sqlite:///tmp/test.sqlite3")

    with pytest.raises(DatabaseConfigurationError, match="not permitted"):
        database_settings(
            "postgresql://user:password@production.example/barbershop_test",
            allowed_hosts=frozenset({"127.0.0.1"}),
            required_database_suffix="_test",
        )


def test_migration_check_uses_only_a_disposable_local_database() -> None:
    """Проверить использование только одноразовой локальной базы для миграций."""
    check_url = check_database_url("postgresql://user:password@127.0.0.1:54329/postgres")

    assert check_url.endswith("/barbershop_migration_check")
    with pytest.raises(DatabaseConfigurationError, match="maintenance database"):
        check_database_url("postgresql://user:password@production.example/postgres")


def test_test_settings_ignore_database_url_from_the_environment() -> None:
    """Проверить независимость тестовых настроек от переменной DATABASE_URL."""
    environment = os.environ | {
        "DATABASE_URL": "postgresql://user:password@production.example/barbershop",
    }
    environment.pop("TEST_DATABASE_URL", None)
    environment["DJANGO_SETTINGS_MODULE"] = "barbershop.settings.test"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.DATABASES['default']['HOST'])",
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.stdout.strip() == "127.0.0.1"


@pytest.mark.django_db(transaction=True)
def test_postgres_17_btree_gist_utc_and_independent_connections() -> None:
    """Проверить PostgreSQL 17, btree_gist, UTC и независимые соединения."""
    assert connection.vendor == "postgresql"
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"

    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        (server_version,) = cursor.fetchone()
        cursor.execute("SHOW TimeZone")
        (timezone,) = cursor.fetchone()
        cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'btree_gist'")
        extension = cursor.fetchone()
        cursor.execute("SELECT pg_backend_pid()")
        (first_backend_pid,) = cursor.fetchone()

    assert 170000 <= int(server_version) < 180000
    assert timezone == "UTC"
    assert extension == ("btree_gist",)
    applied_migrations = MigrationRecorder(connection).applied_migrations()
    assert ("database", "0001_enable_btree_gist") in applied_migrations

    independent = connections["default"].copy()
    try:
        with independent.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            (second_backend_pid,) = cursor.fetchone()
    finally:
        independent.close()

    assert first_backend_pid != second_backend_pid
