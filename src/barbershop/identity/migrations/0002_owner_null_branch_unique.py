"""Prevent duplicate global owner assignments for one user."""

from django.db import migrations, models


class Migration(migrations.Migration):  # type: ignore[misc]
    dependencies = [
        ("identity", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="staffscope",
            name="identity_scope_user_role_branch_unique",
        ),
        migrations.AddConstraint(
            model_name="staffscope",
            constraint=models.UniqueConstraint(
                condition=models.Q(branch_id__isnull=False),
                fields=("user", "role", "branch_id"),
                name="identity_scope_user_role_branch_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="staffscope",
            constraint=models.UniqueConstraint(
                condition=models.Q(role="OWNER", branch_id__isnull=True),
                fields=("user",),
                name="identity_scope_one_global_owner_per_user",
            ),
        ),
    ]
