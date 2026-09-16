"""BOOT-01: the empty backend imports, checks and serves health."""

import os
import subprocess
import sys

from django.test import Client


def test_health_endpoint_is_the_only_public_route(client: Client) -> None:
    """Проверить, что публично доступна только проверка здоровья."""
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/").status_code == 404


def test_production_settings_require_secret() -> None:
    """Проверить обязательность секретного ключа в production-настройках."""
    environment = os.environ.copy()
    environment.pop("DJANGO_SECRET_KEY", None)

    result = subprocess.run(
        [sys.executable, "-c", "import barbershop.settings.production"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY is required in production" in result.stderr
