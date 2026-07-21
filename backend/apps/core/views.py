"""
Cross-domain executive overview — the "one screen for the CEO" endpoint.

This is what makes the platform a single source of truth rather than two
dashboards side by side: sales and production are joined on the conformed
DimPeriod and read from the conformed FactKPI table.

IMPORTANT BUSINESS RULE encoded here: the production domain's درامد is
piece-rate earnings (اجرت × quantity) — an *internal* valuation of factory
output — while the sales domain's فروش ریالی is externally invoiced revenue.
They are different measures of different things and are deliberately NOT
summed. The response exposes them as separate figures.
"""
from django.db.models import Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import DimPeriod, FactKPI, KPIScope
from apps.production.models import FactProduction, FactProductionCost, FactProductionRevenue
from apps.sales.models import ApprovalStatus, FactSalesMonthly
from apps.sales.serializers import KPIResultSerializer, PeriodSerializer


def _kpi_map(period, domain, channel=""):
    """{kpi_code: FactKPI} for a domain/channel's company-level results."""
    return {
        k.kpi.code: k
        for k in FactKPI.objects.filter(
            period=period, scope=KPIScope.COMPANY,
            kpi__domain=domain, channel=channel,
        ).select_related("kpi")
    }


class ExecutiveOverviewView(APIView):
    """Sales + production for one period, in one payload."""

    @extend_schema(
        parameters=[OpenApiParameter("period", int, required=True)],
        responses=dict,
    )
    def get(self, request):
        from apps.sales.models import SalesChannel

        period = DimPeriod.objects.get(pk=request.query_params.get("period"))

        team = _kpi_map(period, "sales", SalesChannel.TEAM)
        org = _kpi_map(period, "sales", SalesChannel.ORGANIZATIONAL)
        production = _kpi_map(period, "production")

        def actual(m, code):
            k = m.get(code)
            return k.actual if k else None

        team_revenue = actual(team, "revenue") or 0
        org_revenue = actual(org, "revenue") or 0
        total_sales_revenue = team_revenue + org_revenue
        production_cost = (
            FactProductionCost.objects.filter(period=period).aggregate(
                t=Sum("amount_rial")
            )["t"]
            or 0
        )
        piece_rate_revenue = sum(
            (r.amount_rial for r in FactProductionRevenue.objects.filter(
                period=period).select_related("product")),
            0,
        )

        # Data-completeness signal so executives know how much to trust the view.
        def completeness(model):
            total = model.objects.filter(period=period).count()
            approved = model.objects.filter(
                period=period, status=ApprovalStatus.APPROVED
            ).count()
            return {"total": total, "approved": approved,
                    "complete": total > 0 and total == approved}

        return Response(
            {
                "period": PeriodSerializer(period).data,
                # فروش تیم (همکار)
                "sales_team": {
                    "kpis": KPIResultSerializer(list(team.values()), many=True).data,
                    "revenue": team_revenue,
                },
                # فروش سازمانی (کلی)
                "sales_org": {
                    "kpis": KPIResultSerializer(list(org.values()), many=True).data,
                    "revenue": org_revenue,
                },
                "sales_completeness": completeness(FactSalesMonthly),
                "production": {
                    "kpis": KPIResultSerializer(list(production.values()), many=True).data,
                    "output": actual(production, "prod_productivity"),
                    "cost": production_cost,
                    "piece_rate_revenue": piece_rate_revenue,
                    "completeness": completeness(FactProduction),
                },
                # Company-wide figures. Sales channels DO sum (two distinct
                # external channels, no double-count). Production piece-rate is
                # internal and kept separate from external sales.
                "combined": {
                    "total_sales_revenue": total_sales_revenue,
                    "sales_team_revenue": team_revenue,
                    "sales_org_revenue": org_revenue,
                    "internal_piece_rate_revenue": piece_rate_revenue,
                    "production_cost": production_cost,
                    "production_margin": (piece_rate_revenue - production_cost),
                    "note": (
                        "فروش تیم و فروش سازمانی دو کانال خارجی مجزا هستند و جمع "
                        "می‌شوند؛ اما درآمد اجرت تولید (داخلی) با فروش خارجی جمع نمی‌شود."
                    ),
                },
            }
        )
