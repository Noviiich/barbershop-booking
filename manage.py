#!/usr/bin/env python3
"""Django command-line entry point for local development."""

import os
import sys


def main() -> None:
    """Запустить административную команду Django из аргументов командной строки."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "barbershop.settings.development")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
