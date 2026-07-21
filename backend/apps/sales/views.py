from django.db.models import Sum
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import DimKPI, DimPeriod, FactKPI, KPIScope
from apps.sales.models import (
    ApprovalStatus,
    DimBank,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactCollection,
    FactSalesMonthly,
    FactSalesProvince,
)
from apps.core.audit import diff as audit_diff, log as audit_log, snapshot
from apps.core.models import AuditLog
from apps.core.notify import notify_decision, notify_submitted
from apps.core.permissions import (
    CHANNEL_DEPARTMENT,
    ApprovalPermission,
    DepartmentEntryPermission,
    SalesChannelOwnership,
)
from apps.sales.permissions import CanApprove, CanEnterData
from rest_framework.exceptions import PermissionDenied
from apps.sales.serializers import (
    BankSerializer,
    CollectionSerializer,
    EmployeeSerializer,
    KPIDefinitionSerializer,
    KPIResultSerializer,
    PeriodSerializer,
    ProvinceSerializer,
    SalesMonthlySerializer,
    SalesProvinceSerializer,
    TeamSerializer,
)
from apps.sales.services.kpi import compute_period_kpis


# -------------------- Dimensions (read-mostly) --------------------
class PeriodViewSet(viewsets.ModelViewSet):
    queryset = DimPeriod.objects.all()
    serializer_class = PeriodSerializer


class TeamViewSet(viewsets.ModelViewSet):
    queryset = DimTeam.objects.all()
    serializer_class = TeamSerializer


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = DimEmployee.objects.select_related("team").all()
    serializer_class = EmployeeSerializer
    filterset_fields = ["team", "is_active"]


class ProvinceViewSet(viewsets.ModelViewSet):
    queryset = DimProvince.objects.all()
    serializer_class = ProvinceSerializer


class BankViewSet(viewsets.ModelViewSet):
    queryset = DimBank.objects.all()
    serializer_class = BankSerializer
    filterset_fields = ["kind"]


# -------------------- Facts (data entry) --------------------
class SalesMonthlyViewSet(viewsets.ModelViewSet):
    """Excel-like grid backs onto this. Supports approval transitions."""

    queryset = FactSalesMonthly.objects.select_related("employee", "period").all()
    serializer_class = SalesMonthlySerializer
    permission_classes = [SalesChannelOwnership]
    filterset_fields = ["period", "employee", "status", "channel"]

    def _assert_owns_channel(self, channel):
        user = self.request.user
        if user.is_superuser:
            return
        if user.department != CHANNEL_DEPARTMENT.get(channel):
            raise PermissionDenied("این ردیف متعلق به کانال فروش دیگری است.")

    def perform_create(self, serializer):
        self._assert_owns_channel(serializer.validated_data.get("channel", "team"))
        instance = serializer.save()
        audit_log(self.request.user, instance, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        # Any edit to an approved row sends it back to draft.
        instance = serializer.save(status=ApprovalStatus.DRAFT)
        audit_log(self.request.user, instance, AuditLog.Action.UPDATE,
                  audit_diff(before, snapshot(instance)))

    def _detail(self, fact) -> str:
        return f"فروش {fact.employee.full_name_fa} · {fact.period.label}"

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.SUBMITTED
        fact.submitted_by = request.user
        fact.save(update_fields=["status", "submitted_by", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.SUBMIT)
        notify_submitted(request.user, fact,
                         CHANNEL_DEPARTMENT.get(fact.channel, ""), self._detail(fact))
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission])
    def approve(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.APPROVED
        fact.approved_by = request.user
        fact.save(update_fields=["status", "approved_by", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.APPROVE)
        notify_decision(request.user, fact, "approved", self._detail(fact))
        # Recompute KPIs for the affected period.
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
        """ارسال برای اصلاح — back to the submitter with a note."""
        fact = self.get_object()
        fact.status = ApprovalStatus.NEEDS_REVISION
        fact.save(update_fields=["status", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.REVISION,
                  {"note": {"before": None, "after": request.data.get("note", "")}})
        notify_decision(request.user, fact, "revision", self._detail(fact))
        return Response(self.get_serializer(fact).data)


class SalesProvinceViewSet(viewsets.ModelViewSet):
    queryset = FactSalesProvince.objects.select_related("province", "period").all()
    serializer_class = SalesProvinceSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "sales_org"
    filterset_fields = ["period", "province"]


class CollectionViewSet(viewsets.ModelViewSet):
    queryset = FactCollection.objects.select_related("bank", "period").all()
    serializer_class = CollectionSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "sales_org"
    filterset_fields = ["period", "bank"]


# -------------------- KPI catalog + results --------------------
class KPIDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DimKPI.objects.all()
    serializer_class = KPIDefinitionSerializer
    filterset_fields = ["domain"]


class KPIResultViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FactKPI.objects.select_related("kpi", "period").all()
    serializer_class = KPIResultSerializer
    filterset_fields = ["period", "scope", "kpi__code", "channel", "kpi__domain"]

    @extend_schema(
        parameters=[OpenApiParameter("period", int, description="Period id to recompute")],
    )
    @action(detail=False, methods=["post"], permission_classes=[CanApprove])
    def recompute(self, request):
        period_id = request.data.get("period") or request.query_params.get("period")
        period = DimPeriod.objects.get(pk=period_id)
        n = compute_period_kpis(period)
        return Response({"period": period.label, "rows_written": n})


# -------------------- Executive dashboard summary --------------------
class DashboardSummaryView(APIView):
    """One call that returns everything the executive sales dashboard needs."""

    @extend_schema(
        parameters=[
            OpenApiParameter("period", int, required=True),
            OpenApiParameter(
                "channel", str,
                description="team | organizational (default: team)",
            ),
        ],
        responses=dict,
    )
    def get(self, request):
        from apps.sales.models import SalesChannel

        period_id = request.query_params.get("period")
        period = DimPeriod.objects.get(pk=period_id)
        channel = request.query_params.get("channel", SalesChannel.TEAM)

        company_kpis = FactKPI.objects.filter(
            period=period, scope=KPIScope.COMPANY, kpi__domain="sales", channel=channel
        ).select_related("kpi")

        team_revenue = (
            FactKPI.objects.filter(
                period=period, scope=KPIScope.TEAM, kpi__code="revenue", channel=channel
            )
            .select_related("kpi")
            .values("scope_label", "actual")
            .order_by("-actual")
        )

        # Province + collections belong to the organizational channel's detail,
        # but province sales are merged, so we scope province to the channel's
        # own facts.
        province = (
            FactSalesProvince.objects.filter(period=period)
            .select_related("province")
            .values("province__name_fa")
            .annotate(sales=Sum("sales_rial"), target=Sum("target_rial"))
            .order_by("-sales")
        )

        collections = (
            FactCollection.objects.filter(period=period)
            .select_related("bank")
            .values("bank__name_fa")
            .annotate(amount=Sum("amount_rial"))
            .order_by("-amount")
        )

        leaderboard = (
            FactKPI.objects.filter(
                period=period, scope=KPIScope.EMPLOYEE,
                kpi__code="target_achievement", channel=channel,
            )
            .values("scope_label", "actual")
            .order_by("-actual")
        )

        return Response(
            {
                "period": PeriodSerializer(period).data,
                "channel": channel,
                "kpis": KPIResultSerializer(company_kpis, many=True).data,
                "team_revenue": list(team_revenue),
                "province_sales": list(province),
                "collections": list(collections),
                "leaderboard": list(leaderboard),
            }
        )
