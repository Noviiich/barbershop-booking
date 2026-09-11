"""Django app configuration for the branch catalog."""

from django.apps import AppConfig


class CatalogConfig(AppConfig):  # type: ignore[misc]
    default_auto_field = "django.db.models.BigAutoField"
    name = "barbershop.catalog"
    verbose_name = "Branch catalog"
