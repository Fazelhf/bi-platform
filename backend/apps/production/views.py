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
from apps.core.audit import diff as audit_diff, log as audit_log, snapshot
from apps.core.models import AuditLog
from apps.core.notify import notify_decision, notify_submitted
from apps.core.permissions import ApprovalPermission, DepartmentEntryPermission
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
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "machine", "status"]

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save(status=ApprovalStatus.DRAFT)
        audit_log(self.request.user, instance, AuditLog.Action.UPDATE,
                  audit_diff(before, snapshot(instance)))

    def _detail(self, fact) -> str:
        return f"تولید {fact.machine.name_fa} · {fact.period.label}"

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.SUBMITTED
        fact.submitted_by = request.user
        fact.save(update_fields=["status", "submitted_by", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.SUBMIT)
        notify_submitted(request.user, fact, "production", self._detail(fact))
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission])
    def approve(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.APPROVED
        fact.approved_by = request.user
        fact.save(update_fields=["status", "approved_by", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.APPROVE)
        notify_decision(request.user, fact, "approved", self._detail(fact))
        compute_period_kpis(fact.period)
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission])
    def reject(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.REJECTED
        fact.save(update_fields=["status", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.REJECT)
        notify_decision(request.user, fact, "rejected", self._detail(fact))
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission],
            url_path="request-revision")
    def request_revision(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.NEEDS_REVISION
        fact.save(update_fields=["status", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.REVISION,
                  {"note": {"before": None, "after": request.data.get("note", "")}})
        notify_decision(request.user, fact, "revision", self._detail(fact))
        return Response(self.get_serializer(fact).data)


class ProductionCostViewSet(viewsets.ModelViewSet):
    queryset = FactProductionCost.objects.select_related("category", "period").all()
    serializer_class = ProductionCostSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "category"]


class ProductionRevenueViewSet(viewsets.ModelViewSet):
    queryset = FactProductionRevenue.objects.select_related("product", "period").all()
    serializer_class = ProductionRevenueSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "product"]


class PrintColorViewSet(viewsets.ModelViewSet):
    queryset = FactPrintColor.objects.select_related("period").all()
    serializer_class = PrintColorSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period"]


class MaterialBalanceViewSet(viewsets.ModelViewSet):
    queryset = FactMaterialBalance.objects.select_related("period").all()
    serializer_class = MaterialBalanceSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
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

        bench, _ = ProductionBenchmark.objects.get_or_create(period=period)
        total_cost = sum((c["amount"] for c in costs), 0)
        total_revenue = sum((r["amount"] for r in revenue), 0)

        return Response(
            {
                "period": PeriodSerializer(period).data,
                "kpis": KPIResultSerializer(company_kpis, many=True).data,
                "machine_kpis": KPIResultSerializer(machine_kpis, many=True).data,
                "machines": list(machines),
                "costs": list(costs),
                "revenue": revenue,
                "print_colors": list(print_colors),
                "days_in_month": bench.days_in_month,
                "financials": {
                    "revenue": total_revenue,      # درآمد
                    "cost": total_cost,            # هزینه
                    "net": total_revenue - total_cost,  # کارکرد / سود
                },
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


# --------------------------------------------------------------------------
# Combined production INPUT — the manager fills all four Excel tables here
# --------------------------------------------------------------------------
CUT_FIELDS = [
    "active_shifts", "output_units", "waste_pct", "repair_count",
    "downtime_breakdown_shifts", "downtime_sizechange_shifts", "downtime_nowork_shifts",
]


class ProductionInputView(APIView):
    """
    One endpoint that mirrors the production workbook's four input tables:
      1) cutting lines (برش ۱–۵) · 2) resources & costs (منابع) ·
      3) print by colour (چاپ) · 4) roll counts (تعداد رول).
    GET returns everything for a period; POST upserts everything at once.
    """

    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"

    def _bench(self, period):
        b, _ = ProductionBenchmark.objects.get_or_create(period=period)
        return b

    @extend_schema(parameters=[OpenApiParameter("period", int, required=True)], responses=dict)
    def get(self, request):
        period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        bench = self._bench(period)

        machines = list(DimMachine.objects.all())
        facts = {f.machine_id: f for f in FactProduction.objects.filter(period=period)}

        def machine_row(m):
            f = facts.get(m.id)
            row = {"machine": m.id, "machine_name": m.name_fa, "kind": m.kind,
                   "status": f.status if f else "draft"}
            for fld in CUT_FIELDS:
                row[fld] = str(getattr(f, fld)) if f else "0"
            return row

        cutting = [machine_row(m) for m in machines if m.kind == DimMachine.Kind.CUTTING]
        print_machine = next((m for m in machines if m.kind == DimMachine.Kind.PRINT), None)
        print_row = machine_row(print_machine) if print_machine else None

        colors = {c.color_count: c for c in FactPrintColor.objects.filter(period=period)}
        print_colors = [
            {"color_count": n, "area_sqm": str(colors[n].area_sqm) if n in colors else "0"}
            for n in (1, 2, 3, 4)
        ]

        cost_rows = {c.category_id: c for c in FactProductionCost.objects.filter(period=period)}
        costs = [
            {"category": c.id, "category_name": c.name_fa,
             "amount_rial": str(cost_rows[c.id].amount_rial) if c.id in cost_rows else "0"}
            for c in DimCostCategory.objects.all()
        ]

        rev_rows = {r.product_id: r for r in FactProductionRevenue.objects.filter(period=period)}
        rolls = [
            {"product": p.id, "product_name": p.name_fa,
             "piece_rate_rial": str(p.piece_rate_rial),
             "quantity": str(rev_rows[p.id].quantity) if p.id in rev_rows else "0"}
            for p in DimProduct.objects.all()
        ]

        return Response({
            "period": PeriodSerializer(period).data,
            "benchmark": BenchmarkSerializer(bench).data,
            "cutting": cutting,
            "print": print_row,
            "print_colors": print_colors,
            "costs": costs,
            "rolls": rolls,
        })

    def post(self, request):
        period = DimPeriod.objects.get(pk=request.data.get("period"))
        data = request.data
        user = request.user
        submit = bool(data.get("submit"))
        status = ApprovalStatus.SUBMITTED if submit else ApprovalStatus.DRAFT

        # 1) Headcount (benchmark)
        bench = self._bench(period)
        if "total_headcount" in data:
            bench.total_headcount = int(float(data["total_headcount"] or 0))
            bench.save(update_fields=["total_headcount"])

        # 2) Machines (cutting + print)
        for row in list(data.get("cutting", [])) + ([data["print"]] if data.get("print") else []):
            machine = DimMachine.objects.get(pk=row["machine"])
            defaults = {f: (row.get(f) or 0) for f in CUT_FIELDS}
            defaults["status"] = status
            if submit:
                defaults["submitted_by"] = user
            obj, _ = FactProduction.objects.update_or_create(
                period=period, machine=machine, defaults=defaults
            )
            audit_log(user, obj, AuditLog.Action.UPDATE)

        # 3) Print colours
        for c in data.get("print_colors", []):
            FactPrintColor.objects.update_or_create(
                period=period, color_count=int(c["color_count"]),
                defaults={"area_sqm": c.get("area_sqm") or 0},
            )

        # 4) Costs
        for c in data.get("costs", []):
            FactProductionCost.objects.update_or_create(
                period=period, category_id=c["category"],
                defaults={"amount_rial": c.get("amount_rial") or 0},
            )

        # 5) Roll counts (revenue)
        for r in data.get("rolls", []):
            product = DimProduct.objects.get(pk=r["product"])
            FactProductionRevenue.objects.update_or_create(
                period=period, product=product,
                defaults={"quantity": r.get("quantity") or 0,
                          "piece_rate_rial": product.piece_rate_rial},
            )

        # Material balance from paper weights (optional inputs)
        if "input_weight" in data or "output_weight" in data:
            FactMaterialBalance.objects.update_or_create(
                period=period, stream=FactMaterialBalance.Stream.CUTTING,
                defaults={"input_weight": data.get("input_weight") or 0,
                          "output_weight": data.get("output_weight") or 0},
            )

        if submit:
            # Notify approvers that production data is pending.
            first = FactProduction.objects.filter(period=period).first()
            if first:
                notify_submitted(user, first, "production", f"اطلاعات تولید · {period.label}")

        return Response({"ok": True, "submitted": submit, "period": period.label})
