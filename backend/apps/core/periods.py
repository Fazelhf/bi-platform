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
def ensure_weeks(
    month: DimPeriod, min_days: int = jalali.MIN_WEEK_DAYS, guard: bool = True,
) -> list[DimPeriod]:
    """
    Create (idempotently) the week children of a month.

    With `guard`, refuses if the month itself already carries facts. Since
    each section records at its own grain (PeriodGrain), a monthly section's
    figures on the month and a weekly section's on its weeks are both valid,
    so the calendar is deepened with guard=False by ensure_depth().
    """
    if month.kind != PeriodKind.MONTH:
        raise ValueError("only a month can be split into weeks")
    if guard and has_any_facts(month):
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
def ensure_days(week: DimPeriod, guard: bool = True) -> list[DimPeriod]:
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
    if guard and has_any_facts(week):
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
    filled = [
        c for c in period.children.all()
        if any(has_any_facts(l) for l in leaves_of(c))
    ]
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


# --------------------------------------------------------------------------
# Per-section grain
# --------------------------------------------------------------------------
# The tree is the calendar — as deep as the finest section needs in a month —
# and each section (PeriodGrain.department) stores and totals its figures at
# its own level of it. Every read of a section's facts goes through
# units_of(period, department), never through the raw tree.

LEVEL = {"month": 0, "week": 1, "day": 2}
KIND_LEVEL = {PeriodKind.MONTH: 0, PeriodKind.WEEK: 1, PeriodKind.DAY: 2}


def channel_department(channel: str) -> str:
    """The section a sales channel's figures belong to ("" for none)."""
    from apps.core.permissions import CHANNEL_DEPARTMENT

    return CHANNEL_DEPARTMENT.get(channel, "")


def _deepest(period: DimPeriod) -> int:
    """The finest level (by kind) anywhere under a period."""
    here = KIND_LEVEL.get(period.kind, 0)
    return max([here, *(_deepest(c) for c in period.children.all())])


def physical_grain(month: DimPeriod) -> str:
    """How deep the calendar under a month goes right now."""
    return {0: "month", 1: "week", 2: "day"}[_deepest(month)]


def ensure_depth(month: DimPeriod, grain: str) -> None:
    """Deepen the calendar under a month to `grain`. Never removes anything."""
    from apps.core.models import SiteSetting

    level = LEVEL[grain]
    if level >= 1 and not month.children.exists():
        ensure_weeks(month, min_days=SiteSetting.get().min_week_days, guard=False)
    if level >= 2:
        for week in month.children.filter(kind=PeriodKind.WEEK).order_by("seq"):
            # A week with no dates cannot be cut into days; it is left as is
            # rather than failing whatever read happened to deepen the month.
            if not week.children.exists() and week.start_date and week.end_date:
                ensure_days(week, guard=False)


def _materialise(month: DimPeriod) -> None:
    """
    Write down every section's grain for a month the first time any of them
    touches it.

    All sections at once, and judged against the calendar *before* anything is
    deepened: otherwise مالی opening a month (and cutting it into days) would
    make the next section to look at it daily too.

    * تولید starts at its default — its sheet has only ever written the month.
    * The others start at their default, or at the calendar's current depth
      when that is finer: a month someone already cut into weeks for weekly
      sales stays weekly.
    """
    from apps.core.models import GRAIN_DEPARTMENTS, GrainDefault, PeriodGrain

    have = set(PeriodGrain.objects.filter(month=month).values_list("department", flat=True))
    missing = [d for d, _ in GRAIN_DEPARTMENTS if d not in have]
    if not missing:
        return
    depth = _deepest(month)
    finest = 0
    for dept in missing:
        default = LEVEL[GrainDefault.for_department(dept)]
        level = default if dept == "production" else max(default, depth)
        finest = max(finest, level)
        PeriodGrain.objects.get_or_create(
            month=month, department=dept,
            defaults={"grain": {0: "month", 1: "week", 2: "day"}[level]},
        )
    ensure_depth(month, {0: "month", 1: "week", 2: "day"}[finest])


def grain_of(period: DimPeriod, department: str) -> str:
    """
    The grain a section records the month of `period` at.

    A month nobody has set yet is written down on first use (see
    _materialise): a later change of default must not quietly re-grain a
    month that has already been worked in.
    """
    from apps.core.models import GRAIN_DEPARTMENTS, PeriodGrain

    month = month_of(period)
    if department not in dict(GRAIN_DEPARTMENTS):
        return physical_grain(month)
    row = PeriodGrain.objects.filter(month=month, department=department).first()
    if row is None:
        with transaction.atomic():
            _materialise(month)
        row = PeriodGrain.objects.get(month=month, department=department)
    return row.grain


def units_of(period: DimPeriod, department: str) -> list[DimPeriod]:
    """
    The periods a section's figures for `period` are stored on.

    A month read by a weekly section is its weeks; by a monthly one, the month
    itself. A period finer than the section records at (a week, for a monthly
    section) holds none of its figures, so it comes back empty. With no
    section, the plain leaves — the old rule.
    """
    if not department:
        return leaves_of(period)
    level = LEVEL[grain_of(period, department)]

    def collect(node: DimPeriod) -> list[DimPeriod]:
        here = KIND_LEVEL.get(node.kind, 0)
        if here == level:
            return [node]
        if here > level:
            return []
        return [x for c in node.children.order_by("seq") for x in collect(c)]

    return collect(period)


def unit_ids(period: DimPeriod, department: str) -> list[int]:
    return [p.id for p in units_of(period, department)]


def children_for(period: DimPeriod, department: str) -> list[DimPeriod]:
    """A period's children as a section sees them: none below its grain."""
    if not department:
        return list(period.children.order_by("seq"))
    if KIND_LEVEL.get(period.kind, 0) >= LEVEL[grain_of(period, department)]:
        return []
    return list(period.children.order_by("seq"))


def is_unit(period: DimPeriod, department: str) -> bool:
    """Does this section store figures on exactly this period?"""
    if not department:
        return not period.children.exists()
    return KIND_LEVEL.get(period.kind, 0) == LEVEL[grain_of(period, department)]


def month_nodes(month: DimPeriod) -> list[DimPeriod]:
    """The month and everything under it."""
    out = [month]
    for week in month.children.all():
        out.append(week)
        out.extend(week.children.all())
    return out


def department_has_facts(month: DimPeriod, department: str) -> bool:
    """Has this section stored any figure anywhere in this month?"""
    from apps.core.permissions import CHANNEL_DEPARTMENT
    from apps.finance.models import CashMovement
    from apps.production.models import (
        FactPrintColor,
        FactProduction,
        FactProductionCost,
        FactProductionRevenue,
    )
    from apps.sales.models import FactSalesByCustomerGroup, FactSalesMonthly, FactSalesProvince

    ids = [p.id for p in month_nodes(month)]
    if department == "production":
        models = (FactProduction, FactProductionCost, FactProductionRevenue, FactPrintColor)
        return any(m.objects.filter(period_id__in=ids).exists() for m in models)
    if department == "finance":
        return CashMovement.objects.filter(period_id__in=ids).exists()
    channels = [c for c, d in CHANNEL_DEPARTMENT.items() if d == department]
    return any(
        m.objects.filter(period_id__in=ids, channel__in=channels).exists()
        for m in (FactSalesMonthly, FactSalesProvince, FactSalesByCustomerGroup)
    )


def trim_depth(month: DimPeriod) -> None:
    """
    Drop calendar levels no section records at any more — only where nothing
    is stored in them, so no figure is ever lost to a tidy-up.
    """
    needed = max(
        (LEVEL[g] for g in month.grains.values_list("grain", flat=True)), default=0,
    )
    weeks = list(month.children.all())
    if needed < 2:
        for week in weeks:
            days = list(week.children.all())
            if days and not any(has_any_facts(d) for d in days):
                week.children.all().delete()
    if needed < 1 and weeks:
        if not any(has_any_facts(n) for n in month_nodes(month)[1:]):
            month.children.all().delete()


@transaction.atomic
def set_grain(month: DimPeriod, department: str, grain: str) -> str:
    """
    Record a section's grain for a month.

    Refused once the section holds figures in that month: they sit at the old
    level, and moving them would mean inventing how a month's total splits
    into weeks (or folding weeks into a number nobody typed).
    """
    from apps.core.models import GRAIN_DEPARTMENTS, PeriodGrain

    if month.kind != PeriodKind.MONTH:
        raise ValueError("دانه‌بندی برای یک ماه تعیین می‌شود.")
    if department not in dict(GRAIN_DEPARTMENTS):
        raise ValueError("بخش نامعتبر است.")
    if grain not in LEVEL:
        raise ValueError("دانه‌بندی نامعتبر است.")
    current = grain_of(month, department)
    if current == grain:
        return grain
    if department_has_facts(month, department):
        raise ValueError(
            f"«{dict(GRAIN_DEPARTMENTS)[department]}» در {month.label} داده‌ی ثبت‌شده دارد؛ "
            "دانه‌بندی این ماه دیگر قابل تغییر نیست."
        )
    ensure_depth(month, grain)
    PeriodGrain.objects.update_or_create(
        month=month, department=department, defaults={"grain": grain},
    )
    trim_depth(month)
    return grain


def has_facts(period: DimPeriod, domain: str = "sales") -> bool:
    """
    True when *this* domain has stored numbers against this exact period.

    Scoped per domain on purpose. The no-double-counting rule is really
    "within one fact table, store at exactly one level of the tree" — so
    sales can sit on weeks while production stays on months. Both are safe;
    what would break is one domain writing to a month *and* its weeks.
    """
    from apps.finance.models import CashMovement
    from apps.production.models import FactProduction
    from apps.sales.models import FactSalesMonthly, FactSalesProvince

    if domain == "production":
        return FactProduction.objects.filter(period=period).exists()
    if domain == "finance":
        return CashMovement.objects.filter(period=period).exists()
    return (
        FactSalesMonthly.objects.filter(period=period).exists()
        or FactSalesProvince.objects.filter(period=period).exists()
    )


def has_any_facts(period: DimPeriod) -> bool:
    """
    True when *any* domain stored numbers against this exact period.

    Reshaping the tree is not a per-domain decision: splitting a month moves
    where every report looks for its figures. A month carrying nothing but
    cash movements used to pass the sales-only check, and its حرکت‌های نقدی
    then vanished from گزارش نقدینگی, which reads the leaves.
    """
    return any(has_facts(period, d) for d in ("sales", "production", "finance"))


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


def _channels(department: str) -> list[str] | None:
    """The sales channels a section owns; None means every channel."""
    from apps.core.permissions import CHANNEL_DEPARTMENT

    if not department:
        return None
    return [c for c, d in CHANNEL_DEPARTMENT.items() if d == department]


def reconciliation(month: DimPeriod, department: str = "") -> dict:
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

    channels = _channels(department)

    def revenue_of(p) -> Decimal:
        rows = FactKPI.objects.filter(
            period=p, scope=KPIScope.COMPANY, kpi__code="revenue"
        )
        if channels is not None:
            rows = rows.filter(channel__in=channels)
        return sum((r.actual or Decimal(0) for r in rows), Decimal(0))

    def sales_level(nodes) -> list[DimPeriod]:
        """With no section named, only the levels sales figures sit on — the
        calendar may be deeper for another section (مالی's days)."""
        if department or any(_holds(x, None) for n in nodes for x in [n, *leaves_of(n)]):
            return nodes
        return []

    weeks = sales_level(children_for(month, department))
    month_total = revenue_of(month)
    weeks_total = sum((revenue_of(w) for w in weeks), Decimal(0))
    # Figures on the month while this section records by the week would be
    # counted by nothing that reads the weeks.
    orphan = bool(weeks) and _holds(month, channels)

    # With a day layer the same proof has to hold one level down: each week's
    # KPI must equal the sum of its days. Checking only month-vs-weeks would
    # declare a balanced month while a week silently disagreed with its days.
    day_checks = []
    for w in weeks:
        days = sales_level(children_for(w, department))
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
            "balanced": w_total == d_total and not (_holds(w, channels) and bool(days)),
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


def _holds(period: DimPeriod, channels: list[str] | None) -> bool:
    """Sales figures stored on exactly this period (for these channels)."""
    from apps.sales.models import FactSalesMonthly, FactSalesProvince

    for model in (FactSalesMonthly, FactSalesProvince):
        qs = model.objects.filter(period=period)
        if channels is not None:
            qs = qs.filter(channel__in=channels)
        if qs.exists():
            return True
    return False


def _state_of(period: DimPeriod, channels: list[str] | None = None) -> str:
    """empty / draft / submitted / approved for one leaf period."""
    from apps.sales.models import ApprovalStatus, FactSalesMonthly

    rows = FactSalesMonthly.objects.filter(period=period)
    if channels is not None:
        rows = rows.filter(channel__in=channels)
    if rows.filter(status=ApprovalStatus.APPROVED).exists():
        return "approved"
    if rows.filter(status=ApprovalStatus.SUBMITTED).exists():
        return "submitted"
    return "draft" if rows.exists() else "empty"


def progress(month: DimPeriod, department: str = "") -> dict:
    """
    How much of a month has been filled in — drives the dots strip and the
    "ماه هنوز کامل نشده" badge on the dashboards. With a section, at that
    section's grain and for its channels only.
    """
    from apps.sales.models import ApprovalStatus, FactSalesMonthly

    channels = _channels(department)

    def sales_rows(ids):
        qs = FactSalesMonthly.objects.filter(period_id__in=ids)
        return qs.filter(channel__in=channels) if channels is not None else qs

    weeks = children_for(month, department)
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
        leaf_ids = unit_ids(wk, department)
        rows = sales_rows(leaf_ids)
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
                sales_rows(leaf_ids)
                .order_by("-period__end_date").values_list("period__end_date", flat=True)
                .first()
            )
            as_of = filled_days or wk.end_date
        days = children_for(wk, department) if wk.pk != month.pk else []
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
                    "state": _state_of(d, channels),
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
