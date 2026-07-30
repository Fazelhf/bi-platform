from decimal import Decimal, InvalidOperation

from django.db.models import Count, Max, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.jalali import from_gregorian
from apps.core.models import DimKPI, DimPeriod, FactKPI, KPIScope, PeriodKind
from apps.core.periods import month_of
from apps.sales.models import (
    ApprovalStatus,
    DimBank,
    DimEmployee,
    EmployeeChannel,
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
    IsExecutiveOrAdmin,
    SalesChannelOwnership,
)
from apps.sales.permissions import CanApprove, CanEnterData
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.sales.serializers import (
    BankSerializer,
    CollectionSerializer,
    EmployeeSerializer,
    KPIDefinitionSerializer,
    KPIResultSerializer,
    PeriodSerializer,
    ProvinceSerializer,
    RosterMemberSerializer,
    SalesMonthlySerializer,
    SalesProvinceSerializer,
    TeamSerializer,
)
from apps.sales.services.kpi import compute_period_kpis


def assert_channel_visible(user, channel: str) -> None:
    """
    A sales channel is only visible to the department that owns it.

    Reads were wide open: any signed-in user could pull فروش بانکی or B2B
    figures by changing `?channel=` or typing the dashboard URL, even though
    the sidebar only ever offered them their own. The menu was the whole
    boundary, which is no boundary at all.

    The CEO, executives and superusers still see every channel — that is the
    point of the overview.
    """
    if not (user and user.is_authenticated):
        raise PermissionDenied("وارد نشده‌اید.")
    if user.is_superuser or user.role == "executive":
        return
    owner = CHANNEL_DEPARTMENT.get(channel)
    if owner and user.department == owner:
        return
    raise PermissionDenied("این بخش فروش متعلق به شما نیست.")


def current_jalali_year() -> int:
    """The Jalali year we are in right now."""
    return from_gregorian(timezone.localdate())[0]


# -------------------- Dimensions (read-mostly) --------------------
class PeriodViewSet(viewsets.ModelViewSet):
    """
    Months by default — the dropdowns everywhere expect months, so weeks must
    not leak into them. Pass ?kind=week to list the children instead.

    Also scoped to the CURRENT Jalali year by default. Every dashboard and
    entry sheet reads this one endpoint, so last year's months were appearing
    in nine different dropdowns and burying the months anyone actually works
    in. Scoped to the current year rather than pinned to 1405, otherwise the
    dashboards would keep showing 1405 and hide the new year the moment
    Nowruz passes — the exact opposite of what the scoping is for.

    `?year=1404` reads a specific year and `?year=all` reads every year, so
    nothing is unreachable; the CEO's «دوره‌ها» panel uses its own year-grain
    action and is unaffected.
    """

    # Kept so the router can still derive a basename; the real filtering
    # happens in get_queryset().
    queryset = DimPeriod.objects.all()
    serializer_class = PeriodSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = DimPeriod.objects.all()

        # Detail routes (and writes) must reach ANY period — any kind, any
        # year. Both filters below are listing conveniences, not permissions:
        # leaving the kind filter in place made /periods/<week>/unsplit/ and
        # every day-level action return 404, because the default kind is month.
        if self.detail:
            return qs

        kind = params.get("kind", "month")
        if kind != "all":
            qs = qs.filter(kind=kind)

        year = (params.get("year") or "").strip()
        if year == "all":
            return qs
        if year.isdigit():
            return qs.filter(jalali_year=int(year))
        return qs.filter(jalali_year=current_jalali_year())

    @action(detail=True, methods=["get"])
    def weeks(self, request, pk=None):
        """
        The month's weeks plus how far through it we are — this is what draws
        the progress dots and the «داده تا …» / «ماه کامل نشده» badge.
        """
        from apps.core.periods import progress

        from apps.core.periods import calendar, reconciliation

        month = self.get_object()
        data = progress(month)
        data["period"] = self.get_serializer(month).data
        # The calendar lets the UI show which days each week covers, and the
        # reconciliation proves جمع هفته‌ها == ماه instead of just claiming it.
        data["calendar"] = calendar(month)
        data["reconciliation"] = reconciliation(month)
        return Response(data)

    @action(detail=True, methods=["post"], permission_classes=[IsExecutiveOrAdmin])
    def split(self, request, pk=None):
        """
        Cut a period one level finer: a month into weeks, a week into days.
        Executive-only, and refused once the period holds figures — see the
        invariant on DimPeriod.
        """
        from apps.core.models import PeriodKind, SiteSetting
        from apps.core.periods import ensure_days, ensure_weeks

        period = self.get_object()
        try:
            if period.kind == PeriodKind.WEEK:
                children = ensure_days(period)
            else:
                children = ensure_weeks(period, min_days=SiteSetting.get().min_week_days)
        except ValueError as exc:
            return Response({"detail": str(exc)},
                            status=http_status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(children, many=True).data)

    @action(detail=True, methods=["post"], url_path="split-days",
            permission_classes=[IsExecutiveOrAdmin])
    def split_days(self, request, pk=None):
        """
        Put a whole month onto daily entry in one action — split it into weeks
        if needed, then split every week into days. Doing it week by week from
        the UI would be six clicks for one decision.
        """
        from django.db import transaction

        from apps.core.models import PeriodKind, SiteSetting
        from apps.core.periods import ensure_days, ensure_weeks, has_facts

        month = self.get_object()
        if month.kind != PeriodKind.MONTH:
            return Response({"detail": "فقط یک ماه را می‌توان روزانه کرد."},
                            status=http_status.HTTP_400_BAD_REQUEST)
        try:
            # All or nothing. ensure_days() is atomic per week, but this walks
            # several of them: without an outer transaction a month whose third
            # week held figures came back 400 having already converted the
            # first two — a refusal that half-applied.
            with transaction.atomic():
                weeks = list(month.children.order_by("seq")) or ensure_weeks(
                    month, min_days=SiteSetting.get().min_week_days
                )
                # Name every blocking week up front, rather than stopping at the
                # first: the manager needs to know what to clear, not to
                # discover it one refusal at a time.
                blocked = [
                    w for w in weeks
                    if w.kind == PeriodKind.WEEK and not w.children.exists() and has_facts(w)
                ]
                if blocked:
                    raise ValueError(
                        "این هفته‌ها داده‌ی ثبت‌شده دارند و باید اول پاک شوند: "
                        + "، ".join(f"هفته {w.seq}" for w in blocked)
                    )
                days = []
                for w in weeks:
                    if w.kind != PeriodKind.WEEK:
                        continue
                    days.extend(ensure_days(w) if not w.children.exists()
                                else list(w.children.order_by("seq")))
        except ValueError as exc:
            return Response({"detail": str(exc)},
                            status=http_status.HTTP_400_BAD_REQUEST)
        return Response({"weeks": len(weeks), "days": len(days)})

    @action(detail=True, methods=["post"], permission_classes=[IsExecutiveOrAdmin])
    def unsplit(self, request, pk=None):
        """Back to monthly entry. Refused while any week still holds data."""
        from apps.core.periods import unsplit

        try:
            removed = unsplit(self.get_object())
        except ValueError as exc:
            return Response({"detail": str(exc)},
                            status=http_status.HTTP_400_BAD_REQUEST)
        return Response({"removed": removed})

    @action(detail=False, methods=["get"], url_path="year-grain")
    def year_grain(self, request):
        """
        Every month of a year with its current grain and whether it can be
        changed — this is what the CEO's «دوره‌ها» panel renders.
        """
        from apps.core.periods import has_facts, leaves_of

        year = int(request.query_params.get("year") or 0)
        months = DimPeriod.objects.filter(kind="month")
        if year:
            months = months.filter(jalali_year=year)

        out = []
        for m in months.order_by("jalali_year", "jalali_month"):
            weeks = list(m.children.order_by("seq"))
            day_count = sum(w.children.count() for w in weeks)
            month_has_facts = has_facts(m)
            # A week counts as filled if anything under it holds figures, so a
            # week whose days have data still blocks going back to weekly.
            filled_weeks = [
                w.seq for w in weeks if any(has_facts(l) for l in leaves_of(w))
            ]
            filled_days = [
                w.seq for w in weeks
                if w.children.exists() and any(has_facts(d) for d in w.children.all())
            ]

            grain = "month"
            if day_count:
                grain = "day"
            elif weeks:
                grain = "week"

            out.append({
                "id": m.id,
                "label": m.label,
                "jalali_year": m.jalali_year,
                "jalali_month": m.jalali_month,
                "grain": grain,
                "week_count": len(weeks),
                "day_count": day_count,
                "days": m.days,
                # Why a switch is unavailable, so the UI can explain itself.
                "can_go_weekly": (
                    (not weeks and not month_has_facts)          # from monthly
                    or (grain == "day" and not filled_days)      # back from daily
                ),
                "can_go_monthly": bool(weeks) and not filled_weeks,
                "can_go_daily": bool(weeks) and grain != "day" and not filled_weeks
                                or (not weeks and not month_has_facts),
                "blocked_reason": (
                    "این ماه داده‌ی ماهانه دارد" if month_has_facts and not weeks
                    else f"هفته‌های {'، '.join(map(str, filled_weeks))} داده دارند"
                    if filled_weeks else ""
                ),
            })
        return Response(out)


class TeamManagePermission(BasePermission):
    """Read for anyone signed in; only the CEO, an admin or a sales department
    manager may reshape the teams themselves."""

    message = "شما مجاز به تغییر تیم‌ها نیستید."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(
            u.is_superuser
            or u.role == "executive"
            or u.department in CHANNEL_DEPARTMENT.values()
        )


class TeamViewSet(viewsets.ModelViewSet):
    """
    گروه‌های فروش (ایران غرب، تهران، …) — now editable from «تیم من» rather
    than only through the Django admin.
    """

    queryset = DimTeam.objects.all().order_by("name_fa")
    serializer_class = TeamSerializer
    permission_classes = [TeamManagePermission]

    def perform_create(self, serializer):
        # `code` is a slug nobody wants to invent when adding «ایران غرب».
        import uuid

        code = (serializer.validated_data.get("code") or "").strip()
        serializer.save(code=code or f"team-{uuid.uuid4().hex[:8]}")

    def destroy(self, request, *args, **kwargs):
        """
        Refused while anyone is still in the team. `team` is SET_NULL, so
        deleting it would quietly strip the grouping off every member and the
        team dashboards would lose a column with no warning.
        """
        team = self.get_object()
        members = DimEmployee.objects.filter(team=team)
        if members.exists():
            names = "، ".join(members.values_list("full_name_fa", flat=True)[:5])
            return Response(
                {"detail": f"این تیم {members.count()} عضو دارد و حذف نمی‌شود: {names}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


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
        assert_channel_visible(request.user, channel)

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
# Targets are set by the CEO in the «تارگت» section, never by the department
# manager filling in the month's actuals. They still appear as a row on the
# sheet (managers need to see what they are aiming at) but read-only, and the
# server strips them from a non-executive's payload — see TARGET_FIELDS.
TARGET_FIELDS = {"target_rial"}


def _nonzero(value) -> bool:
    """True when a submitted cell holds a real number other than zero."""
    try:
        return Decimal(str(value or 0)) != 0
    except (InvalidOperation, ValueError):
        return False

# Row labels, in the exact order of the source workbook.
_BASE_ROWS = [
    ("revenue_rial", "فروش ریالی"),
    ("invoice_count", "تعداد فاکتور فروش"),
    ("active_customers", "تعداد مشتری فعال ماه"),
    ("new_customers", "تعداد مشتری جدید"),
    ("profit_rial", "سود فروش"),
    ("cost_rial", "هزینه فروش"),
    ("target_rial", "تارگت فروش"),
    ("calls", "تعداد تماس"),
]

# فروش همکار — the field team quotes before it invoices, so proforma issued
# vs cancelled is its leading indicator.
TEAM_METRIC_ROWS = _BASE_ROWS + [
    ("proforma_issued_rial", "مبلغ پیش‌فاکتورهای صادره"),
    ("proforma_cancelled_rial", "مبلغ پیش‌فاکتورهای کنسل‌شده"),
]

# فروش بانکی — the original eight rows, unchanged.
ORG_METRIC_ROWS = list(_BASE_ROWS)

# B2B (فروش شرکت‌به‌شرکت / عمده) is a different business: paper is sold by
# tonnage to companies on credit terms, so the sheet tracks volume, collection
# and tender wins instead of call activity. Its provinces are tracked
# separately too (FactSalesProvince is channel-scoped).
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
    ("won_invoices_rial", "مبلغ فاکتورهای برنده‌شده"),
]

# Kept for backwards compatibility with anything importing the old name.
SALES_METRIC_ROWS = ORG_METRIC_ROWS
SALES_METRIC_FIELDS = [f for f, _ in ORG_METRIC_ROWS]


def metric_rows_for(channel: str):
    """The input sheet's rows for a channel — each one has its own set."""
    from apps.sales.models import SalesChannel

    if channel == SalesChannel.B2B:
        return B2B_METRIC_ROWS
    if channel == SalesChannel.TEAM:
        return TEAM_METRIC_ROWS
    return ORG_METRIC_ROWS


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
        # Only POST used to be checked, so another department's sheet — names,
        # figures and all — could simply be read.
        self._assert_owner(request, channel)
        facts = FactSalesMonthly.objects.filter(
            period=period, channel=channel
        ).select_related("employee").order_by("employee__id")

        from apps.sales.models import SalesTarget

        # Targets are the CEO's monthly plan and live in their own table now;
        # the sheet shows them read-only for context.
        # month_of, not `parent`: a day's parent is its week, so `parent`
        # would look targets up against a week and find none.
        month = month_of(period)
        plans = {
            t.employee_id: t.target_rial
            for t in SalesTarget.objects.filter(
                period=month, channel=channel, province__isnull=True
            )
        }
        prov_plans = {
            t.province_id: t.target_rial
            for t in SalesTarget.objects.filter(
                period=month, channel=channel, employee__isnull=True
            )
        }

        fields = metric_fields_for(channel)
        columns = [{
            "employee_id": f.employee_id,
            "name": f.employee.full_name_fa,
            "status": f.status,
            **{m: str(getattr(f, m)) for m in fields},
            "target_rial": str(plans.get(f.employee_id, 0)),
        } for f in facts]

        # Then everyone on the roster who has no row yet, as blank columns.
        #
        # The sheet used to be built from the facts alone, so a new period
        # opened empty and the manager retyped the same names every time —
        # and anyone who sold nothing simply disappeared instead of showing a
        # zero, which is a different statement entirely.
        entered = {c["employee_id"] for c in columns}
        roster = (
            EmployeeChannel.objects.filter(channel=channel, is_active=True)
            .select_related("employee")
            .order_by("employee__full_name_fa")
        )
        for member in roster:
            if member.employee_id in entered:
                continue
            columns.append({
                "employee_id": member.employee_id,
                "name": member.employee.full_name_fa,
                "status": ApprovalStatus.DRAFT,
                **{m: "0" for m in fields},
                "target_rial": str(plans.get(member.employee_id, 0)),
            })

        # Every province is listed from the start — managers fill in the ones
        # they sold to instead of hunting for them in an "add" dropdown. Rows
        # that have no fact yet come back as zeros.
        saved = {
            p.province_id: p
            for p in FactSalesProvince.objects.filter(period=period, channel=channel)
        }
        provinces = []
        for prov in DimProvince.objects.all().order_by("id"):
            row = saved.get(prov.id)
            provinces.append({
                "province_id": prov.id,
                "name": prov.name_fa,
                "sales_rial": str(row.sales_rial) if row else "0",
                "target_rial": str(prov_plans.get(prov.id, 0)),
            })

        all_provinces = [{"id": p.id, "name": p.name_fa}
                         for p in DimProvince.objects.all()]

        return Response({
            "period": PeriodSerializer(period).data,
            "channel": channel,
            "metric_rows": [{"field": f, "label": l} for f, l in metric_rows_for(channel)],
            # Targets belong to the CEO; the sheet shows them read-only.
            "readonly_fields": sorted(TARGET_FIELDS),
            "can_edit_targets": bool(
                request.user.is_superuser or request.user.role == "executive"
            ),
            "columns": columns,
            "provinces": provinces,
            "all_provinces": all_provinces,
        })

    def post(self, request):
        import uuid
        period = DimPeriod.objects.get(pk=request.data.get("period"))
        channel = self._channel(request)
        self._assert_owner(request, channel)

        # Hard stop: never write figures to a period that has children. If a
        # month held its own numbers *and* its weeks held theirs, the two
        # would drift apart and every total would be ambiguous. Weekly months
        # are filled in week by week — that is what keeps جمع هفته‌ها == ماه
        # true by construction rather than by hope.
        if period.children.exists():
            raise ValidationError(
                "این ماه به هفته تقسیم شده است؛ اطلاعات باید در هر هفته جداگانه "
                "وارد شود، نه روی خود ماه."
            )
        submit = bool(request.data.get("submit"))
        status = ApprovalStatus.SUBMITTED if submit else ApprovalStatus.DRAFT
        user = request.user

        # Targets live in SalesTarget at month grain and are set only in the
        # «تارگت» section — never through this sheet, whoever is posting.
        editable = [f for f in metric_fields_for(channel) if f not in TARGET_FIELDS]

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
            values = {m: (row.get(m) or 0) for m in editable}
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

        # Provinces. Every province is sent back, so skip untouched empty rows
        # to avoid creating 31 zero facts per channel per month. The province
        # target is the CEO's too.
        for p in request.data.get("provinces", []):
            pid = p.get("province_id")
            if not pid:
                continue
            sales = p.get("sales_rial") or 0
            existing = FactSalesProvince.objects.filter(
                period=period, province_id=pid, channel=channel
            ).first()
            if existing is None and not _nonzero(sales):
                continue  # nothing entered for this province — don't store it
            FactSalesProvince.objects.update_or_create(
                period=period, province_id=pid, channel=channel,
                defaults={"sales_rial": sales},
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
# TARGETS — the CEO's own section (بخش تارگت)
# --------------------------------------------------------------------------
class SalesTargetView(APIView):
    """
    Set the month's targets for one sales channel: a figure per salesperson
    and a figure per province. Department managers see these on their entry
    sheet but cannot change them — only the CEO/admin can write here.
    """

    permission_classes = [IsExecutiveOrAdmin]

    @extend_schema(parameters=[OpenApiParameter("period", int, required=True),
                              OpenApiParameter("channel", str)], responses=dict)
    def get(self, request):
        from apps.core.periods import leaf_ids_for
        from apps.sales.models import SalesTarget

        period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        month = month_of(period)  # plans are always held on the month
        channel = request.query_params.get("channel", "team")
        leaves = leaf_ids_for(month)

        plans = {
            (t.employee_id, t.province_id): t.target_rial
            for t in SalesTarget.objects.filter(period=month, channel=channel)
        }

        # Actuals come from the leaves so the CEO sees month-to-date beside
        # the plan, whatever grain the month is recorded at.
        actual_by_emp: dict[int, Decimal] = {}
        names: dict[int, str] = {}
        for f in FactSalesMonthly.objects.filter(
            period_id__in=leaves, channel=channel
        ).select_related("employee"):
            actual_by_emp[f.employee_id] = (
                actual_by_emp.get(f.employee_id, Decimal(0)) + f.revenue_rial
            )
            names[f.employee_id] = f.employee.full_name_fa

        # Every salesperson, not only the ones already on the entry sheet.
        # Building this list from the month's facts meant the CEO could not
        # set a plan until the sales manager had added that person — plans are
        # made before the month starts, so the list has to come from the
        # employee dimension, exactly as the province list does.
        #
        # Union rather than a plain filter: someone deactivated mid-year who
        # still has figures or a plan for this month must not vanish from it.
        employees = list(
            DimEmployee.objects.filter(is_active=True)
            .exclude(full_name_fa__in=["", "0"])
            .select_related("team")
        )
        seen = {e.id for e in employees}
        extra_ids = (set(actual_by_emp) | {e for e, p in plans if e and p is None}) - seen
        employees += list(
            DimEmployee.objects.filter(id__in=extra_ids).select_related("team")
        )
        employees.sort(key=lambda e: e.id)

        people = [{
            "employee_id": e.id,
            "name": e.full_name_fa,
            "team": e.team.name_fa if e.team else "",
            "is_active": e.is_active,
            "target_rial": str(plans.get((e.id, None), 0)),
            "revenue_rial": str(actual_by_emp.get(e.id, 0)),
        } for e in employees]

        actual_by_prov: dict[int, Decimal] = {}
        for p in FactSalesProvince.objects.filter(
            period_id__in=leaves, channel=channel
        ):
            actual_by_prov[p.province_id] = (
                actual_by_prov.get(p.province_id, Decimal(0)) + p.sales_rial
            )

        provinces = [{
            "province_id": prov.id,
            "name": prov.name_fa,
            "target_rial": str(plans.get((None, prov.id), 0)),
            "sales_rial": str(actual_by_prov.get(prov.id, 0)),
        } for prov in DimProvince.objects.all().order_by("id")]

        return Response({
            "period": PeriodSerializer(month).data,
            "channel": channel,
            "people": people,
            "provinces": provinces,
        })

    def post(self, request):
        from apps.sales.models import SalesTarget

        period = DimPeriod.objects.get(pk=request.data.get("period"))
        month = month_of(period)
        channel = request.data.get("channel", "team")

        for row in request.data.get("people", []):
            emp_id = row.get("employee_id")
            if not emp_id:
                continue
            SalesTarget.objects.update_or_create(
                period=month, channel=channel, employee_id=emp_id, province=None,
                defaults={"target_rial": row.get("target_rial") or 0},
            )

        for row in request.data.get("provinces", []):
            pid = row.get("province_id")
            if not pid:
                continue
            target = row.get("target_rial") or 0
            exists = SalesTarget.objects.filter(
                period=month, channel=channel, province_id=pid
            ).exists()
            if not exists and not _nonzero(target):
                continue  # no plan set and none stored — nothing to do
            SalesTarget.objects.update_or_create(
                period=month, channel=channel, province_id=pid, employee=None,
                defaults={"target_rial": target},
            )

        audit_log(request.user, month, AuditLog.Action.UPDATE,
                  {"targets": {"before": None, "after": f"{channel} · {month.label}"}})
        # Target changes move تحقق تارگت everywhere under this month — every
        # level of the tree, not just the weeks, now that days exist.
        compute_period_kpis(month)
        for wk in month.children.all():
            compute_period_kpis(wk, cascade=False)
            for day in wk.children.all():
                compute_period_kpis(day, cascade=False)
        return Response({"ok": True})


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
        assert_channel_visible(request.user, channel)

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


class RosterViewSet(viewsets.ModelViewSet):
    """
    «کارشناسان بخش» — each department manager's own roster.

    Until now nothing said which salespeople belong to a channel: the entry
    sheet listed whoever already had figures, so a new month opened blank and
    a rep who sold nothing simply disappeared. This is the list the manager
    maintains, and the entry sheet is built from it.

    Scoped by channel, and a manager only ever sees and edits their own —
    the CEO and superusers see any of them.
    """

    serializer_class = RosterMemberSerializer
    permission_classes = [SalesChannelOwnership]
    queryset = EmployeeChannel.objects.select_related("employee", "employee__team", "employee__user")

    def _channel(self):
        return (
            self.request.query_params.get("channel")
            or self.request.data.get("channel")
            or self._own_channel()
            or "team"
        )

    def _own_channel(self):
        """The channel this user's department owns, if any."""
        dept = getattr(self.request.user, "department", "")
        for channel, d in CHANNEL_DEPARTMENT.items():
            if d == dept:
                return channel
        return None

    def _assert_owner(self, channel):
        u = self.request.user
        if u.is_superuser or u.role == "executive":
            return
        if u.department != CHANNEL_DEPARTMENT.get(channel):
            raise PermissionDenied("این بخش متعلق به شما نیست.")

    def get_queryset(self):
        qs = super().get_queryset()
        if self.detail:
            return qs
        channel = self._channel()
        self._assert_owner(channel)
        qs = qs.filter(channel=channel)
        if self.request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return qs

    def list(self, request, *args, **kwargs):
        members = list(self.filter_queryset(self.get_queryset()))
        channel = self._channel()

        # One pass over the facts instead of three queries per member.
        stats = (
            FactSalesMonthly.objects.filter(
                channel=channel, employee_id__in=[m.employee_id for m in members]
            )
            .values("employee_id")
            .annotate(
                periods_filled=Count("id", distinct=True),
                total_revenue=Sum("revenue_rial"),
                last_seen=Max("period__end_date"),
            )
        )
        by_employee = {s["employee_id"]: s for s in stats}

        # Resolve "last month with data" by DATE RANGE, not by matching the
        # end date to a month row. Figures live on leaves, so once a month is
        # entered weekly or daily the latest fact sits on a week or a day and
        # would never line up with any month's end date — the column just came
        # back empty for exactly the people who report most often.
        months = list(
            DimPeriod.objects.filter(kind=PeriodKind.MONTH)
            .exclude(start_date=None).exclude(end_date=None)
            .order_by("start_date")
        )

        def month_label_for(day):
            if not day:
                return ""
            for p in months:
                if p.start_date <= day <= p.end_date:
                    return p.label
            return ""

        for m in members:
            s = by_employee.get(m.employee_id, {})
            m.periods_filled = s.get("periods_filled", 0)
            m.total_revenue = s.get("total_revenue") or 0
            m.last_period = month_label_for(s.get("last_seen"))

        return Response(self.get_serializer(members, many=True).data)

    def create(self, request, *args, **kwargs):
        """
        Add someone to this roster — an existing کارشناس by id, or a new one by
        name. Re-adding a person who was deactivated revives that membership
        instead of failing on the unique constraint.
        """
        import uuid

        channel = self._channel()
        self._assert_owner(channel)

        employee_id = request.data.get("employee")
        name = (request.data.get("name") or "").strip()

        if employee_id:
            employee = DimEmployee.objects.filter(pk=employee_id).first()
            if not employee:
                return Response({"detail": "کارشناس پیدا نشد."},
                                status=http_status.HTTP_400_BAD_REQUEST)
        elif name:
            employee = DimEmployee.objects.filter(full_name_fa=name).first()
            if not employee:
                employee = DimEmployee.objects.create(
                    code=f"emp-{uuid.uuid4().hex[:8]}", full_name_fa=name,
                )
        else:
            return Response({"detail": "نام کارشناس را وارد کنید."},
                            status=http_status.HTTP_400_BAD_REQUEST)

        if request.data.get("team"):
            employee.team_id = request.data["team"]
            employee.save(update_fields=["team"])

        member, created = EmployeeChannel.objects.get_or_create(
            employee=employee, channel=channel,
            defaults={"note": request.data.get("note", "")},
        )
        if not created and not member.is_active:
            member.is_active = True
            member.left_at = None
            member.save(update_fields=["is_active", "left_at"])
        return Response(self.get_serializer(member).data,
                        status=http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK)

    def perform_update(self, serializer):
        self._assert_owner(serializer.instance.channel)
        member = serializer.save()
        # The name and team live on the employee, not the membership, but the
        # manager edits them from this one screen.
        emp = member.employee
        changed = []
        name = (self.request.data.get("employee_name") or "").strip()
        if name and name != emp.full_name_fa:
            emp.full_name_fa = name
            changed.append("full_name_fa")
        if "team" in self.request.data:
            emp.team_id = self.request.data["team"] or None
            changed.append("team")
        if changed:
            emp.save(update_fields=changed)

    def destroy(self, request, *args, **kwargs):
        """
        Remove from the roster — but only while the person has no figures in
        this channel. Deleting someone who has sold would strip their history
        out of every past dashboard, so they are deactivated instead: gone
        from the sheet, still in the reports they earned.
        """
        member = self.get_object()
        self._assert_owner(member.channel)
        if FactSalesMonthly.objects.filter(
            employee_id=member.employee_id, channel=member.channel
        ).exists():
            member.is_active = False
            member.left_at = member.left_at or timezone.localdate()
            member.save(update_fields=["is_active", "left_at"])
            return Response(
                {"detail": "این کارشناس سابقه فروش دارد؛ به‌جای حذف، غیرفعال شد.",
                 "deactivated": True},
                status=http_status.HTTP_200_OK,
            )
        member.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="available")
    def available(self, request):
        """کارشناسانی که در این بخش نیستند — برای افزودن از میان افراد موجود."""
        channel = self._channel()
        self._assert_owner(channel)
        taken = EmployeeChannel.objects.filter(channel=channel).values_list("employee_id", flat=True)
        rows = (
            DimEmployee.objects.filter(is_active=True)
            .exclude(id__in=taken)
            .exclude(full_name_fa__in=["", "0"])
            .select_related("team")
            .order_by("full_name_fa")
        )
        return Response([
            {"id": e.id, "name": e.full_name_fa,
             "team": e.team_id, "team_name": e.team.name_fa if e.team else "",
             "channels": list(
                 EmployeeChannel.objects.filter(employee=e).values_list("channel", flat=True)
             )}
            for e in rows
        ])
