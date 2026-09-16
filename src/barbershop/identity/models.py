"""Persisted staff roles without a dependency on the future catalog schema."""

from django.conf import settings
from django.db import models


class StaffRole(models.TextChoices):  # type: ignore[misc]
    MASTER = "MASTER", "Master"
    ADMIN = "ADMIN", "Administrator"
    OWNER = "OWNER", "Owner"


class StaffScope(models.Model):  # type: ignore[misc]
    """A trusted role assignment scoped to one branch or the whole business."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=StaffRole.choices)
    branch_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(role=StaffRole.OWNER, branch_id__isnull=True)
                    | models.Q(
                        role__in=[StaffRole.MASTER, StaffRole.ADMIN], branch_id__isnull=False
                    )
                ),
                name="identity_scope_role_branch_consistent",
            ),
            models.UniqueConstraint(
                fields=["user", "role", "branch_id"],
                condition=models.Q(branch_id__isnull=False),
                name="identity_scope_user_role_branch_unique",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(role=StaffRole.OWNER, branch_id__isnull=True),
                name="identity_scope_one_global_owner_per_user",
            ),
        ]

    def __str__(self) -> str:
        """Вернуть пользователя, роль и область назначения сотрудника."""
        return f"{self.user_id}:{self.role}:{self.branch_id or '*'}"
