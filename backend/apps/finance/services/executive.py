"""
نمای مالی — the finance half of the CEO's overview, in one call.

Where cash stands, what is owed, how the month is running against budget and
how the last six months moved. The overview page asks one question and gets
one answer, instead of re-deriving three finance pages' figures on its own
and eventually disagreeing with them: every number here comes from the same
service those pages use.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import month_of
from apps.finance.budget_models import BudgetPeriod
from apps.finance.models import CashMovement, Direction
from apps.finance.services import budget as budget_service
from apps.finance.services import cash_report

ZERO = Decimal(0)


def _months_up_to(month: DimPeriod, count: int) -> list[DimPeriod]:
    key = (month.jalali_year, month.jalali_month)
    months = [
        m for m in DimPeriod.objects.filter(kind=PeriodKind.MONTH).order_by("jalali_year", "jalali_month")
        if (m.jalali_year, m.jalali_month) <= key
    ]
    return months[-count:]


def cash_trend(month: DimPeriod, count: int = 6) -> list[dict]:
    """
    Cash in and out per month for the last `count` months, ending at `month`.

    Summed straight from the ledger by Jalali month: a month's weeks and days
    carry its year and month, so this is one grouped query per month however
    the month was entered.
    """
    points = []
    for m in _months_up_to(month, count):
        rows = (
            CashMovement.objects.filter(
                period__jalali_year=m.jalali_year, period__jalali_month=m.jalali_month,
            )
            .values("direction")
            .annotate(total=Sum("amount_rial"))
        )
        got = {r["direction"]: r["total"] or ZERO for r in rows}
        cash_in, cash_out = got.get(Direction.IN, ZERO), got.get(Direction.OUT, ZERO)
        points.append({
            "period_id": m.id,
            "label": m.label,
            "in": str(cash_in),
            "out": str(cash_out),
            "net": str(cash_in - cash_out),
        })
    return points


def _mix(report: dict, side: str, limit: int = 6) -> list[dict]:
    """The month's money by category, largest first, the tail folded into «سایر»."""
    names = {str(c["id"]): c["name"] for c in report["categories"][side]}
    rows = sorted(
        ((names.get(key, "—"), Decimal(value)) for key, value in report["totals"][side].items()
         if Decimal(value)),
        key=lambda item: -item[1],
    )
    out = [{"label": name, "rial": str(value)} for name, value in rows[:limit]]
    rest = sum((value for _, value in rows[limit:]), ZERO)
    if rest:
        out.append({"label": "سایر", "rial": str(rest)})
    return out


def _budget_block(month: DimPeriod) -> dict | None:
    """The active budget covering the month — the newest, if more than one does."""
    bp = (
        BudgetPeriod.objects.filter(period=month, budget__is_active=True)
        .select_related("budget")
        .order_by("-budget__created_at")
        .first()
    )
    if bp is None:
        return None
    report = budget_service.build(bp.budget, month)
    leaves = [r for r in report["rows"] if r["kind"] != "category"]
    bad = sorted(
        (r for r in leaves if r["is_material"] and r["verdict"] == "bad"),
        key=lambda r: -abs(Decimal(r["variance_rial"])),
    )
    return {
        "id": bp.budget.id,
        "title": bp.budget.title,
        "status": report["status"],
        "status_label": report["status_label"],
        "has_actuals": report["has_actuals"],
        "totals": report["totals"],
        "material_bad": len(bad),
        "top_bad": [
            {
                "label": r["label"],
                "direction": r["direction"],
                "variance_rial": r["variance_rial"],
                "variance_pct": r["variance_pct"],
            }
            for r in bad[:3]
        ],
    }


def summary(period: DimPeriod) -> dict:
    month = period if period.kind == PeriodKind.MONTH else month_of(period)
    report = cash_report.build(month)
    totals, balance, credit = report["totals"], report["balance"], report["credit_summary"]
    return {
        "month": {"id": month.id, "label": month.label},
        "cash": {
            "opening_rial": balance["opening"],
            "closing_rial": balance["closing"],
            "low_threshold_rial": balance["low_threshold"],
            "in_rial": totals["total_in"],
            "out_rial": totals["total_out"],
            "net_rial": totals["net"],
            "warnings": report["warnings"],
            "has_movements": bool(Decimal(totals["total_in"]) or Decimal(totals["total_out"])),
        },
        "credit": {
            "owed_by_company_rial": credit["owed_by_company"],
            "owed_to_company_rial": credit["owed_to_company"],
            "partner_net_rial": credit["partner_net"],
            "facility_count": len(credit["lines"]["facility"]),
        },
        "budget": _budget_block(month),
        "trend": cash_trend(month),
        "composition": {"in": _mix(report, "in"), "out": _mix(report, "out")},
    }
