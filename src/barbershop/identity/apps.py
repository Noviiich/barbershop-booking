"""Django app configuration for staff identity."""

from django.apps import AppConfig


class IdentityConfig(AppConfig):  # type: ignore[misc]
    default_auto_field = "django.db.models.BigAutoField"
    name = "barbershop.identity"
    verbose_name = "Staff identity"
