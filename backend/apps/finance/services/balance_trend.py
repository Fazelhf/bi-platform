"""
میانگین موجودی — average cash held, per week and per month, split by account.

A closing balance answers «امروز چقدر داریم؟». It says nothing about whether
the month was comfortable: a company can finish it in credit having been
overdrawn for three weeks. The average of the daily closing balances does say
that, so it is what this computes.

Definition used throughout: **the mean of each day's closing balance over the
days in the period**. Days with no movement still count — holding money for a
quiet day is still holding it — which is why the divisor is the number of
days in the period, not the number of days that had a transaction.
"""
from __future__ import annotations

from decimal import Decimal

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import leaves_of
from apps.finance.models import BankAccount, CashMovement, Direction

ZERO = Decimal(0)


def _days_of(period: DimPeriod) -> list[DimPeriod]:
    return sorted(leaves_of(period), key=lambda p: (p.start_date or p.id, p.id))


def _signed(movement) -> Decimal:
    return (
        movement.amount_rial
        if movement.direction == Direction.IN
        else -movement.amount_rial
    )


def _movements_by_day(day_ids: list[int]) -> dict[tuple[int, int | None], Decimal]:
    """{(day_id, account_id): net} for the given days."""
    out: dict[tuple[int, int | None], Decimal] = {}
    rows = CashMovement.objects.filter(period_id__in=day_ids).only(
        "period_id", "account_id", "direction", "amount_rial"
    )
    for row in rows:
        key = (row.period_id, row.account_id)
        out[key] = out.get(key, ZERO) + _signed(row)
    return out


def _opening_before(first_day: DimPeriod | None) -> dict[int | None, Decimal]:
    """
    Each account's balance the instant `first_day` begins: its own opening
    figure plus every movement recorded earlier.
    """
    balances: dict[int | None, Decimal] = {
        a.id: a.opening_balance_rial for a in BankAccount.objects.all()
    }
    if first_day is None:
        return balances

    earlier = (
        CashMovement.objects.filter(period__start_date__lt=first_day.start_date)
        if first_day.start_date
        else CashMovement.objects.filter(period_id__lt=first_day.id)
    )
    for row in earlier.only("account_id", "direction", "amount_rial"):
        balances[row.account_id] = balances.get(row.account_id, ZERO) + _signed(row)
    return balances


def _walk(days: list[DimPeriod], opening: dict[int | None, Decimal]) -> dict:
    """
    Run the balance forward one day at a time.

    Returns the per-account average and closing balance, plus the same for
    the total. Averaging happens over `len(days)`, so a quiet day pulls the
    average toward the balance it was held at rather than being skipped.
    """
    if not days:
        return {"average": {}, "closing": dict(opening), "average_total": ZERO,
                "closing_total": sum(opening.values(), ZERO), "day_count": 0}

    net = _movements_by_day([d.id for d in days])
    running = dict(opening)
    sums: dict[int | None, Decimal] = {}
    total_sum = ZERO

    for day in days:
        for account_id in set(running) | {
            key[1] for key in net if key[0] == day.id
        }:
            running[account_id] = running.get(account_id, ZERO) + net.get(
                (day.id, account_id), ZERO
            )
        for account_id, balance in running.items():
            sums[account_id] = sums.get(account_id, ZERO) + balance
        total_sum += sum(running.values(), ZERO)

    count = Decimal(len(days))
    return {
        "average": {k: (v / count) for k, v in sums.items()},
        "closing": running,
        "average_total": total_sum / count,
        "closing_total": sum(running.values(), ZERO),
        "day_count": len(days),
    }


def _accounts_index() -> dict[int | None, dict]:
    index: dict[int | None, dict] = {
        a.id: {"id": a.id, "title": a.title, "label": a.label,
               "color": a.color or "", "kind": a.kind}
        for a in BankAccount.objects.all()
    }
    # Rows recorded before accounts existed are reported honestly rather than
    # folded into whichever account happens to be first.
    index[None] = {"id": None, "title": "بدون حساب", "label": "بدون حساب",
                   "color": "#94a3b8", "kind": ""}
    return index


def _split(values: dict[int | None, Decimal], index: dict) -> list[dict]:
    rows = [
        {**index.get(account_id, index[None]), "amount": str(amount)}
        for account_id, amount in values.items()
        if amount != ZERO or account_id is not None
    ]
    rows.sort(key=lambda r: abs(Decimal(r["amount"])), reverse=True)
    return rows


def for_month(month: DimPeriod) -> dict:
    """
    One month, week by week — «در آبان هر هفته چقدر میانگین داشتیم؟».

    Falls back to a single row covering the month when it was never split
    into weeks, so the answer is never simply missing.
    """
    index = _accounts_index()
    weeks = [c for c in month.children.all() if c.kind == PeriodKind.WEEK]
    weeks.sort(key=lambda w: (w.start_date or w.id, w.id))

    buckets = weeks or [month]
    rows = []
    for bucket in buckets:
        days = _days_of(bucket)
        walked = _walk(days, _opening_before(days[0] if days else None))
        rows.append({
            "period_id": bucket.id,
            "label": bucket.label,
            "day_count": walked["day_count"],
            "average_rial": str(walked["average_total"]),
            "closing_rial": str(walked["closing_total"]),
            "by_account": _split(walked["average"], index),
        })

    month_days = _days_of(month)
    whole = _walk(month_days, _opening_before(month_days[0] if month_days else None))
    return {
        "period": {"id": month.id, "label": month.label},
        "grain": "week" if weeks else "month",
        "rows": rows,
        "month": {
            "day_count": whole["day_count"],
            "average_rial": str(whole["average_total"]),
            "closing_rial": str(whole["closing_total"]),
            "by_account": _split(whole["average"], index),
        },
        "accounts": [v for k, v in index.items() if k is not None],
    }


def for_year(year: int) -> dict:
    """
    Every month of a Jalali year — the chart of «هر ماه چقدر میانگین موجودی
    داشتیم», each column split into the accounts that make it up.
    """
    index = _accounts_index()
    months = sorted(
        DimPeriod.objects.filter(kind=PeriodKind.MONTH, jalali_year=year),
        key=lambda m: m.jalali_month,
    )

    rows = []
    for month in months:
        days = _days_of(month)
        walked = _walk(days, _opening_before(days[0] if days else None))
        rows.append({
            "period_id": month.id,
            "label": month.label,
            "month": month.jalali_month,
            "day_count": walked["day_count"],
            "average_rial": str(walked["average_total"]),
            "closing_rial": str(walked["closing_total"]),
            "by_account": _split(walked["average"], index),
            # A month nobody has recorded yet is flagged rather than drawn as
            # a real zero next to months that genuinely held nothing.
            "has_data": bool(
                CashMovement.objects.filter(
                    period_id__in=[d.id for d in days]
                ).exists()
            ),
        })

    recorded = [r for r in rows if r["has_data"]]
    year_average = (
        sum((Decimal(r["average_rial"]) for r in recorded), ZERO) / len(recorded)
        if recorded else ZERO
    )
    return {
        "year": year,
        "years": sorted(
            {p.jalali_year for p in DimPeriod.objects.filter(kind=PeriodKind.MONTH)},
            reverse=True,
        ),
        "rows": rows,
        "year_average_rial": str(year_average),
        "accounts": [v for k, v in index.items() if k is not None],
    }
