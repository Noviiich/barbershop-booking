from django.apps import AppConfig


class IdempotencyConfig(AppConfig):  # type: ignore[misc]
    default_auto_field = "django.db.models.BigAutoField"
    name = "barbershop.idempotency"
