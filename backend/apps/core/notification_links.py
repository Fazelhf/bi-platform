"""
Where a notification takes you when you click it.

The decision is made **on the server**, not in the bell, because it depends on
who is reading. The same "اطلاعات جدید ثبت شده است" row means «go approve it»
to the CEO and «your submission is waiting» to the person who sent it — and a
frontend mapping would have had to re-derive the role and department rules that
already live here. It would also happily hand someone a route their own router
bounces them out of, which reads as a broken link rather than as a permission.

Returning ``None`` is a real answer, not a failure: an announcement has no page
to open, and the bell shows the message itself instead.
"""
from __future__ import annotations

#: model label → the route a *submitter* should land on: where their own
#: figures live, so «رد شد» opens the sheet they need to fix.
ENTRY_ROUTES = {
    "sales.FactSalesMonthly": {
        "team": "sales-entry",
        "organizational": "sales-org-entry",
        "b2b": "sales-b2b-entry",
    },
    "production.FactProduction": "production-entry",
    "finance.CashMovement": "finance-cash-entry",
    "commercial.PurchaseRequest": "commercial-requests",
    "commercial.PurchaseOrder": "commercial-orders",
}

#: Where the same record is *read* — used when the reader is not its owner.
REPORT_ROUTES = {
    "sales.FactSalesMonthly": "overview",
    "production.FactProduction": "production-dashboard",
    "finance.CashMovement": "finance-cash-report",
    "commercial.PurchaseRequest": "commercial-dashboard",
    "commercial.PurchaseOrder": "commercial-dashboard",
}

#: Departments that own each fact, so a manager is only sent to their own sheet.
OWNER_DEPARTMENTS = {
    "production.FactProduction": {"production"},
    "finance.CashMovement": {"finance"},
    "commercial.PurchaseRequest": {"commercial"},
    "commercial.PurchaseOrder": {"commercial"},
}

SALES_CHANNEL_BY_DEPARTMENT = {
    "sales_team": "team",
    "sales_org": "organizational",
    "sales_b2b": "b2b",
}


def _entry_route(label: str, user) -> str | None:
    """The route where this user keys this kind of record, if they do at all."""
    target = ENTRY_ROUTES.get(label)
    if target is None:
        return None
    if isinstance(target, dict):  # sales: one endpoint, three channels
        channel = SALES_CHANNEL_BY_DEPARTMENT.get(user.department)
        return target.get(channel) if channel else None
    if user.department in OWNER_DEPARTMENTS.get(label, set()):
        return target
    return None


def link_for(notification, user) -> dict | None:
    """
    ``{"name": <route name>, "params": {...}}`` — or None when there is no page.

    Ordered by what the reader is expected to *do*: something waiting on their
    decision outranks something merely reported to them.
    """
    if user is None or not user.is_authenticated:
        return None

    label = notification.target_label or ""

    # Waiting on you: the کارتابل is where the decision is actually made, so a
    # "submitted" notice goes there rather than to a read-only dashboard.
    if notification.verb == "submitted" and (
        getattr(user, "can_approve", False) or user.is_superuser
    ):
        return {"name": "inbox"}

    # Your own submission came back — open the sheet you have to correct.
    entry = _entry_route(label, user)
    if entry and notification.verb in {"approved", "rejected", "revision"}:
        return {"name": entry}

    if entry:
        return {"name": entry}

    report = REPORT_ROUTES.get(label)
    if report:
        # `overview` is executive-only; sending a manager there would bounce
        # them home, which looks like the link is broken.
        if report == "overview" and not (
            user.is_superuser or getattr(user, "role", "") == "executive"
        ):
            return None
        return {"name": report}

    return None
