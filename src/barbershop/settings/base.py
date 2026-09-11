"""Shared settings with no external service access at import time."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]

SECRET_KEY = "environment-specific-settings-must-replace-this"
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.postgres",
    "barbershop.database.apps.DatabaseConfig",
    "barbershop.identity.apps.IdentityConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
ROOT_URLCONF = "barbershop.urls"
TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "barbershop.wsgi.application"
ASGI_APPLICATION = "barbershop.asgi.application"

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
