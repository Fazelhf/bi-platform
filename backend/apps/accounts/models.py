from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Coarse RBAC roles that map onto BI-platform personas."""

    EXECUTIVE = "executive", "Executive (CEO / board)"
    MANAGER = "manager", "Manager / supervisor (approves data)"
    OPERATOR = "operator", "Operator (enters data)"
    VIEWER = "viewer", "Viewer (read-only dashboards)"


class User(AbstractUser):
    """
    Custom user so we can attach a role and (later) a department without
    a painful migration. Role drives object-level permissions in the API.
    """

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.VIEWER
    )
    display_name_fa = models.CharField(
        "display name (Persian)", max_length=150, blank=True
    )

    @property
    def can_approve(self) -> bool:
        return self.role in {Role.MANAGER, Role.EXECUTIVE} or self.is_superuser

    @property
    def can_enter_data(self) -> bool:
        return (
            self.role in {Role.OPERATOR, Role.MANAGER, Role.EXECUTIVE}
            or self.is_superuser
        )

    def __str__(self) -> str:
        return self.display_name_fa or self.get_username()
