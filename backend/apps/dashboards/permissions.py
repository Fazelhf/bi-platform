"""
Who may read a board, and who may rearrange one.

Nothing new is invented here. A board shows a section's own figures, so it
follows exactly the rule that section already has — finance stays with finance,
بازرگانی with بازرگانی, CRM behind its demo password. What is new is the
*editing* right: composing the report is the manager's job, so it belongs to
the CEO and to administrators, and to nobody else. A department manager opens
their board and reads it; they do not get to redefine what the CEO sees.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.dashboards.catalog import Dataset, Section, get_section

EXECUTIVE_ROLES = {"executive"}


def _is_executive(user) -> bool:
    return bool(user and (user.is_superuser or user.role in EXECUTIVE_ROLES))


def can_edit_boards(user) -> bool:
    """The CEO and administrators lay out the reports. See the module docstring."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role in EXECUTIVE_ROLES or user.role == "admin")
    )


def _crm_unlocked(user, request) -> bool:
    """CRM data stays behind its own demo password, dashboards included."""
    from apps.crm import gate

    if not request:
        return False
    if not gate.demo_password():
        return False
    return gate.verify(request.META.get(gate.HEADER, ""), user)


def _has_access(user, access: str, request=None) -> bool:
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser or _is_executive(user):
        # The CEO oversees every section — except the demo lock, which is a
        # password, not a privilege.
        return access != "crm" or _crm_unlocked(user, request)
    if access == "":
        return True
    if access == "executive":
        return False
    if access == "crm":
        return _crm_unlocked(user, request)
    # "finance" / "commercial" — the owning department, matching the router.
    return user.department == access


def can_read_section(user, section: Section | str, request=None) -> bool:
    if isinstance(section, str):
        resolved = get_section(section)
        if resolved is None:
            return False
        section = resolved
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser or _is_executive(user):
        return section.access != "crm" or _crm_unlocked(user, request)
    if section.access:
        return _has_access(user, section.access, request)
    # A department's board is for that department; a section that names no
    # department (production) is readable by everyone, as its dashboard is.
    if section.department:
        return user.department == section.department
    return True


def can_read_dataset(user, dataset: Dataset, request=None) -> bool:
    return _has_access(user, dataset.access, request)


class BoardPermission(BasePermission):
    """Read for anyone who can see the section; write for board editors only."""

    message = "چیدمان داشبورد فقط توسط مدیر قابل تغییر است."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return can_edit_boards(request.user)

    def has_object_permission(self, request, view, obj):
        section = getattr(obj, "section", None) or obj.dashboard.section
        if request.method in SAFE_METHODS:
            return can_read_section(request.user, section, request)
        return can_edit_boards(request.user)
