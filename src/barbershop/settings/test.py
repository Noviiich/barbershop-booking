"""PostgreSQL-only settings for integration and concurrency tests."""

import os

from barbershop.database.connection import database_settings
from barbershop.settings.base import *  # noqa: F403

SECRET_KEY = "tests-only-not-for-production"
ALLOWED_HOSTS = ["testserver"]

# Test settings deliberately ignore DATABASE_URL. A production connection cannot
# become a test target merely because it is present in the process environment.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://barbershop:barbershop@127.0.0.1:54329/barbershop_test"
)
DATABASES = {
    "default": database_settings(
        TEST_DATABASE_URL,
        allowed_hosts=frozenset({"127.0.0.1", "localhost", "db"}),
        required_database_suffix="_test",
    )
}
