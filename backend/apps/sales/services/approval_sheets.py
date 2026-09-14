"""
The sales half of the کارتابل: one decision per sheet, not per row.

A sales sheet is what a department manager fills in for one channel and one
period — every salesperson's column, the provincial block, and for B2B the
customer-segment split. It is entered as one thing and submitted as one thing,
but it used to arrive in the کارتابل as its pieces: a row per salesperson,
each approved on its own, and the provincial figures not at all — they had no
status, so they went straight onto the dashboards the moment they were saved,
approved or not.

So the unit of approval is now the sheet:

* **One item per channel × period.** A weekly month gives one item per week,
  a monthly one gives one per month — whatever grain the period was entered
  at. A week entered day by day is still one weekly item; its days are rolled
  up underneath it.
* **Everything in it moves together.** Approving a sheet approves its
  salespeople, its provinces and its segments in one transaction, so a
  dashboard can never show a week's provincial split without the salesperson
  figures it is a split *of*.
* **Only what was submitted.** Rows still in draft in the same period are
  left alone; the decision is about what the manager actually sent.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.core.audit import log as audit_log
from apps.core.models import AuditLog, DimPeriod, PeriodKind
from apps.core.notify import notify_decision
from apps.core.periods import leaves_of
from apps.core.permissions import CHANNEL_DEPARTMENT
from apps.sales.models import (
    ApprovalStatus,
    FactSalesByCustomerGroup,
    FactSalesMonthly,
    FactSalesProvince,
    SalesChannel,
)

#: Every table a sheet writes. Order is only the order they are reported in.
SHEET_MODELS = (FactSalesMonthly, FactSalesProvince, FactSalesByCustomerGroup)

#: The salesperson measures an approver reviews. Targets are not among them:
#: they are the CEO's own plan and live in SalesTarget, not on the sheet.
PEOPLE_FIELDS = (
    "revenue_rial", "invoice_count", "profit_rial", "cost_rial",
    "new_customers", "active_customers", "calls",
    "proforma_issued_rial", "proforma_cancelled_rial",
    "quantity_ton", "collected_rial", "receivables_rial", "won_invoices_rial",
)

#: Measures that describe a *state* rather than a flow. Rolling a week's days
#: up, «مشتری فعال» and «مانده مطالبات» take the latest day's value — adding
#: seven days of outstanding receivables together would report a debt seven
#: times the size of the real one.
STOCK_FIELDS = {"active_customers", "receivables_rial"}

ACTIONS = {
    "approve": (ApprovalStatus.APPROVED, "approved", AuditLog.Action.APPROVE),
    "reject": (ApprovalStatus.REJECTED, "rejected", AuditLog.Action.REJECT),
    "request-revision": (
        ApprovalStatus.NEEDS_REVISION, "revision", AuditLog.Action.REVISION,
    ),
}

CHANNEL_LABELS = dict(SalesChannel.choices)


class AlreadyDecided(APIException):
    status_code = 409
    default_detail = "این دوره قبلاً تعیین تکلیف شده است."
    default_code = "already_decided"


def sheet_period(period: DimPeriod) -> DimPeriod:
    """The period a row is approved under: a day belongs to its week's sheet."""
    if period.kind == PeriodKind.DAY and period.parent_id:
        return period.parent
    return period


def visible_channels(user) -> set[str] | None:
    """Channels whose sheets this account may see. None means all of them."""
    if user.is_superuser or getattr(user, "role", "") == "executive":
        return None
    return {ch for ch, dept in CHANNEL_DEPARTMENT.items() if dept == user.department}


def _display_name(user) -> str:
    if user is None:
        return ""
    return getattr(user, "display_name_fa", "") or user.get_full_name() or user.username


def _money(value) -> str:
    """A plain decimal string. `normalize()` alone turns 1000 into «1E+3»,
    which the page would show as it is."""
    if not value:
        return "0"
    return format(Decimal(value).normalize(), "f")


def list_sheets(user, status: str = ApprovalStatus.SUBMITTED) -> list[dict]:
    """
    Every sheet carrying rows in `status`, oldest first — a queue is worked
    from the front.
    """
    channels = visible_channels(user)
    if channels is not None and not channels:
        return []

    sheets: dict[tuple[int, str], dict] = {}

    def scoped(qs):
        qs = qs.filter(status=status)
        if channels is not None:
            qs = qs.filter(channel__in=channels)
        # Oldest day first, so a stock measure ends on its latest value.
        return qs.select_related("period", "period__parent", "submitted_by").order_by(
            "period__start_date", "period_id",
        )

    def bucket(row) -> dict:
        period = sheet_period(row.period)
        key = (period.id, row.channel)
        sheet = sheets.get(key)
        if sheet is None:
            sheet = sheets[key] = {
                "period": period, "channel": row.channel,
                "people": {}, "provinces": {}, "groups": {},
                "submitted_at": None, "submitted_by": None,
            }
        if sheet["submitted_at"] is None or row.updated_at > sheet["submitted_at"]:
            sheet["submitted_at"] = row.updated_at
            if row.submitted_by_id:
                sheet["submitted_by"] = row.submitted_by
        return sheet

    for fact in scoped(FactSalesMonthly.objects.select_related("employee")):
        person = bucket(fact)["people"].setdefault(fact.employee_id, {
            "employee_id": fact.employee_id,
            "name": fact.employee.full_name_fa,
            **{f: Decimal(0) for f in PEOPLE_FIELDS},
        })
        for f in PEOPLE_FIELDS:
            value = Decimal(getattr(fact, f) or 0)
            person[f] = value if f in STOCK_FIELDS else person[f] + value

    for row in scoped(FactSalesProvince.objects.select_related("province")):
        prov = bucket(row)["provinces"].setdefault(row.province_id, {
            "province_id": row.province_id,
            "name": row.province.name_fa,
            "sales_rial": Decimal(0),
        })
        prov["sales_rial"] += row.sales_rial or 0

    for row in scoped(FactSalesByCustomerGroup.objects.select_related("customer_group")):
        group = bucket(row)["groups"].setdefault(row.customer_group_id, {
            "group_id": row.customer_group_id,
            "name": row.customer_group.name_fa,
            "sales_rial": Decimal(0), "profit_rial": Decimal(0), "invoice_count": 0,
        })
        group["sales_rial"] += row.sales_rial or 0
        group["profit_rial"] += row.profit_rial or 0
        group["invoice_count"] += row.invoice_count or 0

    out = []
    for sheet in sheets.values():
        period = sheet["period"]
        people = sorted(sheet["people"].values(), key=lambda p: p["revenue_rial"], reverse=True)
        provinces = sorted(
            (p for p in sheet["provinces"].values() if p["sales_rial"]),
            key=lambda p: p["sales_rial"], reverse=True,
        )
        groups = sorted(sheet["groups"].values(), key=lambda g: g["sales_rial"], reverse=True)
        people_revenue = sum((p["revenue_rial"] for p in people), Decimal(0))
        province_sales = sum((p["sales_rial"] for p in provinces), Decimal(0))

        out.append({
            "key": f"{period.id}:{sheet['channel']}",
            "period": {"id": period.id, "label": period.label, "kind": period.kind},
            "channel": sheet["channel"],
            "channel_label": CHANNEL_LABELS.get(sheet["channel"], sheet["channel"]),
            "status": status,
            "submitted_by": _display_name(sheet["submitted_by"]),
            "submitted_at": sheet["submitted_at"].isoformat() if sheet["submitted_at"] else None,
            "salespeople": [
                {**p, **{f: _money(p[f]) for f in PEOPLE_FIELDS}} for p in people
            ],
            "provinces": [{**p, "sales_rial": _money(p["sales_rial"])} for p in provinces],
            "customer_groups": [
                {**g, "sales_rial": _money(g["sales_rial"]),
                 "profit_rial": _money(g["profit_rial"])}
                for g in groups
            ],
            "totals": {
                "people_revenue_rial": _money(people_revenue),
                "province_sales_rial": _money(province_sales),
                "salespeople": len(people),
                "provinces": len(provinces),
                "customer_groups": len(groups),
            },
        })

    out.sort(key=lambda s: s["submitted_at"] or "")
    return out


def decide_sheet(user, *, period_id, channel: str, action: str, note: str = "") -> dict:
    """Approve, reject or return one whole sheet."""
    if action not in ACTIONS:
        raise ValidationError({"action": "اقدام نامعتبر است."})
    if channel not in CHANNEL_LABELS:
        raise ValidationError({"channel": "کانال فروش نامعتبر است."})
    period = DimPeriod.objects.filter(pk=period_id).first()
    if period is None:
        raise ValidationError({"period": "دوره پیدا نشد."})
    period = sheet_period(period)
    if period.kind == PeriodKind.MONTH and period.children.exists():
        # The list never offers a split month; this stops a hand-built request
        # approving four weeks at once under one click nobody made per week.
        raise ValidationError(
            {"period": "این ماه هفته‌بندی شده است؛ هر هفته جداگانه تایید می‌شود."}
        )

    leaf_ids = [p.id for p in leaves_of(period)]
    pending = [
        model.objects.filter(
            period_id__in=leaf_ids, channel=channel, status=ApprovalStatus.SUBMITTED,
        )
        for model in SHEET_MODELS
    ]
    counts = [qs.count() for qs in pending]
    if not any(counts):
        raise AlreadyDecided()

    # Read before the update: afterwards these rows no longer match the filter.
    representative = next(
        (qs.select_related("submitted_by").exclude(submitted_by=None).first()
         for qs in pending if qs.exclude(submitted_by=None).exists()),
        None,
    ) or next(qs.first() for qs in pending if qs.exists())
    touched = set()
    for qs in pending:
        touched.update(qs.values_list("period_id", flat=True))

    new_status, verb, audit_action = ACTIONS[action]
    label = CHANNEL_LABELS[channel]
    changes = {"sales_sheet": {"before": ApprovalStatus.SUBMITTED, "after": f"{label} · {new_status}"}}
    if note:
        changes["note"] = {"before": None, "after": note}

    with transaction.atomic():
        now = timezone.now()
        for qs in pending:
            fields = {"status": new_status, "updated_at": now}
            if new_status == ApprovalStatus.APPROVED:
                fields["approved_by"] = user
            qs.update(**fields)
        audit_log(user, period, audit_action, changes)

    # One notification for the sheet, not one per salesperson in it.
    notify_decision(user, representative, verb, f"فروش {label} · {period.label}")

    if new_status == ApprovalStatus.APPROVED:
        from apps.sales.services.kpi import compute_period_kpis

        for leaf in DimPeriod.objects.filter(id__in=touched):
            compute_period_kpis(leaf)

    return {
        "period": period.id,
        "channel": channel,
        "status": new_status,
        "salespeople": counts[0],
        "provinces": counts[1],
        "customer_groups": counts[2],
    }
