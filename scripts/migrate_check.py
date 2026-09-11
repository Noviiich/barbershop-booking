"""Create a disposable local database and validate all Django migrations."""

import os
import sys
from subprocess import run

import psycopg
from psycopg import sql

from barbershop.database.connection import DatabaseConfigurationError, parse_postgres_url

CHECK_DATABASE = "barbershop_migration_check"
DEFAULT_ADMIN_URL = "postgresql://barbershop:barbershop@127.0.0.1:54329/postgres"
SAFE_HOSTS = frozenset({"127.0.0.1", "localhost", "db"})


def check_database_url(admin_url: str) -> str:
    """Derive the fixed disposable target after validating the local admin URL."""
    parsed = parse_postgres_url(admin_url)
    if parsed.host not in SAFE_HOSTS or parsed.name != "postgres":
        raise DatabaseConfigurationError(
            "Migration check requires the local postgres maintenance database"
        )

    source = admin_url.split("?", 1)[0].split("#", 1)[0]
    prefix, _, _ = source.rpartition("/")
    return f"{prefix}/{CHECK_DATABASE}"


def main() -> None:
    admin_url = os.environ.get("MIGRATION_CHECK_ADMIN_URL", DEFAULT_ADMIN_URL)
    check_url = check_database_url(admin_url)
    admin_connection = psycopg.connect(admin_url, autocommit=True)
    try:
        with admin_connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [CHECK_DATABASE],
            )
            drop_database = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(CHECK_DATABASE)
            )
            cursor.execute(drop_database)
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(CHECK_DATABASE)))
    finally:
        admin_connection.close()

    environment = os.environ | {
        "DJANGO_SETTINGS_MODULE": "barbershop.settings.migration_check",
        "MIGRATION_CHECK_DATABASE_URL": check_url,
    }
    for command in (
        [sys.executable, "manage.py", "migrate", "--noinput"],
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
    ):
        run(command, check=True, env=environment)


if __name__ == "__main__":
    main()
