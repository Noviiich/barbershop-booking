"""Production settings fail closed when required secrets are absent."""

import os

from django.core.exceptions import ImproperlyConfigured

from barbershop.database.connection import DatabaseConfigurationError, database_settings
from barbershop.settings.base import *  # noqa: F403

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production")
MANAGEMENT_TOKEN_ENCRYPTION_KEY = os.environ.get("MANAGEMENT_TOKEN_ENCRYPTION_KEY", "")
if not MANAGEMENT_TOKEN_ENCRYPTION_KEY:
    raise ImproperlyConfigured("MANAGEMENT_TOKEN_ENCRYPTION_KEY is required in production")

try:
    DATABASES = {"default": database_settings(os.environ["DATABASE_URL"])}
except KeyError as error:
    raise ImproperlyConfigured("DATABASE_URL is required in production") from error
except DatabaseConfigurationError as error:
    raise ImproperlyConfigured("DATABASE_URL is invalid in production") from error

ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()
]

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
