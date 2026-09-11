"""Create scoped staff role assignments."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):  # type: ignore[misc]
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("database", "0001_enable_btree_gist"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffScope",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("MASTER", "Master"),
                            ("ADMIN", "Administrator"),
                            ("OWNER", "Owner"),
                        ],
                        max_length=16,
                    ),
                ),
                ("branch_id", models.UUIDField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(role="OWNER", branch_id__isnull=True)
                            | models.Q(
                                role__in=["MASTER", "ADMIN"],
                                branch_id__isnull=False,
                            )
                        ),
                        name="identity_scope_role_branch_consistent",
                    ),
                    models.UniqueConstraint(
                        fields=("user", "role", "branch_id"),
                        name="identity_scope_user_role_branch_unique",
                    ),
                ],
            },
        ),
    ]
