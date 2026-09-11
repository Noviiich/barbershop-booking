"""Shared settings with no external service access at import time."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]

SECRET_KEY = "environment-specific-settings-must-replace-this"
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS: list[str] = []
MIDDLEWARE: list[str] = []
ROOT_URLCONF = "barbershop.urls"
TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "barbershop.wsgi.application"
ASGI_APPLICATION = "barbershop.asgi.application"

# PR-02 introduces PostgreSQL. An implicit SQLite fallback would violate the
# architecture, so the bootstrap deliberately has no database configuration.
DATABASES: dict[str, object] = {}

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
