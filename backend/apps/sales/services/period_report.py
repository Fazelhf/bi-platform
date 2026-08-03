"""
Period report — the one thing the B2B manager's workbook does that the
platform could not: look at a *range* of months rather than a single one, and
put it next to the equivalent range before it.

A quarter, a half-year or any custom span: pick the first and last month and
this returns each salesperson's sales, profit and target for the span, the
same figures for the preceding span of equal length, and the growth between
them — plus the province and customer-segment cuts of the same range.

Everything is aggregated from facts that already exist (FactSalesMonthly,
FactSalesProvince, FactSalesByCustomerGroup, SalesTarget). No new storage:
a period report is a question, not a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import leaf_ids_for
from apps.sales.models import (
    FactSalesByCustomerGroup,
    FactSalesMonthly,
    FactSalesProvince,
    SalesTarget,
)

ZERO = Decimal(0)


class PeriodRangeError(ValueError):
    """The requested range cannot be interpreted."""


# --------------------------------------------------------------------------
# Range arithmetic
# --------------------------------------------------------------------------
def _month_key(period: DimPeriod) -> int:
    """Sortable absolute month number, so ranges can cross a year boundary."""
    return period.jalali_year * 12 + (period.jalali_month - 1)


def months_between(start: DimPeriod, end: DimPeriod) -> list[DimPeriod]:
    """
    Every month row from `start` to `end` inclusive, in calendar order.

    Only months that actually exist are returned — a gap in the calendar is
    simply absent rather than an error, because a department that recorded
    nothing in a month should still be able to report across it.
    """
    if _month_key(start) > _month_key(end):
        raise PeriodRangeError("ماه شروع باید پیش از ماه پایان باشد.")
    lo, hi = _month_key(start), _month_key(end)
    months = [
        p for p in DimPeriod.objects.filter(kind=PeriodKind.MONTH)
        if lo <= _month_key(p) <= hi
    ]
    return sorted(months, key=_month_key)


def previous_span(start: DimPeriod, length: int) -> list[DimPeriod]:
    """
    The `length` months immediately before `start`.

    Equal-length is the point: comparing a quarter against a half-year would
    make growth meaningless. When the calendar does not reach back far enough
    the list comes back short, and the caller reports "no comparable period"
    rather than dividing by a partial one.
    """
    if length <= 0:
        return []
    hi = _month_key(start) - 1
    lo = hi - (length - 1)
    months = [
        p for p in DimPeriod.objects.filter(kind=PeriodKind.MONTH)
        if lo <= _month_key(p) <= hi
    ]
    return sorted(months, key=_month_key)


def _leaves(months: list[DimPeriod]) -> list[int]:
    """
    Fact ids to sum over.

    A month may be split into weeks (and weeks into days); figures then live
    on the leaves, never on the month itself, so summing the month rows would
    silently return zero.
    """
    ids: list[int] = []
    for month in months:
        ids.extend(leaf_ids_for(month))
    return ids


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
@dataclass
class Totals:
    sales: Decimal = ZERO
    profit: Decimal = ZERO
    cost: Decimal = ZERO
    invoices: int = 0
    calls: int = 0
    collected: Decimal = ZERO
    receivables: Decimal = ZERO
    target: Decimal = ZERO
    names: dict = field(default_factory=dict)


def _sum_by_employee(months: list[DimPeriod], channel: str) -> dict[int, Totals]:
    """Per-salesperson totals across the whole span."""
    out: dict[int, Totals] = {}
    leaves = _leaves(months)
    rows = FactSalesMonthly.objects.filter(
        period_id__in=leaves, channel=channel
    ).select_related("employee")
    for row in rows:
        t = out.setdefault(row.employee_id, Totals())
        t.sales += row.revenue_rial
        t.profit += row.profit_rial
        t.cost += row.cost_rial
        t.invoices += row.invoice_count
        t.calls += row.calls
        t.collected += row.collected_rial
        t.receivables += row.receivables_rial
        t.names[row.employee_id] = row.employee.full_name_fa

    # Targets are a monthly plan, so they sum over the months themselves —
    # never over the leaves, which would multiply the plan by the number of
    # weeks in each month.
    plans = SalesTarget.objects.filter(
        period_id__in=[m.id for m in months], channel=channel,
        province__isnull=True, employee__isnull=False,
    )
    for plan in plans:
        out.setdefault(plan.employee_id, Totals()).target += plan.target_rial
    return out


def _growth(current: Decimal, previous: Decimal):
    """Percent change, or None when there is no base to grow from."""
    if previous is None or previous == 0:
        return None
    return float((current - previous) / previous * 100)


def _ratio(numerator: Decimal, denominator: Decimal):
    if not denominator:
        return None
    return float(numerator / denominator * 100)


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------
def build(start: DimPeriod, end: DimPeriod, channel: str = "b2b") -> dict:
    months = months_between(start, end)
    if not months:
        raise PeriodRangeError("در این بازه هیچ ماهی تعریف نشده است.")

    length = len(months)
    prior = previous_span(start, length)
    comparable = len(prior) == length  # a short tail is not a fair comparison

    current = _sum_by_employee(months, channel)
    before = _sum_by_employee(prior, channel) if comparable else {}

    names: dict[int, str] = {}
    for bucket in (current, before):
        for totals in bucket.values():
            names.update(totals.names)

    rows = []
    for employee_id in sorted(current.keys() | before.keys()):
        now = current.get(employee_id, Totals())
        was = before.get(employee_id)
        rows.append({
            "employee_id": employee_id,
            "name": names.get(employee_id, "—"),
            "sales_rial": str(now.sales),
            "profit_rial": str(now.profit),
            "cost_rial": str(now.cost),
            "invoice_count": now.invoices,
            "calls": now.calls,
            "collected_rial": str(now.collected),
            "receivables_rial": str(now.receivables),
            "target_rial": str(now.target),
            "achievement_pct": _ratio(now.sales, now.target),
            "margin_pct": _ratio(now.profit, now.sales),
            "prev_sales_rial": str(was.sales) if was else None,
            "growth_pct": _growth(now.sales, was.sales) if was else None,
        })
    rows.sort(key=lambda r: Decimal(r["sales_rial"]), reverse=True)

    def totals_of(bucket: dict[int, Totals]) -> Totals:
        merged = Totals()
        for t in bucket.values():
            merged.sales += t.sales
            merged.profit += t.profit
            merged.cost += t.cost
            merged.invoices += t.invoices
            merged.calls += t.calls
            merged.collected += t.collected
            merged.receivables += t.receivables
            merged.target += t.target
        return merged

    now_total = totals_of(current)
    was_total = totals_of(before) if comparable else None

    return {
        "channel": channel,
        "range": {
            "from": {"id": start.id, "label": start.label},
            "to": {"id": end.id, "label": end.label},
            "months": [{"id": m.id, "label": m.label} for m in months],
            "length": length,
        },
        "previous_range": {
            "comparable": comparable,
            "from": {"id": prior[0].id, "label": prior[0].label} if comparable else None,
            "to": {"id": prior[-1].id, "label": prior[-1].label} if comparable else None,
            "note": None if comparable else
                    "دوره‌ی هم‌طولِ قبلی در تقویم موجود نیست، پس مقایسه‌ای انجام نشده.",
        },
        "rows": rows,
        "totals": {
            "sales_rial": str(now_total.sales),
            "profit_rial": str(now_total.profit),
            "cost_rial": str(now_total.cost),
            "invoice_count": now_total.invoices,
            "calls": now_total.calls,
            "collected_rial": str(now_total.collected),
            "receivables_rial": str(now_total.receivables),
            "target_rial": str(now_total.target),
            "achievement_pct": _ratio(now_total.sales, now_total.target),
            "margin_pct": _ratio(now_total.profit, now_total.sales),
            "collection_pct": _ratio(now_total.collected, now_total.sales),
            "prev_sales_rial": str(was_total.sales) if was_total else None,
            "growth_pct": _growth(now_total.sales, was_total.sales) if was_total else None,
        },
        "provinces": _provinces(months, prior if comparable else [], channel),
        "customer_groups": _customer_groups(months, prior if comparable else [], channel),
        "monthly": _monthly(months, channel),
    }


def _provinces(months, prior, channel) -> list[dict]:
    """Sales by province across the span, biggest first, zeros omitted."""
    def totals(period_ids):
        out: dict[int, dict] = {}
        rows = FactSalesProvince.objects.filter(
            period_id__in=period_ids, channel=channel
        ).select_related("province")
        for row in rows:
            bucket = out.setdefault(
                row.province_id,
                {"name": row.province.name_fa, "sales": ZERO, "target": ZERO},
            )
            bucket["sales"] += row.sales_rial
            bucket["target"] += row.target_rial
        return out

    now = totals(_leaves(months))
    was = totals(_leaves(prior)) if prior else {}

    rows = [
        {
            "province_id": pid,
            "name": data["name"],
            "sales_rial": str(data["sales"]),
            "target_rial": str(data["target"]),
            "achievement_pct": _ratio(data["sales"], data["target"]),
            "prev_sales_rial": str(was[pid]["sales"]) if pid in was else None,
            "growth_pct": _growth(data["sales"], was[pid]["sales"]) if pid in was else None,
        }
        for pid, data in now.items() if data["sales"]
    ]
    rows.sort(key=lambda r: Decimal(r["sales_rial"]), reverse=True)
    return rows


def _customer_groups(months, prior, channel) -> list[dict]:
    """Sales by customer segment, with each segment's share of the span."""
    def totals(period_ids):
        out: dict[int, dict] = {}
        rows = FactSalesByCustomerGroup.objects.filter(
            period_id__in=period_ids, channel=channel
        ).select_related("customer_group")
        for row in rows:
            bucket = out.setdefault(row.customer_group_id, {
                "name": row.customer_group.name_fa,
                "sort": row.customer_group.sort_order,
                "sales": ZERO, "profit": ZERO, "invoices": 0,
            })
            bucket["sales"] += row.sales_rial
            bucket["profit"] += row.profit_rial
            bucket["invoices"] += row.invoice_count
        return out

    now = totals(_leaves(months))
    was = totals(_leaves(prior)) if prior else {}
    grand = sum((d["sales"] for d in now.values()), ZERO)

    rows = [
        {
            "group_id": gid,
            "name": data["name"],
            "sales_rial": str(data["sales"]),
            "profit_rial": str(data["profit"]),
            "invoice_count": data["invoices"],
            "share_pct": _ratio(data["sales"], grand),
            "margin_pct": _ratio(data["profit"], data["sales"]),
            "prev_sales_rial": str(was[gid]["sales"]) if gid in was else None,
            "growth_pct": _growth(data["sales"], was[gid]["sales"]) if gid in was else None,
        }
        for gid, data in sorted(now.items(), key=lambda kv: kv[1]["sort"])
    ]
    return rows


def _monthly(months, channel) -> list[dict]:
    """The span month by month, for the trend line."""
    out = []
    for month in months:
        leaves = leaf_ids_for(month)
        sales = ZERO
        profit = ZERO
        for row in FactSalesMonthly.objects.filter(
            period_id__in=leaves, channel=channel
        ):
            sales += row.revenue_rial
            profit += row.profit_rial
        target = ZERO
        for plan in SalesTarget.objects.filter(
            period=month, channel=channel, province__isnull=True, employee__isnull=False
        ):
            target += plan.target_rial
        out.append({
            "period_id": month.id,
            "label": month.label,
            "sales_rial": str(sales),
            "profit_rial": str(profit),
            "target_rial": str(target),
            "achievement_pct": _ratio(sales, target),
        })
    return out
