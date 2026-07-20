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


def _kpi_map(period, domain):
    """{kpi_code: FactKPI} for a domain's company-level results."""
    return {
        k.kpi.code: k
        for k in FactKPI.objects.filter(
            period=period, scope=KPIScope.COMPANY, kpi__domain=domain
        ).select_related("kpi")
    }


class ExecutiveOverviewView(APIView):
    """Sales + production for one period, in one payload."""

    @extend_schema(
        parameters=[OpenApiParameter("period", int, required=True)],
        responses=dict,
    )
    def get(self, request):
        period = DimPeriod.objects.get(pk=request.query_params.get("period"))

        sales = _kpi_map(period, "sales")
        production = _kpi_map(period, "production")

        def actual(m, code):
            k = m.get(code)
            return k.actual if k else None

        sales_revenue = actual(sales, "revenue")
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
                "sales": {
                    "kpis": KPIResultSerializer(list(sales.values()), many=True).data,
                    "revenue": sales_revenue,
                    "completeness": completeness(FactSalesMonthly),
                },
                "production": {
                    "kpis": KPIResultSerializer(list(production.values()), many=True).data,
                    "output": actual(production, "prod_productivity"),
                    "cost": production_cost,
                    "piece_rate_revenue": piece_rate_revenue,
                    "completeness": completeness(FactProduction),
                },
                # Cross-domain figures. Kept explicit and labelled so nobody
                # mistakes internal piece-rate income for external sales.
                "combined": {
                    "external_sales_revenue": sales_revenue,
                    "internal_piece_rate_revenue": piece_rate_revenue,
                    "production_cost": production_cost,
                    "production_margin": (piece_rate_revenue - production_cost),
                    "note": (
                        "فروش ریالی (خارجی) و درآمد اجرت (داخلی) دو معیار متفاوت‌اند "
                        "و با هم جمع نمی‌شوند."
                    ),
                },
            }
        )
