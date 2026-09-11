from django.apps import AppConfig


class ScheduleConfig(AppConfig):  # type: ignore[misc]
    default_auto_field = "django.db.models.BigAutoField"
    name = "barbershop.schedule"
