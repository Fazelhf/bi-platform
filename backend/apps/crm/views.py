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
from decimal import Decimal

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import merge as crm_merge, reports as rpt
from apps.crm.jalali import jalali_month_of, month_bounds, month_label, period_for
from apps.crm.models import (
    CustomerMatchCandidate, Dataset, SalesInvoice,
    Activity, Customer, CustomerFeedback, CustomerGroup, Deal, DealItem,
    DealStageEvent, LeadSource, LostReason, PipelineStage, Product,
    ProductCategory, Tag, Task,
)
from apps.crm.serializers import (
    MatchCandidateSerializer, SalesInvoiceSerializer,
    ActivitySerializer, CustomerDetailSerializer, CustomerFeedbackSerializer,
    CustomerGroupSerializer, CustomerListSerializer, CustomerWriteSerializer,
    DealDetailSerializer, DealItemSerializer, DealListSerializer,
    DealStageEventSerializer, DealWriteSerializer, LeadSourceSerializer,
    LostReasonSerializer, PipelineStageSerializer, ProductCategorySerializer,
    ProductSerializer, TagSerializer, TaskSerializer,
)
from apps.sales.models import DimEmployee, DimProvince, SalesChannel


def employee_for(user) -> DimEmployee | None:
    """The salesperson record behind a login, or None for staff who are not
    in the sales team (the CEO, admins)."""
    return DimEmployee.objects.filter(user=user).first()


#: The sales departments whose people work in CRM. فروش همکار built it and
#: owns most of the records; بی‌تو‌بی and فروش بانکی sell to their own books
#: through the same screens. Membership is the department on the account —
#: adding a fourth sales department later is one entry here, not a hunt
#: through permission classes.
CRM_DEPARTMENTS = {"sales_team", "sales_b2b", "sales_org"}

#: Which sales channel each department's CRM covers. The three departments
#: keep separate books: a customer فروش بانکی opened is not in فروش همکار's
#: file and must not appear in its lists, its reports or its pipeline.
#:
#: The channel values are the company's existing ones from
#: `apps.sales.models.SalesChannel` — the same ones the sales workbooks and
#: the budget already use — so a CRM figure and a sales figure for «فروش B2B»
#: mean the same thing rather than nearly the same thing.
CHANNEL_FOR_DEPARTMENT = {
    "sales_team": SalesChannel.TEAM,
    "sales_org": SalesChannel.ORGANIZATIONAL,
    "sales_b2b": SalesChannel.B2B,
}

#: Roles that supervise rather than sell. Everyone else in a CRM department
#: is a کارشناس and sees only their own book.
MANAGER_ROLES = {"executive", "manager"}


def channels_for(user) -> tuple[str, ...] | None:
    """
    Which books this account reads and writes. None means all of them.

    Department first, deliberately. An account carrying a sales department is
    *of* that department whatever else its role says, and pinning it is the
    safe reading of the one configuration that is otherwise ambiguous — an
    executive with a department set. A superuser is the escape hatch and keeps
    the global view; the CEO, who has no department, gets it too.
    """
    if getattr(user, "is_superuser", False):
        return None
    channel = CHANNEL_FOR_DEPARTMENT.get(getattr(user, "department", "") or "")
    if channel:
        return (channel,)
    if getattr(user, "role", "") == "executive":
        return None
    return ()   # in no book at all — CrmAccess has already refused them


def is_crm_manager(user) -> bool:
    """
    Supervision, not seniority.

    The distinction this draws is the one the section is built around: a
    manager is answerable for a team's numbers and therefore has to see all of
    them, while a کارشناس is answerable for their own and must not see the
    rest. Everything else that differs between the two — which filters appear,
    whether «کارشناس» is a question or a statement, who may reassign an
    account — follows from that one fact.
    """
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role in MANAGER_ROLES)
    )


def crm_scope(user) -> rpt.Scope:
    """
    Which records this account may see at all.

    Note the shape of the unhappy path: a non-manager with no DimEmployee row
    gets a scope that matches nothing, not one that matches everything. An
    account nobody has linked to a salesperson is a half-finished setup, and
    the cost of guessing wrong in the generous direction is the whole customer
    file.
    """
    channels = channels_for(user)
    if is_crm_manager(user):
        return rpt.Scope(sees_all=True, channels=channels)
    emp = employee_for(user)
    return rpt.Scope(
        sees_all=False, employee_id=emp.id if emp else None, channels=channels,
    )


def can_write_crm(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user.role == "executive"
            or user.department in CRM_DEPARTMENTS
        )
    )


def can_read_crm(user) -> bool:
    """The CEO reads it, the sales departments work it, an admin maintains it."""
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or user.role == "executive"
            or user.department in CRM_DEPARTMENTS
        )
    )


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
        return can_write_crm(u)


class CrmManagerOnly(BasePermission):
    """
    For the screens that are about the file rather than about a book of
    customers — merging duplicates, chiefly. Those span everybody's accounts
    by definition, so there is no version of them a کارشناس could be shown
    that would not also show them the rest of the team's customers.
    """

    message = "این بخش فقط برای مدیران فروش است."

    def has_permission(self, request, view):
        return can_read_crm(request.user) and is_crm_manager(request.user)


class CrmAccess(BasePermission):
    """
    Who may open CRM at all.

    This used to be a shared demo password, which made sense while the section
    held generated sample data and was shown to people without accounts. It
    holds the company's real customer file now — every contact, every deal
    value — and a single password that ships in the source is the wrong shape
    of protection for that. Access is a property of the account instead: the
    sales team who own the records, and the CEO who reads them.
    """

    message = "دسترسی به CRM ندارید."

    def has_permission(self, request, view):
        return can_read_crm(request.user)


class GatedAPIView(APIView):
    """Base for the CRM's non-viewset endpoints."""

    permission_classes = [CrmAccess]


# --------------------------------------------------------------------------
# Lookup viewsets
# --------------------------------------------------------------------------
def active_dataset(request) -> str:
    """
    The body of data every CRM request reads and writes: the real one.

    CRM used to carry a fabricated showroom beside the company's customer
    file, chosen per account. It was removed — the rows deleted, the switch
    taken out — because a second, invented customer file that looks exactly
    like the real one is a standing way to act on numbers that are not true.

    The `dataset` column is still on every table and still stamped, so this
    stays the one place that says which value; nothing reads the account's
    old `crm_dataset` preference any more.
    """
    return Dataset.REAL


def employee_options(request):
    """
    The کارشناس roster a filter dropdown and the «به نام چه کسی» picker offer.

    Scoped to the account's own channel, using the membership roster the sales
    module already keeps. Without it a فروش بانکی manager picked from a list of
    every salesperson in the company and could file a customer under someone
    who has never worked their book — a row that then shows up in nobody's
    reports, because the rest of the system agrees the two are separate.
    """
    qs = (
        DimEmployee.objects.select_related("team")
        .filter(is_active=True)
        .exclude(full_name_fa__in=["", "0"])
    )
    channels = channels_for(request.user)
    if channels is not None:
        wanted = list(channels)
        # The roster, *plus* anyone who already owns something in this book.
        # Nine of the nineteen active salespeople have no membership row —
        # the roster was added long after the customer file — and dropping
        # them would mean opening an existing customer and finding its owner
        # missing from the list that is supposed to contain it.
        qs = qs.filter(
            Q(memberships__channel__in=wanted, memberships__is_active=True)
            | Q(customers__channel__in=wanted)
            | Q(deals__channel__in=wanted)
        ).distinct()
    return qs


def query_filters(request) -> rpt.Filters:
    """
    The parsed query for this request, with the two things that must never
    come from the URL already applied: which dataset, and whose records.

    Every endpoint that slices CRM data goes through here. Four of them used
    to call `Filters.from_query(q)` with no dataset at all, which meant the
    معامله‌ها and پیگیری‌ها lists kept showing the real customer file while the
    screen said «داده نمایشی» — the exact failure the dataset column exists to
    prevent, reintroduced one call site at a time. One helper is harder to
    forget than one argument.
    """
    return rpt.Filters.from_query(
        request.query_params, active_dataset(request), crm_scope(request.user)
    )


class _Base(viewsets.ModelViewSet):
    # Two checks, deliberately: CrmAccess decides who sees the section at all,
    # CrmWritePermission decides who may change what is in it.
    permission_classes = [CrmAccess, CrmWritePermission]

    #: The lookup that answers "whose record is this", or None for reference
    #: data every rep needs in full — products, stages, tags, groups. Getting
    #: this wrong in the None direction is a leak, so it is stated per
    #: viewset rather than guessed from the model.
    owner_field: str | None = None

    #: The writable FK behind `owner_field`, when the record carries one. Used
    #: to stamp a rep's own id on anything they create and to stop them
    #: handing a record to someone else.
    owns_via: str | None = None

    #: The lookup that answers "whose book is this in", or None for reference
    #: data the departments share (products, stages, tags). Stated per viewset
    #: for the same reason `owner_field` is: guessing it in the None direction
    #: puts another department's customers on the page.
    channel_field: str | None = None

    #: True when `channel_field` runs through a nullable relation. A کار with
    #: no customer belongs to nobody's book and must not vanish because of it.
    channel_allows_null: bool = False

    def get_queryset(self):
        """
        Every CRM list is scoped twice — to the caller's dataset and to the
        records they may see — in one override rather than a filter repeated
        in fourteen viewsets, because the one that got forgotten would be the
        leak.

        This covers detail routes as well as lists, which is the half that is
        easy to miss: a viewset whose list is filtered but whose `retrieve`
        is not still answers /deals/1417/ for anybody who guesses the number.
        """
        qs = super().get_queryset().filter(dataset=active_dataset(self.request))
        return self.scoped(qs)

    def scoped(self, qs):
        """
        Narrow `qs` to what the caller may see, along both axes: whose book
        (channel) and whose row (owner). Shared by the overrides that build
        their queryset from `Filters` instead of from super().
        """
        scope = crm_scope(self.request.user)
        channels = self.effective_channels()

        if self.channel_field and channels is not None:
            if not channels:
                return qs.none()
            match = Q(**{f"{self.channel_field}__in": list(channels)})
            if self.channel_allows_null:
                head = self.channel_field.rsplit("__", 1)[0]
                match |= Q(**{f"{head}__isnull": True})
            qs = qs.filter(match)

        if not self.owner_field or scope.sees_all:
            return qs
        if scope.employee_id is None:
            return qs.none()
        return qs.filter(**{f"{self.owner_field}_id": scope.employee_id})

    def effective_channels(self) -> tuple[str, ...] | None:
        """
        The books this request covers: the account's, narrowed by a `channel`
        param when one was asked for and is inside them.

        A list honours the narrowing so a drill-down lands on exactly the rows
        its chart counted. A lookup by id does not: the record either is in
        one of the caller's books or is not theirs to see, and a stray param
        on a detail URL should not be able to turn that into a 404.
        """
        if self.detail:
            return crm_scope(self.request.user).channels
        return query_filters(self.request).channels

    def own_channel(self) -> str | None:
        """The one channel this account writes into, or None when it covers
        several and the record has to say which for itself."""
        channels = crm_scope(self.request.user).channels
        return channels[0] if channels and len(channels) == 1 else None

    def create_defaults(self, serializer) -> dict:
        """
        Fields stamped onto anything created through this viewset.

        Subclasses extend this rather than overriding `perform_create`, which
        is the whole point: four viewsets had their own `perform_create` for
        owner and timestamp defaults, and every one of them silently dropped
        the dataset — a customer added while the screen said «داده نمایشی»
        was filed with the real ones, where nobody would look for it. A hook
        that *contributes* cannot be forgotten by the next viewset the way an
        override can.
        """
        extra = {"dataset": active_dataset(self.request)}
        # A rep's records are their own, whatever the payload said. The form
        # does not offer them the choice; this is what makes that true rather
        # than merely displayed.
        scope = crm_scope(self.request.user)
        if self.owns_via and not scope.sees_all and scope.employee_id is not None:
            extra[self.owns_via] = employee_for(self.request.user)
        # A record filed by a department account belongs to that department's
        # book. Stamped rather than asked for: nobody in فروش بانکی has ever
        # wanted to file a customer into فروش همکار's file, and offering the
        # choice only creates the row that lands in the wrong one.
        if self.channel_field == "channel":
            mine = self.own_channel()
            if mine:
                extra["channel"] = mine
        return extra

    def perform_create(self, serializer):
        serializer.save(**self.create_defaults(serializer))

    def perform_update(self, serializer):
        """
        A rep cannot edit someone else's record — `get_queryset` already saw
        to that — but could otherwise hand their own record away by setting a
        different owner. Ownership is the scope, so it is not theirs to move.
        """
        extra = {}
        scope = crm_scope(self.request.user)
        if self.owns_via and not scope.sees_all and scope.employee_id is not None:
            extra[self.owns_via] = employee_for(self.request.user)
        serializer.save(**extra)


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
    owner_field = "owner"
    channel_field = "channel"
    owns_via = "owner"
    queryset = Customer.objects.select_related(
        "group", "province", "owner", "lead_source"
    ).prefetch_related("tags")
    serializer_class = CustomerListSerializer

    def perform_destroy(self, instance):
        # Through the tombstone helper, not `instance.delete()`: a bare delete
        # forgets the customer's آرپا id and the next accounting load brings
        # the customer straight back.
        crm_merge.delete_customers(
            Customer.objects.filter(pk=instance.pk), self.request.user
        )

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return CustomerWriteSerializer
        if self.action == "retrieve":
            return CustomerDetailSerializer
        return CustomerListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.detail:  # a lookup by id is never a time slice — see DealViewSet
            return qs
        # A row folded into another is not a customer any more; its deals and
        # invoices now hang off the survivor. It is kept so the merge can be
        # undone, not so it keeps appearing in the list the merge was meant to
        # clean up.
        qs = qs.filter(merged_into__isnull=True)
        q = self.request.query_params
        f = query_filters(self.request)

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

    def create_defaults(self, serializer) -> dict:
        # A rep adding a customer should not have to fill in "who owns this"
        # or "when did we first talk" — it is them, and it is now.
        extra = super().create_defaults(serializer)
        if not serializer.validated_data.get("owner"):
            mine = employee_for(self.request.user)
            if mine:
                extra["owner"] = mine
        if not serializer.validated_data.get("first_contact_at"):
            extra["first_contact_at"] = timezone.now()
        return extra

    def perform_create(self, serializer):
        super().perform_create(serializer)
        obj = serializer.instance
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


    # -- bulk actions on the list -------------------------------------------
    @action(detail=False, methods=["post"], url_path="bulk-review")
    def bulk_review(self, request):
        """
        Send selected customers to the merge queue.

        Two shapes, because the reviewer arrives with two different amounts of
        knowledge. Picking exactly two rows says «these are one company» — the
        pair is queued as it stands. Picking one, or several, says «this looks
        wrong but I do not know its twin» — so the matching ladder is run for
        each against the rest of the file and whatever it suspects is queued.

        Neither merges anything. The point of the queue is that a fusion of
        two customers' order histories is invisible once done, so it happens
        only after someone has looked at both sides.
        """
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response(
                {"detail": "هیچ مشتری‌ای انتخاب نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dataset = active_dataset(request)
        rows = list(
            Customer.objects.filter(
                pk__in=ids, dataset=dataset, merged_into__isnull=True
            )
        )
        if len(rows) < 1:
            return Response(
                {"detail": "مشتری معتبری در انتخاب نبود."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(rows) == 2:
            queued, skipped = crm_merge.queue_pair(*rows), []
            queued = [queued] if queued else []
            if not queued:
                skipped = [{
                    "name_fa": rows[0].name_fa,
                    "reason": "این جفت از قبل در صف است یا تعیین تکلیف شده.",
                }]
        else:
            queued, skipped = crm_merge.queue_scan(rows, dataset)

        return Response({
            "queued": len(queued),
            "pairs": [
                {"primary": c.customer.name_fa,
                 "duplicate": c.duplicate.name_fa if c.duplicate else c.external_name,
                 "method": c.get_method_display()}
                for c in queued
            ],
            "skipped": skipped,
        })

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """
        Delete selected customers — but only the ones that are safe to lose.

        A customer with deals cascades: deleting it takes the deals, their
        lines and their stage history with it, silently. A customer with
        invoices cannot be deleted at all, because `SalesInvoice.customer` is
        PROTECT, and the ones that got that far are exactly the accounts worth
        keeping. So anything carrying history is refused *by name and reason*
        rather than half-deleted, and the answer for those is the merge queue,
        not the delete button.
        """
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response(
                {"detail": "هیچ مشتری‌ای انتخاب نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rows = Customer.objects.filter(
            pk__in=ids, dataset=active_dataset(request)
        ).annotate(
            n_deals=Count("deals", distinct=True),
            n_invoices=Count("invoices", distinct=True),
            n_activities=Count("activities", distinct=True),
            n_tasks=Count("tasks", distinct=True),
        )

        REASONS = (
            ("n_invoices", "فاکتور"),
            ("n_deals", "معامله"),
            ("n_activities", "فعالیت"),
            ("n_tasks", "کار"),
        )
        deletable, blocked = [], []
        for c in rows:
            held = [
                f"{getattr(c, attr)} {label}"
                for attr, label in REASONS if getattr(c, attr)
            ]
            if held:
                blocked.append({
                    "id": c.id, "name_fa": c.name_fa,
                    "reason": "، ".join(held) + " دارد",
                })
            else:
                deletable.append(c.id)

        deleted = 0
        if deletable:
            deleted = crm_merge.delete_customers(
                Customer.objects.filter(pk__in=deletable), request.user
            )

        return Response({
            "deleted": len(deletable),
            "rows_removed": deleted,
            "blocked": blocked,
        })

class CustomerFeedbackViewSet(_Base):
    # Feedback is filed against the rep it is about, not an "owner".
    owner_field = "employee"
    channel_field = "customer__channel"
    owns_via = "employee"
    queryset = CustomerFeedback.objects.select_related("customer", "employee")
    serializer_class = CustomerFeedbackSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.detail:
            return qs
        f = query_filters(self.request)
        if f.blind:
            return qs.none()
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
    owner_field = "owner"
    channel_field = "channel"
    owns_via = "owner"
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
        in a month (فرصت‌های جدید) vs deals *closed* in it (فروش موفق).
        """
        # Only list-style requests are a slice of time. Applying the window to
        # a lookup by id made every open deal's page 404, because an open deal
        # has no closed_at to fall inside the window.
        if self.detail:
            return super().get_queryset()

        q = self.request.query_params
        f = query_filters(self.request)
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

    def create_defaults(self, serializer) -> dict:
        data = serializer.validated_data
        extra = super().create_defaults(serializer)
        if not data.get("owner"):
            mine = employee_for(self.request.user)
            if mine:
                extra["owner"] = mine
        if not data.get("opened_at"):
            extra["opened_at"] = timezone.now()
        if not data.get("stage"):
            # Default to the first open stage so a new deal always appears on
            # the board rather than in a stage-less limbo.
            first = PipelineStage.objects.filter(
                dataset=active_dataset(self.request),
                is_active=True, kind=PipelineStage.Kind.OPEN
            ).order_by("order").first()
            if first:
                extra["stage"] = first
        # The channel is the customer's, not the typist's. A deal filed
        # against a فروش بانکی account belongs in فروش بانکی's book even when
        # a CEO with the global view is the one entering it — otherwise the
        # model default («همکار») quietly files it in the wrong department.
        if data.get("customer"):
            extra["channel"] = data["customer"].channel
        if not data.get("lead_source") and data.get("customer"):
            extra["lead_source"] = data["customer"].lead_source
        if not data.get("title") and data.get("customer"):
            extra["title"] = f"فروش به {data['customer'].name_fa}"
        return extra

    def perform_create(self, serializer):
        super().perform_create(serializer)
        obj = serializer.instance
        obj.code = obj.code or f"deal-{obj.pk}"
        obj.period = period_for(obj.opened_at)
        self._sync_close(obj)
        obj.save()
        DealStageEvent.objects.create(
            deal=obj, from_stage=None, to_stage=obj.stage,
            at=obj.opened_at, by=self.request.user,
        )

    def perform_update(self, serializer):
        """
        Editing a deal can change its stage just as a board drag can, so the
        same stage-event has to be written here. Without it the funnel and
        cycle-time reports would silently miss every transition made from the
        edit form.
        """
        before = self.get_object()
        previous_stage, previous_status = before.stage, before.status
        super().perform_update(serializer)
        obj = serializer.instance
        self._sync_close(obj)
        obj.save()

        if obj.stage_id != (previous_stage.id if previous_stage else None):
            last = obj.stage_events.order_by("-at").first()
            now = timezone.now()
            DealStageEvent.objects.create(
                deal=obj, from_stage=previous_stage, to_stage=obj.stage, at=now,
                by=self.request.user,
                days_in_previous=max((now - (last.at if last else obj.opened_at)).days, 0),
            )
        if obj.status == Deal.Status.WON and previous_status != Deal.Status.WON:
            self._mark_customer_won(obj)

    @staticmethod
    def _sync_close(deal: Deal) -> None:
        """
        The stage is the single source of truth: status and the close date are
        derived from it. A won deal with no `closed_at` would vanish from every
        report that measures on the closing date, and a deal moved back to an
        open stage while still flagged won would be counted as revenue twice.
        """
        if deal.stage:
            deal.status = {
                PipelineStage.Kind.WON: Deal.Status.WON,
                PipelineStage.Kind.LOST: Deal.Status.LOST,
            }.get(deal.stage.kind, Deal.Status.OPEN)

        if deal.status == Deal.Status.OPEN:
            deal.closed_at, deal.close_period = None, None
        else:
            deal.closed_at = deal.closed_at or timezone.now()
            deal.close_period = period_for(deal.closed_at)
        if deal.status != Deal.Status.LOST:
            deal.lost_reason, deal.lost_note = None, ""

    @staticmethod
    def _mark_customer_won(deal: Deal) -> None:
        cust = deal.customer
        won_at = deal.closed_at or timezone.now()
        if not cust.first_deal_won_at or won_at < cust.first_deal_won_at:
            cust.first_deal_won_at = won_at
        cust.status = Customer.Status.ACTIVE
        cust.save(update_fields=["first_deal_won_at", "status"])

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
        stage = PipelineStage.objects.filter(
            pk=request.data.get("stage"), dataset=active_dataset(request)
        ).first()
        if not stage:
            return Response({"detail": "مرحله نامعتبر است."}, status=400)
        # Same rule as the edit form: a loss with no reason would leave a hole
        # in the "دلایل از دست رفتن" report, and every path into that state
        # has to enforce it — not just the one with a nice prompt attached.
        if stage.kind == PipelineStage.Kind.LOST and not request.data.get("lost_reason"):
            return Response(
                {"lost_reason": "برای ثبت فرصت از دست رفته، انتخاب دلیل الزامی است."},
                status=400,
            )

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
            self._mark_customer_won(deal)
        elif stage.kind == PipelineStage.Kind.LOST:
            deal.status = Deal.Status.LOST
            deal.closed_at = now
            deal.close_period = period_for(now)
            reason = LostReason.objects.filter(
                pk=request.data.get("lost_reason"),
                dataset=active_dataset(request),
            ).first()
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
    channel_field = "deal__channel"
    # A line has no owner of its own; it belongs to whoever owns the deal.
    # Without this, a rep could read every line of every deal in the company
    # by walking /deal-items/?deal=<n>.
    owner_field = "deal__owner"
    queryset = DealItem.objects.select_related("product", "deal")
    serializer_class = DealItemSerializer
    filterset_fields = ["deal", "product"]

    def perform_create(self, serializer):
        super().perform_create(serializer)
        serializer.instance.deal.recalculate()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        serializer.instance.deal.recalculate()

    def perform_destroy(self, instance):
        deal = instance.deal
        instance.delete()
        deal.recalculate()


# --------------------------------------------------------------------------
# Activity / Task
# --------------------------------------------------------------------------
class ActivityViewSet(_Base):
    owner_field = "owner"
    channel_field = "customer__channel"
    owns_via = "owner"
    queryset = Activity.objects.select_related("customer", "owner", "deal")
    serializer_class = ActivitySerializer

    def get_queryset(self):
        if self.detail:
            return super().get_queryset()
        q = self.request.query_params
        f = query_filters(self.request)
        # Filters already understands the pseudo-kind "call" (both directions).
        qs = f.activities()
        deal_id = q.get("deal")
        if deal_id:
            qs = qs.filter(deal_id=deal_id)
        return qs.select_related("customer", "owner", "deal")

    def create_defaults(self, serializer) -> dict:
        extra = super().create_defaults(serializer)
        if not serializer.validated_data.get("owner"):
            mine = employee_for(self.request.user)
            if mine:
                extra["owner"] = mine
        if not serializer.validated_data.get("at"):
            extra["at"] = timezone.now()
        return extra

    def perform_create(self, serializer):
        super().perform_create(serializer)
        obj = serializer.instance
        obj.period = period_for(obj.at)
        obj.save(update_fields=["period"])
        Customer.objects.filter(pk=obj.customer_id).update(last_activity_at=obj.at)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        obj = serializer.instance
        obj.period = period_for(obj.at)
        obj.save(update_fields=["period"])

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
    # A کار may stand on its own with no customer behind it, so the channel
    # lookup has to tolerate the gap rather than filter the task away.
    channel_field = "customer__channel"
    channel_allows_null = True
    owner_field = "owner"
    owns_via = "owner"
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

    def create_defaults(self, serializer) -> dict:
        # This used to be a `perform_create` override, which silently dropped
        # the dataset stamp — a کار added while the screen said «داده نمایشی»
        # was filed with the real ones. Contributing to the hook cannot lose
        # what the hook already does.
        extra = super().create_defaults(serializer)
        if not serializer.validated_data.get("owner"):
            mine = employee_for(self.request.user)
            if mine:
                extra["owner"] = mine
        return extra

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        task.done_at = timezone.now()
        task.save(update_fields=["done_at"])
        return Response(TaskSerializer(task).data)


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------
class CrmDashboardView(GatedAPIView):
    """داشبورد — every widget of the CRM home screen in one response."""

    @extend_schema(
        parameters=[
            OpenApiParameter("period", int), OpenApiParameter("owner", int),
            OpenApiParameter("date_from", str), OpenApiParameter("date_to", str),
        ]
    )
    def get(self, request):
        f = query_filters(request)
        data = rpt.dashboard(f)
        data["window"] = {
            "start": f.start.isoformat() if f.start else None,
            "end": f.end.isoformat() if f.end else None,
        }
        return Response(data)


class CrmReportView(GatedAPIView):
    """گزارش‌ها — /api/crm/reports/<key>/?axis=time|user|product|…"""

    def get(self, request, key: str):
        if key not in rpt.REPORTS:
            return Response(
                {"detail": f"گزارش «{key}» تعریف نشده است."},
                status=status.HTTP_404_NOT_FOUND,
            )
        f = query_filters(request)
        axis = request.query_params.get("axis") or ""
        data = rpt.run_report(key, f, axis)
        data["axis_labels"] = rpt.AXIS_LABELS
        data["window"] = {
            "start": f.start.isoformat() if f.start else None,
            "end": f.end.isoformat() if f.end else None,
        }
        return Response(data)


class CrmReportIndexView(GatedAPIView):
    """The report catalogue, so the UI builds its menu from the server."""

    def get(self, request):
        return Response({
            "reports": [
                {"key": k, "title": t, "axes": a} for k, (_fn, t, a) in rpt.REPORTS.items()
            ],
            "axis_labels": rpt.AXIS_LABELS,
        })


class PipelineBoardView(GatedAPIView):
    """مراحل فروش — the kanban board: stages with their open deals."""

    def get(self, request):
        ds = active_dataset(request)
        f = query_filters(request)
        qs = Deal.objects.none() if f.blind else f.by_channel(
            Deal.objects.filter(status=Deal.Status.OPEN, dataset=ds)
        )
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
        for st in PipelineStage.objects.filter(
            is_active=True, dataset=ds
        ).order_by("order"):
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


class CrmMeView(GatedAPIView):
    """
    Who the caller is *as a salesperson*, and what they may do.

    The UI needs both: it hides the create/edit affordances when the user
    cannot write (rather than letting them fill in a form and hit a 403), and
    it pre-selects them as the owner of anything they add.
    """

    def get(self, request):
        emp = employee_for(request.user)
        return Response({
            "can_edit": can_write_crm(request.user),
            "employee": emp.id if emp else None,
            "employee_name": emp.full_name_fa if emp else "",
            "team": emp.team.name_fa if emp and emp.team else "",
            "is_manager": is_crm_manager(request.user),
            # True when the account reads the whole team's book. The UI uses
            # it to decide whether to offer a «کارشناس» filter at all: showing
            # one that can only ever return your own rows is worse than not
            # showing it.
            "sees_all": crm_scope(request.user).sees_all,
            # Which book this account works. `null` for the CEO and admins,
            # who read every department's. The UI shows it in the header:
            # three departments now share these screens and «CRM» alone no
            # longer says whose customers are on them.
            "channel": (channels_for(request.user) or (None,))[0],
            "channel_label": SalesChannel(
                channels_for(request.user)[0]
            ).label if channels_for(request.user) else "",
            # A non-manager with no employee row sees nothing, and the screen
            # has to say so rather than look like an empty CRM.
            "unlinked": crm_scope(request.user).blind,
        })


class CrmOptionsView(GatedAPIView):
    """Every filter dropdown the CRM UI needs, in one request."""

    def get(self, request):
        # The month list is served rather than computed in the browser so the
        # Jalali calendar lives in exactly one place.
        ds = active_dataset(request)
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
                for e in employee_options(request)
            ],
            "groups": CustomerGroupSerializer(
                CustomerGroup.objects.filter(dataset=ds), many=True
            ).data,
            "sources": LeadSourceSerializer(
                LeadSource.objects.filter(dataset=ds), many=True
            ).data,
            "reasons": LostReasonSerializer(
                LostReason.objects.filter(dataset=ds), many=True
            ).data,
            "stages": PipelineStageSerializer(
                PipelineStage.objects.filter(is_active=True, dataset=ds), many=True
            ).data,
            "products": ProductSerializer(
                Product.objects.filter(is_active=True, dataset=ds)
                .select_related("category"),
                many=True,
            ).data,
            "tags": TagSerializer(Tag.objects.filter(dataset=ds), many=True).data,
            "activity_kinds": [
                {"code": c, "label": l} for c, l in Activity.Kind.choices
            ],
            "activity_results": [
                {"code": c, "label": l} for c, l in Activity.Result.choices
            ],
        })


# --------------------------------------------------------------------------
# Merge review
# --------------------------------------------------------------------------
class MatchCandidateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The queue of suspected duplicates, and the two answers to one.

    Read-only as a viewset on purpose: a candidate is not an editable record,
    it is a question. The only writes are the two decisions, and both go
    through `apps.crm.merge` so the screen and any future importer take the
    same path — accepting a match has to write accounting's fields exactly as
    the bulk import would, or the two ways into the same row diverge.

    Not a `_Base` subclass: a candidate pairs a source row with a customer and
    has no dataset column of its own, so the usual dataset filter has nothing
    to filter on. It is applied through the customer instead.

    Managers only: the queue is a view of the whole customer file, so there is
    no per-rep slice of it that would still be useful.
    """

    permission_classes = [CrmManagerOnly, CrmWritePermission]
    serializer_class = MatchCandidateSerializer
    queryset = CustomerMatchCandidate.objects.select_related(
        "customer", "customer__province", "customer__owner", "decided_by"
    )

    def get_queryset(self):
        qs = super().get_queryset().filter(
            customer__dataset=active_dataset(self.request)
        )
        # The list defaults to what is still open; a single candidate is
        # fetched by id whatever its state. Filtering both alike made a
        # second decision on the same row answer 404 — which reads as «that
        # never existed» when the truth is «someone already ruled on it», and
        # sends the reviewer looking for a bug instead of a colleague.
        if self.action != "list":
            return qs

        state = self.request.query_params.get("state", "pending")
        if state and state != "all":
            qs = qs.filter(state=state)
        method = self.request.query_params.get("method")
        if method:
            qs = qs.filter(method=method)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(external_name__icontains=search)
                | Q(customer__name_fa__icontains=search)
            )
        return qs.order_by("state", "method", "-score")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts per tier and per state — what the screen's header shows."""
        qs = super().get_queryset().filter(
            customer__dataset=active_dataset(request)
        )
        by_method = dict(
            qs.filter(state=CustomerMatchCandidate.State.PENDING)
            .values_list("method")
            .annotate(n=Count("id"))
        )
        by_state = dict(qs.values_list("state").annotate(n=Count("id")))
        return Response({
            "by_method": [
                {"key": k, "label": label, "count": by_method.get(k, 0)}
                for k, label in CustomerMatchCandidate.Method.choices
                if by_method.get(k)
            ],
            "by_state": by_state,
            "pending": by_state.get(CustomerMatchCandidate.State.PENDING, 0),
        })

    @action(detail=True, methods=["get"])
    def alternatives(self, request, pk=None):
        """
        Other customers carrying the same name.

        The «ambig» tier exists because the name matched more than one CRM
        row — a duplicate the دیدار import left behind. Picking which of them
        is the real account is the reviewer's actual contribution there, so
        the rivals have to be visible.
        """
        rows = crm_merge.alternatives(self.get_object())
        return Response([
            {
                "id": c.id, "name_fa": c.name_fa, "code": c.code,
                "phone": c.phone, "city": c.city,
                "deals": c.deals.count(), "invoices": c.invoices.count(),
            }
            for c in rows
        ])

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        """«Same customer.» An optional `customer` picks a different target."""
        candidate = self.get_object()
        target = None
        chosen = request.data.get("customer")
        if chosen:
            target = Customer.objects.filter(
                pk=chosen, dataset=active_dataset(request)
            ).first()
            if not target:
                return Response(
                    {"detail": "مشتری انتخاب‌شده پیدا نشد."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            customer = crm_merge.accept(candidate, request.user, target)
        except crm_merge.MergeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({
            "state": candidate.state,
            "customer": {"id": customer.id, "name_fa": customer.name_fa},
        })

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """
        «Different customers.»

        Which makes the آرپا party an account in its own right, so one is
        created. Rejecting is not discarding: an unresolved party is invisible
        to the invoice import and its invoices stay out of every total.
        """
        candidate = self.get_object()
        try:
            customer = crm_merge.reject(candidate, request.user)
        except crm_merge.MergeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({
            "state": candidate.state,
            "created": {"id": customer.id, "name_fa": customer.name_fa},
        })



# --------------------------------------------------------------------------
# Invoices (read-only — they are owned by accounting)
# --------------------------------------------------------------------------
class SalesInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The invoices behind a «فروش فاکتورشده» figure.

    Read-only on purpose: an invoice is accounting's record, loaded from آرپا,
    and a correction typed here would be silently overwritten by the next
    export — or worse, not overwritten, and disagree with the ledger for good.

    The queryset comes from `Filters.invoices()`, the same one the dashboard
    sums, so the drawer can never list a different set of invoices than the
    number that opened it.
    """

    permission_classes = [CrmAccess]
    serializer_class = SalesInvoiceSerializer
    queryset = SalesInvoice.objects.all()

    def get_queryset(self):
        qs = query_filters(self.request).invoices().select_related(
            "customer", "owner", "deal"
        )
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(number__icontains=search) | Q(customer__name_fa__icontains=search)
            )
        return qs.order_by("-issued_at", "-number")
