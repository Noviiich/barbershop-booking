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


class BookingManagementToken(models.Model):  # type: ignore[misc]
    """Hashed guest capability bound to one booking and its issuing session."""

    booking = models.OneToOneField(
        "booking.Booking", on_delete=models.PROTECT, related_name="management_token"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    guest_session_key = models.CharField(max_length=64)
    encrypted_token = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """Вернуть нераскрывающий идентификатор capability записи."""
        return str(self.booking_id)


class ApiRateLimit(models.Model):  # type: ignore[misc]
    """Durable fixed-window counter for mutation scopes across API processes."""

    scope_digest = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope_digest", "window_start"],
                name="identity_rate_limit_scope_window_unique",
            )
        ]

    def __str__(self) -> str:
        """Вернуть диагностическую идентичность окна без данных клиента."""
        return f"{self.scope_digest}:{self.window_start.isoformat()}"
