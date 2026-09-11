"""Install the extension required by the future booking exclusion constraint."""

from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):  # type: ignore[misc]
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        CreateExtension("btree_gist"),
    ]
