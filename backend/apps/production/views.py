from django.db.models import Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import DimPeriod, FactKPI, KPIScope
from apps.production.models import (
    DimCostCategory,
    DimMachine,
    DimProduct,
    FactMaterialBalance,
    FactPrintColor,
    FactProduction,
    FactProductionCost,
    FactProductionRevenue,
    ProductionBenchmark,
)
from apps.production.serializers import (
    BenchmarkSerializer,
    CostCategorySerializer,
    MachineSerializer,
    MaterialBalanceSerializer,
    PrintColorSerializer,
    ProductSerializer,
    ProductionCostSerializer,
    ProductionRevenueSerializer,
    ProductionSerializer,
)
from apps.production.services.kpi import compute_period_kpis
from apps.sales.models import ApprovalStatus
from apps.sales.permissions import CanApprove, CanEnterData
from apps.sales.serializers import KPIResultSerializer, PeriodSerializer


# -------------------- Dimensions --------------------
class MachineViewSet(viewsets.ModelViewSet):
    queryset = DimMachine.objects.all()
    serializer_class = MachineSerializer
    filterset_fields = ["kind", "is_active"]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = DimProduct.objects.all()
    serializer_class = ProductSerializer


class CostCategoryViewSet(viewsets.ModelViewSet):
    queryset = DimCostCategory.objects.all()
    serializer_class = CostCategorySerializer


class BenchmarkViewSet(viewsets.ModelViewSet):
    queryset = ProductionBenchmark.objects.select_related("period").all()
    serializer_class = BenchmarkSerializer
    permission_classes = [CanApprove]
    filterset_fields = ["period"]


# -------------------- Facts --------------------
class ProductionViewSet(viewsets.ModelViewSet):
    """Excel-like production entry grid, with the same approval workflow as sales."""

    queryset = FactProduction.objects.select_related("machine", "period").all()
    serializer_class = ProductionSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["period", "machine", "status"]

    def perform_update(self, serializer):
        serializer.save(status=ApprovalStatus.DRAFT)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.SUBMITTED
        fact.submitted_by = request.user
        fact.save(update_fields=["status", "submitted_by", "updated_at"])
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[CanApprove])
    def approve(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.APPROVED
        fact.approved_by = request.user
        fact.save(update_fields=["status", "approved_by", "updated_at"])
        compute_period_kpis(fact.period)
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[CanApprove])
    def reject(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.REJECTED
        fact.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(fact).data)


class ProductionCostViewSet(viewsets.ModelViewSet):
    queryset = FactProductionCost.objects.select_related("category", "period").all()
    serializer_class = ProductionCostSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["period", "category"]


class ProductionRevenueViewSet(viewsets.ModelViewSet):
    queryset = FactProductionRevenue.objects.select_related("product", "period").all()
    serializer_class = ProductionRevenueSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["period", "product"]


class PrintColorViewSet(viewsets.ModelViewSet):
    queryset = FactPrintColor.objects.select_related("period").all()
    serializer_class = PrintColorSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["period"]


class MaterialBalanceViewSet(viewsets.ModelViewSet):
    queryset = FactMaterialBalance.objects.select_related("period").all()
    serializer_class = MaterialBalanceSerializer
    permission_classes = [CanEnterData]
    filterset_fields = ["period", "stream"]


# -------------------- Production dashboard --------------------
class ProductionDashboardView(APIView):
    """Everything the production dashboard needs, in one call."""

    @extend_schema(
        parameters=[OpenApiParameter("period", int, required=True)],
        responses=dict,
    )
    def get(self, request):
        period = DimPeriod.objects.get(pk=request.query_params.get("period"))

        company_kpis = FactKPI.objects.filter(
            period=period, scope=KPIScope.COMPANY, kpi__domain="production"
        ).select_related("kpi")

        machine_kpis = FactKPI.objects.filter(
            period=period, scope=KPIScope.MACHINE
        ).select_related("kpi")

        machines = (
            FactProduction.objects.filter(period=period)
            .select_related("machine")
            .order_by("machine__sort_order")
            .values(
                "machine__name_fa", "machine__kind", "active_shifts", "output_units",
                "waste_pct", "downtime_breakdown_shifts",
                "downtime_sizechange_shifts", "downtime_nowork_shifts",
            )
        )

        costs = (
            FactProductionCost.objects.filter(period=period)
            .select_related("category")
            .values("category__name_fa")
            .annotate(amount=Sum("amount_rial"))
            .order_by("-amount")
        )

        revenue = [
            {
                "product": r.product.name_fa,
                "quantity": r.quantity,
                "amount": r.amount_rial,
            }
            for r in FactProductionRevenue.objects.filter(
                period=period
            ).select_related("product")
        ]

        print_colors = (
            FactPrintColor.objects.filter(period=period)
            .values("color_count", "area_sqm")
            .order_by("color_count")
        )

        return Response(
            {
                "period": PeriodSerializer(period).data,
                "kpis": KPIResultSerializer(company_kpis, many=True).data,
                "machine_kpis": KPIResultSerializer(machine_kpis, many=True).data,
                "machines": list(machines),
                "costs": list(costs),
                "revenue": revenue,
                "print_colors": list(print_colors),
            }
        )


class RecomputeProductionView(APIView):
    permission_classes = [CanApprove]

    @extend_schema(parameters=[OpenApiParameter("period", int)], responses=dict)
    def post(self, request):
        period_id = request.data.get("period") or request.query_params.get("period")
        period = DimPeriod.objects.get(pk=period_id)
        n = compute_period_kpis(period)
        return Response({"period": period.label, "rows_written": n})
