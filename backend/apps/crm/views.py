"""
CRM API.

Two families of endpoints:

  1. CRUD viewsets over the CRM records. Their list filtering accepts the very
     same query params the reports emit in `row.drill.params`, which is what
     makes "click a number, see the records behind it" work with no extra
     server code.

  2. Analytics — /reports/<key>/, /dashboard/ and /pipeline/ — built on
     apps.crm.reports.

Write access follows the platform rule already in place for فروش همکار: the
sales_team department owns the data, the CEO reads everything.
"""
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import reports as rpt
from apps.crm.jalali import jalali_month_of, month_bounds, month_label, period_for
from apps.crm.models import (
    Activity, Customer, CustomerFeedback, CustomerGroup, Deal, DealItem,
    DealStageEvent, LeadSource, LostReason, PipelineStage, Product,
    ProductCategory, Tag, Task,
)
from apps.crm.serializers import (
    ActivitySerializer, CustomerDetailSerializer, CustomerFeedbackSerializer,
    CustomerGroupSerializer, CustomerListSerializer, CustomerWriteSerializer,
    DealDetailSerializer, DealItemSerializer, DealListSerializer,
    DealStageEventSerializer, DealWriteSerializer, LeadSourceSerializer,
    LostReasonSerializer, PipelineStageSerializer, ProductCategorySerializer,
    ProductSerializer, TagSerializer, TaskSerializer,
)
from apps.sales.models import DimEmployee, DimProvince


class CrmWritePermission(BasePermission):
    """Read: any authenticated user. Write: the sales-team department, the
    CEO, or a superuser — CRM records belong to فروش همکار."""

    message = "شما مجاز به ویرایش اطلاعات CRM نیستید."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(
            u.is_superuser or u.role == "executive" or u.department == "sales_team"
        )


# --------------------------------------------------------------------------
# Lookup viewsets
# --------------------------------------------------------------------------
class _Base(viewsets.ModelViewSet):
    permission_classes = [CrmWritePermission]


class CustomerGroupViewSet(_Base):
    queryset = CustomerGroup.objects.all()
    serializer_class = CustomerGroupSerializer


class TagViewSet(_Base):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer


class LeadSourceViewSet(_Base):
    queryset = LeadSource.objects.all()
    serializer_class = LeadSourceSerializer


class LostReasonViewSet(_Base):
    queryset = LostReason.objects.all()
    serializer_class = LostReasonSerializer


class ProductCategoryViewSet(_Base):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer


class ProductViewSet(_Base):
    queryset = Product.objects.select_related("category").all()
    serializer_class = ProductSerializer
    filterset_fields = ["category", "is_active", "unit"]


class PipelineStageViewSet(_Base):
    queryset = PipelineStage.objects.all()
    serializer_class = PipelineStageSerializer


# --------------------------------------------------------------------------
# Customer
# --------------------------------------------------------------------------
class CustomerViewSet(_Base):
    queryset = Customer.objects.select_related(
        "group", "province", "owner", "lead_source"
    ).prefetch_related("tags")
    serializer_class = CustomerListSerializer

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return CustomerWriteSerializer
        if self.action == "retrieve":
            return CustomerDetailSerializer
        return CustomerListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params
        f = rpt.Filters.from_query(q)

        # `date_basis` decides which date the window applies to, so a drill
        # from "مشتریان جدید" lands on exactly the customers that were counted.
        basis = q.get("date_basis")
        if basis == "first_won":
            qs = qs.filter(
                first_deal_won_at__gte=rpt._aware(f.start),
                first_deal_won_at__lt=rpt._aware(f.end),
            ) if f.start and f.end else qs.filter(first_deal_won_at__isnull=False)
        elif basis == "first_contact" and f.start and f.end:
            qs = qs.filter(
                first_contact_at__gte=rpt._aware(f.start),
                first_contact_at__lt=rpt._aware(f.end),
            )

        if f.owner:
            qs = qs.filter(owner_id=f.owner)
        if f.group:
            qs = qs.filter(group_id=f.group)
        if f.province:
            qs = qs.filter(province_id=f.province)
        if f.source:
            qs = qs.filter(lead_source_id=f.source)
        if f.tag:
            qs = qs.filter(tags__id=f.tag)
        if q.get("status") in dict(Customer.Status.choices):
            qs = qs.filter(status=q["status"])
        search = (q.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(name_fa__icontains=search)
                | Q(contact_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(mobile__icontains=search)
                | Q(code__icontains=search)
            )
        return qs.distinct()

    def perform_create(self, serializer):
        obj = serializer.save()
        if not obj.code:
            obj.code = f"cust-{obj.pk}"
            obj.save(update_fields=["code"])

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        data = CustomerDetailSerializer(obj).data
        deals = obj.deals.all()
        won = deals.filter(status=Deal.Status.WON)
        data["stats"] = {
            "deals": deals.count(),
            "won": won.count(),
            "lost": deals.filter(status=Deal.Status.LOST).count(),
            "open": deals.filter(status=Deal.Status.OPEN).count(),
            "revenue": float(won.aggregate(s=Sum("amount_rial"))["s"] or 0),
            "profit": float(won.aggregate(s=Sum("profit_rial"))["s"] or 0),
            "activities": obj.activities.count(),
            "calls": obj.activities.filter(kind__in=["call_out", "call_in"]).count(),
            "open_tasks": obj.tasks.filter(done_at__isnull=True).count(),
        }
        return Response(data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """کارنامه مشتری — deals and activities merged into one feed."""
        obj = self.get_object()
        acts = ActivitySerializer(
            obj.activities.select_related("owner", "deal")[:200], many=True
        ).data
        deals = DealListSerializer(
            obj.deals.select_related("owner", "stage", "lost_reason"), many=True
        ).data
        return Response({"activities": acts, "deals": deals})


class CustomerFeedbackViewSet(_Base):
    queryset = CustomerFeedback.objects.select_related("customer", "employee")
    serializer_class = CustomerFeedbackSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        f = rpt.Filters.from_query(self.request.query_params)
        if f.start:
            qs = qs.filter(at__gte=rpt._aware(f.start))
        if f.end:
            qs = qs.filter(at__lt=rpt._aware(f.end))
        if f.owner:
            qs = qs.filter(employee_id=f.owner)
        if f.customer:
            qs = qs.filter(customer_id=f.customer)
        if self.request.query_params.get("unhappy") == "1":
            qs = qs.filter(score__lte=2)
        return qs


# --------------------------------------------------------------------------
# Deal
# --------------------------------------------------------------------------
class DealViewSet(_Base):
    queryset = Deal.objects.select_related(
        "customer", "customer__province", "customer__group", "owner", "stage",
        "lead_source", "lost_reason",
    ).prefetch_related("tags")
    serializer_class = DealListSerializer

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return DealWriteSerializer
        if self.action == "retrieve":
            return DealDetailSerializer
        return DealListSerializer

    def get_queryset(self):
        """
        Accepts the exact params a report row's `drill.params` carries.
        `date_basis` selects which date the window filters on: deals *created*
        in a month (معاملات ورودی) vs deals *closed* in it (فروش موفق).
        """
        q = self.request.query_params
        f = rpt.Filters.from_query(q)
        basis = q.get("date_basis") or (
            "opened" if (q.get("status") or "") == "open" else "closed"
        )
        date_field = "opened_at" if basis == "opened" else "closed_at"
        qs = f.deals(date_field)
        # Open deals have no closed_at; when browsing them, fall back to
        # opened_at so the list is not silently empty.
        if date_field == "closed_at" and q.get("status") == "open":
            qs = f.deals("opened_at")
        search = (q.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(customer__name_fa__icontains=search)
                | Q(code__icontains=search)
            )
        return qs.select_related(
            "customer", "customer__province", "customer__group", "owner",
            "stage", "lead_source", "lost_reason",
        ).distinct()

    def perform_create(self, serializer):
        obj = serializer.save()
        if not obj.opened_at:
            obj.opened_at = timezone.now()
        if not obj.code:
            obj.code = f"deal-{obj.pk}"
        obj.period = period_for(obj.opened_at)
        obj.save(update_fields=["code", "opened_at", "period"])
        DealStageEvent.objects.create(
            deal=obj, from_stage=None, to_stage=obj.stage,
            at=obj.opened_at, by=self.request.user,
        )

    # ---- Actions ---------------------------------------------------------
    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """
        Move a deal to another pipeline stage (kanban drag, or the detail
        page). Writing the stage event here — rather than in a signal — keeps
        the funnel and velocity reports honest, because a stage change that
        did not go through the API cannot silently skip the log.
        """
        deal = self.get_object()
        stage = PipelineStage.objects.filter(pk=request.data.get("stage")).first()
        if not stage:
            return Response({"detail": "مرحله نامعتبر است."}, status=400)

        previous = deal.stage
        now = timezone.now()
        last = deal.stage_events.order_by("-at").first()
        days = max((now - (last.at if last else deal.opened_at)).days, 0)

        deal.stage = stage
        if stage.kind == PipelineStage.Kind.WON:
            deal.status = Deal.Status.WON
            deal.closed_at = now
            deal.close_period = period_for(now)
            deal.lost_reason = None
            cust = deal.customer
            if not cust.first_deal_won_at:
                cust.first_deal_won_at = now
                cust.status = Customer.Status.ACTIVE
                cust.save(update_fields=["first_deal_won_at", "status"])
        elif stage.kind == PipelineStage.Kind.LOST:
            deal.status = Deal.Status.LOST
            deal.closed_at = now
            deal.close_period = period_for(now)
            reason = LostReason.objects.filter(pk=request.data.get("lost_reason")).first()
            deal.lost_reason = reason
            deal.lost_note = request.data.get("lost_note", "")
        else:
            deal.status = Deal.Status.OPEN
            deal.closed_at = None
            deal.close_period = None
        deal.save()

        DealStageEvent.objects.create(
            deal=deal, from_stage=previous, to_stage=stage, at=now,
            by=request.user, days_in_previous=days,
        )
        return Response(DealDetailSerializer(deal).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        deal = self.get_object()
        return Response(
            DealStageEventSerializer(
                deal.stage_events.select_related("from_stage", "to_stage"), many=True
            ).data
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Totals for the current filter — shown above a drill-down list so
        the drawer's numbers visibly reconcile with the chart."""
        qs = self.get_queryset()
        agg = qs.aggregate(
            count=Count("id", distinct=True),
            amount=Sum("amount_rial"),
            profit=Sum("profit_rial"),
            cost=Sum("cost_rial"),
        )
        amount = float(agg["amount"] or 0)
        profit = float(agg["profit"] or 0)
        return Response({
            "count": agg["count"] or 0,
            "amount": amount,
            "profit": profit,
            "cost": float(agg["cost"] or 0),
            "margin_pct": round(profit / amount * 100, 1) if amount else 0.0,
        })


class DealItemViewSet(_Base):
    queryset = DealItem.objects.select_related("product", "deal")
    serializer_class = DealItemSerializer
    filterset_fields = ["deal", "product"]

    def perform_create(self, serializer):
        item = serializer.save()
        item.deal.recalculate()

    def perform_update(self, serializer):
        item = serializer.save()
        item.deal.recalculate()

    def perform_destroy(self, instance):
        deal = instance.deal
        instance.delete()
        deal.recalculate()


# --------------------------------------------------------------------------
# Activity / Task
# --------------------------------------------------------------------------
class ActivityViewSet(_Base):
    queryset = Activity.objects.select_related("customer", "owner", "deal")
    serializer_class = ActivitySerializer

    def get_queryset(self):
        q = self.request.query_params
        f = rpt.Filters.from_query(q)
        # Filters already understands the pseudo-kind "call" (both directions).
        qs = f.activities()
        deal_id = q.get("deal")
        if deal_id:
            qs = qs.filter(deal_id=deal_id)
        return qs.select_related("customer", "owner", "deal")

    def perform_create(self, serializer):
        obj = serializer.save()
        obj.period = period_for(obj.at)
        obj.save(update_fields=["period"])
        Customer.objects.filter(pk=obj.customer_id).update(last_activity_at=obj.at)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.get_queryset()
        total = qs.count()
        success = qs.filter(result=Activity.Result.SUCCESS).count()
        return Response({
            "count": total,
            "success": success,
            "success_rate": round(success / total * 100, 1) if total else 0.0,
            "customers": qs.values("customer_id").distinct().count(),
            "minutes": qs.aggregate(s=Sum("duration_min"))["s"] or 0,
        })


class TaskViewSet(_Base):
    queryset = Task.objects.select_related("customer", "owner", "deal")
    serializer_class = TaskSerializer
    filterset_fields = ["owner", "customer", "deal", "kind"]

    def get_queryset(self):
        qs = super().get_queryset()
        state = self.request.query_params.get("state")
        if state == "open":
            qs = qs.filter(done_at__isnull=True)
        elif state == "overdue":
            qs = qs.filter(done_at__isnull=True, due_at__lt=timezone.now())
        elif state == "done":
            qs = qs.filter(done_at__isnull=False)
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        task.done_at = timezone.now()
        task.save(update_fields=["done_at"])
        return Response(TaskSerializer(task).data)


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------
class CrmDashboardView(APIView):
    """نشانگر — every widget of the CRM home screen in one response."""

    @extend_schema(
        parameters=[
            OpenApiParameter("period", int), OpenApiParameter("owner", int),
            OpenApiParameter("date_from", str), OpenApiParameter("date_to", str),
        ]
    )
    def get(self, request):
        f = rpt.Filters.from_query(request.query_params)
        data = rpt.dashboard(f)
        data["window"] = {
            "start": f.start.isoformat() if f.start else None,
            "end": f.end.isoformat() if f.end else None,
        }
        return Response(data)


class CrmReportView(APIView):
    """گزارش‌ها — /api/crm/reports/<key>/?axis=time|user|product|…"""

    def get(self, request, key: str):
        if key not in rpt.REPORTS:
            return Response(
                {"detail": f"گزارش «{key}» تعریف نشده است."},
                status=status.HTTP_404_NOT_FOUND,
            )
        f = rpt.Filters.from_query(request.query_params)
        axis = request.query_params.get("axis") or ""
        data = rpt.run_report(key, f, axis)
        data["axis_labels"] = rpt.AXIS_LABELS
        data["window"] = {
            "start": f.start.isoformat() if f.start else None,
            "end": f.end.isoformat() if f.end else None,
        }
        return Response(data)


class CrmReportIndexView(APIView):
    """The report catalogue, so the UI builds its menu from the server."""

    def get(self, request):
        return Response({
            "reports": [
                {"key": k, "title": t, "axes": a} for k, (_fn, t, a) in rpt.REPORTS.items()
            ],
            "axis_labels": rpt.AXIS_LABELS,
        })


class PipelineBoardView(APIView):
    """کاریز فروش — the kanban board: stages with their open deals."""

    def get(self, request):
        f = rpt.Filters.from_query(request.query_params)
        qs = Deal.objects.filter(channel=f.channel, status=Deal.Status.OPEN)
        if f.owner:
            qs = qs.filter(owner_id=f.owner)
        if f.group:
            qs = qs.filter(customer__group_id=f.group)
        if f.province:
            qs = qs.filter(customer__province_id=f.province)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(customer__name_fa__icontains=search)
            )
        qs = qs.select_related("customer", "owner", "stage")

        by_stage: dict[int, list] = {}
        for deal in qs:
            by_stage.setdefault(deal.stage_id, []).append(deal)

        columns = []
        for st in PipelineStage.objects.filter(is_active=True).order_by("order"):
            deals = by_stage.get(st.id, [])
            columns.append({
                "id": st.id,
                "name_fa": st.name_fa,
                "kind": st.kind,
                "order": st.order,
                "probability_pct": st.probability_pct,
                "count": len(deals),
                "amount": float(sum(d.amount_rial for d in deals)),
                "weighted": float(sum(d.weighted_rial for d in deals)),
                "deals": DealListSerializer(deals, many=True).data,
            })
        return Response({"columns": columns})


class CrmOptionsView(APIView):
    """Every filter dropdown the CRM UI needs, in one request."""

    def get(self, request):
        # The month list is served rather than computed in the browser so the
        # Jalali calendar lives in exactly one place.
        jy, jm = jalali_month_of(timezone.localdate())
        months = []
        for _ in range(24):
            start, end = month_bounds(jy, jm)
            months.append({
                "key": f"{jy}-{jm}", "label": month_label(jy, jm),
                "year": jy, "month": jm,
                "date_from": start.isoformat(),
                "date_to": (end - timedelta(days=1)).isoformat(),
            })
            jm -= 1
            if jm < 1:
                jm, jy = 12, jy - 1

        return Response({
            "months": months,
            "provinces": [
                {"id": p.id, "name_fa": p.name_fa}
                for p in DimProvince.objects.all()
            ],
            # The employee dimension carries a placeholder row with no real
            # name; it must not show up in a filter dropdown.
            "employees": [
                {"id": e.id, "name": e.full_name_fa,
                 "team": e.team.name_fa if e.team else ""}
                for e in DimEmployee.objects.select_related("team")
                .filter(is_active=True)
                .exclude(full_name_fa__in=["", "0"])
            ],
            "groups": CustomerGroupSerializer(CustomerGroup.objects.all(), many=True).data,
            "sources": LeadSourceSerializer(LeadSource.objects.all(), many=True).data,
            "reasons": LostReasonSerializer(LostReason.objects.all(), many=True).data,
            "stages": PipelineStageSerializer(
                PipelineStage.objects.filter(is_active=True), many=True
            ).data,
            "products": ProductSerializer(
                Product.objects.filter(is_active=True).select_related("category"),
                many=True,
            ).data,
            "tags": TagSerializer(Tag.objects.all(), many=True).data,
            "activity_kinds": [
                {"code": c, "label": l} for c, l in Activity.Kind.choices
            ],
            "activity_results": [
                {"code": c, "label": l} for c, l in Activity.Result.choices
            ],
        })
