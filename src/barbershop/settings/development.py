"""Local PostgreSQL settings for development only."""

import os

from barbershop.database.connection import database_settings
from barbershop.settings.base import *  # noqa: F403

SECRET_KEY = "development-only-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {
    "default": database_settings(
        os.environ.get(
            "DATABASE_URL", "postgresql://barbershop:barbershop@127.0.0.1:54329/barbershop"
        )
    )
}
