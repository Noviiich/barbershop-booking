"""ASGI entry point, retained for Django tooling compatibility."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "barbershop.settings.production")

application = get_asgi_application()
