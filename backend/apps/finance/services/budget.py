"""
انحراف بودجه — what was expected beside what happened, rolled up the two trees.

Categories roll child into parent, and everything is monthly — the plan, the
actuals and every report. No total is ever stored, so a figure here cannot
disagree with the figures it is made of.

Three rules the grid depends on, all of them decided here rather than in the
UI, because a client that got one of them wrong would be quietly lying:

* **The budget reads the sections, it is not an island.** A سرفصل's actual
  is the cash ledger's figure for its category (what the cash report shows),
  unless finance keyed one on «ورود ارقام واقعی بودجه» or brought it from the
  Excel sheet — a keyed figure replaces the ledger's, never adds to it, so a
  rial cannot count twice. Sales forecasts read the sales section's approved
  figures per channel, the same ones every sales dashboard shows.

* **Over budget is not the same as bad.** Direction decides: spending more than
  planned is unfavourable, collecting more is favourable. Every row says so
  explicitly so no caller has to infer it from a sign.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import channel_department, unit_ids
from apps.finance.budget_models import (
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetLine,
    BudgetPeriod,
    BudgetSalesForecast,
    BudgetStatus,
)
from apps.finance.models import CashCategory, CashMovement, Direction, FinanceSetting
from apps.sales.models import ApprovalStatus, FactSalesMonthly, SalesChannel

ZERO = Decimal(0)


# --------------------------------------------------------------------------
# actuals
# --------------------------------------------------------------------------

def _as_month(period: DimPeriod) -> DimPeriod:
    """
    The month a period belongs to. The budget is monthly throughout, so a week
    or a day asked for is read as its whole month.
    """
    node = period
    while node.kind != PeriodKind.MONTH and node.parent_id:
        node = node.parent
    return node


def actual_period_ids(period: DimPeriod) -> list[int]:
    """Actuals are keyed on the month, so any period's actuals are its month's."""
    return [_as_month(period).id]


def _ledger(lines: list[BudgetLine], month: DimPeriod) -> dict[int, Decimal]:
    """
    What the cash ledger (نقدینگی) recorded on each line's category this month
    — the figure the cash report shows. A line naming a credit line reads
    only that counterparty's movements; one that does not reads them all.
    """
    if not lines:
        return {}
    ids = unit_ids(month, "finance")
    rows = (
        CashMovement.objects.filter(
            period_id__in=ids, category_id__in={ln.category_id for ln in lines}
        )
        .values("category_id", "direction", "credit_line_id")
        .annotate(total=Sum("amount_rial"))
    )
    by: dict[tuple, Decimal] = {}
    for r in rows:
        by[(r["category_id"], r["direction"], r["credit_line_id"])] = r["total"] or ZERO
    out: dict[int, Decimal] = {}
    for ln in lines:
        if ln.credit_line_id:
            got = by.get((ln.category_id, ln.direction, ln.credit_line_id))
        else:
            vals = [v for (c, d, _), v in by.items() if c == ln.category_id and d == ln.direction]
            got = sum(vals, ZERO) if vals else None
        if got is not None:
            out[ln.id] = got
    return out


def actuals_with_source(
    lines: list[BudgetLine], period: DimPeriod
) -> dict[int, tuple[Decimal, str]]:
    """
    Each سرفصل's actual for the month and where it came from.

    The budget is not an island: a line reads the cash ledger the treasury
    team already keeps, so a payment recorded on «خرید جمبو» shows up here
    without being typed twice. A figure finance keys on «ورود ارقام واقعی»
    (or brings in from the Excel sheet) **replaces** the ledger's for that
    line and month — never adds to it — so the same rial cannot count twice.

    source: 'keyed' | 'ledger' | 'none'.
    """
    month = _as_month(period)
    keyed = {
        r["line_id"]: r["total"] or ZERO
        for r in BudgetActual.objects.filter(line__in=lines, period_id__in=actual_period_ids(month))
        .values("line_id").annotate(total=Sum("amount_rial"))
    }
    ledger = _ledger([ln for ln in lines if ln.id not in keyed], month)
    out: dict[int, tuple[Decimal, str]] = {}
    for ln in lines:
        if ln.id in keyed:
            out[ln.id] = (keyed[ln.id], "keyed")
        elif ln.id in ledger:
            out[ln.id] = (ledger[ln.id], "ledger")
        else:
            out[ln.id] = (ZERO, "none")
    return out


def actuals_by_line(
    lines: list[BudgetLine], period: DimPeriod
) -> tuple[dict[int, Decimal], list[dict]]:
    """
    Each سرفصل's actual under a period — keyed, else the cash ledger's.

    Returns `(actual per line id, extras)`. Extras are always empty — there is
    no money without a line to land on — and the slot stays so the report's
    shape does not change.
    """
    got = actuals_with_source(lines, period)
    return {k: v for k, (v, src) in got.items() if src != "none"}, []


# --------------------------------------------------------------------------
# sales forecast — read from the sales section
# --------------------------------------------------------------------------

def sales_channels() -> list[tuple[str, str]]:
    return [(c.value, c.label) for c in SalesChannel]


def actual_sales(month: DimPeriod) -> dict[str, Decimal]:
    """
    Approved sales per channel for a month, exactly as the sales dashboards
    and the CEO's overview total them: each channel read at its own grain.
    """
    out: dict[str, Decimal] = {}
    for channel, _ in sales_channels():
        ids = unit_ids(month, channel_department(channel))
        total = (
            FactSalesMonthly.objects.filter(
                period_id__in=ids, channel=channel, status=ApprovalStatus.APPROVED
            ).aggregate(t=Sum("revenue_rial"))["t"]
        )
        if total:
            out[channel] = total
    return out


def sales_block(budget: Budget, period: DimPeriod, setting: FinanceSetting | None = None) -> dict:
    """
    Forecast sales per channel against what the sales section recorded.

    Judged as an inflow — selling more than forecast is good news — and kept
    out of the cash totals, because the cash those sales bring in is planned
    on the collection lines.
    """
    setting = setting or FinanceSetting.get()
    month = _as_month(period)
    bp = BudgetPeriod.objects.filter(budget=budget, period=month).first()
    forecasts = (
        {f.channel: f for f in BudgetSalesForecast.objects.filter(budget_period=bp)}
        if bp else {}
    )
    actual = actual_sales(month)
    rows = []
    total_budget = total_actual = ZERO
    for channel, label in sales_channels():
        forecast = forecasts.get(channel)
        sold = actual.get(channel, ZERO)
        planned = forecast.amount_rial if forecast else ZERO
        total_budget += planned
        total_actual += sold
        rows.append({
            "channel": channel,
            "label": label,
            **_cell(planned, sold, forecast.baseline_rial if forecast else None, Direction.IN, setting),
        })
    return {
        "rows": rows,
        "total": _cell(total_budget, total_actual, None, Direction.IN, setting),
        "has_actuals": bool(actual),
    }


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
    The variance grid for one month. The budget is monthly: a week or a day
    asked for is read as its whole month.
    """
    setting = FinanceSetting.get()
    month = _month_of(budget, period)
    period = month

    bp = BudgetPeriod.objects.filter(budget=budget, period=month).first()
    lines = list(
        BudgetLine.objects.filter(budget=budget, is_active=True)
        .select_related("category", "category__parent", "credit_line")
    )
    amounts = {
        a.line_id: a
        for a in BudgetAmount.objects.filter(budget_period=bp).select_related("line")
    } if bp else {}

    sourced = actuals_with_source(lines, month)
    actual = {k: v for k, (v, _) in sourced.items()}
    extras: list[dict] = []

    # ---- one entry per line ------------------------------------------------
    leaf_rows: dict[int, list[dict]] = {}
    for line in lines:
        amount = amounts.get(line.id)
        planned = amount.amount_rial if amount else ZERO
        baseline = amount.baseline_rial if amount else None
        row = {
            "kind": "line",
            "line_id": line.id,
            "label": str(line),
            "code": line.category.code,
            "direction": line.direction,
            "credit_line": line.credit_line.counterparty if line.credit_line_id else "",
            "note": amount.variance_note if amount else "",
            "source": sourced[line.id][1],
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

    def walk(category: CashCategory, depth: int, only: str | None = None,
             suffix: str = "") -> dict[str, Decimal]:
        own = {"budget": ZERO, "actual": ZERO}
        header_index = len(rows)
        rows.append(None)  # placeholder; filled once the children are summed

        for child in category.children.filter(is_active=True).order_by("sort_order"):
            got = walk(child, depth + 1, only)
            own["budget"] += got["budget"]
            own["actual"] += got["actual"]

        for row in sorted(
            (r for r in leaf_rows.get(category.id, []) if only is None or r["direction"] == only),
            key=lambda r: (r["kind"] != "line", r["label"]),
        ):
            own["budget"] += Decimal(row["budget_rial"])
            own["actual"] += Decimal(row["actual_rial"])
            rows.append({**row, "depth": depth + 1})

        direction = only or (category.direction if category.direction != "both" else Direction.OUT)
        rows[header_index] = {
            "kind": "category",
            "line_id": None,
            "label": f"{category.name_fa}{suffix}",
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

    # A two-way group (تسهیلات: drawn down in, repaid out) is walked once per
    # side. One header summing both would add a loan received to the
    # instalments paid — 300 in plus 440 out is not «740 of outflow».
    line_dirs: dict[int, set[str]] = {}
    for line in lines:
        line_dirs.setdefault(line.category_id, set()).add(line.direction)
    all_cats = list(CashCategory.objects.filter(is_active=True).only("id", "parent_id"))
    kids: dict[int | None, list[int]] = {}
    for c in all_cats:
        kids.setdefault(c.parent_id, []).append(c.id)

    def sides(cat_id: int) -> set[str]:
        got = set(line_dirs.get(cat_id, set()))
        for k in kids.get(cat_id, []):
            got |= sides(k)
        return got

    for root in CashCategory.objects.filter(parent=None, is_active=True).order_by("sort_order"):
        both = sides(root.id)
        if root.direction == "both" and len(both) == 2:
            walk(root, 0, Direction.IN, " · ورودی")
            walk(root, 0, Direction.OUT, " · خروجی")
        elif root.direction == "both" and both:
            walk(root, 0, next(iter(both)))
        else:
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
    sales = sales_block(budget, month, setting)

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "period": {"id": period.id, "label": period.label, "kind": period.kind},
        "month": {"id": month.id, "label": month.label},
        # What a variance note is saved against — notes belong to the month.
        "budget_period_id": bp.id if bp else None,
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
        "has_actuals": any(src != "none" for _, src in sourced.values()) or sales["has_actuals"],
        "sources": {
            src: sum(1 for _, s in sourced.values() if s == src)
            for src in ("keyed", "ledger", "none")
        },
        "sales": sales,
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


        net_budget = planned[Direction.IN] - planned[Direction.OUT]
        net_actual = got[Direction.IN] - got[Direction.OUT]
        run_budget += net_budget
        run_actual += net_actual
        forecast = sum(
            (f.amount_rial for f in BudgetSalesForecast.objects.filter(budget_period=bp)), ZERO
        )
        sold = sum(actual_sales(bp.period).values(), ZERO)

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
            "has_actuals": bool(actual),
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
# actual entry
# --------------------------------------------------------------------------

def entry_sheet(budget: Budget, period: DimPeriod) -> dict:
    """
    The finance team's monthly sheet: every سرفصل of the budget, its plan for
    the month and the actual keyed against it.
    """
    setting = FinanceSetting.get()
    month = _month_of(budget, period)

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
    stored = {row.line_id: row for row in BudgetActual.objects.filter(line__in=lines, period=month)}
    ledger = _ledger(lines, month)

    totals = {
        Direction.IN: {"budget": ZERO, "actual": ZERO},
        Direction.OUT: {"budget": ZERO, "actual": ZERO},
    }
    out_lines = []
    for line in lines:
        plan = planned.get(line.id, ZERO)
        row = stored.get(line.id)
        linked = ledger.get(line.id)
        actual = row.amount_rial if row else (linked or ZERO)
        totals[line.direction]["budget"] += plan
        totals[line.direction]["actual"] += actual
        out_lines.append({
            "line_id": line.id,
            "label": str(line),
            "category_name": line.category.name_fa,
            "parent_name": line.category.parent.name_fa if line.category.parent_id else "",
            "counterparty": line.credit_line.counterparty if line.credit_line_id else "",
            "direction": line.direction,
            "entered": row is not None,
            # The cash ledger's figure for this سرفصل — the actual when
            # nothing is keyed; a keyed figure replaces it.
            "ledger_rial": None if linked is None else str(linked),
            "source": "keyed" if row else ("ledger" if linked is not None else "none"),
            "note": row.note if row else "",
            **_cell(plan, actual, None, line.direction, setting),
        })

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "period": {"id": month.id, "label": month.label, "kind": month.kind},
        "month": {"id": month.id, "label": month.label},
        "line_count": len(lines),
        "lines": out_lines,
        "sales": sales_block(budget, month, setting),
        "totals": {
            "in": _cell(totals[Direction.IN]["budget"], totals[Direction.IN]["actual"],
                        None, Direction.IN, setting),
            "out": _cell(totals[Direction.OUT]["budget"], totals[Direction.OUT]["actual"],
                         None, Direction.OUT, setting),
        },
    }


# --------------------------------------------------------------------------
# dashboard charts
# --------------------------------------------------------------------------

def heatmap(budget: Budget) -> dict:
    """
    Every top-level group of the budget against every month of it: how far the
    actual strayed from plan. The year's pattern on one screen — which groups
    run over every month, and which only did once.

    Grouped by the line's top-level category *and* direction, so تسهیلات
    received and تسهیلات repaid are two rows rather than one sum that cancels.
    """
    setting = FinanceSetting.get()
    categories = {c.id: c for c in CashCategory.objects.all()}

    def root_of(category_id: int) -> CashCategory:
        node = categories[category_id]
        while node.parent_id and node.parent_id in categories:
            node = categories[node.parent_id]
        return node

    lines = list(BudgetLine.objects.filter(budget=budget, is_active=True))
    periods = list(
        BudgetPeriod.objects.filter(budget=budget)
        .select_related("period")
        .order_by("period__jalali_year", "period__jalali_month")
    )

    groups: dict[str, dict] = {}
    cells: list[dict] = []
    months: list[dict] = []
    for bp in periods:
        planned = {a.line_id: a.amount_rial for a in BudgetAmount.objects.filter(budget_period=bp)}
        actual, _ = actuals_by_line(lines, bp.period)
        sums: dict[str, list[Decimal]] = {}
        for line in lines:
            root = root_of(line.category_id)
            key = f"{root.code}:{line.direction}"
            groups.setdefault(key, {
                "key": key,
                "code": root.code,
                "label": root.name_fa,
                "direction": line.direction,
                "_order": (0 if line.direction == Direction.IN else 1, root.sort_order),
            })
            acc = sums.setdefault(key, [ZERO, ZERO])
            acc[0] += planned.get(line.id, ZERO)
            acc[1] += actual.get(line.id, ZERO)
        for key, (plan, got) in sums.items():
            cells.append({
                "group": key,
                "period_id": bp.period_id,
                **_cell(plan, got, None, groups[key]["direction"], setting),
            })
        months.append({
            "period_id": bp.period_id,
            "label": bp.period.label,
            "has_actuals": any(actual.values()),
        })

    ordered = sorted(groups.values(), key=lambda g: g["_order"])
    both_ways = {g["code"] for g in ordered if sum(1 for h in ordered if h["code"] == g["code"]) > 1}
    for g in ordered:
        g.pop("_order")
        if g["code"] in both_ways:
            g["label"] = f"{g['label']} · {'ورودی' if g['direction'] == Direction.IN else 'خروجی'}"

    return {
        "budget": {"id": budget.id, "title": budget.title},
        "months": months,
        "groups": ordered,
        "cells": cells,
    }

