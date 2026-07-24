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
class KPIDefinitionViewSet(viewsets.ModelViewSet):
    """Everyone reads the catalog; only executives edit display metadata."""

    queryset = DimKPI.objects.all()
    serializer_class = KPIDefinitionSerializer
    filterset_fields = ["domain"]
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        from apps.core.permissions import IsExecutiveOrAdmin
        from rest_framework.permissions import IsAuthenticated

        if self.request.method in ("PATCH",):
            return [IsExecutiveOrAdmin()]
        return [IsAuthenticated()]


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


# --------------------------------------------------------------------------
# Combined SALES INPUT — the Excel single-sheet table (salespeople as columns)
# --------------------------------------------------------------------------
SALES_METRIC_FIELDS = [
    "revenue_rial", "invoice_count", "active_customers", "new_customers",
    "profit_rial", "cost_rial", "target_rial", "calls",
]
# Row labels, in the exact order of the source workbook.
SALES_METRIC_ROWS = [
    ("revenue_rial", "فروش ریالی"),
    ("invoice_count", "تعداد فاکتور فروش"),
    ("active_customers", "تعداد مشتری فعال ماه"),
    ("new_customers", "تعداد مشتری جدید"),
    ("profit_rial", "سود فروش"),
    ("cost_rial", "هزینه فروش"),
    ("target_rial", "تارگت فروش"),
    ("calls", "تعداد تماس"),
]

# B2B (فروش شرکت‌به‌شرکت / عمده) is a different business: paper is sold by
# tonnage to companies on credit terms, so the sheet tracks volume and
# collection instead of call activity. Its provinces are tracked separately
# too (FactSalesProvince is channel-scoped).
B2B_METRIC_ROWS = [
    ("revenue_rial", "فروش ریالی"),
    ("quantity_ton", "مقدار فروش (تن)"),
    ("invoice_count", "تعداد قرارداد / فاکتور"),
    ("active_customers", "تعداد شرکت فعال"),
    ("new_customers", "تعداد شرکت جدید"),
    ("profit_rial", "سود فروش"),
    ("cost_rial", "هزینه فروش"),
    ("target_rial", "تارگت فروش"),
    ("collected_rial", "مبلغ وصول‌شده"),
    ("receivables_rial", "مانده مطالبات"),
]


def metric_rows_for(channel: str):
    """The input sheet's rows for a channel — B2B has its own set."""
    from apps.sales.models import SalesChannel

    return B2B_METRIC_ROWS if channel == SalesChannel.B2B else SALES_METRIC_ROWS


def metric_fields_for(channel: str) -> list[str]:
    return [f for f, _ in metric_rows_for(channel)]


class SalesInputView(APIView):
    """
    Mirrors the sales workbook's single input sheet: one column per
    salesperson (کارشناس), the 8 metric rows, plus the provincial block.
    Managers may add/rename/remove salespeople by hand (not tied to a fixed
    DB list). GET returns the table; POST syncs it (upsert + prune).
    """

    permission_classes = [SalesChannelOwnership]

    def _channel(self, request):
        return request.query_params.get("channel") or request.data.get("channel") or "team"

    def _assert_owner(self, request, channel):
        u = request.user
        if u.is_superuser or u.role == "executive":
            return
        if u.department != CHANNEL_DEPARTMENT.get(channel):
            raise PermissionDenied("این کانال فروش متعلق به بخش شما نیست.")

    @extend_schema(parameters=[OpenApiParameter("period", int, required=True),
                              OpenApiParameter("channel", str)], responses=dict)
    def get(self, request):
        period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        channel = self._channel(request)
        facts = FactSalesMonthly.objects.filter(
            period=period, channel=channel
        ).select_related("employee").order_by("employee__id")

        fields = metric_fields_for(channel)
        columns = [{
            "employee_id": f.employee_id,
            "name": f.employee.full_name_fa,
            "status": f.status,
            **{m: str(getattr(f, m)) for m in fields},
        } for f in facts]

        provinces = [{
            "province_id": p.province_id,
            "name": p.province.name_fa,
            "sales_rial": str(p.sales_rial),
            "target_rial": str(p.target_rial),
        } for p in FactSalesProvince.objects.filter(
            period=period, channel=channel
        ).select_related("province").order_by("province__id")]

        # Also expose the full province catalog so managers can add any.
        all_provinces = [{"id": p.id, "name": p.name_fa}
                         for p in DimProvince.objects.all()]

        return Response({
            "period": PeriodSerializer(period).data,
            "channel": channel,
            "metric_rows": [{"field": f, "label": l} for f, l in metric_rows_for(channel)],
            "columns": columns,
            "provinces": provinces,
            "all_provinces": all_provinces,
        })

    def post(self, request):
        import uuid
        period = DimPeriod.objects.get(pk=request.data.get("period"))
        channel = self._channel(request)
        self._assert_owner(request, channel)
        submit = bool(request.data.get("submit"))
        status = ApprovalStatus.SUBMITTED if submit else ApprovalStatus.DRAFT
        user = request.user

        kept_employee_ids = set()
        for row in request.data.get("columns", []):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            emp_id = row.get("employee_id")
            if emp_id:
                employee = DimEmployee.objects.filter(pk=emp_id).first()
                if employee and employee.full_name_fa != name:
                    employee.full_name_fa = name
                    employee.save(update_fields=["full_name_fa"])
            else:
                employee = DimEmployee.objects.filter(full_name_fa=name).first()
            if employee is None:
                employee = DimEmployee.objects.create(
                    full_name_fa=name, code=f"emp-{uuid.uuid4().hex[:8]}"
                )
            values = {m: (row.get(m) or 0) for m in metric_fields_for(channel)}
            values["status"] = status
            if submit:
                values["submitted_by"] = user
            obj, _ = FactSalesMonthly.objects.update_or_create(
                period=period, employee=employee, channel=channel, defaults=values
            )
            kept_employee_ids.add(employee.id)

        # Prune salespeople the manager removed from the table.
        FactSalesMonthly.objects.filter(period=period, channel=channel).exclude(
            employee_id__in=kept_employee_ids
        ).delete()

        # Provinces
        for p in request.data.get("provinces", []):
            if not p.get("province_id"):
                continue
            FactSalesProvince.objects.update_or_create(
                period=period, province_id=p["province_id"], channel=channel,
                defaults={"sales_rial": p.get("sales_rial") or 0,
                          "target_rial": p.get("target_rial") or 0},
            )

        audit_log(user, period, AuditLog.Action.UPDATE,
                  {"sales_input": {"before": None, "after": f"{channel} · {len(kept_employee_ids)} کارشناس"}})

        if submit:
            first = FactSalesMonthly.objects.filter(period=period, channel=channel).first()
            if first:
                notify_submitted(user, first, CHANNEL_DEPARTMENT.get(channel, ""),
                                 f"فروش {channel} · {period.label}")

        return Response({"ok": True, "submitted": submit, "salespeople": len(kept_employee_ids)})


# --------------------------------------------------------------------------
# DETAILED SALES DASHBOARD — mirrors the workbook's two chart sheets:
#   داشبورد فروشنده (11 charts, per salesperson + provinces)
#   داشبورد تیم     (9 charts, per team across the 5 teams)
# --------------------------------------------------------------------------
def _ratio(num, den):
    return float(num) / float(den) if den else None


class SalesDashboardDetailView(APIView):
    """Per-salesperson and per-team series for the sales chart dashboards."""

    @extend_schema(parameters=[OpenApiParameter("period", int, required=True),
                              OpenApiParameter("channel", str)], responses=dict)
    def get(self, request):
        period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        channel = request.query_params.get("channel", "team")

        # ---- Salesperson block (channel-scoped) — Sheet3 rows 18-30 ----
        facts = list(
            FactSalesMonthly.objects.filter(
                period=period, channel=channel, status=ApprovalStatus.APPROVED
            ).select_related("employee").order_by("employee__id")
        )
        channel_revenue = sum(float(f.revenue_rial) for f in facts)

        salespeople = []
        for f in facts:
            rev = float(f.revenue_rial)
            salespeople.append({
                "name": f.employee.full_name_fa,
                "revenue": rev,
                "invoices": f.invoice_count,
                "active_customers": f.active_customers,
                "new_customers": f.new_customers,
                "profit": float(f.profit_rial),
                "cost": float(f.cost_rial),
                "target": float(f.target_rial),
                "calls": f.calls,
                # B2B-only measures (0 elsewhere)
                "quantity_ton": float(f.quantity_ton),
                "collected": float(f.collected_rial),
                "receivables": float(f.receivables_rial),
                # derived (Sheet3 rows 28-30)
                "volume_share": _ratio(rev, channel_revenue) and _ratio(rev, channel_revenue) * 100,
                "target_achievement": _ratio(rev, f.target_rial) and _ratio(rev, f.target_rial) * 100,
                "call_conversion": _ratio(f.invoice_count, f.calls) and _ratio(f.invoice_count, f.calls) * 100,
                # derived B2B
                "collection_rate": _ratio(f.collected_rial, rev) and _ratio(f.collected_rial, rev) * 100,
                "price_per_ton": _ratio(rev, f.quantity_ton),
            })

        # ---- Team block — Sheet3 rows 47-59 ----
        # Scoped to THIS channel so the team charts match the channel the user is
        # viewing (previously this aggregated across all channels, so the B2B and
        # banking dashboards showed company-wide team totals that did not match
        # their own recorded figures).
        all_facts = FactSalesMonthly.objects.filter(
            period=period, channel=channel, status=ApprovalStatus.APPROVED
        ).select_related("employee", "employee__team")

        agg: dict[int, dict] = {}
        for f in all_facts:
            t = f.employee.team
            if t is None:
                continue
            a = agg.setdefault(t.id, {
                "name": t.name_fa, "revenue": 0.0, "invoices": 0, "active_customers": 0,
                "new_customers": 0, "profit": 0.0, "cost": 0.0, "target": 0.0, "calls": 0,
            })
            a["revenue"] += float(f.revenue_rial)
            a["invoices"] += f.invoice_count
            a["active_customers"] += f.active_customers
            a["new_customers"] += f.new_customers
            a["profit"] += float(f.profit_rial)
            a["cost"] += float(f.cost_rial)
            a["target"] += float(f.target_rial)
            a["calls"] += f.calls

        total_target = sum(a["target"] for a in agg.values())
        teams = []
        for t in DimTeam.objects.all().order_by("id"):
            a = agg.get(t.id)
            if a is None:
                a = {"name": t.name_fa, "revenue": 0.0, "invoices": 0, "active_customers": 0,
                     "new_customers": 0, "profit": 0.0, "cost": 0.0, "target": 0.0, "calls": 0}
            r = _ratio(a["calls"], a["invoices"])            # نسبت تماس موفق
            tp = _ratio(a["revenue"], a["target"])            # درصد تحقق تارگت
            share = _ratio(a["revenue"], total_target)        # سهم تیم از فروش به تارگت
            c2s = _ratio(a["cost"], a["revenue"])             # هزینه به فروش
            teams.append({
                **a,
                "success_call_ratio": r,
                "target_achievement": tp and tp * 100,
                "share_of_total_target": share and share * 100,
                "cost_to_sales": c2s and c2s * 100,
            })

        # ---- Provinces (channel-scoped) ----
        provinces = [{
            "name": p.province.name_fa,
            "sales": float(p.sales_rial),
            "target": float(p.target_rial),
        } for p in FactSalesProvince.objects.filter(
            period=period, channel=channel
        ).select_related("province").order_by("-sales_rial")]

        return Response({
            "period": PeriodSerializer(period).data,
            "channel": channel,
            "salespeople": salespeople,
            "teams": teams,
            "provinces": provinces,
        })
