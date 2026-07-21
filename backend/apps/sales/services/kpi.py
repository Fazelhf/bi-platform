"""
Sales KPI engine.

Reads approved FactSalesMonthly rows for a period and materialises FactKPI
rows at three scopes: per employee, per team, and company-wide. This is the
code that replaces the workbooks' hidden calculation sheets — every formula
here traces back to a cell in Employee!Sheet3.

Ratios are computed from *aggregated* numerators/denominators at team and
company scope (never averaged from per-person ratios), which is the correct
way and fixes an inconsistency present in the source spreadsheet.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from apps.core.models import DimKPI, DimPeriod, FactKPI, KPIScope
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimTeam,
    FactSalesMonthly,
)

DOMAIN = "sales"

# KPI catalog: (code, name_fa, name_en, unit, direction, note)
KPI_CATALOG = [
    ("revenue", "فروش ریالی", "Revenue", "rial", "higher",
     "Sum of revenue_rial. Source: ورودی row 3."),
    ("target_achievement", "درصد تحقق تارگت", "Target achievement", "%", "higher",
     "revenue / target * 100. Source: Sheet3 'درصد رسیدن به تارگت'."),
    ("volume_share", "سهم از حجم فروش", "Share of sales volume", "%", "higher",
     "revenue / company_revenue * 100. Source: Sheet3 'درصد از حجم فروش'."),
    ("call_conversion", "نرخ تبدیل تماس به فروش", "Call-to-sale conversion", "%", "higher",
     "invoices / calls * 100. Source: Sheet3 'تماس به فروش'."),
    ("profit_margin", "حاشیه سود", "Profit margin", "%", "higher",
     "profit / revenue * 100."),
    ("cost_to_sales", "نسبت هزینه به فروش", "Cost-to-sales", "%", "lower",
     "cost / revenue * 100. Source: Sheet3 'هزینه به فروش'."),
    ("avg_invoice_value", "میانگین ارزش فاکتور", "Average invoice value", "rial", "higher",
     "revenue / invoices."),
    ("new_customer_ratio", "نسبت مشتری جدید", "New-customer ratio", "%", "higher",
     "new_customers / active_customers * 100."),
]


def ensure_kpi_catalog() -> dict[str, DimKPI]:
    """Idempotently upsert the KPI catalog; return {code: DimKPI}."""
    catalog = {}
    for code, fa, en, unit, direction, note in KPI_CATALOG:
        obj, _ = DimKPI.objects.update_or_create(
            code=code,
            defaults=dict(
                name_fa=fa, name_en=en, domain="sales",
                unit=unit, direction=direction, formula_note=note,
            ),
        )
        catalog[code] = obj
    return catalog


@dataclass
class Measures:
    """Additive raw measures for one scope (employee/team/company)."""

    revenue: Decimal = Decimal(0)
    invoices: int = 0
    active_customers: int = 0
    new_customers: int = 0
    profit: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)
    target: Decimal = Decimal(0)
    calls: int = 0

    def add(self, f: FactSalesMonthly) -> None:
        self.revenue += f.revenue_rial
        self.invoices += f.invoice_count
        self.active_customers += f.active_customers
        self.new_customers += f.new_customers
        self.profit += f.profit_rial
        self.cost += f.cost_rial
        self.target += f.target_rial
        self.calls += f.calls


def _pct(num, den) -> Decimal | None:
    if not den:
        return None
    return (Decimal(num) / Decimal(den)) * 100


def _div(num, den) -> Decimal | None:
    if not den:
        return None
    return Decimal(num) / Decimal(den)


def _kpi_values(m: Measures, company_revenue: Decimal) -> dict[str, Decimal | None]:
    """All KPI actuals for a scope, keyed by KPI code."""
    return {
        "revenue": m.revenue,
        "target_achievement": _pct(m.revenue, m.target),
        "volume_share": _pct(m.revenue, company_revenue),
        "call_conversion": _pct(m.invoices, m.calls),
        "profit_margin": _pct(m.profit, m.revenue),
        "cost_to_sales": _pct(m.cost, m.revenue),
        "avg_invoice_value": _div(m.revenue, m.invoices),
        "new_customer_ratio": _pct(m.new_customers, m.active_customers),
    }


def _compute_channel(period, catalog, facts, channel, rows):
    """Aggregate one channel's facts into company/team/employee KPI rows."""
    company = Measures()
    by_employee: dict[int, Measures] = {}
    by_team: dict[int, Measures] = {}
    for f in facts:
        company.add(f)
        by_employee.setdefault(f.employee_id, Measures()).add(f)
        if f.employee.team_id:
            by_team.setdefault(f.employee.team_id, Measures()).add(f)

    company_revenue = company.revenue

    def emit(scope, scope_id, label, measures):
        values = _kpi_values(measures, company_revenue)
        for code, actual in values.items():
            rows.append(
                FactKPI(
                    period=period, kpi=catalog[code], channel=channel,
                    scope=scope, scope_id=scope_id, scope_label=label,
                    actual=actual,
                    target=measures.target if code == "revenue" else None,
                )
            )

    emit(KPIScope.COMPANY, None, "کل شرکت", company)

    team_names = {t.id: t.name_fa for t in DimTeam.objects.all()}
    for team_id, m in by_team.items():
        emit(KPIScope.TEAM, team_id, team_names.get(team_id, ""), m)

    emp_names = {
        e.id: e.full_name_fa
        for e in DimEmployee.objects.filter(id__in=by_employee.keys())
    }
    for emp_id, m in by_employee.items():
        emit(KPIScope.EMPLOYEE, emp_id, emp_names.get(emp_id, ""), m)


@transaction.atomic
def compute_period_kpis(period: DimPeriod, *, only_approved: bool = True) -> int:
    """
    (Re)compute all sales KPIs for a period, separately per channel (team vs
    organizational). Returns the number of FactKPI rows written. Idempotent —
    replaces this period's sales KPI rows without touching production.
    """
    from apps.sales.models import SalesChannel

    catalog = ensure_kpi_catalog()

    base = FactSalesMonthly.objects.filter(period=period).select_related(
        "employee", "employee__team"
    )
    if only_approved:
        base = base.filter(status=ApprovalStatus.APPROVED)

    # Wipe & rewrite this period's SALES KPI rows only. FactKPI is shared
    # across domains, so this must never touch production results.
    FactKPI.objects.filter(period=period, kpi__domain=DOMAIN).delete()

    rows: list[FactKPI] = []
    for channel in SalesChannel.values:
        facts = [f for f in base if f.channel == channel]
        if facts:
            _compute_channel(period, catalog, facts, channel, rows)

    FactKPI.objects.bulk_create(rows)
    return len(rows)
