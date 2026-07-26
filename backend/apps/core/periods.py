"""
Period-tree services: building the weeks of a month, and walking the tree.

Everything that reads facts must go through `leaves_of()`. Summing a parent's
own row together with its children's would double count — see the invariant on
DimPeriod.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction

from apps.core import jalali
from apps.core.models import DimPeriod, PeriodKind


def month_bounds(period: DimPeriod) -> tuple:
    start = jalali.to_gregorian(period.jalali_year, period.jalali_month, 1)
    end = jalali.to_gregorian(
        period.jalali_year,
        period.jalali_month,
        jalali.month_days(period.jalali_year, period.jalali_month),
    )
    return start, end


def backfill_dates(period: DimPeriod) -> DimPeriod:
    """Give a month row its Gregorian bounds and code (used by the migration)."""
    period.kind = PeriodKind.MONTH
    period.seq = period.jalali_month
    period.start_date, period.end_date = month_bounds(period)
    period.code = f"{period.jalali_year}.{period.jalali_month:02d}"
    return period


@transaction.atomic
def ensure_weeks(month: DimPeriod, min_days: int = jalali.MIN_WEEK_DAYS) -> list[DimPeriod]:
    """
    Create (idempotently) the week children of a month.

    Refuses if the month itself already carries facts: splitting it then would
    leave figures on both the month and its weeks, and every total would be
    counted twice. Such a month must stay monthly — which is exactly how the
    existing history keeps working.
    """
    if month.kind != PeriodKind.MONTH:
        raise ValueError("only a month can be split into weeks")
    if has_facts(month):
        raise ValueError(
            "این ماه داده‌ی ثبت‌شده دارد و دیگر نمی‌تواند به هفته تقسیم شود."
        )

    spans = jalali.split_month_into_weeks(
        month.jalali_year, month.jalali_month, min_days=min_days
    )
    weeks = []
    for i, (first_day, last_day) in enumerate(spans, start=1):
        week, _ = DimPeriod.objects.update_or_create(
            parent=month,
            seq=i,
            defaults={
                "jalali_year": month.jalali_year,
                "jalali_month": month.jalali_month,
                "kind": PeriodKind.WEEK,
                "start_date": jalali.to_gregorian(
                    month.jalali_year, month.jalali_month, first_day
                ),
                "end_date": jalali.to_gregorian(
                    month.jalali_year, month.jalali_month, last_day
                ),
                "code": f"{month.code}.{i}",
            },
        )
        weeks.append(week)

    # A month that used to have more weeks (min_days changed) loses the extras.
    DimPeriod.objects.filter(parent=month).exclude(
        id__in=[w.id for w in weeks]
    ).delete()
    return weeks


@transaction.atomic
def unsplit(month: DimPeriod) -> int:
    """
    Drop a month's weeks so it goes back to monthly entry.

    Refused once any week holds figures: those numbers were recorded against
    a week and there is no honest way to fold them into a single monthly row
    the manager never typed. Clear the weeks first, deliberately.
    """
    if month.kind != PeriodKind.MONTH:
        raise ValueError("only a month can be un-split")

    filled = [w for w in month.children.all() if has_facts(w)]
    if filled:
        names = "، ".join(f"هفته {w.seq}" for w in filled)
        raise ValueError(
            f"این هفته‌ها داده دارند و باید اول پاک شوند: {names}"
        )

    count, _ = month.children.all().delete()
    return count


def leaves_of(period: DimPeriod) -> list[DimPeriod]:
    """Every leaf under a period — or the period itself when it has no children."""
    children = list(period.children.all())
    if not children:
        return [period]
    out: list[DimPeriod] = []
    for child in children:
        out.extend(leaves_of(child))
    return out


def leaf_ids_for(period: DimPeriod) -> list[int]:
    return [p.id for p in leaves_of(period)]


def has_facts(period: DimPeriod, domain: str = "sales") -> bool:
    """
    True when *this* domain has stored numbers against this exact period.

    Scoped per domain on purpose. The no-double-counting rule is really
    "within one fact table, store at exactly one level of the tree" — so
    sales can sit on weeks while production stays on months. Both are safe;
    what would break is one domain writing to a month *and* its weeks.
    """
    from apps.production.models import FactProduction
    from apps.sales.models import FactSalesMonthly, FactSalesProvince

    if domain == "production":
        return FactProduction.objects.filter(period=period).exists()
    return (
        FactSalesMonthly.objects.filter(period=period).exists()
        or FactSalesProvince.objects.filter(period=period).exists()
    )


def calendar(month: DimPeriod) -> dict:
    """
    Day-by-day layout of the month, so the UI can draw a real calendar and a
    manager can see exactly which days a week covers before filling it in.
    All Jalali maths stays here; the frontend just renders.
    """
    total = jalali.month_days(month.jalali_year, month.jalali_month)
    weeks = list(month.children.order_by("seq"))

    # day-of-month → week seq
    owner: dict[int, int] = {}
    for w in weeks:
        if not (w.start_date and w.end_date):
            continue
        for n in range((w.end_date - w.start_date).days + 1):
            _, _, jd = jalali.from_gregorian(w.start_date + timedelta(days=n))
            owner[jd] = w.seq

    days = []
    for jd in range(1, total + 1):
        g = jalali.to_gregorian(month.jalali_year, month.jalali_month, jd)
        days.append({
            "day": jd,
            "weekday": jalali.weekday(g),            # 0 = شنبه
            "weekday_fa": jalali.WEEKDAYS_FA[jalali.weekday(g)],
            "gregorian": g.isoformat(),
            "week_seq": owner.get(jd),               # None when not split
        })

    return {
        "month_label": month.label,
        "total_days": total,
        "days": days,
        "weeks": [
            {
                "seq": w.seq,
                "label": w.label,
                "days": w.days,
                "first_day": jalali.from_gregorian(w.start_date)[2] if w.start_date else None,
                "last_day": jalali.from_gregorian(w.end_date)[2] if w.end_date else None,
            }
            for w in weeks
        ],
    }


def reconciliation(month: DimPeriod) -> dict:
    """
    Prove that جمع هفته‌ها == ماه, rather than asserting it.

    The two figures are produced by different code paths — each week's KPI is
    computed from that week's own rows, while the month's is computed from all
    its leaves at once — so comparing them genuinely exercises the roll-up. A
    mismatch would mean a bug, not a data-entry problem.

    Also reports the only structural way a discrepancy could ever arise: a
    period holding figures while also having children.
    """
    from decimal import Decimal

    from apps.core.models import FactKPI, KPIScope

    def revenue_of(p) -> Decimal:
        rows = FactKPI.objects.filter(
            period=p, scope=KPIScope.COMPANY, kpi__code="revenue"
        )
        return sum((r.actual or Decimal(0) for r in rows), Decimal(0))

    weeks = list(month.children.order_by("seq"))
    month_total = revenue_of(month)
    weeks_total = sum((revenue_of(w) for w in weeks), Decimal(0))
    orphan = has_facts(month) and bool(weeks)

    return {
        "month_total": str(month_total),
        "weeks_total": str(weeks_total),
        "difference": str(month_total - weeks_total),
        "balanced": month_total == weeks_total and not orphan,
        # True only if something wrote to the month after it was split.
        "month_holds_own_figures": orphan,
        "weeks": [
            {"seq": w.seq, "label": w.label, "revenue": str(revenue_of(w))}
            for w in weeks
        ],
    }


def progress(month: DimPeriod) -> dict:
    """
    How much of a month has been filled in — drives the dots strip and the
    "ماه هنوز کامل نشده" badge on the dashboards.
    """
    from apps.sales.models import ApprovalStatus, FactSalesMonthly

    weeks = list(month.children.order_by("seq"))
    if not weeks:
        # A plain monthly period: it is its own single "week".
        weeks = [month]

    entered = 0
    as_of = None
    items = []
    for wk in weeks:
        rows = FactSalesMonthly.objects.filter(period=wk)
        state = "empty"
        if rows.filter(status=ApprovalStatus.APPROVED).exists():
            state = "approved"
        elif rows.filter(status=ApprovalStatus.SUBMITTED).exists():
            state = "submitted"
        elif rows.exists():
            state = "draft"
        if state != "empty":
            entered += 1
            as_of = wk.end_date
        items.append({
            "id": wk.id,
            "seq": wk.seq,
            "label": wk.label,
            "days": wk.days,
            "state": state,
        })

    total_days = month.days or 0
    elapsed_days = 0
    if as_of and month.start_date:
        elapsed_days = (as_of - month.start_date).days + 1

    return {
        "weeks": items,
        "entered": entered,
        "total": len(items),
        "complete": entered == len(items),
        "as_of": as_of,
        "elapsed_days": elapsed_days,
        "total_days": total_days,
        # Fraction of the month covered so far — targets are pro-rated by DAYS,
        # never by week count, because weeks differ in length.
        "elapsed_ratio": (elapsed_days / total_days) if total_days else 0.0,
    }
