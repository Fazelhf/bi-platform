"""Commercial API: the buying loop, the price file, and the reports over it."""
from __future__ import annotations

from datetime import date, datetime

from django.db import transaction
from django.db.models import Count
from django.utils.text import slugify
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.commercial.models import (
    Material,
    MaterialCategory,
    PurchaseOrder,
    PurchaseRequest,
    Quote,
    QuoteReason,
    Supplier,
)
from apps.commercial.permissions import (
    CommercialAccess,
    assert_commercial_visible,
    is_commercial,
)
from apps.commercial.serializers import (
    AwardSerializer,
    MaterialCategorySerializer,
    MaterialSerializer,
    PurchaseOrderSerializer,
    PurchaseRequestListSerializer,
    PurchaseRequestSerializer,
    QuoteReasonSerializer,
    QuoteSerializer,
    SupplierSerializer,
    UnitChoiceSerializer,
)
from apps.commercial.services import (
    consumption,
    forecast,
    price_history,
    purchase_report,
    supplier_stats,
)
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog, DimPeriod, PeriodKind
from apps.core import jalali


def _unique_code(model, source: str, field: str = "code") -> str:
    """
    Derive a URL-safe code from a Persian name.

    `slugify` strips Persian entirely, so a name like «نوار شیرینگ» would give
    an empty slug and every material would collide on "". Fall back to the
    model's own name with a counter — the code is an identifier, not a label,
    and the Persian name is what people actually read.
    """
    stem = slugify(source, allow_unicode=True) or model.__name__.lower()
    candidate = stem
    n = 2
    while model.objects.filter(**{field: candidate}).exists():
        candidate = f"{stem}-{n}"
        n += 1
    return candidate[:50]


def _month_period(on: date | None) -> DimPeriod | None:
    """
    The month row this date belongs to, if the period tree has one.

    Never creates it. The period tree is administered deliberately, and a
    purchase quietly inventing a month would put a row on the CEO's calendar
    that nobody planned.
    """
    if not on:
        return None
    jy, jm, _ = jalali.from_gregorian(on)
    return DimPeriod.objects.filter(
        kind=PeriodKind.MONTH, jalali_year=jy, jalali_month=jm
    ).first()


def _as_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError({"detail": "تاریخ معتبر نیست."})


class MaterialCategoryViewSet(viewsets.ModelViewSet):
    queryset = MaterialCategory.objects.all()
    serializer_class = MaterialCategorySerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["is_active"]
    search_fields = ["code", "name_fa"]

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        serializer.save(
            code=code or _unique_code(
                MaterialCategory, serializer.validated_data.get("name_fa", "")
            )
        )

    def perform_destroy(self, instance):
        if instance.materials.exists():
            raise ValidationError({
                "detail": "این دسته کالا دارد؛ به‌جای حذف، غیرفعالش کنید."
            })
        super().perform_destroy(instance)


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.select_related("category")
    serializer_class = MaterialSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["category", "unit", "is_active"]
    search_fields = ["code", "name_fa", "note"]
    ordering_fields = ["name_fa", "created_at"]

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        material = serializer.save(
            code=code or _unique_code(
                Material, serializer.validated_data.get("name_fa", "")
            )
        )
        audit_log(self.request.user, material, AuditLog.Action.CREATE)

    def perform_destroy(self, instance):
        # PROTECT on the FKs would raise a database error the browser shows as
        # a 500; refusing here says what to do instead.
        if instance.orders.exists() or instance.requests.exists():
            raise ValidationError({
                "detail": "این کالا در خرید یا درخواست استفاده شده؛ "
                          "به‌جای حذف، غیرفعالش کنید."
            })
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """تاریخچه قیمت — every quote and purchase this material has drawn."""
        assert_commercial_visible(request.user)
        return Response(price_history.for_material(self.get_object()))

    # The method names carry a `_report` suffix only so they do not shadow the
    # service modules of the same name at a glance; the URL keeps the plain word.
    @action(detail=True, methods=["get"], url_path="consumption")
    def consumption_report(self, request, pk=None):
        """گزارش مصرف — monthly quantity and spend."""
        assert_commercial_visible(request.user)
        return Response(consumption.monthly(self.get_object()))

    @action(detail=True, methods=["get"], url_path="forecast")
    def forecast_report(self, request, pk=None):
        assert_commercial_visible(request.user)
        return Response(
            forecast.for_material(
                self.get_object(), horizon=request.query_params.get("horizon", 3)
            )
        )


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active"]
    search_fields = ["code", "name_fa", "contact_name", "mobile", "phone",
                     "email", "activity", "note"]
    ordering_fields = ["name_fa", "created_at"]

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        supplier = serializer.save(
            created_by=self.request.user,
            code=code or _unique_code(
                Supplier, serializer.validated_data.get("name_fa", "")
            ),
        )
        audit_log(self.request.user, supplier, AuditLog.Action.CREATE)

    def perform_destroy(self, instance):
        if instance.orders.exists() or instance.quotes.exists():
            raise ValidationError({
                "detail": "این تامین‌کننده سابقه استعلام یا خرید دارد؛ "
                          "به‌جای حذف، غیرفعالش کنید."
            })
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Everything this supplier quoted and everything it delivered."""
        assert_commercial_visible(request.user)
        return Response(supplier_stats.history(self.get_object()))


class QuoteReasonViewSet(viewsets.ModelViewSet):
    """Reasons are data — the department adds its own without a deploy."""

    queryset = QuoteReason.objects.all()
    serializer_class = QuoteReasonSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["kind", "is_active"]
    search_fields = ["code", "name_fa"]

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        serializer.save(
            code=code or _unique_code(
                QuoteReason, serializer.validated_data.get("name_fa", "")
            )
        )

    def perform_destroy(self, instance):
        if instance.quotes.exists():
            raise ValidationError({
                "detail": "این دلیل روی استعلام‌های ثبت‌شده نشسته؛ "
                          "به‌جای حذف، غیرفعالش کنید."
            })
        super().perform_destroy(instance)


class PurchaseRequestViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequest.objects.select_related("material", "period")
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "material", "period"]
    search_fields = ["request_no", "requester_unit", "note", "material__name_fa"]
    ordering_fields = ["requested_on", "needed_by", "created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return PurchaseRequestListSerializer
        return PurchaseRequestSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            return qs.annotate(quote_count=Count("quotes"))
        return qs.prefetch_related("quotes__supplier", "quotes__reason")

    def perform_create(self, serializer):
        requested_on = serializer.validated_data.get("requested_on")
        instance = serializer.save(
            created_by=self.request.user,
            period=serializer.validated_data.get("period")
            or _month_period(requested_on),
        )
        audit_log(self.request.user, instance, AuditLog.Action.CREATE)

    def perform_destroy(self, instance):
        if instance.orders.exists():
            raise ValidationError({
                "detail": "این درخواست سفارش خرید دارد؛ "
                          "وضعیتش را «لغو شده» کنید."
            })
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()

    @extend_schema(request=AwardSerializer, responses=PurchaseRequestSerializer)
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def award(self, request, pk=None):
        """
        انتخاب تامین‌کننده — one winner, with a reason on every quote.

        Written in one transaction across the whole استعلام rather than as a
        PATCH per quote: a half-applied award would leave two winners, and the
        supplier win-rate statistics read straight off these flags.
        """
        if not is_commercial(request.user):
            raise ValidationError({"detail": "فقط واحد بازرگانی می‌تواند ثبت کند."})

        purchase_request = self.get_object()
        payload = AwardSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        winner = payload.validated_data["quote"]

        if winner.request_id != purchase_request.id:
            raise ValidationError({
                "quote": "این استعلام متعلق به درخواست دیگری است."
            })

        rejections = {
            int(item["quote"]): item
            for item in payload.validated_data.get("rejections", [])
            if item.get("quote")
        }

        for quote in purchase_request.quotes.all():
            if quote.id == winner.id:
                quote.is_selected = True
                quote.reason = payload.validated_data.get("reason")
                quote.decision_note = payload.validated_data.get("decision_note", "")
            else:
                quote.is_selected = False
                item = rejections.get(quote.id)
                if item:
                    reason_id = item.get("reason")
                    quote.reason = (
                        QuoteReason.objects.filter(
                            pk=reason_id, kind=QuoteReason.Kind.LOSE
                        ).first()
                        if reason_id else None
                    )
                    quote.decision_note = str(item.get("decision_note", ""))[:300]
            quote.save(update_fields=["is_selected", "reason", "decision_note"])

        purchase_request.status = PurchaseRequest.Status.AWARDED
        purchase_request.save(update_fields=["status", "updated_at"])

        audit_log(request.user, purchase_request, AuditLog.Action.UPDATE,
                  {"award": {"before": None, "after": winner.supplier.name_fa}})

        return Response(PurchaseRequestSerializer(purchase_request).data)


class QuoteViewSet(viewsets.ModelViewSet):
    queryset = Quote.objects.select_related(
        "supplier", "request", "request__material", "reason"
    )
    serializer_class = QuoteSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["request", "supplier", "is_selected"]
    ordering_fields = ["unit_price_rial", "delivery_days", "quoted_on"]

    def perform_create(self, serializer):
        quote = serializer.save()
        # A request that has drawn its first price is no longer merely "open".
        if quote.request.status == PurchaseRequest.Status.OPEN:
            quote.request.status = PurchaseRequest.Status.QUOTING
            quote.request.save(update_fields=["status", "updated_at"])


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related(
        "supplier", "material", "request", "period"
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # `request` is here so the استعلام page can ask for its own orders. Without
    # it DRF ignores the parameter rather than erroring, and that page silently
    # listed every order in the system as if they all belonged to it.
    filterset_fields = ["status", "material", "supplier", "period", "request"]
    search_fields = ["order_no", "note", "material__name_fa", "supplier__name_fa"]
    ordering_fields = ["ordered_on", "delivered_on", "quantity", "unit_price_rial"]

    def perform_create(self, serializer):
        ordered_on = serializer.validated_data.get("ordered_on")
        order = serializer.save(
            created_by=self.request.user,
            period=serializer.validated_data.get("period") or _month_period(ordered_on),
        )
        if order.request and order.request.status != PurchaseRequest.Status.CANCELLED:
            order.request.status = PurchaseRequest.Status.ORDERED
            order.request.save(update_fields=["status", "updated_at"])
        audit_log(self.request.user, order, AuditLog.Action.CREATE,
                  {"total": {"before": None, "after": str(order.total_rial)}})

    def perform_update(self, serializer):
        before = serializer.instance.status
        order = serializer.save()
        if order.period_id is None:
            order.period = _month_period(order.ordered_on)
            order.save(update_fields=["period"])
        if before != order.status:
            audit_log(self.request.user, order, AuditLog.Action.UPDATE,
                      {"status": {"before": before, "after": order.status}})

    def perform_destroy(self, instance):
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()


class DashboardView(APIView):
    """داشبورد بازرگانی — this month at a glance."""

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        data = purchase_report.dashboard(today)
        data["forecast"] = forecast.overview()
        data["can_edit"] = is_commercial(request.user)
        return Response(data)


class PurchaseReportView(APIView):
    """گزارش خرید — the filterable list plus its breakdowns."""

    permission_classes = [CommercialAccess]

    @extend_schema(
        parameters=[
            OpenApiParameter("material", int),
            OpenApiParameter("supplier", int),
            OpenApiParameter("status", str),
            OpenApiParameter("from", str, description="YYYY-MM-DD"),
            OpenApiParameter("to", str, description="YYYY-MM-DD"),
        ],
        responses=dict,
    )
    def get(self, request):
        assert_commercial_visible(request.user)
        params = request.query_params
        return Response(purchase_report.report(
            material=_int(params.get("material")),
            supplier=_int(params.get("supplier")),
            status=params.get("status") or None,
            date_from=_as_date(params.get("from")),
            date_to=_as_date(params.get("to")),
        ))


class SupplierReportView(APIView):
    """تحلیل تامین‌کنندگان — the ranked analytics grid."""

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        return Response({"rows": supplier_stats.table()})


class PriceIncreaseView(APIView):
    """گزارش افزایش قیمت — what got more expensive, worst first."""

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        return Response({"rows": price_history.increases()})


class MonthlySpendView(APIView):
    """Total purchase spend per month — the dashboard and reports chart."""

    permission_classes = [CommercialAccess]

    @extend_schema(parameters=[OpenApiParameter("months", int)], responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        months = _int(request.query_params.get("months")) or 12
        return Response({"rows": purchase_report.monthly_spend(months=months)})


class ForecastOverviewView(APIView):
    """پیش‌بینی — next months' need across every material."""

    permission_classes = [CommercialAccess]

    @extend_schema(parameters=[OpenApiParameter("horizon", int)], responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        horizon = _int(request.query_params.get("horizon")) or 3
        return Response({"rows": forecast.overview(horizon=horizon)})


class UnitsView(APIView):
    """The unit list, so no form keeps its own copy of the model's choices."""

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"units": UnitChoiceSerializer.all()})


def _int(raw) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None
