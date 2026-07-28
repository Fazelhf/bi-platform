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
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins
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
    PeriodKind,
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


class ExecutiveTrendView(APIView):
    """
    The whole year in one payload: sales per channel per month, plus plan.

    The overview page previously showed a single month with nothing to judge it
    against — a bare figure cannot answer "is this good?", which is the only
    question an executive summary exists to answer. One request rather than
    twelve, because the page needs the shape of the year before it can draw
    anything.

    Figures are read from the LEAF periods of each month, so a month that has
    been split into weeks totals its weeks and a month that has not totals
    itself. Reading the month row directly would return zero for every split
    month.
    """

    @extend_schema(parameters=[OpenApiParameter("year", int)], responses=dict)
    def get(self, request):
        from apps.core.periods import leaf_ids_for
        from apps.sales.models import SalesChannel, SalesTarget

        year = int(request.query_params.get("year") or 0)
        if not year:
            from apps.core.jalali import from_gregorian

            year = from_gregorian(timezone.localdate())[0]

        months = list(
            DimPeriod.objects.filter(jalali_year=year, kind=PeriodKind.MONTH)
            .order_by("jalali_month")
            .prefetch_related("children")
        )

        # One query per fact table rather than per month.
        leaf_map = {m.id: leaf_ids_for(m) for m in months}
        all_leaves = [i for ids in leaf_map.values() for i in ids]

        revenue_rows = (
            FactSalesMonthly.objects.filter(
                period_id__in=all_leaves, status=ApprovalStatus.APPROVED
            )
            .values("period_id", "channel")
            .annotate(total=Sum("revenue_rial"), profit=Sum("profit_rial"))
        )
        by_leaf: dict[int, dict[str, dict]] = {}
        for r in revenue_rows:
            by_leaf.setdefault(r["period_id"], {})[r["channel"]] = r

        target_rows = (
            SalesTarget.objects.filter(period__in=months, employee__isnull=False)
            .values("period_id")
            .annotate(total=Sum("target_rial"))
        )
        targets = {r["period_id"]: float(r["total"] or 0) for r in target_rows}

        cost_rows = (
            FactProductionCost.objects.filter(period_id__in=all_leaves)
            .values("period_id").annotate(total=Sum("amount_rial"))
        )
        costs = {r["period_id"]: float(r["total"] or 0) for r in cost_rows}

        out = []
        for m in months:
            leaves = leaf_map[m.id]
            channels = {c: 0.0 for c, _ in SalesChannel.choices}
            profit = 0.0
            for leaf in leaves:
                for channel, row in by_leaf.get(leaf, {}).items():
                    channels[channel] = channels.get(channel, 0.0) + float(row["total"] or 0)
                    profit += float(row["profit"] or 0)
            total = sum(channels.values())
            target = targets.get(m.id, 0.0)
            out.append({
                "period": m.id,
                "label": m.label,
                "month": m.jalali_month,
                "total": total,
                "profit": profit,
                "target": target,
                "achievement": round(total / target * 100, 1) if target else 0.0,
                "production_cost": sum(costs.get(l, 0.0) for l in leaves),
                **{f"channel_{c}": v for c, v in channels.items()},
            })
        return Response({"year": year, "months": out})


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
        b2b = _kpi_map(period, "sales", SalesChannel.B2B)
        production = _kpi_map(period, "production")

        def actual(m, code):
            k = m.get(code)
            return k.actual if k else None

        team_revenue = actual(team, "revenue") or 0
        org_revenue = actual(org, "revenue") or 0
        b2b_revenue = actual(b2b, "revenue") or 0
        total_sales_revenue = team_revenue + org_revenue + b2b_revenue
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
                # فروش بانکی (سازمانی)
                "sales_org": {
                    "kpis": KPIResultSerializer(list(org.values()), many=True).data,
                    "revenue": org_revenue,
                },
                # فروش B2B
                "sales_b2b": {
                    "kpis": KPIResultSerializer(list(b2b.values()), many=True).data,
                    "revenue": b2b_revenue,
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
                    "sales_b2b_revenue": b2b_revenue,
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
    permission_classes = [IsExecutiveOrAdmin]  # CEO + admin only — not others
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


def models_Q_exec():
    from django.db.models import Q
    return Q(role="executive") | Q(is_superuser=True)


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
class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Read + delete. The queryset is always scoped to the signed-in user, so
    nobody can read or delete somebody else's notifications."""

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

    @action(detail=False, methods=["post"], url_path="clear-read")
    def clear_read(self, request):
        """Delete the ones already read — the everyday tidy-up."""
        deleted, _ = self.get_queryset().filter(is_read=True).delete()
        return Response({"deleted": deleted})

    @action(detail=False, methods=["post"], url_path="clear-all")
    def clear_all(self, request):
        """Delete every notification of this user, read or not."""
        deleted, _ = self.get_queryset().delete()
        return Response({"deleted": deleted})


# --------------------------------------------------------------------------
# Excel export — the CEO's one-click board report
# --------------------------------------------------------------------------
class DashboardExportView(APIView):
    """Download one dashboard section as .xlsx. Executive/admin only."""

    permission_classes = [IsExecutiveOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter("period", int, required=True),
            OpenApiParameter(
                "section", str, required=True,
                description="team | organizational | b2b | production",
            ),
        ],
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request):
        from urllib.parse import quote

        from apps.core.export import build_workbook

        period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        section = request.query_params.get("section", "team")
        try:
            stream, filename = build_workbook(period, section)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(
            stream.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        # Persian filenames must be RFC 5987 encoded to survive the header.
        response["Content-Disposition"] = (
            f"attachment; filename=export.xlsx; filename*=UTF-8''{quote(filename)}"
        )
        return response


# --------------------------------------------------------------------------
# Site settings — chart theme picker (read: everyone, write: CEO/admin)
# --------------------------------------------------------------------------
class SiteSettingView(APIView):
    """GET is open to any signed-in user (the app needs the theme to render);
    PATCH is restricted to the CEO/admin."""

    def get_permissions(self):
        from rest_framework.permissions import IsAuthenticated
        return [IsExecutiveOrAdmin()] if self.request.method == "PATCH" else [IsAuthenticated()]

    def get(self, request):
        from apps.core.models import SiteSetting
        s = SiteSetting.get()
        return Response({
            "chart_theme": s.chart_theme,
            "company_name": s.company_name,
            "themes": [{"key": k, "label": v} for k, v in SiteSetting.THEMES],
            "sales_grain": s.sales_grain,
            "sales_grains": [{"key": k, "label": v} for k, v in SiteSetting.SALES_GRAINS],
            "min_week_days": s.min_week_days,
        })

    def patch(self, request):
        from apps.core.models import SiteSetting
        s = SiteSetting.get()
        before = {"chart_theme": s.chart_theme, "sales_grain": s.sales_grain}
        if "chart_theme" in request.data:
            s.chart_theme = request.data["chart_theme"]
        if "company_name" in request.data:
            s.company_name = request.data["company_name"]
        if "sales_grain" in request.data:
            s.sales_grain = request.data["sales_grain"]
        if "min_week_days" in request.data:
            s.min_week_days = int(request.data["min_week_days"])
        s.save()
        audit_log(request.user, s, AuditLog.Action.UPDATE, {
            "chart_theme": {"before": before["chart_theme"], "after": s.chart_theme},
            "sales_grain": {"before": before["sales_grain"], "after": s.sales_grain},
        })
        return Response({
            "chart_theme": s.chart_theme,
            "company_name": s.company_name,
            "sales_grain": s.sales_grain,
            "min_week_days": s.min_week_days,
        })
