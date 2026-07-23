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

from apps.core.formula import FormulaError, evaluate
from apps.core.models import DimKPI, DimPeriod, FactKPI, KPIFormula, KPIScope
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimTeam,
    FactSalesMonthly,
)

DOMAIN = "sales"


def active_formula_map(domain: str) -> dict[tuple[str, str], str]:
    """{(kpi_code, slot): expression} for a domain's active formulas."""
    return {
        (f.kpi.code, f.slot): f.expression
        for f in KPIFormula.objects.filter(
            is_active=True, kpi__domain=domain
        ).select_related("kpi")
    }

# KPI catalog: (code, name_fa, name_en, unit, direction, note)
# Notes cite the exact source cell and flag any deliberate deviation.
KPI_CATALOG = [
    ("revenue", "فروش ریالی", "Revenue", "rial", "higher",
     "جمع فروش ریالی همه فروشندگان. منبع: شیت ورودی ردیف ۳ (=SUM). فرمول: فروش."),
    ("target_achievement", "درصد تحقق تارگت", "Target achievement", "%", "higher",
     "فروش ÷ تارگت × ۱۰۰. عیناً مطابق Sheet3!C29 = (C19/C25)*100 «درصد رسیدن به تارگت»."),
    ("volume_share", "سهم از حجم فروش", "Share of sales volume", "%", "higher",
     "فروش هر واحد ÷ کل فروش شرکت × ۱۰۰. اکسل (Sheet3!C28) بر عدد ثابت ۲۴۰ میلیارد "
     "تقسیم می‌کرد که با جمع تارگت‌ها (۷۵۰ میلیارد) هم‌خوان نبود؛ اینجا بر فروش واقعی "
     "کل تقسیم می‌شود که معیار درست «سهم» است."),
    ("call_conversion", "نرخ تبدیل تماس به فروش", "Call-to-sale conversion", "%", "higher",
     "تعداد فاکتور ÷ تعداد تماس × ۱۰۰. عیناً مطابق Sheet3!C30 = (C20/C26)*100 «تماس به فروش»."),
    ("profit_margin", "حاشیه سود", "Profit margin", "%", "higher",
     "سود فروش ÷ فروش ریالی × ۱۰۰. حاشیه سود استاندارد (از ردیف‌های ۳ و ۷ ورودی)."),
    ("cost_to_sales", "نسبت هزینه به فروش", "Cost-to-sales", "%", "lower",
     "هزینه فروش ÷ فروش ریالی × ۱۰۰ (کمتر بهتر). توجه: اکسل (Sheet3!J59) برعکس "
     "«فروش÷هزینه» را حساب می‌کرد؛ اینجا نسبت استاندارد هزینه‌به‌فروش استفاده شده."),
    ("avg_invoice_value", "میانگین ارزش فاکتور", "Average invoice value", "rial", "higher",
     "فروش ریالی ÷ تعداد فاکتور. میانگین مبلغ هر فاکتور (ردیف‌های ۳ و ۴ ورودی)."),
    ("new_customer_ratio", "نسبت مشتری جدید", "New-customer ratio", "%", "higher",
     "مشتری جدید ÷ مشتری فعال × ۱۰۰ (ردیف‌های ۶ و ۵ ورودی)."),
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
    """Built-in KPI actuals — the fallback when no DB formula is active."""
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


def formula_context(m: Measures, company_revenue: Decimal) -> dict[str, object]:
    """
    Variables available to sales formulas — every raw measure under both an
    English and a Persian name. This is the vocabulary admins write with.
    """
    return {
        # English
        "revenue": m.revenue, "invoices": m.invoices,
        "active_customers": m.active_customers, "new_customers": m.new_customers,
        "profit": m.profit, "cost": m.cost, "target": m.target, "calls": m.calls,
        "company_revenue": company_revenue,
        # Persian aliases
        "فروش": m.revenue, "تعداد_فاکتور": m.invoices,
        "مشتری_فعال": m.active_customers, "مشتری_جدید": m.new_customers,
        "سود": m.profit, "هزینه": m.cost, "تارگت": m.target, "تماس": m.calls,
        "فروش_کل_شرکت": company_revenue,
    }


def resolve_kpi_values(
    m: Measures, company_revenue: Decimal, formulas: dict[tuple[str, str], str]
) -> dict[str, Decimal | None]:
    """DB formula wins; on any formula error or absence, fall back to the
    built-in calculation so dashboards never go dark from a bad edit."""
    builtin = _kpi_values(m, company_revenue)
    ctx = formula_context(m, company_revenue)
    out: dict[str, Decimal | None] = {}
    for code, fallback in builtin.items():
        expr = formulas.get((code, "actual"))
        if expr:
            try:
                out[code] = evaluate(expr, ctx)
                continue
            except FormulaError:
                pass  # broken formula must never take the dashboard down
        out[code] = fallback
    return out


def _compute_channel(period, catalog, facts, channel, rows, formulas):
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
        values = resolve_kpi_values(measures, company_revenue, formulas)
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

    formulas = active_formula_map(DOMAIN)
    rows: list[FactKPI] = []
    for channel in SalesChannel.values:
        facts = [f for f in base if f.channel == channel]
        if facts:
            _compute_channel(period, catalog, facts, channel, rows, formulas)

    FactKPI.objects.bulk_create(rows)
    return len(rows)
