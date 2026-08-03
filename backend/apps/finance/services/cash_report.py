"""
گزارش نقدینگی — the finance colleague's weekly sheet, computed rather than typed.

His workbook gives a day-by-day grid of واریز and برداشت with a total row and
a total column. This reproduces that exactly, and adds the two things a
treasury needs that a flow-only sheet cannot give:

* a **running balance** — opening + cumulative net, so the report says how
  much cash there is, not only which way it moved;
* an **honest warning** when the period burned cash or the balance fell under
  the threshold. His sample week netted −۳٫۸ میلیارد; a report that shows two
  totals and leaves the subtraction to the reader buries that.
"""
from __future__ import annotations

from decimal import Decimal

from apps.core.models import DimPeriod
from apps.core.periods import leaves_of
from apps.finance.models import (
    CashCategory,
    CashMovement,
    CreditLine,
    Direction,
    FinanceSetting,
)

ZERO = Decimal(0)


def _day_leaves(period: DimPeriod) -> list[DimPeriod]:
    """Every day under a month/week — the grain movements are stored at."""
    return sorted(leaves_of(period), key=lambda p: (p.start_date or p.id, p.id))


def _ordered_days(periods: list[DimPeriod]) -> list[DimPeriod]:
    out: list[DimPeriod] = []
    for p in periods:
        out.extend(_day_leaves(p))
    return sorted(out, key=lambda p: (p.start_date or p.id, p.id))


def running_balance_before(days: list[DimPeriod]) -> Decimal:
    """
    Cash on hand the instant the report's first day begins.

    Opening balance plus every approved-or-draft movement recorded earlier.
    Movements are summed regardless of approval state on purpose: the balance
    is meant to reflect what the bank actually did, and money does not wait
    for the CEO to click تایید.
    """
    setting = FinanceSetting.get()
    balance = setting.opening_balance_rial
    if not days:
        return balance

    first = days[0]
    earlier = CashMovement.objects.filter(
        period__start_date__lt=first.start_date
    ) if first.start_date else CashMovement.objects.filter(period_id__lt=first.id)

    for movement in earlier.only("direction", "amount_rial"):
        balance += movement.signed_rial
    return balance


def build(period: DimPeriod) -> dict:
    """The grid for one month or week, day by day."""
    days = _day_leaves(period)
    return _grid(days, title=period.label, period_id=period.id)


def build_range(start: DimPeriod, end: DimPeriod) -> dict:
    """The grid across a span of periods."""
    from apps.core.models import PeriodKind

    lo = (start.start_date, start.id)
    hi = (end.end_date or end.start_date, end.id)
    months = [
        p for p in DimPeriod.objects.filter(kind=PeriodKind.MONTH)
        if p.start_date and lo[0] and hi[0] and lo[0] <= p.start_date <= hi[0]
    ]
    days = _ordered_days(months or [start, end])
    return _grid(days, title=f"{start.label} تا {end.label}", period_id=None)


def _grid(days: list[DimPeriod], title: str, period_id: int | None) -> dict:
    categories = list(CashCategory.objects.filter(is_active=True))
    in_cats = [c for c in categories if c.allows(Direction.IN)]
    out_cats = [c for c in categories if c.allows(Direction.OUT)]

    day_ids = [d.id for d in days]
    movements = (
        CashMovement.objects.filter(period_id__in=day_ids)
        .select_related("category", "credit_line")
    )

    # (day, direction, category) -> amount
    cells: dict[tuple[int, str, int], Decimal] = {}
    for m in movements:
        key = (m.period_id, m.direction, m.category_id)
        cells[key] = cells.get(key, ZERO) + m.amount_rial

    opening = running_balance_before(days)
    balance = opening

    rows = []
    for day in days:
        row_in = {c.id: cells.get((day.id, Direction.IN, c.id), ZERO) for c in in_cats}
        row_out = {c.id: cells.get((day.id, Direction.OUT, c.id), ZERO) for c in out_cats}
        total_in = sum(row_in.values(), ZERO)
        total_out = sum(row_out.values(), ZERO)
        balance += total_in - total_out
        rows.append({
            "period_id": day.id,
            "label": day.label,
            "date": day.start_date.isoformat() if day.start_date else None,
            "in": {str(k): str(v) for k, v in row_in.items()},
            "out": {str(k): str(v) for k, v in row_out.items()},
            "total_in": str(total_in),
            "total_out": str(total_out),
            "net": str(total_in - total_out),
            "balance": str(balance),
        })

    def column_totals(cats, direction):
        return {
            str(c.id): str(sum(
                (cells.get((d.id, direction, c.id), ZERO) for d in days), ZERO
            ))
            for c in cats
        }

    totals_in = column_totals(in_cats, Direction.IN)
    totals_out = column_totals(out_cats, Direction.OUT)
    grand_in = sum((Decimal(v) for v in totals_in.values()), ZERO)
    grand_out = sum((Decimal(v) for v in totals_out.values()), ZERO)

    setting = FinanceSetting.get()
    warnings = []
    if grand_out > grand_in:
        warnings.append({
            "level": "warning",
            "text": "در این بازه برداشت از واریز بیشتر بوده است.",
            "amount": str(grand_out - grand_in),
        })
    if setting.low_balance_rial and balance < setting.low_balance_rial:
        warnings.append({
            "level": "danger",
            "text": "موجودی پایان دوره زیر آستانه هشدار است.",
            "amount": str(balance),
        })
    if balance < ZERO:
        warnings.append({
            "level": "danger",
            "text": "موجودی پایان دوره منفی است.",
            "amount": str(balance),
        })

    return {
        "title": title,
        "period_id": period_id,
        "categories": {
            "in": [{"id": c.id, "name": c.name_fa, "code": c.code} for c in in_cats],
            "out": [{"id": c.id, "name": c.name_fa, "code": c.code} for c in out_cats],
        },
        "days": rows,
        "totals": {
            "in": totals_in,
            "out": totals_out,
            "total_in": str(grand_in),
            "total_out": str(grand_out),
            "net": str(grand_in - grand_out),
        },
        "balance": {
            "opening": str(opening),
            "closing": str(balance),
            "low_threshold": str(setting.low_balance_rial),
        },
        "warnings": warnings,
        "credit_summary": credit_summary(),
    }


def credit_summary() -> dict:
    """
    Where the company stands on facilities, lending and partner accounts.

    Balances are summed from the ledger, so this cannot disagree with the
    movements above it.
    """
    out = {"facility": [], "lending": [], "partner": []}
    totals = {"facility": ZERO, "lending": ZERO, "partner": ZERO}

    lines = CreditLine.objects.exclude(
        status=CreditLine.Status.CANCELLED
    ).prefetch_related("movements")

    for line in lines:
        balance = line.balance_rial
        totals[line.kind] += balance
        out[line.kind].append({
            "id": line.id,
            "title": line.title,
            "counterparty": line.counterparty,
            "principal_rial": str(line.principal_rial),
            "balance_rial": str(balance),
            "status": line.status,
            "due_on": line.due_on.isoformat() if line.due_on else None,
        })

    for kind in out:
        out[kind].sort(key=lambda r: abs(Decimal(r["balance_rial"])), reverse=True)

    return {
        "lines": out,
        # Signed from the company's point of view: what it owes on facilities
        # is negative, what it is owed on lending is positive.
        "owed_by_company": str(-totals["facility"]),
        "owed_to_company": str(totals["lending"]),
        "partner_net": str(totals["partner"]),
    }
