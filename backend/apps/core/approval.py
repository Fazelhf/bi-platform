"""
Who approves what — the one rule every section's submit and approve paths share.

The flow:

* A کارشناس (operator) in فروش، تولید or مالی enters figures and submits them;
  they land in the کارتابل of **their own department's manager**, whose
  approval is final.
* A department manager's own submission needs nobody: it is approved the
  moment it is sent.
* The CEO is not a step in the chain. They (and superusers) can still decide
  on anything — a fallback for a department with no manager, or to correct
  history — but submissions are not routed to them.
"""
from __future__ import annotations

from apps.core.permissions import CHANNEL_DEPARTMENT


def is_department_manager(user, department: str) -> bool:
    return bool(
        user and user.is_authenticated and department
        and getattr(user, "role", "") == "manager"
        and getattr(user, "department", "") == department
    )


def approves(user, department: str) -> bool:
    """May this account decide on figures that belong to `department`?"""
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser or getattr(user, "role", "") == "executive":
        return True
    return is_department_manager(user, department)


def auto_approves(user, department: str) -> bool:
    """
    Is this account's own submission final as sent?

    A department manager's is; so is a superuser's or the CEO's, who would
    otherwise be asked to approve their own figures.
    """
    return approves(user, department)


def department_of(obj, fallback: str = "") -> str:
    """The department a record belongs to: its sales channel's, else `fallback`."""
    channel = getattr(obj, "channel", None)
    if channel:
        return CHANNEL_DEPARTMENT.get(channel, fallback)
    return fallback


def submission_status(user, department: str, submit: bool) -> str:
    """The status a save should write: draft, pending the manager, or approved."""
    from apps.sales.models import ApprovalStatus

    if not submit:
        return ApprovalStatus.DRAFT
    if auto_approves(user, department):
        return ApprovalStatus.APPROVED
    return ApprovalStatus.SUBMITTED
