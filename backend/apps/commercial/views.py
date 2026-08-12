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
    PaymentTerm,
    PurchaseOrder,
    PurchaseRequest,
    Quote,
    QuoteReason,
    Sample,
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
    PaymentTermSerializer,
    PurchaseOrderSerializer,
    PurchaseRequestListSerializer,
    PurchaseRequestSerializer,
    QuoteReasonSerializer,
    QuoteSerializer,
    SampleSerializer,
    SampleVerdictSerializer,
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
    filterset_fields = ["is_active", "origin"]
    search_fields = ["code", "name_fa", "name_en", "contact_name", "mobile",
                     "phone", "email", "activity", "country", "note"]
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
            # Not `quote_count`: PurchaseRequest already has a property of that
            # name, and Django assigns an annotation by setattr — which on a
            # property with no setter raises, so the whole list 500s as soon
            # as there is a single row to serialise.
            return qs.annotate(quotes_n=Count("quotes"))
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


class PaymentTermViewSet(viewsets.ModelViewSet):
    """شرایط پرداخت — a short list the department maintains itself."""

    queryset = PaymentTerm.objects.all()
    serializer_class = PaymentTermSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["is_active"]
    ordering_fields = ["sort_order", "days", "advance_pct", "name_fa"]

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        serializer.save(
            code=code or _unique_code(
                PaymentTerm, serializer.validated_data.get("name_fa", "")
            ),
        )

    def perform_destroy(self, instance):
        if instance.quotes.exists() or instance.orders.exists():
            raise ValidationError({
                "detail": "این شرایط پرداخت روی استعلام یا سفارش ثبت شده و "
                          "حذف نمی‌شود. می‌توانید غیرفعالش کنید.",
            })
        instance.delete()


class SampleViewSet(viewsets.ModelViewSet):
    """نمونه — asking for one, receiving it, and deciding on it."""

    queryset = Sample.objects.select_related(
        "supplier", "material", "request", "reason", "decided_by"
    )
    serializer_class = SampleSerializer
    permission_classes = [CommercialAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "supplier", "material", "request"]
    search_fields = [
        "sample_no", "spec", "lab_note", "note",
        "supplier__name_fa", "material__name_fa",
    ]
    ordering_fields = ["requested_on", "received_on", "decided_on", "created_at"]

    def perform_create(self, serializer):
        sample = serializer.save(created_by=self.request.user)
        audit_log(self.request.user, sample, AuditLog.Action.CREATE)

    @extend_schema(request=SampleVerdictSerializer, responses=SampleSerializer)
    @action(detail=True, methods=["post"])
    def verdict(self, request, pk=None):
        """
        تایید یا رد نمونه.

        Its own endpoint rather than a PATCH on `status`, because a verdict is
        four facts that must land together — the outcome, the date, who
        decided, and (on a rejection) why. Written one field at a time, a
        sample spends a moment «رد شد» with no reason attached, and that is
        the state someone screenshots.
        """
        sample = self.get_object()
        payload = SampleVerdictSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        approve = data["approve"]
        if not approve and not data.get("reason"):
            raise ValidationError({
                "reason": "برای رد نمونه، دلیل رد الزامی است.",
            })

        with transaction.atomic():
            sample.status = (
                Sample.Status.APPROVED if approve else Sample.Status.REJECTED
            )
            sample.decided_on = data.get("decided_on") or date.today()
            sample.decided_by = request.user
            # A reason belongs to a rejection. Keeping the old one on an
            # approval would leave «تایید شد — گرماژ خارج از تلورانس» on screen.
            sample.reason = None if approve else data["reason"]
            if data.get("lab_note"):
                sample.lab_note = data["lab_note"]
            sample.save()

        audit_log(request.user, sample, AuditLog.Action.UPDATE)
        return Response(SampleSerializer(sample).data)


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


def _seen_values(model, field: str, limit: int = 60) -> list[str]:
    """
    The values already typed into a free-text field, commonest first.

    Frequency order rather than alphabetical: the point of the list is that
    the answer someone needs is usually the one they gave last time, and
    «شهید رجایی» should not sit twenty rows below a port used once in 1403.
    """
    rows = (
        model.objects.exclude(**{field: ""})
        .exclude(**{f"{field}__isnull": True})
        .values(field)
        .annotate(n=Count("id"))
        .order_by("-n", field)[:limit]
    )
    return [row[field] for row in rows]


class SuggestionsView(APIView):
    """
    What has been typed into each free-text field before.

    کشور, برند, شرکت حمل and بندر are not lookup tables and should not become
    them — the department must be able to write a port nobody has used yet
    without asking anyone to add a row first. But left as bare text inputs
    they drift: «شهید رجایی» and «شهید رجائی» become two ports, and every
    report that groups by port quietly splits in half.

    Suggesting the existing values costs one query per field and removes most
    of that drift, while still letting anything new through.
    """

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        from apps.commercial.models import ForeignOrder, Shipment

        return Response({
            "requester_units": _seen_values(PurchaseRequest, "requester_unit"),
            "activities": _seen_values(Supplier, "activity"),
            "countries": sorted(set(
                _seen_values(Supplier, "country") + _seen_values(ForeignOrder, "country")
            )),
            "brands": _seen_values(ForeignOrder, "brand"),
            "goods": _seen_values(ForeignOrder, "goods_desc"),
            "carriers": _seen_values(Shipment, "carrier"),
            "origin_ports": _seen_values(Shipment, "origin_port"),
            "destination_ports": _seen_values(Shipment, "destination_port"),
        })


def _int(raw) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None
