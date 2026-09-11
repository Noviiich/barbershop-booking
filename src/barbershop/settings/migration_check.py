"""Settings for the disposable clean-migration database."""

import os

from django.core.exceptions import ImproperlyConfigured

from barbershop.database.connection import DatabaseConfigurationError, database_settings
from barbershop.settings.base import *  # noqa: F403

SECRET_KEY = "migration-check-only-not-for-production"
ALLOWED_HOSTS = []

try:
    DATABASES = {
        "default": database_settings(
            os.environ["MIGRATION_CHECK_DATABASE_URL"],
            allowed_hosts=frozenset({"127.0.0.1", "localhost", "db"}),
            required_database_suffix="_migration_check",
        )
    }
except KeyError as error:
    raise ImproperlyConfigured("MIGRATION_CHECK_DATABASE_URL is required") from error
except DatabaseConfigurationError as error:
    raise ImproperlyConfigured("MIGRATION_CHECK_DATABASE_URL is unsafe") from error
