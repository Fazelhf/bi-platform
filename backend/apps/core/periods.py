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
def ensure_days(week: DimPeriod) -> list[DimPeriod]:
    """
    Create (idempotently) the day children of a week.

    Days hang under weeks rather than directly under the month so everything
    built for weekly reporting keeps working — the progress strip, the
    calendar, the week-vs-month reconciliation — and the day layer is simply
    one level further down. Thirty-one dots in a row would not be a strip.

    Refused if the week itself already holds figures, for the same reason a
    month with figures cannot be split: the numbers would then sit on both the
    week and its days and every total would count them twice.
    """
    if week.kind != PeriodKind.WEEK:
        raise ValueError("only a week can be split into days")
    if has_facts(week):
        raise ValueError(
            "این هفته داده‌ی ثبت‌شده دارد و دیگر نمی‌تواند به روز تقسیم شود."
        )
    if not (week.start_date and week.end_date):
        raise ValueError("این هفته تاریخ شروع و پایان ندارد.")

    days = []
    span = (week.end_date - week.start_date).days + 1
    for i in range(span):
        g = week.start_date + timedelta(days=i)
        jy, jm, jd = jalali.from_gregorian(g)
        day, _ = DimPeriod.objects.update_or_create(
            parent=week,
            seq=i + 1,
            defaults={
                # The Jalali month of the day itself, which for a week clipped
                # to a month is always the week's month.
                "jalali_year": jy,
                "jalali_month": jm,
                "kind": PeriodKind.DAY,
                "start_date": g,
                "end_date": g,
                "code": f"{week.code}.{jd:02d}",
            },
        )
        days.append(day)

    DimPeriod.objects.filter(parent=week).exclude(
        id__in=[d.id for d in days]
    ).delete()
    return days


@transaction.atomic
def unsplit(period: DimPeriod) -> int:
    """
    Drop a period's children so entry goes back to the coarser grain — a
    month back to monthly, or a week back to weekly.

    Refused once any child holds figures: those numbers were recorded against
    a day or a week and there is no honest way to fold them into a single row
    the manager never typed. Clear the children first, deliberately.
    """
    if period.kind not in (PeriodKind.MONTH, PeriodKind.WEEK):
        raise ValueError("only a month or a week can be un-split")

    unit = "هفته" if period.kind == PeriodKind.MONTH else "روز"
    # Check the whole subtree: a week whose days hold figures still blocks the
    # month, even though the week row itself is empty.
    filled = [c for c in period.children.all() if any(has_facts(l) for l in leaves_of(c))]
    if filled:
        names = "، ".join(f"{unit} {c.seq}" for c in filled)
        raise ValueError(f"این {unit}‌ها داده دارند و باید اول پاک شوند: {names}")

    count, _ = period.children.all().delete()
    return count


def month_of(period: DimPeriod) -> DimPeriod:
    """
    Walk up to the month a period belongs to.

    Targets are set monthly, so every sheet needs its month — and `parent`
    alone is no longer enough now that a day's parent is a week, not a month.
    """
    node = period
    while node.parent_id and node.kind != PeriodKind.MONTH:
        node = node.parent
    return node


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

    # With a day layer the same proof has to hold one level down: each week's
    # KPI must equal the sum of its days. Checking only month-vs-weeks would
    # declare a balanced month while a week silently disagreed with its days.
    day_checks = []
    for w in weeks:
        days = list(w.children.order_by("seq"))
        if not days:
            continue
        w_total = revenue_of(w)
        d_total = sum((revenue_of(d) for d in days), Decimal(0))
        day_checks.append({
            "week_seq": w.seq,
            "week_label": w.label,
            "week_total": str(w_total),
            "days_total": str(d_total),
            "difference": str(w_total - d_total),
            "balanced": w_total == d_total and not (has_facts(w) and bool(days)),
            "day_count": len(days),
        })

    return {
        "month_total": str(month_total),
        "weeks_total": str(weeks_total),
        "difference": str(month_total - weeks_total),
        "balanced": (
            month_total == weeks_total
            and not orphan
            and all(c["balanced"] for c in day_checks)
        ),
        # True only if something wrote to the month after it was split.
        "month_holds_own_figures": orphan,
        "weeks": [
            {"seq": w.seq, "label": w.label, "revenue": str(revenue_of(w))}
            for w in weeks
        ],
        # Empty unless at least one week is entered day by day.
        "day_checks": day_checks,
    }


def _state_of(period: DimPeriod) -> str:
    """empty / draft / submitted / approved for one leaf period."""
    from apps.sales.models import ApprovalStatus, FactSalesMonthly

    rows = FactSalesMonthly.objects.filter(period=period)
    if rows.filter(status=ApprovalStatus.APPROVED).exists():
        return "approved"
    if rows.filter(status=ApprovalStatus.SUBMITTED).exists():
        return "submitted"
    return "draft" if rows.exists() else "empty"


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
        # Figures live on leaves. Once a week is split into days its own row is
        # empty by design, so its state has to come from the days beneath it —
        # otherwise every daily week would show as "not entered".
        leaf_ids = [p.id for p in leaves_of(wk)]
        rows = FactSalesMonthly.objects.filter(period_id__in=leaf_ids)
        state = "empty"
        if rows.filter(status=ApprovalStatus.APPROVED).exists():
            state = "approved"
        elif rows.filter(status=ApprovalStatus.SUBMITTED).exists():
            state = "submitted"
        elif rows.exists():
            state = "draft"
        if state != "empty":
            entered += 1
            # "data as of" is the last day actually filled, not the end of the
            # week — with daily entry a week is usually half done.
            filled_days = (
                FactSalesMonthly.objects.filter(period_id__in=leaf_ids)
                .order_by("-period__end_date").values_list("period__end_date", flat=True)
                .first()
            )
            as_of = filled_days or wk.end_date
        days = list(wk.children.order_by("seq")) if wk.pk != month.pk else []
        items.append({
            "id": wk.id,
            "seq": wk.seq,
            "label": wk.label,
            "days": wk.days,
            "state": state,
            # Present only when this week is entered day by day.
            "day_periods": [
                {
                    "id": d.id,
                    "seq": d.seq,
                    "label": d.label,
                    "date": d.start_date.isoformat() if d.start_date else None,
                    "jalali_day": jalali.from_gregorian(d.start_date)[2] if d.start_date else None,
                    "state": _state_of(d),
                }
                for d in days
            ],
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
