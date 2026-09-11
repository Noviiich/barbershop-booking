"""Django app containing only database infrastructure migrations."""

from django.apps import AppConfig


class DatabaseConfig(AppConfig):  # type: ignore[misc]
    default_auto_field = "django.db.models.BigAutoField"
    name = "barbershop.database"
    verbose_name = "Database infrastructure"
