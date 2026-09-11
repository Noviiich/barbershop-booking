"""Root URL configuration for the empty backend scaffold."""

from django.urls import path

from barbershop.health import health

urlpatterns = [
    path("health/", health, name="health"),
]
