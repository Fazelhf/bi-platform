"""بازرگانی خارجی API: the import pipeline, the queue, and what it all costs."""
from __future__ import annotations

from datetime import date, datetime

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.commercial.models import (
    Bank,
    Currency,
    ForeignOrder,
    FxRate,
    OrderEvent,
    RateKind,
    Shipment,
    ShipmentCost,
)
from apps.commercial.permissions import (
    CommercialAccess,
    ForeignAccess,
    assert_commercial_visible,
    assert_foreign_visible,
    is_foreign,
)
from apps.commercial.serializers_foreign import (
    BankSerializer,
    ForeignOrderDetailSerializer,
    ForeignOrderSerializer,
    FxRateSerializer,
    OrderEventSerializer,
    ShipmentCostSerializer,
    ShipmentSerializer,
)
from apps.commercial.services import (
    allocation_queue,
    demurrage,
    domestic_cards,
    foreign_alerts,
    foreign_cards,
    foreign_dashboard,
    full_report,
    fx,
    history,
    payments,
    stalled,
    workbench,
)
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog


def _as_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError({"detail": "تاریخ معتبر نیست."})


def _unique_code(model, source: str) -> str:
    from django.utils.text import slugify

    stem = slugify(source, allow_unicode=True) or model.__name__.lower()
    candidate, n = stem, 2
    while model.objects.filter(code=candidate).exists():
        candidate = f"{stem}-{n}"
        n += 1
    return candidate[:50]


class BankViewSet(viewsets.ModelViewSet):
    queryset = Bank.objects.all()
    serializer_class = BankSerializer
    permission_classes = [ForeignAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["is_active"]
    search_fields = ["code", "name_fa", "note"]

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        serializer.save(
            code=code or _unique_code(Bank, serializer.validated_data.get("name_fa", ""))
        )

    def perform_destroy(self, instance):
        if instance.orders.exists():
            raise ValidationError({
                "detail": "این بانک پرونده ثبت‌شده دارد؛ به‌جای حذف، غیرفعالش کنید."
            })
        super().perform_destroy(instance)


class FxRateViewSet(viewsets.ModelViewSet):
    """نرخ ارز — typed by hand here; the feed writes through the sync command."""

    queryset = FxRate.objects.all()
    serializer_class = FxRateSerializer
    permission_classes = [ForeignAccess]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["currency", "kind", "on_date"]
    ordering_fields = ["on_date", "rate_rial"]

    def perform_create(self, serializer):
        # Anything entered through the API is a human deciding a number, and
        # the sync deliberately refuses to overwrite those.
        rate = serializer.save(is_manual=True, source="")
        audit_log(self.request.user, rate, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        rate = serializer.save(is_manual=True)
        audit_log(self.request.user, rate, AuditLog.Action.UPDATE)

    @action(detail=False, methods=["get"])
    def board(self, request):
        """The six-rate grid as of a date."""
        assert_foreign_visible(request.user)
        on = _as_date(request.query_params.get("on")) or date.today()
        return Response({
            "on": on.isoformat(),
            "rows": fx.board(on),
            "currencies": [
                {"value": v, "label": l} for v, l in Currency.choices
            ],
            "kinds": [{"value": v, "label": l} for v, l in RateKind.choices],
            "provider": bool(fx.get_provider()),
        })

    @action(detail=False, methods=["get"])
    def history(self, request):
        assert_foreign_visible(request.user)
        currency = request.query_params.get("currency") or Currency.USD
        kind = request.query_params.get("kind") or RateKind.CENTRE
        return Response({
            "currency": currency,
            "kind": kind,
            "rows": fx.history(currency, kind),
        })

    @action(detail=False, methods=["post"])
    def sync(self, request):
        """Pull from the configured source now, rather than waiting for cron."""
        if not is_foreign(request.user):
            raise ValidationError({"detail": "فقط واحد بازرگانی خارجی می‌تواند اجرا کند."})
        return Response(fx.sync(_as_date(request.data.get("on"))))


class ForeignOrderViewSet(viewsets.ModelViewSet):
    queryset = ForeignOrder.objects.select_related("bank", "supplier", "owner")
    permission_classes = [ForeignAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "bank", "supplier", "currency", "country"]
    search_fields = [
        "file_no", "pi_no", "registration_no", "statistical_no",
        "goods_desc", "brand", "note",
    ]
    ordering_fields = ["registered_on", "queued_on", "amount", "created_at"]

    def get_serializer_class(self):
        if self.action in {"retrieve", "award"}:
            return ForeignOrderDetailSerializer
        return ForeignOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "retrieve":
            return qs.prefetch_related("shipments__costs", "events")
        return qs.prefetch_related("events")

    def perform_create(self, serializer):
        order = serializer.save(created_by=self.request.user)
        audit_log(self.request.user, order, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        before = serializer.instance.status
        order = serializer.save()
        if before != order.status:
            # A status change is an action, so it lands on the timeline too —
            # otherwise moving a file forward would leave it looking stalled.
            OrderEvent.objects.create(
                order=order, at=date.today(),
                title=f"وضعیت به «{order.get_status_display()}» تغییر کرد",
                created_by=self.request.user,
            )
            audit_log(self.request.user, order, AuditLog.Action.UPDATE,
                      {"status": {"before": before, "after": order.status}})

    def perform_destroy(self, instance):
        if instance.shipments.exists():
            raise ValidationError({
                "detail": "این پرونده محموله ثبت‌شده دارد؛ وضعیتش را «لغو شده» کنید."
            })
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()

    @extend_schema(request=OrderEventSerializer, responses=OrderEventSerializer)
    @action(detail=True, methods=["post"], url_path="events")
    def add_event(self, request, pk=None):
        """Log an action — or a reason nothing is happening."""
        if not is_foreign(request.user):
            raise ValidationError({"detail": "فقط واحد بازرگانی خارجی می‌تواند ثبت کند."})
        order = self.get_object()
        serializer = OrderEventSerializer(data={**request.data, "order": order.id})
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=201)


class ShipmentViewSet(viewsets.ModelViewSet):
    queryset = Shipment.objects.select_related("order").prefetch_related("costs")
    serializer_class = ShipmentSerializer
    permission_classes = [ForeignAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "order", "carrier"]
    search_fields = [
        "bl_no", "container_no", "carrier", "goods_desc",
        "order__pi_no", "order__file_no",
    ]
    ordering_fields = ["eta", "etd", "arrived_on", "weight_ton"]

    def perform_create(self, serializer):
        shipment = serializer.save()
        audit_log(self.request.user, shipment, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        before = serializer.instance.status
        shipment = serializer.save()
        if before != shipment.status:
            audit_log(self.request.user, shipment, AuditLog.Action.UPDATE,
                      {"status": {"before": before, "after": shipment.status}})


class ShipmentCostViewSet(viewsets.ModelViewSet):
    queryset = ShipmentCost.objects.select_related("shipment")
    serializer_class = ShipmentCostSerializer
    permission_classes = [ForeignAccess]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["shipment", "kind", "is_estimate"]


class ForeignDashboardView(APIView):
    """داشبورد بازرگانی خارجی."""

    permission_classes = [ForeignAccess]

    @extend_schema(parameters=[OpenApiParameter("on", str)], responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        data = foreign_dashboard.build(today)
        data["can_edit"] = is_foreign(request.user)
        return Response(data)


class AllocationQueueView(APIView):
    """صف تخصیص ارز، به تفکیک بانک."""

    permission_classes = [ForeignAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(allocation_queue.build(today))


class StalledOrdersView(APIView):
    """سفارش‌های راکد."""

    permission_classes = [ForeignAccess]

    @extend_schema(parameters=[OpenApiParameter("min_days", int)], responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        raw = request.query_params.get("min_days")
        try:
            min_days = int(raw) if raw not in (None, "") else 0
        except (TypeError, ValueError):
            min_days = 0
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(stalled.build(min_days=min_days, today=today))


class DemurrageView(APIView):
    """دموراژ و انبارداری، کانتینر به کانتینر."""

    permission_classes = [ForeignAccess]

    @extend_schema(parameters=[OpenApiParameter("accruing", bool)], responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        only = str(request.query_params.get("accruing", "")).lower() in {"1", "true"}
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(demurrage.build(only_accruing=only, today=today))


class ForeignAlertsView(APIView):
    """هشدارها — فقط چیزهایی که امروز می‌شود برایشان کاری کرد."""

    permission_classes = [ForeignAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response({"rows": foreign_alerts.build(today)})


class WorkbenchView(APIView):
    """میز کار — files that need a person today, grouped by why."""

    permission_classes = [ForeignAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        data = workbench.build(today)
        # The rate strip lives here rather than on its own page: it is
        # reference material someone glances at, not a place they work.
        data["rates"] = fx.board(today)
        data["can_edit"] = is_foreign(request.user)
        return Response(data)


class PaymentsView(APIView):
    """پرداخت‌ها — outstanding to the seller, and the interest on lateness."""

    permission_classes = [ForeignAccess]

    @extend_schema(parameters=[OpenApiParameter("outstanding", bool)], responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        only = str(request.query_params.get("outstanding", "")).lower() in {"1", "true"}
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(payments.build(today, outstanding_only=only))


class HistoryView(APIView):
    """تاریخچه — files finished in a Jalali year, and how long they took."""

    permission_classes = [ForeignAccess]

    @extend_schema(parameters=[OpenApiParameter("year", int)], responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        raw = request.query_params.get("year")
        try:
            year = int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(history.build(year=year, today=today))


class ForeignCardsView(APIView):
    """
    داشبورد بازرگانی خارجی — each figure with the rows behind it.

    The breakdown ships with the number rather than being fetched on click, so
    a panel can never show a list that disagrees with the headline it opened
    from.
    """

    permission_classes = [ForeignAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_foreign_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(foreign_cards.build(today))


class DomesticCardsView(APIView):
    """داشبورد بازرگانی داخلی — each figure with the rows behind it."""

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(domestic_cards.build(today))


class FullReportView(APIView):
    """گزارش کامل بازرگانی — both halves in tables, every row openable."""

    permission_classes = [CommercialAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        assert_commercial_visible(request.user)
        today = _as_date(request.query_params.get("on")) or date.today()
        return Response(full_report.build(today))


class ForeignOptionsView(APIView):
    """Choice lists, so no form keeps its own copy of the model's."""

    permission_classes = [ForeignAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({
            "currencies": [{"value": v, "label": l} for v, l in Currency.choices],
            "rate_kinds": [{"value": v, "label": l} for v, l in RateKind.choices],
            "order_statuses": [
                {"value": v, "label": l} for v, l in ForeignOrder.Status.choices
            ],
            "shipment_statuses": [
                {"value": v, "label": l} for v, l in Shipment.Status.choices
            ],
            "cost_kinds": [
                {"value": v, "label": l} for v, l in ShipmentCost.Kind.choices
            ],
        })
