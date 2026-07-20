"""
Production KPI engine — the 7 factory KPIs from the تولید workbook's KPI sheet.

Each KPI is reported the way the workbook frames it:
    واقعی (actual) · مطلوب (desired) · ایده‌آل (ideal) · انحراف · درصد بهره‌وری

CONVENTIONS (uniform, unlike the source sheet which was inconsistent):
  deviation      = actual - desired.  Read it together with `direction`:
                   for higher-is-better KPIs positive is good, for
                   lower-is-better KPIs positive is bad.
  efficiency_pct = performance against IDEAL, normalised so 100 = at ideal
                   and higher is always better:
                       higher-better -> actual / ideal * 100
                       lower-better  -> ideal / actual * 100

CORRECTIONS TO THE SOURCE WORKBOOK (each was a real defect, not a preference):
  1. بهره وری تولید — KPI!G3 was
         (مجموع!C3 * مجموع!C4) / (مجموع!C3 * مجموع!H3)
     where the shift count C3 cancels out of numerator and denominator,
     silently reducing the "efficiency %" to output/16000 (a shift-equivalent
     count, not a percentage). Here it is actual/desired * 100.
  2. نرخ ضایعات — KPI!C5 was missing a closing parenthesis, evaluating to
         ((in1+in2)/out1 + out2) / 1000000
     which is arithmetically meaningless. Waste is computed here from the
     material balance: (input - output) / input * 100.
  3. نرخ توقف خط تولید — KPI!C7 referenced a deleted cell (#REF!). Rebuilt as
     downtime shifts / scheduled shifts * 100.
  4. Ideal/desired constants that were hard-coded in مجموع (16000, 120, 8, 33)
     now live in ProductionBenchmark, per period.

KNOWN AMBIGUITY (surfaced rather than guessed): بهره وری نیروی انسانی.
KPI!C9 divides by منابع!C3 (total headcount, 675 man-days) while the cached
dashboard value implies مجموع!H6 (33 full-system staff) was used instead. The
two differ by ~20x. This engine uses total man-hours = total_headcount ×
hours_per_shift consistently for actual, desired and ideal, which is the
internally coherent reading. Confirm with the plant manager before relying on
the absolute number — the trend is valid either way.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.core.models import DimKPI, DimPeriod, FactKPI, KPIScope
from apps.production.models import (
    DimMachine,
    FactMaterialBalance,
    FactProduction,
    FactProductionCost,
    FactProductionRevenue,
    ProductionBenchmark,
)
from apps.sales.models import ApprovalStatus

DOMAIN = "production"

# (code, name_fa, name_en, unit, direction, note)
KPI_CATALOG = [
    ("prod_productivity", "بهره وری تولید", "Production productivity", "unit", "higher",
     "Total output vs 16,000/shift benchmark. Source: KPI!B3 (efficiency formula corrected)."),
    ("waste_rate", "نرخ ضایعات", "Waste rate", "%", "lower",
     "(input weight - output weight) / input weight * 100. Source: KPI!B5 (formula rebuilt)."),
    ("line_stoppage_rate", "نرخ توقف خط تولید", "Line stoppage rate", "%", "lower",
     "Downtime shifts / scheduled shifts * 100. Source: KPI!B7 (was #REF!)."),
    ("labor_productivity", "بهره وری نیروی انسانی", "Labour productivity", "unit/man-hour", "higher",
     "Output / (headcount * hours per shift). Source: KPI!B9. See ambiguity note."),
    ("defect_free_rate", "نرخ تولید بدون نقص", "Defect-free rate", "%", "higher",
     "(output - repairs) / output * 100. Source: KPI!B11."),
    ("cost_per_roll", "هزینه تولید به ازای هر رول", "Cost per roll", "rial", "lower",
     "Total production cost / total output. Source: KPI!B13."),
    ("financial_return", "نرخ بازدهی مالی", "Financial return", "rial", "higher",
     "Piece-rate revenue - total cost. Source: KPI!B15."),
    # Machine-scope KPIs (the KPI!B21-25 per-line block).
    ("machine_output", "تولید دستگاه", "Machine output", "unit", "higher",
     "Output per line. Source: KPI!B22."),
    ("machine_output_per_shift", "میانگین تولید در شیفت", "Output per shift", "unit", "higher",
     "Output / active shifts. Source: KPI!B25."),
    ("machine_utilization", "درصد بهره‌برداری دستگاه", "Machine utilisation", "%", "higher",
     "Active shifts / shifts available in month * 100. Derived from KPI!B24."),
]


def ensure_kpi_catalog() -> dict[str, DimKPI]:
    catalog = {}
    for code, fa, en, unit, direction, note in KPI_CATALOG:
        obj, _ = DimKPI.objects.update_or_create(
            code=code,
            defaults=dict(
                name_fa=fa, name_en=en, domain=DOMAIN,
                unit=unit, direction=direction, formula_note=note,
            ),
        )
        catalog[code] = obj
    return catalog


DIRECTION = {code: direction for code, _, _, _, direction, _ in KPI_CATALOG}


def _div(num, den) -> Decimal | None:
    """Safe division — the source workbook is full of live #DIV/0! cells."""
    if not den:
        return None
    return Decimal(num) / Decimal(den)


def _pct(num, den) -> Decimal | None:
    r = _div(num, den)
    return None if r is None else r * 100


@dataclass
class Totals:
    """Aggregated cutting-line measures for a period."""

    output: Decimal = Decimal(0)
    active_shifts: Decimal = Decimal(0)
    repairs: Decimal = Decimal(0)
    downtime: Decimal = Decimal(0)
    machines: int = 0
    print_area: Decimal = Decimal(0)
    per_machine: dict = field(default_factory=dict)


def _collect(period: DimPeriod, only_approved: bool) -> Totals:
    rows = FactProduction.objects.filter(period=period).select_related("machine")
    if only_approved:
        rows = rows.filter(status=ApprovalStatus.APPROVED)

    t = Totals()
    for r in rows:
        t.per_machine[r.machine_id] = r
        if r.machine.kind == DimMachine.Kind.PRINT:
            t.print_area += r.output_units
            continue
        t.output += r.output_units
        t.active_shifts += r.active_shifts
        t.repairs += r.repair_count
        t.downtime += r.total_downtime_shifts
        t.machines += 1
    return t


def _efficiency(code: str, actual, ideal) -> Decimal | None:
    if actual is None or ideal in (None, 0):
        return None
    if DIRECTION[code] == "higher":
        return _pct(actual, ideal)
    if not actual:
        return None
    return _pct(ideal, actual)


@transaction.atomic
def compute_period_kpis(period: DimPeriod, *, only_approved: bool = True) -> int:
    """
    (Re)compute all production KPIs for a period. Idempotent: replaces this
    period's production rows only, leaving sales KPIs untouched.
    """
    catalog = ensure_kpi_catalog()
    bench, _ = ProductionBenchmark.objects.get_or_create(period=period)
    t = _collect(period, only_approved)

    # --- Cost & revenue ---
    total_cost = sum(
        (c.amount_rial for c in FactProductionCost.objects.filter(period=period)),
        Decimal(0),
    )
    total_revenue = sum(
        (r.amount_rial for r in FactProductionRevenue.objects.filter(
            period=period).select_related("product")),
        Decimal(0),
    )

    # --- Waste from the material balance (all streams combined) ---
    balances = list(FactMaterialBalance.objects.filter(period=period))
    total_in = sum((b.input_weight for b in balances), Decimal(0))
    total_out = sum((b.output_weight for b in balances), Decimal(0))

    # --- Benchmark-derived denominators ---
    per_shift = Decimal(bench.ideal_output_per_shift)
    desired_output = per_shift * t.active_shifts
    ideal_output = per_shift * Decimal(bench.ideal_shift_count)
    man_hours = Decimal(bench.total_headcount) * Decimal(bench.hours_per_shift)
    scheduled_shifts = Decimal(t.machines or 0) * Decimal(bench.days_in_month)
    capacity_output = per_shift * Decimal(bench.monthly_shift_capacity)

    # --- The 7 company-level KPIs: (code, actual, desired, ideal) ---
    company: list[tuple[str, Decimal | None, Decimal | None, Decimal | None]] = [
        ("prod_productivity", t.output, desired_output or None, ideal_output),
        ("waste_rate", _pct(total_in - total_out, total_in), Decimal(1), Decimal(1)),
        ("line_stoppage_rate", _pct(t.downtime, scheduled_shifts), Decimal(0), Decimal(0)),
        ("labor_productivity",
         _div(t.output, man_hours),
         _div(desired_output, man_hours),
         _div(ideal_output, man_hours)),
        ("defect_free_rate",
         _pct(t.output - t.repairs, t.output), Decimal(100), Decimal(100)),
        ("cost_per_roll",
         _div(total_cost, t.output),
         _div(total_cost, desired_output),
         _div(total_cost, capacity_output)),
        ("financial_return", total_revenue - total_cost, None, None),
    ]

    # Replace this period's production KPI rows only.
    FactKPI.objects.filter(period=period, kpi__domain=DOMAIN).delete()
    rows: list[FactKPI] = []

    for code, actual, desired, ideal in company:
        rows.append(
            FactKPI(
                period=period, kpi=catalog[code],
                scope=KPIScope.COMPANY, scope_id=None, scope_label="کل کارخانه",
                actual=actual, target=desired, ideal=ideal,
                deviation=(actual - desired) if (actual is not None and desired is not None) else None,
                efficiency_pct=_efficiency(code, actual, ideal),
            )
        )

    # --- Per-machine KPIs ---
    for machine in DimMachine.objects.all():
        r = t.per_machine.get(machine.id)
        if r is None:
            continue
        avg = _div(r.output_units, r.active_shifts)
        util = _pct(r.active_shifts, bench.days_in_month)
        for code, actual, desired, ideal in (
            ("machine_output", r.output_units, desired_output and per_shift * r.active_shifts, None),
            ("machine_output_per_shift", avg, per_shift, per_shift),
            ("machine_utilization", util, Decimal(100), Decimal(100)),
        ):
            rows.append(
                FactKPI(
                    period=period, kpi=catalog[code],
                    scope=KPIScope.MACHINE, scope_id=machine.id,
                    scope_label=machine.name_fa,
                    actual=actual, target=desired, ideal=ideal,
                    deviation=(actual - desired) if (actual is not None and desired is not None) else None,
                    efficiency_pct=_efficiency(code, actual, ideal),
                )
            )

    FactKPI.objects.bulk_create(rows)
    return len(rows)
