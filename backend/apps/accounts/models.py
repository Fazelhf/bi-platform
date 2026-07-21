from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Coarse RBAC roles that map onto BI-platform personas."""

    EXECUTIVE = "executive", "Executive (CEO / board)"
    MANAGER = "manager", "Manager / supervisor (approves data)"
    OPERATOR = "operator", "Operator (enters data)"
    VIEWER = "viewer", "Viewer (read-only dashboards)"


class Department(models.TextChoices):
    """
    Which section a manager owns. Data entry is scoped to a manager's own
    department; the CEO (executive) owns none and only views dashboards.
    """

    NONE = "", "— (no data-entry section)"
    PRODUCTION = "production", "تولید"
    SALES_ORG = "sales_org", "فروش سازمانی"
    SALES_TEAM = "sales_team", "تیم فروش (همکار)"


class User(AbstractUser):
    """
    Custom user with a role (what they may do) and a department (which
    section's data they own). Together these drive API permissions:
    executives view every dashboard but enter nothing; department managers
    enter/approve only their own section.
    """

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.VIEWER
    )
    department = models.CharField(
        max_length=20, choices=Department.choices, default=Department.NONE, blank=True
    )
    display_name_fa = models.CharField(
        "display name (Persian)", max_length=150, blank=True
    )

    @property
    def can_approve(self) -> bool:
        # Per the approval workflow, the CEO (executive) is the final
        # approver; department managers may also approve their own section.
        return self.role in {Role.MANAGER, Role.EXECUTIVE} or self.is_superuser

    @property
    def can_enter_data(self) -> bool:
        return (
            self.role in {Role.OPERATOR, Role.MANAGER}
            and bool(self.department)
        ) or self.is_superuser

    def owns_department(self, dept: str) -> bool:
        """True if this user may enter data for the given section."""
        return self.is_superuser or (self.can_enter_data and self.department == dept)

    def __str__(self) -> str:
        return self.display_name_fa or self.get_username()
