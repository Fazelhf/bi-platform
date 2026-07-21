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
from django.db.models import Max, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.core.formula import FormulaError, evaluate, validate
from apps.core.models import (
    AuditLog,
    DimPeriod,
    FactKPI,
    KPIFormula,
    KPIScope,
    Notification,
)
from apps.core.permissions import IsExecutiveOrAdmin
from apps.core.serializers import (
    AuditLogSerializer,
    FormulaSerializer,
    NotificationSerializer,
)
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


# --------------------------------------------------------------------------
# Formula engine API — versioned, no code changes needed to edit a KPI
# --------------------------------------------------------------------------
class FormulaViewSet(viewsets.ModelViewSet):
    """
    Formulas are immutable versions. POST creates version N+1 for the
    (kpi, slot) pair and activates it; `activate` re-activates an older
    version (rollback); `deactivate` turns a formula family off entirely
    (the engine then uses the built-in fallback). PUT/PATCH are disabled.
    """

    queryset = KPIFormula.objects.select_related("kpi", "created_by").all()
    serializer_class = FormulaSerializer
    permission_classes = [IsExecutiveOrAdmin]
    filterset_fields = ["kpi", "kpi__code", "kpi__domain", "slot", "is_active"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        kpi = serializer.validated_data["kpi"]
        slot = serializer.validated_data.get("slot", "actual")
        expression = serializer.validated_data["expression"]
        # Validate against the domain's variable vocabulary before saving.
        validate(expression, _variables_for_domain(kpi.domain))
        siblings = KPIFormula.objects.filter(kpi=kpi, slot=slot)
        version = (siblings.aggregate(m=Max("version"))["m"] or 0) + 1
        siblings.filter(is_active=True).update(is_active=False)
        instance = serializer.save(
            version=version, is_active=True, created_by=self.request.user
        )
        audit_log(
            self.request.user, instance, AuditLog.Action.FORMULA,
            {"expression": {"before": None, "after": expression},
             "version": {"before": None, "after": str(version)}},
        )
        _recompute_all_periods()

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        formula = self.get_object()
        KPIFormula.objects.filter(kpi=formula.kpi, slot=formula.slot).update(
            is_active=False
        )
        formula.is_active = True
        formula.save(update_fields=["is_active", "updated_at"])
        audit_log(request.user, formula, AuditLog.Action.FORMULA,
                  {"is_active": {"before": "False", "after": "True"}})
        _recompute_all_periods()
        return Response(self.get_serializer(formula).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        formula = self.get_object()
        formula.is_active = False
        formula.save(update_fields=["is_active", "updated_at"])
        audit_log(request.user, formula, AuditLog.Action.FORMULA,
                  {"is_active": {"before": "True", "after": "False"}})
        _recompute_all_periods()
        return Response(self.get_serializer(formula).data)

    @action(detail=False, methods=["post"])
    def test(self, request):
        """Dry-run an expression against sample or supplied variables."""
        expression = request.data.get("expression", "")
        domain = request.data.get("domain", "sales")
        variables = dict(_sample_variables(domain))
        variables.update(request.data.get("variables") or {})
        try:
            result = evaluate(expression, variables)
        except FormulaError as exc:
            return Response(
                {"ok": False, "error": str(exc)},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "ok": True,
            "result": None if result is None else str(result),
            "variables_used": {k: str(v) for k, v in variables.items()},
        })

    @action(detail=False, methods=["get"])
    def variables(self, request):
        """The vocabulary an admin may use, per domain."""
        domain = request.query_params.get("domain", "sales")
        return Response(sorted(_variables_for_domain(domain)))


def _variables_for_domain(domain: str) -> set:
    if domain == "production":
        return {
            "output", "active_shifts", "repairs", "downtime", "scheduled_shifts",
            "desired_output", "ideal_output", "capacity_output", "man_hours",
            "total_cost", "total_revenue", "input_weight", "output_weight",
            "تولید", "شیفت_فعال", "تعمیری", "توقف", "شیفت_برنامه",
            "تولید_مطلوب", "تولید_ایده_آل", "ظرفیت_تولید", "نفر_ساعت",
            "هزینه_کل", "درآمد_کل", "وزن_ورودی", "وزن_خروجی",
        }
    return {
        "revenue", "invoices", "active_customers", "new_customers",
        "profit", "cost", "target", "calls", "company_revenue",
        "فروش", "تعداد_فاکتور", "مشتری_فعال", "مشتری_جدید",
        "سود", "هزینه", "تارگت", "تماس", "فروش_کل_شرکت",
    }


def _sample_variables(domain: str) -> dict:
    return {name: 100 for name in _variables_for_domain(domain)}


def _recompute_all_periods() -> None:
    """A formula change re-materialises every period's KPIs immediately."""
    from apps.production.services.kpi import compute_period_kpis as compute_production
    from apps.sales.services.kpi import compute_period_kpis as compute_sales

    for period in DimPeriod.objects.all():
        compute_sales(period)
        compute_production(period)


# --------------------------------------------------------------------------
# Audit log API (read-only)
# --------------------------------------------------------------------------
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user").all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsExecutiveOrAdmin]
    filterset_fields = ["action", "model_label", "user"]


# --------------------------------------------------------------------------
# Notifications API — the bell
# --------------------------------------------------------------------------
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["is_read", "verb"]

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user
        ).select_related("actor")

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(is_read=False).count()})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        n = self.get_object()
        n.is_read = True
        n.save(update_fields=["is_read", "updated_at"])
        return Response(self.get_serializer(n).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"marked": updated})
