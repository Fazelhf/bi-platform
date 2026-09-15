"""
انحراف بودجه — what was expected beside what happened, rolled up the two trees.

There are two hierarchies in play and the report walks both: categories roll
child into parent, periods roll week into month. Neither ever stores a total,
so a figure here cannot disagree with the ledger it describes.

Three rules the grid depends on, all of them decided here rather than in the
UI, because a client that got one of them wrong would be quietly lying:

* **A سرفصل's actual is what the finance team keyed for it** — weekly, on
  «ورود ارقام واقعی بودجه». A month is the sum of its weeks. The cash ledger
  is not read: the same rial keyed in both places would count twice.

* **Over budget is not the same as bad.** Direction decides: spending more than
  planned is unfavourable, collecting more is favourable. Every row says so
  explicitly so no caller has to infer it from a sign.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import leaf_ids_for
from apps.finance.budget_models import (
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetLine,
    BudgetPeriod,
    BudgetSalesForecast,
    BudgetStatus,
)
from apps.finance.models import CashCategory, Direction, FinanceSetting
from apps.sales.models import FactSalesMonthly, SalesChannel

ZERO = Decimal(0)


# --------------------------------------------------------------------------
# actuals
# --------------------------------------------------------------------------

def entry_periods(month: DimPeriod) -> list[DimPeriod]:
    """
    The periods budget actuals are keyed on for a month: its weeks, or the
    month itself when it was never cut into weeks. Never days — a week the
    sales team enters day by day is still one week for the budget.
    """
    weeks = list(month.children.filter(kind=PeriodKind.WEEK).order_by("seq"))
    return weeks or [month]


def actual_period_ids(period: DimPeriod) -> list[int]:
    """The entry periods a report period covers."""
    if period.kind == PeriodKind.MONTH:
        return [p.id for p in entry_periods(period)]
    if period.kind == PeriodKind.DAY and period.parent_id:
        return [period.parent_id]
    return [period.id]


def actuals_by_line(
    lines: list[BudgetLine], period: DimPeriod
) -> tuple[dict[int, Decimal], list[dict]]:
    """
    What the finance team keyed for each سرفصل under a period.

    Returns `(actual per line id, extras)`. Extras are always empty now that
    actuals are entered per سرفصل — there is no money without a line to land
    on — and the slot stays so the report's shape does not change.
    """
    rows = (
        BudgetActual.objects.filter(line__in=lines, period_id__in=actual_period_ids(period))
        .values("line_id")
        .annotate(total=Sum("amount_rial"))
    )
    return {r["line_id"]: r["total"] or ZERO for r in rows}, []


# --------------------------------------------------------------------------
# variance
# --------------------------------------------------------------------------

def _pct(variance: Decimal, budget: Decimal) -> float | None:
    """Percentage of plan. None when there was no plan — «∞%» helps nobody."""
    if not budget:
        return None
    return float(variance * 100 / abs(budget))


def _verdict(variance: Decimal, direction: str) -> str:
    """
    good / bad / on-track — the only thing a cell should be coloured by.

    Spending more than planned is bad news; collecting more is good news. The
    sign of the number says nothing on its own.
    """
    if variance == ZERO:
        return "on-track"
    favourable = variance > ZERO if direction == Direction.IN else variance < ZERO
    return "good" if favourable else "bad"


def _material(variance: Decimal, budget: Decimal, setting: FinanceSetting) -> bool:
    """Both bars, or the grid is a wall of red — see FinanceSetting."""
    size = abs(variance)
    if setting.variance_threshold_rial and size < setting.variance_threshold_rial:
        return False
    if not budget:
        return size > ZERO
    return size * 100 / abs(budget) >= setting.variance_threshold_pct


def _cell(budget_rial, actual_rial, baseline_rial, direction, setting) -> dict:
    variance = actual_rial - budget_rial
    return {
        "budget_rial": str(budget_rial),
        "baseline_rial": None if baseline_rial is None else str(baseline_rial),
        "actual_rial": str(actual_rial),
        "variance_rial": str(variance),
        "variance_pct": _pct(variance, budget_rial),
        "verdict": _verdict(variance, direction),
        "is_material": _material(variance, budget_rial, setting),
    }


def _month_of(budget: Budget, period: DimPeriod) -> DimPeriod:
    """The month a period belongs to — a week's budget comes from its parent."""
    if period.kind == PeriodKind.MONTH:
        return period
    node = period
    while node.parent_id and node.kind != PeriodKind.MONTH:
        node = node.parent
    return node


def build(budget: Budget, period: DimPeriod) -> dict:
    """
    The variance grid for one period — a month, or one week of one.

    A week's plan is its month's, pro-rated by day count and never stored.
    That is honest for steady lines (اجاره، حقوق) and misleading for lumpy
    ones (اقساط، خرید جمبو), so the response says which grain it used and the
    UI labels the weekly view «رصد جریان نقد» rather than «انحراف بودجه».
    """
    setting = FinanceSetting.get()
    month = _month_of(budget, period)
    is_week = period.kind != PeriodKind.MONTH

    bp = BudgetPeriod.objects.filter(budget=budget, period=month).first()
    lines = list(
        BudgetLine.objects.filter(budget=budget, is_active=True)
        .select_related("category", "category__parent", "credit_line")
    )
    amounts = {
        a.line_id: a
        for a in BudgetAmount.objects.filter(budget_period=bp).select_related("line")
    } if bp else {}

    actual, extras = actuals_by_line(lines, period)

    share = Decimal(1)
    if is_week and month.days and period.days:
        share = Decimal(period.days) / Decimal(month.days)

    # ---- one entry per line ------------------------------------------------
    leaf_rows: dict[int, list[dict]] = {}
    for line in lines:
        amount = amounts.get(line.id)
        planned = (amount.amount_rial if amount else ZERO) * share
        planned = planned.quantize(Decimal("1"))
        baseline = amount.baseline_rial if amount else None
        if baseline is not None and is_week:
            baseline = (baseline * share).quantize(Decimal("1"))
        row = {
            "kind": "line",
            "line_id": line.id,
            "label": str(line),
            "code": line.category.code,
            "direction": line.direction,
            "credit_line": line.credit_line.counterparty if line.credit_line_id else "",
            "note": amount.variance_note if amount else "",
            **_cell(planned, actual.get(line.id, ZERO), baseline, line.direction, setting),
        }
        leaf_rows.setdefault(line.category_id, []).append(row)

    # Unbudgeted money hangs off the same leaf so it is read in context —
    # «خرید جمبو: بودجه ۲۰۰، واقعی ۲۴۰» and «... و ۱۵ بدون بودجه» belong
    # together, not in a footnote.
    for extra in extras:
        leaf_rows.setdefault(extra["category_id"], []).append({
            "kind": "unbudgeted",
            "line_id": None,
            "label": "خارج از بودجه",
            "code": extra["code"],
            "direction": extra["direction"],
            "credit_line": "",
            "note": "",
            **_cell(ZERO, extra["actual_rial"], None, extra["direction"], setting),
        })

    # ---- roll the category tree up ----------------------------------------
    rows: list[dict] = []

    def walk(category: CashCategory, depth: int) -> dict[str, Decimal]:
        own = {"budget": ZERO, "actual": ZERO}
        header_index = len(rows)
        rows.append(None)  # placeholder; filled once the children are summed

        for child in category.children.filter(is_active=True).order_by("sort_order"):
            got = walk(child, depth + 1)
            own["budget"] += got["budget"]
            own["actual"] += got["actual"]

        for row in sorted(
            leaf_rows.get(category.id, []), key=lambda r: (r["kind"] != "line", r["label"])
        ):
            own["budget"] += Decimal(row["budget_rial"])
            own["actual"] += Decimal(row["actual_rial"])
            rows.append({**row, "depth": depth + 1})

        direction = category.direction if category.direction != "both" else Direction.OUT
        rows[header_index] = {
            "kind": "category",
            "line_id": None,
            "label": category.name_fa,
            "code": category.code,
            "direction": direction,
            "credit_line": "",
            "note": "",
            "depth": depth,
            **_cell(own["budget"], own["actual"], None, direction, setting),
        }

        # A leaf carrying a single line would print its own name twice with
        # the same figures — «خرید جمبو» as a header over «خرید جمبو». Drop
        # the header and let the line speak; keep it when there is more than
        # one line beneath (پارسیان and کارآفرین under بازپرداخت اصل) because
        # then it really is a subtotal.
        beneath = len(rows) - header_index - 1
        if beneath == 1 and not category.children.exists():
            rows.pop(header_index)
            rows[header_index]["depth"] = depth

        return own

    totals = {Direction.IN: {"budget": ZERO, "actual": ZERO},
              Direction.OUT: {"budget": ZERO, "actual": ZERO}}

    for root in CashCategory.objects.filter(parent=None, is_active=True).order_by("sort_order"):
        walk(root, 0)

    # Totals come from the line rows, not the category headers — a header is
    # already a sum of them, and adding both would double count.
    for row in rows:
        if row["kind"] == "category":
            continue
        bucket = totals[row["direction"]]
        bucket["budget"] += Decimal(row["budget_rial"])
        bucket["actual"] += Decimal(row["actual_rial"])

    # Categories that hold nothing at all are noise on a 39-row grid.
    keep: list[dict] = []
    for index, row in enumerate(rows):
        if row["kind"] != "category":
            keep.append(row)
            continue
        if Decimal(row["budget_rial"]) or Decimal(row["actual_rial"]):
            keep.append(row)
    rows = keep

    net_budget = totals[Direction.IN]["budget"] - totals[Direction.OUT]["budget"]
    net_actual = totals[Direction.IN]["actual"] - totals[Direction.OUT]["actual"]

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "period": {"id": period.id, "label": period.label, "kind": period.kind},
        "month": {"id": month.id, "label": month.label},
        # What a variance note is saved against — notes belong to the month.
        "budget_period_id": bp.id if bp else None,
        "grain": "week" if is_week else "month",
        "prorated": is_week,
        "status": bp.status if bp else BudgetStatus.DRAFT,
        "status_label": (
            BudgetStatus(bp.status).label if bp else BudgetStatus.DRAFT.label
        ),
        "approved_at": bp.approved_at.isoformat() if bp and bp.approved_at else None,
        "rows": rows,
        "totals": {
            "in": _cell(totals[Direction.IN]["budget"], totals[Direction.IN]["actual"],
                        None, Direction.IN, setting),
            "out": _cell(totals[Direction.OUT]["budget"], totals[Direction.OUT]["actual"],
                         None, Direction.OUT, setting),
            # Net is judged as an inflow: ending with more cash than planned is
            # good news whichever side produced it.
            "net": _cell(net_budget, net_actual, None, Direction.IN, setting),
        },
        "thresholds": {
            "pct": str(setting.variance_threshold_pct),
            "rial": str(setting.variance_threshold_rial),
        },
        "unbudgeted_count": len(extras),
        # A period nobody has entered yet compares the whole plan against
        # zero: every inflow «short», every outflow «saved». The UI must say
        # that plainly instead of dressing it up as a variance.
        "has_actuals": BudgetActual.objects.filter(
            line__budget=budget, period_id__in=actual_period_ids(period)
        ).exists(),
        # Beside the cash grid, never inside its totals — see sales_block.
        "sales": sales_block(budget, period, setting),
    }


# --------------------------------------------------------------------------
# charts
# --------------------------------------------------------------------------

def series(budget: Budget) -> dict:
    """
    Month by month, for the dashboard: planned in/out beside actual in/out,
    plus the cumulative cash line.

    A month's surplus says which way cash moved, not how much the company
    will be sitting on. `cumulative_*` is that position, planned and actual.
    """
    periods = list(
        BudgetPeriod.objects.filter(budget=budget)
        .select_related("period")
        .order_by("period__jalali_year", "period__jalali_month")
    )
    lines = list(BudgetLine.objects.filter(budget=budget, is_active=True))
    by_id = {line.id: line for line in lines}

    points: list[dict] = []
    run_budget = ZERO
    run_actual = ZERO

    for bp in periods:
        amounts = BudgetAmount.objects.filter(budget_period=bp)
        planned = {Direction.IN: ZERO, Direction.OUT: ZERO}
        for amount in amounts:
            line = by_id.get(amount.line_id)
            if line:
                planned[line.direction] += amount.amount_rial

        actual, extras = actuals_by_line(lines, bp.period)
        got = {Direction.IN: ZERO, Direction.OUT: ZERO}
        for line_id, value in actual.items():
            line = by_id.get(line_id)
            if line:
                got[line.direction] += value
        for extra in extras:
            got[extra["direction"]] += extra["actual_rial"]

        forecast = sum(
            (f.amount_rial for f in BudgetSalesForecast.objects.filter(budget_period=bp)),
            ZERO,
        )
        sold = sum(_actual_sales(bp.period).values(), ZERO)

        net_budget = planned[Direction.IN] - planned[Direction.OUT]
        net_actual = got[Direction.IN] - got[Direction.OUT]
        run_budget += net_budget
        run_actual += net_actual

        points.append({
            "period_id": bp.period_id,
            "label": bp.period.label,
            "status": bp.status,
            "budget_in": str(planned[Direction.IN]),
            "budget_out": str(planned[Direction.OUT]),
            "actual_in": str(got[Direction.IN]),
            "actual_out": str(got[Direction.OUT]),
            "budget_net": str(net_budget),
            "actual_net": str(net_actual),
            "cumulative_budget": str(run_budget),
            "cumulative_actual": str(run_actual),
            "budget_sales": str(forecast),
            "actual_sales": str(sold),
        })

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "points": points,
    }


def waterfall(budget: Budget, period: DimPeriod) -> dict:
    """
    From planned net cash to actual net cash, one step per line.

    The single chart that answers «چرا پول‌مان با انتظار فرق کرد؟». Each step
    is signed by its effect on cash — an inflow that came in short pushes the
    bridge down, an overspend does too — so the steps genuinely add up to the
    gap rather than merely being coloured like they do.
    """
    report = build(budget, period)
    steps = []
    for row in report["rows"]:
        if row["kind"] == "category":
            continue
        variance = Decimal(row["variance_rial"])
        if not variance:
            continue
        effect = variance if row["direction"] == Direction.IN else -variance
        steps.append({
            "label": row["label"],
            "code": row["code"],
            "direction": row["direction"],
            "effect_rial": str(effect),
            "verdict": row["verdict"],
            "is_material": row["is_material"],
        })
    steps.sort(key=lambda s: -abs(Decimal(s["effect_rial"])))

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "period": report["period"],
        "start_rial": report["totals"]["net"]["budget_rial"],
        "end_rial": report["totals"]["net"]["actual_rial"],
        "steps": steps,
    }


# --------------------------------------------------------------------------
# sales forecast
# --------------------------------------------------------------------------

def _actual_sales(period: DimPeriod) -> dict[str, Decimal]:
    """Recorded sales per channel under a period, rolled up from its leaves."""
    rows = (
        FactSalesMonthly.objects.filter(period_id__in=leaf_ids_for(period))
        .values("channel")
        .annotate(total=Sum("revenue_rial"))
    )
    return {r["channel"]: r["total"] or ZERO for r in rows}


def sales_block(budget: Budget, period: DimPeriod, setting: FinanceSetting | None = None) -> dict:
    """
    Forecast sales per channel against recorded sales.

    Judged as an inflow — selling more than forecast is good news — and kept
    out of the cash totals, because the cash those sales bring in is already
    planned on the collection lines. A week gets its month's forecast pro-rated
    by day count, exactly like the cash lines.
    """
    setting = setting or FinanceSetting.get()
    month = _month_of(budget, period)
    is_week = period.kind != PeriodKind.MONTH

    share = Decimal(1)
    if is_week and month.days and period.days:
        share = Decimal(period.days) / Decimal(month.days)

    bp = BudgetPeriod.objects.filter(budget=budget, period=month).first()
    forecasts = (
        {f.channel: f for f in BudgetSalesForecast.objects.filter(budget_period=bp)}
        if bp else {}
    )
    actual = _actual_sales(period)

    rows = []
    total_budget = total_actual = ZERO
    for channel in SalesChannel:
        forecast = forecasts.get(channel.value)
        sold = actual.get(channel.value, ZERO)
        if forecast is None and not sold:
            continue
        planned = ((forecast.amount_rial if forecast else ZERO) * share).quantize(Decimal("1"))
        baseline = forecast.baseline_rial if forecast else None
        if baseline is not None and is_week:
            baseline = (baseline * share).quantize(Decimal("1"))
        total_budget += planned
        total_actual += sold
        rows.append({
            "channel": channel.value,
            "label": channel.label,
            **_cell(planned, sold, baseline, Direction.IN, setting),
        })

    return {
        "rows": rows,
        "total": _cell(total_budget, total_actual, None, Direction.IN, setting),
    }


# --------------------------------------------------------------------------
# actual entry
# --------------------------------------------------------------------------

def entry_sheet(budget: Budget, period: DimPeriod) -> dict:
    """
    The finance team's weekly sheet: every سرفصل of the budget, its plan for
    the period and the actual keyed against it.

    `period` is a week or a month. A month cut into weeks comes back as the
    read-only sum of its weeks («کل ماه»); a month that was never cut is itself
    the entry period.
    """
    setting = FinanceSetting.get()
    month = _month_of(budget, period)
    weeks = entry_periods(month)
    week_ids = [w.id for w in weeks]
    is_rollup = period.kind == PeriodKind.MONTH and weeks[0].id != month.id
    ids = actual_period_ids(period)

    bp = BudgetPeriod.objects.filter(budget=budget, period=month).first()
    lines = list(
        BudgetLine.objects.filter(budget=budget, is_active=True)
        .select_related("category", "category__parent", "credit_line")
        .order_by("direction", "sort_order", "category__sort_order")
    )
    planned = (
        {a.line_id: a.amount_rial for a in BudgetAmount.objects.filter(budget_period=bp)}
        if bp else {}
    )

    # A week's plan is the month's, pro-rated by day count — the same rule the
    # variance report uses, so the two pages never disagree about a week.
    share = Decimal(1)
    if period.kind != PeriodKind.MONTH and month.days and period.days:
        share = Decimal(period.days) / Decimal(month.days)

    stored: dict[int, dict] = {}
    for row in BudgetActual.objects.filter(line__in=lines, period_id__in=ids):
        acc = stored.setdefault(row.line_id, {"amount": ZERO, "note": ""})
        acc["amount"] += row.amount_rial
        acc["note"] = row.note or acc["note"]

    month_to_date = {
        r["line_id"]: r["total"] or ZERO
        for r in BudgetActual.objects.filter(line__in=lines, period_id__in=week_ids)
        .values("line_id").annotate(total=Sum("amount_rial"))
    }
    entered_per_week = {
        r["period_id"]: r["n"]
        for r in BudgetActual.objects.filter(line__in=lines, period_id__in=week_ids)
        .values("period_id").annotate(n=Count("id"))
    }

    totals = {
        Direction.IN: {"budget": ZERO, "actual": ZERO},
        Direction.OUT: {"budget": ZERO, "actual": ZERO},
    }
    out_lines = []
    for line in lines:
        plan = (planned.get(line.id, ZERO) * share).quantize(Decimal("1"))
        got = stored.get(line.id)
        actual = got["amount"] if got else ZERO
        totals[line.direction]["budget"] += plan
        totals[line.direction]["actual"] += actual
        out_lines.append({
            "line_id": line.id,
            "label": str(line),
            "category_name": line.category.name_fa,
            "parent_name": line.category.parent.name_fa if line.category.parent_id else "",
            "counterparty": line.credit_line.counterparty if line.credit_line_id else "",
            "direction": line.direction,
            "entered": got is not None,
            "note": got["note"] if got else "",
            "month_budget_rial": str(planned.get(line.id, ZERO)),
            "month_actual_rial": str(month_to_date.get(line.id, ZERO)),
            **_cell(plan, actual, None, line.direction, setting),
        })

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "period": {"id": period.id, "label": period.label, "kind": period.kind},
        "month": {"id": month.id, "label": month.label, "days": month.days},
        "is_rollup": is_rollup,
        "weeks": [
            {
                "period_id": w.id,
                "label": month.label if w.id == month.id else f"هفته {w.seq}",
                "seq": w.seq,
                "days": w.days,
                "entered": entered_per_week.get(w.id, 0),
            }
            for w in weeks
        ],
        "line_count": len(lines),
        "lines": out_lines,
        "totals": {
            "in": _cell(totals[Direction.IN]["budget"], totals[Direction.IN]["actual"],
                        None, Direction.IN, setting),
            "out": _cell(totals[Direction.OUT]["budget"], totals[Direction.OUT]["actual"],
                         None, Direction.OUT, setting),
        },
    }
