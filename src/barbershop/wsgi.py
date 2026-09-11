"""WSGI entry point for the production HTTP server."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "barbershop.settings.production")

application = get_wsgi_application()
