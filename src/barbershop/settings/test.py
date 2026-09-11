"""Deterministic settings for tests that do not require PostgreSQL yet."""

from barbershop.settings.base import *  # noqa: F403

SECRET_KEY = "tests-only-not-for-production"
ALLOWED_HOSTS = ["testserver"]
