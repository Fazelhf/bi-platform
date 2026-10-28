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
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, F, Max, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.crm import merge as crm_merge, reports as rpt
from apps.crm.jalali import jalali_month_of, jalali_str, month_bounds, month_label, period_for
from apps.crm.models import (
    CustomerMatchCandidate, Dataset, SalesInvoice, SalesZone, TerritoryAssignment,
    Activity, Customer, CustomerFeedback, CustomerGroup, Deal, DealItem,
    DealStageEvent, LeadSource, LostReason, PipelineStage, Product,
    ProductCategory, Tag, Task, fit_stage, stages_for, stages_in_view,
)
from apps.crm.serializers import (
    MatchCandidateSerializer, SalesInvoiceSerializer, TerritoryAssignmentSerializer,
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


def is_system_admin(user) -> bool:
    """مدیر سیستم: a superuser or the `admin` role. Runs the imports."""
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or getattr(user, "role", "") == "admin")
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


class SystemAdminOnly(BasePermission):
    """
    ورود از آرپا: it writes the company's sales record and rules on فروش
    سوری, so it belongs to the system admin alone — not to every manager.
    """

    message = "این بخش فقط برای مدیر سیستم است."

    def has_permission(self, request, view):
        return is_system_admin(request.user)


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
    from django.db.models import BooleanField, ExpressionWrapper

    from apps.crm.people import sales_roster

    qs = (
        DimEmployee.objects.select_related("team")
        .filter(is_active=True, is_placeholder=False)
        .exclude(full_name_fa__in=["", "0"])
    )
    channels = channels_for(request.user)
    # Every sales book for an account with no department (the CEO). It used
    # to mean every employee in the company — finance and production too.
    wanted = list(channels) if channels is not None else [c for c, _ in SalesChannel.choices]
    # The roster, *plus* anyone who already owns something in this book, so an
    # existing customer's owner is still on the list that labels it. Those
    # extra rows come back with `in_roster` false: shown, not offered for new
    # assignments — `sales_roster` is what a save is checked against.
    # Ids, not membership rows: a سرپرست or مدیر فروش is on the roster by seat.
    roster = list(sales_roster(wanted).values_list("pk", flat=True))
    return qs.filter(
        Q(pk__in=roster)
        | Q(customers__channel__in=wanted)
        | Q(deals__channel__in=wanted)
    ).annotate(in_roster=ExpressionWrapper(Q(pk__in=roster), output_field=BooleanField())).distinct()


def apply_ordering(qs, request, allowed: dict[str, str]):
    """
    Sort a list by `?ordering=<key>` or `?ordering=-<key>`.

    The keys are the UI's column names, mapped here to real lookups — never
    passed through — so a URL cannot order by a field it has no business
    reading (or one that forces a full-table join). Sorting on the server is
    the point: a table that sorts only the thirty rows it has loaded shows
    «the biggest deal» as the biggest one on page one.
    """
    raw = (request.query_params.get("ordering") or "").strip()
    key = raw.lstrip("-")
    if key not in allowed:
        return qs
    field = allowed[key]
    desc = raw.startswith("-")
    # Blanks last either way: a missing date or owner is not «the smallest».
    expr = F(field).desc(nulls_last=True) if desc else F(field).asc(nulls_last=True)
    return qs.order_by(expr, "-id" if desc else "id")


def id_list(request) -> list[int] | None:
    """`?ids=1,2,3` — the rows a user ticked, for exporting just those."""
    raw = request.query_params.get("ids") or ""
    ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    return ids or None


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
    # A date the parser cannot read used to leave that side of the window
    # open — «from 1405/07/01» silently meant «from the beginning of time»,
    # and every card on the page summed a different period from the one on
    # screen. Refused instead.
    q = request.query_params
    bad = {
        k: ["تاریخ نامعتبر است؛ قالب میلادی YYYY-MM-DD لازم است."]
        for k in ("date_from", "date_to") if q.get(k) and rpt._parse_date(q.get(k)) is None
    }
    if bad:
        raise ValidationError(bad)
    f = rpt.Filters.from_query(q, active_dataset(request), crm_scope(request.user))
    if f.start and f.end and f.start >= f.end:
        raise ValidationError({"date_to": ["پایان بازه پیش از شروع آن است."]})
    return f


class CrmPagination(PageNumberPagination):
    """
    Honour the page size the screen asks for.

    Every CRM list sends `page_size` (30 for the tables, 25 for the drill
    drawer) and computes «صفحه ۱ از N» from it — but the project default
    ignored the parameter and always returned 100. The pager then promised
    eight pages of a three-page result, and «بعدی» past the third answered
    404. The ceiling stops a hand-typed URL from asking for everything.
    """

    # The project default, unchanged: lookups fetched without a size (tags,
    # groups, products for a dropdown) must not start arriving truncated.
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500


class _Base(viewsets.ModelViewSet):
    pagination_class = CrmPagination

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
    """
    گروه‌های مشتری. Everyone reads them; a manager creates, renames, moves
    customers between them and deletes them.

    Moving and deleting touch only customers in the manager's own books: a
    group is shared reference data, but فروش همکار's manager re-filing
    بانکی's customers is not theirs to do. A group that still holds someone
    else's customers after the move is therefore not deleted.
    """

    queryset = CustomerGroup.objects.all()
    serializer_class = CustomerGroupSerializer

    def get_queryset(self):
        # Counted as the customer list will show them — in the caller's own
        # books. A group-wide count beside a book-scoped list read as «2000
        # customers here, none on the list».
        live = Q(customers__merged_into__isnull=True)
        channels = crm_scope(self.request.user).channels
        if channels is not None:
            live &= Q(customers__channel__in=channels)
        return super().get_queryset().annotate(customer_count=Count("customers", filter=live, distinct=True))

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in SAFE_METHODS and not is_crm_manager(request.user):
            self.permission_denied(request, message="مدیریت گروه‌ها با مدیر فروش است.")

    def perform_create(self, serializer):
        from django.utils.text import slugify

        base = "cg-" + (slugify(serializer.validated_data.get("code") or serializer.validated_data["name_fa"],
                                allow_unicode=True)[:40] or "group")
        code, n = base, 1
        while CustomerGroup.objects.filter(code=code).exists():
            n += 1
            code = f"{base}-{n}"
        serializer.save(code=code, **self.create_defaults(serializer))

    def _mine(self, group):
        qs = Customer.objects.filter(group=group)
        channels = crm_scope(self.request.user).channels
        return qs if channels is None else qs.filter(channel__in=channels)

    def _target(self, group):
        raw = self.request.data.get("move_to") or self.request.query_params.get("move_to")
        if not raw:
            return None
        target = CustomerGroup.objects.filter(pk=raw, dataset=group.dataset).first()
        if target is None or target.pk == group.pk:
            raise ValidationError({"move_to": ["گروه مقصد معتبر نیست."]})
        return target

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """All of this group's customers (in the caller's books) to `move_to`."""
        group = self.get_object()
        target = self._target(group)
        if target is None:
            return Response({"move_to": ["گروه مقصد را انتخاب کنید."]}, status=status.HTTP_400_BAD_REQUEST)
        moved = self._mine(group).update(group=target)
        return Response({"moved": moved, "to": target.name_fa})

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()
        if group.is_system:
            return Response({"detail": f"«{group.name_fa}» گروه سیستمی است و حذف نمی‌شود؛ فقط نامش قابل تغییر است."},
                            status=status.HTTP_409_CONFLICT)
        held = group.customers.count()
        target = self._target(group)
        if held and target is None:
            return Response({"detail": f"{held} مشتری در این گروه است؛ گروه مقصد را انتخاب کنید.",
                             "customers": held}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            moved = self._mine(group).update(group=target) if held else 0
            left = group.customers.count()
            if left:
                transaction.set_rollback(True)
                return Response({"detail": f"{left} مشتری این گروه در دفتر واحد دیگری است؛ "
                                           "گروه حذف نشد. مدیر آن واحد باید آن‌ها را منتقل کند."},
                                status=status.HTTP_409_CONFLICT)
            group.delete()
        return Response({"moved": moved, "deleted": True})


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
        if f.group is not None:
            qs = qs.filter(group_id=f.group or None)
        if f.province is not None:
            qs = qs.filter(province_id=f.province or None)
        if f.zone:
            qs = qs.filter(rpt.zone_q(f.zone))
        if f.source:
            qs = qs.filter(lead_source_id=f.source)
        if f.tag:
            qs = qs.filter(tags__id=f.tag)
        if q.get("status") in dict(Customer.Status.choices):
            qs = qs.filter(status=q["status"])
        search = (q.get("search") or "").strip()
        if search:
            from apps.crm.matching import fold, name_key, phone_key

            # The folded key as well as the raw column: «علي» typed in Arabic
            # letters has to find «علی» stored in Persian, and the reverse.
            cond = (
                Q(name_fa__icontains=search)
                | Q(contact_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(mobile__icontains=search)
                | Q(code__icontains=search)
            )
            if name_key(search):
                cond |= Q(name_key__icontains=name_key(search))
            digits = "".join(ch for ch in fold(search) if ch.isdigit())
            if len(digits) >= 8:
                cond |= Q(mobile_key=phone_key(digits)) | Q(phone_key=phone_key(digits))
            qs = qs.filter(cond)
        ids = id_list(self.request)
        if ids:
            qs = qs.filter(pk__in=ids)
        return apply_ordering(qs.distinct(), self.request, {
            "name": "name_fa",
            "group": "group__name_fa",
            "province": "province__name_fa",
            "owner": "owner__full_name_fa",
            "status": "status",
            "last_activity": "last_activity_at",
            "first_won": "first_deal_won_at",
            "first_contact": "first_contact_at",
        })

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
        data["insights"] = customer_insights(obj)
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


    def perform_update(self, serializer):
        # Which department's book a customer is filed in is a manager's call.
        if not is_crm_manager(self.request.user):
            serializer.validated_data.pop("channel", None)
        super().perform_update(serializer)

    # -- bulk actions on the list -------------------------------------------
    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        return bulk_assign(request, self.scoped(
            Customer.objects.filter(dataset=active_dataset(request))
        ))

    @action(detail=False, methods=["post"], url_path="bulk-update")
    def bulk_update(self, request):
        """
        One value onto many customers — group, province, owner, status, lead
        source or city — in one request and one UPDATE. Validated by the same
        serializer as a single edit, and limited to rows the caller may edit.
        """
        ids = [i for i in (request.data.get("ids") or []) if isinstance(i, int)]
        fields = request.data.get("fields") or {}
        if not ids or not isinstance(fields, dict) or not fields:
            return Response({"detail": "ردیف‌ها و مقدار تازه را انتخاب کنید."}, status=status.HTTP_400_BAD_REQUEST)
        bad = set(fields) - set(CustomerWriteSerializer.BULK)
        if bad:
            return Response({"detail": "این فیلدها گروهی ویرایش نمی‌شوند: " + "، ".join(sorted(bad))},
                            status=status.HTTP_400_BAD_REQUEST)
        if "owner" in fields and not is_crm_manager(request.user):
            return Response({"detail": "تغییر کارشناس فقط برای مدیران فروش است."}, status=status.HTTP_403_FORBIDDEN)
        rows = self.scoped(Customer.objects.filter(
            dataset=active_dataset(request), merged_into__isnull=True, pk__in=ids,
        ))
        first = rows.first()
        if first is None:
            return Response({"detail": "مشتری معتبری در انتخاب نبود."}, status=status.HTTP_400_BAD_REQUEST)
        ser = CustomerWriteSerializer(first, data=fields, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        values = {k: ser.validated_data[k] for k in fields if k in ser.validated_data}
        updated = rows.update(**values)
        return Response({"updated": updated})

    @action(detail=True, methods=["get"])
    def similar(self, request, pk=None):
        """
        Customers that may be this one: same شناسه/کد ملی, same mobile or
        phone, or a name that shares its words. A suggestion for the person
        deciding a merge — never a decision; nothing here merges.
        """
        from difflib import SequenceMatcher

        from apps.crm.models import CrmConfig

        me = self.get_object()
        # A manager is looking for duplicates anywhere in the file — the
        # twin of a بانکی customer is often filed under همکار. An expert
        # still sees only their own book.
        base = (
            Customer.objects.filter(dataset=active_dataset(request))
            if is_crm_manager(request.user) else self.scoped(Customer.objects.all())
        )
        live = base.filter(merged_into__isnull=True).exclude(pk=me.pk)
        cfg = CrmConfig.get()
        found: dict[int, dict] = {}

        def add(qs, why):
            for c in qs.select_related("owner", "province")[:10]:
                row = found.setdefault(c.pk, {
                    "id": c.pk, "name_fa": c.name_fa, "city": c.city,
                    "province": c.province.name_fa if c.province_id else "",
                    "owner": c.owner.full_name_fa if c.owner_id else "",
                    "phone": c.mobile or c.phone, "national_id": c.national_id,
                    "deals": c.deals.count(), "invoices": c.invoices.count(),
                    "why": [],
                })
                if why not in row["why"]:
                    row["why"].append(why)

        # Every comparison is on the stored keys, folded the same way on both
        # sides. Comparing them against the raw columns is what used to miss
        # «آقاي سلطاني» (آرپا's Arabic letters) against «آقای سلطانی».
        if me.nid_key:
            add(live.filter(nid_key=me.nid_key), "شناسه/کد ملی یکسان")
        if cfg.match_phone:
            for value in {me.mobile_key, me.phone_key} - {""}:
                add(live.filter(Q(mobile_key=value) | Q(phone_key=value)), "تلفن یکسان")
        if me.name_key:
            add(live.filter(name_key=me.name_key), "نام یکسان")
            words = [w for w in me.name_key.split() if len(w) > 2]
            if words:
                q = Q()
                for w in words:
                    q &= Q(name_key__icontains=w)
                add(live.filter(q), "نام شبیه")
            if len(me.name_key) >= 4:
                threshold = float(cfg.fuzzy_threshold)
                close = [
                    pk for pk, key in live.filter(name_key__startswith=me.name_key[:4])
                    .values_list("pk", "name_key")[:500]
                    if key != me.name_key
                    and SequenceMatcher(None, key, me.name_key).ratio() >= threshold
                ]
                add(live.filter(pk__in=close), "نام مشابه")
        rows = sorted(found.values(), key=lambda r: -len(r["why"]))[:15]
        return Response(rows)

    @action(detail=True, methods=["get"])
    def merges(self, request, pk=None):
        """سابقه ادغام — merges this customer took part in, newest first."""
        from apps.crm.models import CustomerMerge

        me = self.get_object()
        rows = CustomerMerge.objects.filter(
            Q(survivor=me) | Q(absorbed=me)
        ).select_related("survivor", "absorbed", "by")
        return Response([
            {
                "id": m.pk, "at": m.created_at, "at_jalali": jalali_str(m.created_at),
                "by": m.by.get_full_name() or m.by.username if m.by else "",
                "survivor": {"id": m.survivor_id, "name_fa": m.survivor.name_fa},
                "absorbed": {"id": m.absorbed_id, "name_fa": m.absorbed.name_fa,
                             "code": m.absorbed.code},
                "moved": {k: len(v) for k, v in m.moved.items()},
                "before": m.before,
            }
            for m in rows
        ])

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """
        «این دو یک مشتری‌اند» — from the customer page itself.

        `other` is the second customer; `keep` says which survives ("this" or
        "other"). Everything the absorbed one had — deals, invoices,
        activities, tasks, its آرپا/دیدار codes — moves to the survivor, which
        also takes any field it was missing. The absorbed row is kept and
        marked, not deleted. The pair is filed in بازبینی تطبیق as decided, so
        there is a record of who merged what.
        """
        if not is_crm_manager(request.user):
            return Response({"detail": "ادغام مشتری با مدیر فروش است."}, status=status.HTTP_403_FORBIDDEN)
        me = self.get_object()
        try:
            # Any book, as in `similar`: the twin may be filed under another
            # channel. Recorded in CustomerMerge, so it stays traceable.
            other = Customer.objects.filter(dataset=active_dataset(request)).get(
                pk=int(request.data.get("other") or 0)
            )
        except (Customer.DoesNotExist, ValueError):
            return Response({"detail": "مشتری دوم پیدا نشد."}, status=status.HTTP_400_BAD_REQUEST)
        survivor, absorbed = (me, other) if request.data.get("keep", "this") == "this" else (other, me)
        try:
            with transaction.atomic():
                candidate = crm_merge.queue_pair(survivor, absorbed)
                if candidate is None:
                    candidate = CustomerMatchCandidate.objects.filter(
                        source="crm", state=CustomerMatchCandidate.State.PENDING,
                        customer_id__in=(survivor.pk, absorbed.pk),
                        duplicate_id__in=(survivor.pk, absorbed.pk),
                    ).first()
                if candidate is not None:
                    crm_merge.accept(candidate, request.user, customer=survivor)
                else:
                    crm_merge.absorb(survivor, absorbed, request.user)
        except crm_merge.MergeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        from apps.crm.models import CustomerMerge

        survivor.refresh_from_db()
        record = CustomerMerge.objects.filter(survivor=survivor, absorbed=absorbed).first()
        return Response({
            "id": survivor.pk, "name_fa": survivor.name_fa, "absorbed": absorbed.pk,
            "moved": {k: len(v) for k, v in (record.moved if record else {}).items()},
            "last_activity_at": survivor.last_activity_at,
        })

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
        # Scoped like every other write: an expert deletes only their own rows,
        # a department only its own book.
        rows = self.scoped(Customer.objects.filter(
            pk__in=ids, dataset=active_dataset(request)
        )).annotate(
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
def customer_insights(customer) -> dict:
    """
    What the customer page adds on top of the raw record — the part that
    makes it a 360° view rather than a contact card.

    * **Money from accounting**: what آرپا has billed them and what is still
      owed. دیدار's deals say what was agreed; the invoices say what was
      charged, and the unsettled figure is what a کارشناس should know before
      picking up the phone to sell more.
    * **Twelve months of purchases**, by Jalali month, so a customer who used
      to buy monthly and stopped in the spring is visible as such.
    * **A relationship-health score** from recency, frequency and balance,
      with the reasons listed — a score nobody can explain is a score nobody
      trusts.
    * **The open tasks**, so what is owed to them is on the page.
    """
    now = timezone.now()
    today = now.date()

    invoices = SalesInvoice.objects.counted().filter(customer=customer, is_intercompany=False)
    inv = invoices.aggregate(
        count=Count("id"),
        amount=Sum("amount_rial"),
        unsettled=Sum("unsettled_rial"),
        last=Max("issued_at"),
    )
    overdue_debt = invoices.filter(
        unsettled_rial__gt=0, due_date__isnull=False, due_date__lt=today,
    ).aggregate(s=Sum("unsettled_rial"))["s"] or 0

    # ---- twelve Jalali months, oldest first -----------------------------------
    jy, jm = jalali_month_of(today)
    months = []
    for _ in range(12):
        months.append((jy, jm))
        jm -= 1
        if jm == 0:
            jy, jm = jy - 1, 12
    months.reverse()
    first_start = month_bounds(*months[0])[0]

    won = customer.deals.filter(status=Deal.Status.WON, closed_at__date__gte=first_start)
    by_month: dict[tuple[int, int], float] = {m: 0.0 for m in months}
    for closed_at, amount in won.values_list("closed_at", "amount_rial"):
        key = jalali_month_of(closed_at)
        if key in by_month:
            by_month[key] += float(amount or 0)
    invoiced_by_month: dict[tuple[int, int], float] = {m: 0.0 for m in months}
    for issued_at, amount in invoices.filter(issued_at__gte=first_start).values_list("issued_at", "amount_rial"):
        key = jalali_month_of(issued_at)
        if key in invoiced_by_month:
            invoiced_by_month[key] += float(amount or 0)

    series = [
        {"label": month_label(*m), "won": by_month[m], "invoiced": invoiced_by_month[m]}
        for m in months
    ]
    active_months = sum(1 for r in series if r["won"] or r["invoiced"])

    # ---- health ------------------------------------------------------------------
    last_touch = customer.last_activity_at
    days_quiet = (now - last_touch).days if last_touch else None
    # The later of the last invoice (a date) and the last won deal (a
    # timestamp) — whichever system saw the purchase first.
    last_won = customer.deals.filter(status=Deal.Status.WON).aggregate(m=Max("closed_at"))["m"]
    candidates = [d for d in (inv["last"], last_won.date() if last_won else None) if d]
    last_buy = max(candidates) if candidates else None
    days_since_buy = (today - last_buy).days if last_buy else None

    score = 100
    reasons: list[dict] = []
    if days_quiet is None:
        score -= 30
        reasons.append({"tone": "bad", "text": "هیچ تماسی با این مشتری ثبت نشده"})
    elif days_quiet > 90:
        score -= 30
        reasons.append({"tone": "bad", "text": f"{days_quiet} روز بدون تماس"})
    elif days_quiet > 30:
        score -= 15
        reasons.append({"tone": "warn", "text": f"{days_quiet} روز از آخرین تماس گذشته"})
    else:
        reasons.append({"tone": "good", "text": "در تماس منظم"})

    if days_since_buy is None:
        score -= 25
        reasons.append({"tone": "warn", "text": "هنوز خریدی ثبت نشده"})
    elif days_since_buy > 180:
        score -= 25
        reasons.append({"tone": "bad", "text": f"{days_since_buy} روز از آخرین خرید گذشته"})
    elif days_since_buy > 90:
        score -= 10
        reasons.append({"tone": "warn", "text": f"{days_since_buy} روز از آخرین خرید گذشته"})
    else:
        reasons.append({"tone": "good", "text": "خرید اخیر دارد"})

    if active_months >= 6:
        reasons.append({"tone": "good", "text": f"در {active_months} ماه از ۱۲ ماه اخیر خرید داشته"})
    elif active_months == 0 and days_since_buy is not None:
        score -= 10

    if overdue_debt:
        score -= 20
        reasons.append({"tone": "bad", "text": "بدهی سررسیدگذشته دارد"})
    elif inv["unsettled"]:
        reasons.append({"tone": "warn", "text": "فاکتور تسویه‌نشده دارد"})

    overdue_tasks = customer.tasks.filter(done_at__isnull=True, due_at__lt=now).count()
    if overdue_tasks:
        score -= 10
        reasons.append({"tone": "warn", "text": f"{overdue_tasks} کار عقب‌افتاده برای این مشتری"})

    score = max(0, min(100, score))
    label = "خوب" if score >= 70 else "نیازمند توجه" if score >= 40 else "در خطر"

    tasks = customer.tasks.filter(done_at__isnull=True).select_related("owner").order_by("due_at")[:10]
    recent_invoices = invoices.select_related("deal").order_by("-issued_at")[:50]

    return {
        "invoiced": float(inv["amount"] or 0),
        "invoice_count": inv["count"] or 0,
        "unsettled": float(inv["unsettled"] or 0),
        "overdue_debt": float(overdue_debt),
        "last_invoice": jalali_str(inv["last"]) if inv["last"] else "",
        "days_quiet": days_quiet,
        "days_since_buy": days_since_buy,
        "active_months": active_months,
        "series": series,
        "health": {"score": score, "label": label, "reasons": reasons},
        "tasks": TaskSerializer(tasks, many=True).data,
        "invoices": SalesInvoiceSerializer(recent_invoices, many=True).data,
    }


def bulk_assign(request, scoped_qs):
    """
    Set the owner on the selected rows of `scoped_qs`.

    The new owner has to be on this book's roster (`employee_options`), for
    the same reason the single-record picker is limited to it: a customer
    filed under someone who has never worked the book shows up in nobody's
    reports.
    """
    if not is_crm_manager(request.user):
        return Response({"detail": "تغییر کارشناس فقط برای مدیران فروش است."}, status=403)
    ids = [i for i in (request.data.get("ids") or []) if isinstance(i, int)]
    owner_id = request.data.get("owner")
    owner = employee_options(request).filter(pk=owner_id, in_roster=True).first() if owner_id else None
    if not ids or not owner:
        return Response({"detail": "ردیف‌ها و کارشناس جدید را انتخاب کنید."}, status=400)
    updated = scoped_qs.filter(pk__in=ids).update(owner=owner)
    return Response({"updated": updated, "owner_name": owner.full_name_fa})


def deal_summary(qs) -> dict:
    """Totals for a set of deals. Shared by the /summary/ endpoint the
    drill-down header reads and by the Excel export, so the strip above the
    rows and the جمع line inside the file are the same arithmetic."""
    agg = qs.aggregate(
        count=Count("id", distinct=True),
        amount=Sum("amount_rial"),
        profit=Sum("profit_rial"),
        cost=Sum("cost_rial"),
    )
    amount = float(agg["amount"] or 0)
    profit = float(agg["profit"] or 0)
    return {
        "count": agg["count"] or 0,
        "amount": amount,
        "profit": profit,
        "cost": float(agg["cost"] or 0),
        "margin_pct": round(profit / amount * 100, 1) if amount else 0.0,
    }


def activity_summary(qs) -> dict:
    """The call-quality equivalent of `deal_summary`."""
    total = qs.count()
    success = qs.filter(result=Activity.Result.SUCCESS).count()
    return {
        "count": total,
        "success": success,
        "success_rate": round(success / total * 100, 1) if total else 0.0,
        "customers": qs.values("customer_id").distinct().count(),
        "minutes": qs.aggregate(s=Sum("duration_min"))["s"] or 0,
    }


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
        # «فقط بدون استان» — the deals whose customer the map cannot place yet.
        if q.get("no_province") == "1":
            qs = qs.filter(customer__province__isnull=True)
        ids = id_list(self.request)
        if ids:
            qs = qs.filter(pk__in=ids)
        qs = qs.select_related(
            "customer", "customer__province", "customer__group", "owner",
            "stage", "lead_source", "lost_reason",
        ).distinct()
        qs = with_next_action(qs)
        if q.get("next_action") == "missing":
            qs = qs.filter(status=Deal.Status.OPEN, next_task_at__isnull=True)
        return apply_ordering(qs, self.request, self.ORDERING)

    #: Sortable columns of the معامله‌ها table → the lookup behind each.
    ORDERING = {
        "title": "title",
        "customer": "customer__name_fa",
        "owner": "owner__full_name_fa",
        "stage": "stage__order",
        "status": "status",
        "amount": "amount_rial",
        "profit": "profit_rial",
        "opened": "opened_at",
        "closed": "closed_at",
        "expected": "expected_close_date",
    }

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
            # Default to the first open stage of the deal's own book, so a new
            # deal always appears on its board rather than in a stage-less limbo.
            channel = data["customer"].channel if data.get("customer") else data.get("channel", "")
            first = stages_for(channel, active_dataset(self.request)).filter(
                kind=PipelineStage.Kind.OPEN
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
        elif previous_status == Deal.Status.WON and obj.status != Deal.Status.WON:
            Customer.refresh_rollups([obj.customer_id])

    @staticmethod
    def _sync_close(deal: Deal) -> None:
        """
        The stage is the single source of truth: status and the close date are
        derived from it. A won deal with no `closed_at` would vanish from every
        report that measures on the closing date, and a deal moved back to an
        open stage while still flagged won would be counted as revenue twice.
        """
        # A deal moved to another book leaves that book's pipeline behind.
        deal.stage = fit_stage(deal.stage, deal.channel, deal.dataset)
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
        stage, error = self._target_stage(request)
        if error:
            return error
        if not stages_for(deal.channel, deal.dataset).filter(pk=stage.pk).exists():
            return Response({"detail": "این مرحله از قیف این دفتر نیست."}, status=400)
        self._apply_move(deal, stage, request)
        return Response(DealDetailSerializer(deal).data)

    def _target_stage(self, request):
        """The stage a move asks for, or the 400 explaining why not."""
        stage = PipelineStage.objects.filter(
            pk=request.data.get("stage"), dataset=active_dataset(request)
        ).first()
        if not stage:
            return None, Response({"detail": "مرحله نامعتبر است."}, status=400)
        # Same rule as the edit form: a loss with no reason would leave a hole
        # in the "دلایل از دست رفتن" report, and every path into that state
        # has to enforce it — not just the one with a nice prompt attached.
        if stage.kind == PipelineStage.Kind.LOST and not request.data.get("lost_reason"):
            return None, Response(
                {"lost_reason": "برای ثبت فرصت از دست رفته، انتخاب دلیل الزامی است."},
                status=400,
            )
        return stage, None

    def _apply_move(self, deal, stage, request):
        """One deal to one stage, with its stage event — shared by the single
        move and the bulk one so neither can skip the log the funnel reads."""
        previous = deal.stage
        was_won = deal.status == Deal.Status.WON
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
        if was_won and deal.status != Deal.Status.WON:
            Customer.refresh_rollups([deal.customer_id])

        DealStageEvent.objects.create(
            deal=deal, from_stage=previous, to_stage=stage, at=now,
            by=request.user, days_in_previous=days,
        )

    @action(detail=False, methods=["post"], url_path="bulk-move")
    def bulk_move(self, request):
        """
        Move several deals to one stage at once.

        Each still goes through `_apply_move`, so each gets its own stage event
        and its own close date — a bulk path that updated the column in one
        query would be quicker and would leave the funnel report blind to
        every deal moved that way.
        """
        if not can_write_crm(request.user):
            return Response({"detail": CrmWritePermission.message}, status=403)
        stage, error = self._target_stage(request)
        if error:
            return error
        ids = request.data.get("ids") or []
        # Through the scoped queryset: a rep can only move what they can see.
        deals = self.scoped(
            Deal.objects.filter(
                pk__in=[i for i in ids if isinstance(i, int)],
                dataset=active_dataset(request),
            )
        ).select_related("stage", "customer")
        moved = 0
        for deal in deals:
            # Another book's deal stays put: the stage is not on its board.
            if deal.stage_id == stage.id or not stages_for(deal.channel, deal.dataset).filter(pk=stage.pk).exists():
                continue
            self._apply_move(deal, stage, request)
            moved += 1
        return Response({"moved": moved})

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        """Hand several deals to another کارشناس. Managers only — a rep's
        ownership is their scope, so it is not theirs to give away."""
        return bulk_assign(request, self.scoped(
            Deal.objects.filter(dataset=active_dataset(request))
        ))

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
        return Response(deal_summary(self.get_queryset()))


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
        # Recomputed, not overwritten: a call logged today for last week must
        # not pull «آخرین فعالیت» back past yesterday's meeting.
        Customer.refresh_rollups([obj.customer_id])

    def perform_update(self, serializer):
        previous = serializer.instance.customer_id
        super().perform_update(serializer)
        obj = serializer.instance
        obj.period = period_for(obj.at)
        obj.save(update_fields=["period"])
        Customer.refresh_rollups({previous, obj.customer_id})

    def perform_destroy(self, instance):
        customer_id = instance.customer_id
        super().perform_destroy(instance)
        Customer.refresh_rollups([customer_id])

    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(activity_summary(self.get_queryset()))


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


class CrmGeoView(GatedAPIView):
    """
    فروش جغرافیایی — the map. Without `province`, every province on it; with
    one, that province zoomed in: its customers, purchases, cities, products.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter("province", int), OpenApiParameter("owner", int),
            OpenApiParameter("date_from", str), OpenApiParameter("date_to", str),
        ]
    )
    def get(self, request):
        f = query_filters(request)
        pid = f.province
        if pid:
            # The province is the zoom, not a filter on the overview.
            data = rpt.geo_province(replace(f, province=None), pid)
            if data is None:
                return Response({"detail": "استان پیدا نشد."}, status=404)
        else:
            data = rpt.geo_overview(f)
        data["window"] = {
            "start": f.start.isoformat() if f.start else None,
            "end": f.end.isoformat() if f.end else None,
        }
        if request.query_params.get("export") == "1":
            return _geo_workbook(data, request)
        return Response(data)


def _geo_workbook(data: dict, request):
    """فروش جغرافیایی → اکسل, exactly what the map shows: the country, or one province."""
    from apps.crm.export import sheets_workbook

    lbl = {"key": "label", "label": "عنوان", "fmt": "text"}
    amt = {"key": "amount", "label": "فروش (ریال)", "fmt": "rial"}
    context = export_context(request)
    if "customers" not in data:
        sheet = {
            "name": "استان‌ها", "title": "فروش به تفکیک استان",
            "columns": [
                {"key": "label", "label": "استان", "fmt": "text"}, amt,
                {"key": "share_pct", "label": "سهم از کل", "fmt": "pct"},
                {"key": "count", "label": "فاکتور", "fmt": "count"},
                {"key": "customers", "label": "مشتری خریدار", "fmt": "count"},
                {"key": "customer_base", "label": "کل مشتریان", "fmt": "count"},
                {"key": "target", "label": "تارگت (ریال)", "fmt": "rial"},
                {"key": "achievement_pct", "label": "تحقق", "fmt": "pct"},
                {"key": "owner_label", "label": "کارشناسان", "fmt": "text"},
            ],
            "rows": data["rows"],
            "total": {"label": "جمع کل", "amount": data["total"]},
        }
        return xlsx_response(sheets_workbook("فروش جغرافیایی", [sheet], context), "فروش جغرافیایی")

    name = data["label"]
    sheets = [
        {"name": "مشتریان", "title": f"مشتریان {name}", "columns": [
            {"key": "label", "label": "مشتری", "fmt": "text"},
            {"key": "city", "label": "شهر", "fmt": "text"},
            {"key": "owner", "label": "کارشناس", "fmt": "text"},
            {"key": "group", "label": "گروه", "fmt": "text"},
            {"key": "amount", "label": "خرید (ریال)", "fmt": "rial"},
            {"key": "count", "label": "فاکتور", "fmt": "count"},
            {"key": "unsettled", "label": "مانده (ریال)", "fmt": "rial"},
            {"key": "last_purchase", "label": "آخرین خرید", "fmt": "text"},
        ], "rows": [
            {**c, "last_purchase": jalali_str(dt_date(c["last_purchase"])) if c["last_purchase"] else ""}
            for c in data["customers"]
        ], "total": {"label": "جمع کل", "amount": data["amount"], "unsettled": data["unsettled"]}},
        {"name": "آخرین خریدها", "title": f"آخرین خریدهای {name}", "columns": [
            {"key": "number", "label": "برگه", "fmt": "text"},
            {"key": "date", "label": "تاریخ", "fmt": "text"},
            {"key": "customer", "label": "مشتری", "fmt": "text"},
            {"key": "amount", "label": "مبلغ (ریال)", "fmt": "rial"},
            {"key": "unsettled", "label": "مانده (ریال)", "fmt": "rial"},
        ], "rows": [{**r, "date": jalali_str(dt_date(r["date"]))} for r in data["recent"]]},
        {"name": "کالاها", "title": f"پرفروش‌ترین کالاهای {name}", "columns": [
            lbl, amt, {"key": "quantity", "label": "تعداد", "fmt": "count"},
        ], "rows": data["products"]},
        {"name": "شهرها", "title": f"فروش شهرهای {name}", "columns": [
            lbl, amt, {"key": "buyers", "label": "خریدار", "fmt": "count"},
        ], "rows": data["cities"]},
        {"name": "کارشناسان", "title": f"کارشناسان {name}", "columns": [lbl, amt], "rows": data["reps"]},
    ]
    return xlsx_response(sheets_workbook(f"فروش {name}", sheets, context), f"فروش {name}")


def dt_date(iso: str):
    from datetime import date

    return date.fromisoformat(iso[:10])


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


def export_context(request, extra: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """
    The filters behind an export, in words.

    A workbook leaves the app and is read days later by someone who was not
    looking at the screen it came from, so it has to carry its own question:
    which window, whose book, which کارشناس, which narrowing. Names, not ids —
    «استان: اصفهان», not «province=7».
    """
    q = request.query_params
    f = query_filters(request)
    rows: list[tuple[str, str]] = []

    if f.start and f.end:
        last = f.end - timedelta(days=1)
        rows.append(("بازه زمانی", f"{jalali_str(f.start)} تا {jalali_str(last)}"))

    def name_of(model, key, label, field="name_fa"):
        value = q.get(key)
        if not value:
            return
        obj = model.objects.filter(pk=value).first()
        if obj:
            rows.append((label, getattr(obj, field)))

    name_of(DimEmployee, "owner", "کارشناس", "full_name_fa")
    name_of(DimProvince, "province", "استان")
    name_of(CustomerGroup, "group", "گروه مشتری")
    name_of(LeadSource, "source", "منبع سرنخ")
    name_of(Product, "product", "محصول")
    name_of(PipelineStage, "stage", "مرحله فروش")
    name_of(LostReason, "lost_reason", "دلیل عدم موفقیت")
    name_of(Customer, "customer", "مشتری")

    STATUS = {"won": "موفق", "open": "جاری", "lost": "ناموفق"}
    if q.get("status"):
        rows.append(("وضعیت معامله", STATUS.get(q["status"], q["status"])))
    if q.get("search"):
        rows.append(("جستجو", q["search"]))
    if q.get("invoiced") == "0":
        rows.append(("فاکتور", "بدون فاکتور"))
    elif q.get("invoiced") == "1":
        rows.append(("فاکتور", "فاکتورشده"))

    CHANNEL = {
        SalesChannel.TEAM: "فروش همکار",
        SalesChannel.ORGANIZATIONAL: "فروش بانکی",
        SalesChannel.B2B: "فروش B2B",
    }
    if f.channels:
        rows.append(("دفتر", "، ".join(CHANNEL.get(c, c) for c in f.channels)))
    scope = crm_scope(request.user)
    if not scope.sees_all:
        emp = employee_for(request.user)
        rows.append(("محدوده", f"فقط رکوردهای {emp.full_name_fa if emp else 'کاربر'}"))

    rows += extra or []
    rows.append(("تهیه‌شده توسط", request.user.get_full_name() or request.user.username))
    rows.append(("تاریخ خروجی", jalali_str(timezone.now())))
    return rows


def xlsx_response(workbook, filename: str) -> HttpResponse:
    """A workbook as a download, with the Persian filename kept intact."""
    from urllib.parse import quote

    from apps.crm.export import to_stream

    response = HttpResponse(
        to_stream(workbook).read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    safe = quote(f"{filename}.xlsx")
    response["Content-Disposition"] = (
        f"attachment; filename=export.xlsx; filename*=UTF-8''{safe}"
    )
    # The browser reads the name off this header, which CORS hides by default.
    response["Access-Control-Expose-Headers"] = "Content-Disposition"
    return response


class CrmSearchView(GatedAPIView):
    """
    One box, the whole CRM: customers by name, contact, phone or code; deals
    by title or code. Scoped exactly as the lists are — the viewsets do the
    narrowing, so a search can never reveal a row the list would hide.

    Kept small on purpose (a handful of each): this answers «where is X»,
    and the lists answer «show me all of them».
    """

    LIMIT = 6

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"customers": [], "deals": []})

        # Through the list viewset, so the scoping (dataset, book, owner) is
        # the one the customer list applies — not a second copy of it.
        cvs = CustomerViewSet()
        cvs.request = request
        cvs.action, cvs.detail, cvs.kwargs, cvs.format_kwarg = "list", False, {}, None
        customers = cvs.scoped(
            Customer.objects.filter(dataset=active_dataset(request), merged_into__isnull=True)
        ).select_related("group", "province", "owner", "lead_source").filter(
            Q(name_fa__icontains=q) | Q(contact_name__icontains=q)
            | Q(phone__icontains=q) | Q(mobile__icontains=q) | Q(code__icontains=q)
        ).order_by(F("last_activity_at").desc(nulls_last=True))[: self.LIMIT]

        # Deals across every status and all time: «where is the Tolou deal»
        # should not depend on which month the filter bar was left on.
        deals = self_scope_deals(request).filter(
            Q(title__icontains=q) | Q(code__icontains=q) | Q(customer__name_fa__icontains=q)
        ).select_related("customer", "owner", "stage").order_by("-opened_at")[: self.LIMIT]

        return Response({
            "customers": CustomerListSerializer(customers, many=True).data,
            "deals": DealListSerializer(deals, many=True).data,
        })


def self_scope_deals(request):
    """Every deal this account may see, with no time window applied."""
    vs = DealViewSet()
    vs.request = request
    vs.action, vs.detail, vs.kwargs, vs.format_kwarg = "list", False, {}, None
    return vs.scoped(Deal.objects.filter(dataset=active_dataset(request)))


def with_next_action(qs):
    """Each deal's «اقدام بعدی»: its earliest open کار, in one query."""
    first = Task.objects.filter(deal=OuterRef("pk"), done_at__isnull=True).order_by("due_at")
    return qs.annotate(
        next_task_at=Subquery(first.values("due_at")[:1]),
        next_task_title=Subquery(first.values("title")[:1]),
        next_task_id=Subquery(first.values("id")[:1]),
    )


class CrmTodayView(GatedAPIView):
    """
    کارتابل امروز — the working screen, as opposed to the reporting ones.

    Every other CRM screen answers «چه خبر بوده؟» over a window the user
    picks. This one answers «الان باید چه کار کنم؟», which is a different
    question and has no date filter: it is always now. What it surfaces is
    work that is *owed* — a task past its due date, a call that ended in
    «نیاز به پیگیری» and was never followed up, an open deal that has gone
    quiet, a customer who has not been contacted in months — the expensive
    ones first.

    A کارشناس sees their own book; a manager sees the team's and can narrow
    to one person with `?owner=`. That is the ordinary CRM scope applied
    through the same `crm_scope`, not a rule of its own.
    """

    #: An open deal with no activity for this long is not being worked.
    STALE_DEAL_DAYS = 14
    #: A customer who bought before but has heard nothing for this long.
    DORMANT_DAYS = 60
    #: How far ahead «کارهای پیش‌رو» and «نزدیک به بسته‌شدن» look.
    HORIZON_DAYS = 7
    #: Overdue tasks older than this are a backlog, not today's work. CRM was
    #: loaded with sixteen months of دیدار history, so hundreds of tasks are
    #: equally late; listed together they bury the handful that still matter
    #: (a «میز کار» was once removed for exactly that). They are counted and
    #: linked, not listed.
    BACKLOG_DAYS = 60
    #: Rows per list. This is a worklist, not a report: twenty items somebody
    #: can act on today beats four hundred they will scroll past.
    LIMIT = 20

    def get(self, request):
        ds = active_dataset(request)
        scope = crm_scope(request.user)
        now = timezone.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        horizon = now + timedelta(days=self.HORIZON_DAYS)

        asked = request.query_params.get("owner")
        owner_id = int(asked) if (asked or "").isdigit() else None
        if not scope.sees_all:
            # A rep's own book, whatever the URL says.
            owner_id = scope.employee_id
            if owner_id is None:
                return Response(self._empty())

        def mine(qs, field="owner_id"):
            return qs.filter(**{field: owner_id}) if owner_id else qs

        def in_book(qs, field="channel"):
            """Narrow to the books this account covers — the same rule the
            list endpoints apply, and the one it would be dangerous to
            reimplement loosely here."""
            if scope.channels is None:
                return qs
            if not scope.channels:
                return qs.none()
            return qs.filter(**{f"{field}__in": list(scope.channels)})

        # ---- کارها ---------------------------------------------------------
        tasks = mine(Task.objects.filter(dataset=ds, done_at__isnull=True))
        if scope.channels is not None:
            # A کار may stand on its own with no customer behind it; it
            # belongs to nobody's book and must not vanish because of that.
            tasks = (
                tasks.none() if not scope.channels
                else tasks.filter(
                    Q(customer__isnull=True)
                    | Q(customer__channel__in=list(scope.channels))
                )
            )
        tasks = tasks.select_related("customer", "deal", "owner")

        backlog_cut = now - timedelta(days=self.BACKLOG_DAYS)
        # Newest first: yesterday's missed call is more recoverable than one
        # from last season, so it leads.
        overdue_qs = tasks.filter(due_at__lt=now, due_at__gte=backlog_cut).order_by("-due_at")
        backlog = tasks.filter(due_at__lt=backlog_cut).count()
        today_qs = tasks.filter(due_at__gte=now, due_at__lte=today_end).order_by("due_at")
        upcoming_qs = tasks.filter(due_at__gt=today_end, due_at__lte=horizon).order_by("due_at")

        # ---- قول پیگیری ----------------------------------------------------
        # A call that ended in «نیاز به پیگیری» and is still the customer's
        # latest contact: the promise was made and nothing happened since.
        follow = in_book(
            mine(Activity.objects.filter(
                dataset=ds,
                result=Activity.Result.FOLLOW_UP,
                at__gte=now - timedelta(days=90),
            )),
            "customer__channel",
        ).select_related("customer", "owner", "deal")
        pending = [
            a for a in follow.order_by("-at")[:200]
            if not Activity.objects.filter(customer_id=a.customer_id, at__gt=a.at)
            .exclude(pk=a.pk).exists()
        ][: self.LIMIT]

        # ---- معاملات راکد --------------------------------------------------
        stale_cut = now - timedelta(days=self.STALE_DEAL_DAYS)
        stale_qs = in_book(
            mine(Deal.objects.filter(dataset=ds, status=Deal.Status.OPEN))
        ).annotate(last_touch=Max("activities__at")).filter(
            Q(last_touch__lt=stale_cut)
            | Q(last_touch__isnull=True, opened_at__lt=stale_cut)
        ).select_related("customer", "owner", "stage")

        # ---- بدون اقدام بعدی -----------------------------------------------
        # An open deal with no dated next step: nobody owes it anything, so it
        # will not surface anywhere else — the book's «هشدار مستقیم ضعف پیگیری».
        no_next = with_next_action(in_book(
            mine(Deal.objects.filter(dataset=ds, status=Deal.Status.OPEN))
        )).filter(next_task_at__isnull=True).select_related("customer", "owner", "stage")

        # ---- نزدیک به بسته‌شدن ----------------------------------------------
        closing = in_book(mine(Deal.objects.filter(
            dataset=ds, status=Deal.Status.OPEN,
            expected_close_date__isnull=False,
            expected_close_date__lte=horizon.date(),
        ))).select_related("customer", "owner", "stage").order_by("expected_close_date")

        # ---- مشتریان بی‌تماس ------------------------------------------------
        quiet_cut = now - timedelta(days=self.DORMANT_DAYS)
        quiet = in_book(mine(Customer.objects.filter(
            dataset=ds,
            status__in=[Customer.Status.ACTIVE, Customer.Status.DORMANT],
        ))).filter(
            Q(last_activity_at__lt=quiet_cut) | Q(last_activity_at__isnull=True)
        ).select_related("owner", "province", "group").order_by("-first_deal_won_at")

        # ---- امروز تا اینجا --------------------------------------------------
        open_deals = in_book(mine(Deal.objects.filter(dataset=ds, status=Deal.Status.OPEN)))
        # `weighted_rial` is a property, so the forecast is summed in the
        # query rather than by walking every open deal in Python.
        open_agg = open_deals.aggregate(
            count=Count("id"),
            amount=Sum("amount_rial"),
            weighted=Sum(
                F("amount_rial") * Coalesce("probability_pct", "stage__probability_pct") / Value(100),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            ),
        )

        return Response({
            "as_of": jalali_str(now),
            "owner": owner_id,
            "counters": {
                "overdue": overdue_qs.count(),
                "backlog": backlog,
                "due_today": today_qs.count(),
                "pending_follow_up": len(pending),
                "stale_deals": stale_qs.count(),
                "no_next_action": no_next.count(),
                "quiet_customers": quiet.count(),
                "activities_today": mine(
                    Activity.objects.filter(dataset=ds, at__gte=day_start)
                ).count(),
                "open_count": open_agg["count"] or 0,
                "open_amount": float(open_agg["amount"] or 0),
                "open_weighted": float(open_agg["weighted"] or 0),
            },
            "overdue": TaskSerializer(overdue_qs[: self.LIMIT], many=True).data,
            "due_today": TaskSerializer(today_qs[: self.LIMIT], many=True).data,
            "upcoming": TaskSerializer(upcoming_qs[: self.LIMIT], many=True).data,
            "pending_follow_up": ActivitySerializer(pending, many=True).data,
            "stale_deals": DealListSerializer(
                stale_qs.order_by("-amount_rial")[: self.LIMIT], many=True
            ).data,
            "closing_soon": DealListSerializer(closing[: self.LIMIT], many=True).data,
            "no_next_action": DealListSerializer(
                no_next.order_by("-amount_rial")[: self.LIMIT], many=True
            ).data,
            "quiet_customers": CustomerListSerializer(quiet[: self.LIMIT], many=True).data,
            "thresholds": {
                "stale_days": self.STALE_DEAL_DAYS,
                "dormant_days": self.DORMANT_DAYS,
                "horizon_days": self.HORIZON_DAYS,
                "backlog_days": self.BACKLOG_DAYS,
            },
        })

    def _empty(self):
        """An account with no salesperson behind it owns nothing — and must
        not be handed the team's worklist as a consolation."""
        return {
            "as_of": jalali_str(timezone.now()), "owner": None,
            "counters": {k: 0 for k in (
                "overdue", "backlog", "due_today", "pending_follow_up", "stale_deals", "no_next_action",
                "quiet_customers", "activities_today", "open_count",
                "open_amount", "open_weighted",
            )},
            "overdue": [], "due_today": [], "upcoming": [],
            "pending_follow_up": [], "stale_deals": [], "closing_soon": [], "no_next_action": [],
            "quiet_customers": [],
            "thresholds": {
                "stale_days": self.STALE_DEAL_DAYS,
                "dormant_days": self.DORMANT_DAYS,
                "horizon_days": self.HORIZON_DAYS,
                "backlog_days": self.BACKLOG_DAYS,
            },
        }


class CrmReportExportView(GatedAPIView):
    """گزارش‌ها → اکسل. The report exactly as the screen shows it."""

    def get(self, request, key: str):
        from apps.crm.export import report_workbook

        if key not in rpt.REPORTS:
            return Response(
                {"detail": f"گزارش «{key}» تعریف نشده است."},
                status=status.HTTP_404_NOT_FOUND,
            )
        f = query_filters(request)
        data = rpt.run_report(key, f, request.query_params.get("axis") or "")
        context = export_context(request, [("محور گزارش", rpt.AXIS_LABELS.get(data["axis"], data["axis"]))])
        wb = report_workbook(data, context)
        return xlsx_response(wb, data["title"])


#: Which viewset answers for each drill kind. The export reuses the list
#: endpoints rather than rebuilding their queries, so an exported file and the
#: drawer it was opened from cannot list different records — and the scoping
#: those viewsets apply (dataset, channel, owner) is applied here too, which
#: is the half that would be dangerous to reimplement.
DRILL_VIEWSETS = {
    "deals": "DealViewSet",
    "customers": "CustomerViewSet",
    "activities": "ActivityViewSet",
    "feedback": "CustomerFeedbackViewSet",
    "invoices": "SalesInvoiceViewSet",
    "tasks": "TaskViewSet",
}


class CrmDrillExportView(GatedAPIView):
    """
    ریز رکوردها → اکسل: every record behind a number, not one page of them.

    The in-browser CSV this replaces serialised whatever the drawer had
    loaded — 25 rows — under a header that said how many thousands there
    were. A file that quietly holds 6٪ of what it claims is worse than no
    export button at all.
    """

    #: A ceiling, so one click cannot try to stream a million rows into
    #: memory. Far above any real drill-down; if it is ever hit, the file
    #: says so on its «فیلترها» sheet rather than truncating in silence.
    MAX_ROWS = 20000

    def get(self, request):
        from apps.crm.export import KIND_TITLE, drill_workbook

        # `export_kind`, not `kind`: the list's own filters read `kind` (an
        # activity's type), so the two must not share a name.
        kind = request.query_params.get("export_kind") or "deals"
        if kind not in DRILL_VIEWSETS:
            return Response(
                {"detail": f"نوع «{kind}» تعریف نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        viewset = globals()[DRILL_VIEWSETS[kind]]()
        viewset.request = request
        viewset.action = "list"
        viewset.detail = False
        viewset.kwargs = {}
        viewset.format_kwarg = None
        qs = viewset.filter_queryset(viewset.get_queryset())

        total = qs.count()
        rows = viewset.get_serializer(qs[: self.MAX_ROWS], many=True).data
        if kind == "tasks":
            now = timezone.now().isoformat()
            rows = [
                {**r, "state": "انجام شده" if r.get("is_done")
                 else ("عقب‌افتاده" if (r.get("due_at") or "") < now else "باز")}
                for r in rows
            ]

        title = request.query_params.get("title") or KIND_TITLE.get(kind, "ریز اطلاعات")
        extra: list[tuple[str, str]] = []
        if total > self.MAX_ROWS:
            extra.append((
                "هشدار",
                f"{total:,} رکورد یافت شد؛ {self.MAX_ROWS:,} ردیف نخست در این فایل است.",
            ))

        summary = None
        if kind == "deals":
            summary = deal_summary(qs)
        elif kind == "activities":
            summary = activity_summary(qs)

        wb = drill_workbook(kind, [dict(r) for r in rows], title,
                            export_context(request, extra), summary)
        return xlsx_response(wb, title)


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
        if f.group is not None:
            qs = qs.filter(customer__group_id=f.group or None)
        if f.province is not None:
            qs = qs.filter(customer__province_id=f.province or None)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(customer__name_fa__icontains=search)
            )
        # When each deal was last worked. A card's age says how long it has
        # existed; this says whether anyone is still on it, which is the
        # question a manager scanning the board is actually asking.
        qs = qs.select_related("customer", "owner", "stage").annotate(
            last_touch=Max("activities__at"),
        )
        now = timezone.now()

        by_stage: dict[int, list] = {}
        idle: dict[int, int | None] = {}
        for deal in qs:
            by_stage.setdefault(deal.stage_id, []).append(deal)
            touch = deal.last_touch or deal.opened_at
            idle[deal.id] = (now - touch).days if touch else None

        forecast = self._forecast(
            [d for deals in by_stage.values() for d in deals], now.date()
        )

        columns = []
        for st, label in stages_in_view(f.channels, ds):
            deals = by_stage.get(st.id, [])
            columns.append({
                "id": st.id,
                "name_fa": label,
                "channel": st.channel,
                "kind": st.kind,
                "order": st.order,
                "probability_pct": st.probability_pct,
                "count": len(deals),
                "amount": float(sum(d.amount_rial for d in deals)),
                "weighted": float(sum(d.weighted_rial for d in deals)),
                "deals": [
                    {**row, "idle_days": idle.get(row["id"])}
                    for row in DealListSerializer(deals, many=True).data
                ],
            })
        return Response({"columns": columns, "forecast": forecast})

    @staticmethod
    def _forecast(deals, today) -> list[dict]:
        """
        The weighted pipeline by the month each deal is expected to close.

        «ارزش وزنی» on its own is one number with no date on it — it says how
        much is likely, not when. Bucketing by `expected_close_date` answers
        the question a sales manager is asked upstairs: how much lands this
        month, next month, later. Deals with no date, or a date already
        passed, are shown as such rather than folded into «this month», where
        they would inflate the figure everyone reads first.
        """
        this_key = jalali_month_of(today)
        # The day after this Jalali month ends — Gregorian month arithmetic
        # would land back inside the same Jalali month for part of it.
        _start, month_end = month_bounds(*this_key)
        next_key = jalali_month_of(month_end)

        buckets = {
            "overdue": {"key": "overdue", "label": "تاریخش گذشته", "count": 0, "amount": 0.0, "weighted": 0.0},
            "this": {"key": "this", "label": f"این ماه ({month_label(*this_key)})", "count": 0, "amount": 0.0, "weighted": 0.0},
            "next": {"key": "next", "label": f"ماه بعد ({month_label(*next_key)})", "count": 0, "amount": 0.0, "weighted": 0.0},
            "later": {"key": "later", "label": "بعدتر", "count": 0, "amount": 0.0, "weighted": 0.0},
            "none": {"key": "none", "label": "بدون تاریخ", "count": 0, "amount": 0.0, "weighted": 0.0},
        }
        for d in deals:
            when = d.expected_close_date
            if not when:
                b = "none"
            elif when < today:
                b = "overdue"
            else:
                key = jalali_month_of(when)
                b = "this" if key == this_key else "next" if key == next_key else "later"
            buckets[b]["count"] += 1
            buckets[b]["amount"] += float(d.amount_rial)
            buckets[b]["weighted"] += float(d.weighted_rial)
        return list(buckets.values())


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


def has_sample_data() -> bool:
    """Whether `seed_crm_sample` rows are loaded — the screen must say so."""
    return Customer.objects.filter(code__startswith="seed-").exists()


class CrmOptionsView(GatedAPIView):
    """Every filter dropdown the CRM UI needs, in one request."""

    @staticmethod
    def _zones() -> list[dict]:
        SalesZone.ensure_tehran()
        return [
            {"id": z.id, "name_fa": z.name_fa, "province": z.province_id,
             "channel": z.channel, "is_default": z.is_default}
            for z in SalesZone.objects.all()
        ]

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
            "sample_data": has_sample_data(),
            "provinces": [
                {"id": p.id, "name_fa": p.name_fa}
                for p in DimProvince.objects.all()
            ],
            "zones": self._zones(),
            # The employee dimension carries a placeholder row with no real
            # name; it must not show up in a filter dropdown.
            "employees": [
                {"id": e.id, "name": e.full_name_fa,
                 "team": e.team.name_fa if e.team else "",
                 # False: owns records here but is no longer on the sales
                 # roster — a label for old rows, not a choice for new ones.
                 "active": e.in_roster}
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

    pagination_class = CrmPagination

    permission_classes = [SystemAdminOnly]
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
        confidence = self.request.query_params.get("confidence")
        if confidence:
            qs = qs.filter(confidence=confidence)
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
        by_confidence = dict(
            qs.filter(state=CustomerMatchCandidate.State.PENDING)
            .values_list("confidence").annotate(n=Count("id"))
        )
        return Response({
            "by_confidence": by_confidence,
            "by_method": [
                {"key": k, "label": label, "count": by_method.get(k, 0)}
                for k, label in CustomerMatchCandidate.Method.choices
                if by_method.get(k)
            ],
            "by_state": by_state,
            "pending": by_state.get(CustomerMatchCandidate.State.PENDING, 0),
        })

    @action(detail=False, methods=["post"])
    def scan(self, request):
        """
        «جست‌وجوی تکراری‌ها» — the whole customer file against itself.

        `dry_run` counts without queueing. Queued pairs wait for a person;
        nothing here merges, however sure the match.
        """
        pairs, crowded = crm_merge.find_pairs(active_dataset(request))
        definite = sum(1 for p in pairs if p["confidence"] == "definite")
        queued = 0 if request.data.get("dry_run") else crm_merge.queue_found(pairs)
        return Response({
            "found": len(pairs), "definite": definite, "suspect": len(pairs) - definite,
            "queued": queued, "crowded": crowded,
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



class TerritoryAssignmentViewSet(viewsets.ModelViewSet):
    """
    مسئولان استان‌ها و محدوده‌ها. Everyone in CRM reads them (the map shows
    them); a manager assigns. Only roster members can be assigned, and a
    department manager assigns only in their own books.
    """

    permission_classes = [CrmAccess]
    pagination_class = None
    serializer_class = TerritoryAssignmentSerializer
    queryset = TerritoryAssignment.objects.select_related("province", "zone", "employee")

    def get_queryset(self):
        qs = super().get_queryset()
        channels = crm_scope(self.request.user).channels
        return qs if channels is None else qs.filter(channel__in=channels)

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in SAFE_METHODS and not is_crm_manager(request.user):
            self.permission_denied(request, message="تعیین مسئول استان با مدیر فروش است.")

    def perform_create(self, serializer):
        from apps.crm.people import sales_roster

        channels = crm_scope(self.request.user).channels
        channel = serializer.validated_data.get("channel") or (channels[0] if channels else SalesChannel.TEAM)
        if channels is not None and channel not in channels:
            raise ValidationError({"channel": ["این دفتر در دسترس شما نیست."]})
        emp = serializer.validated_data["employee"]
        if not sales_roster([channel]).filter(pk=emp.pk).exists():
            raise ValidationError({"employee": [f"«{emp.full_name_fa}» در فهرست کارشناسان فعال این واحد فروش نیست."]})
        zone = serializer.validated_data.get("zone")
        if zone and zone.province_id != serializer.validated_data["province"].pk:
            raise ValidationError({"zone": ["محدوده به این استان تعلق ندارد."]})
        if serializer.validated_data.get("role") == TerritoryAssignment.Role.MANAGER:
            # One manager per province (zone) and channel: assigning a new one
            # replaces the old, which is what «change manager» means.
            TerritoryAssignment.objects.filter(
                province=serializer.validated_data["province"], zone=zone,
                channel=channel, role=TerritoryAssignment.Role.MANAGER,
            ).delete()
        serializer.save(channel=channel)


class CrmConfigView(GatedAPIView):
    """تنظیمات تشخیص تکراری — read by everyone in CRM, changed by a manager."""

    FIELDS = ("fuzzy_threshold", "match_phone", "queue_on_import")

    def _out(self, cfg):
        return {
            "fuzzy_threshold": float(cfg.fuzzy_threshold),
            "match_phone": cfg.match_phone,
            "queue_on_import": cfg.queue_on_import,
        }

    def get(self, request):
        from apps.crm.models import CrmConfig

        return Response(self._out(CrmConfig.get()))

    def patch(self, request):
        from apps.crm.models import CrmConfig

        if not is_crm_manager(request.user):
            return Response({"detail": "تنظیمات با مدیر فروش است."}, status=status.HTTP_403_FORBIDDEN)
        cfg = CrmConfig.get()
        data = request.data
        if "fuzzy_threshold" in data:
            try:
                value = Decimal(str(data["fuzzy_threshold"]))
            except Exception:
                value = None
            if value is None or not Decimal("0.5") <= value <= Decimal("1"):
                return Response({"fuzzy_threshold": ["عددی بین ۰٫۵ و ۱ وارد کنید."]},
                                status=status.HTTP_400_BAD_REQUEST)
            cfg.fuzzy_threshold = value.quantize(Decimal("0.01"))
        for flag in ("match_phone", "queue_on_import"):
            if flag in data:
                setattr(cfg, flag, bool(data[flag]))
        cfg.save()
        return Response(self._out(cfg))


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

    pagination_class = CrmPagination

    permission_classes = [CrmAccess]
    serializer_class = SalesInvoiceSerializer
    queryset = SalesInvoice.objects.all()

    def get_queryset(self):
        qs = query_filters(self.request).invoices().select_related(
            "customer", "customer__owner", "owner", "deal", "deal__owner"
        )
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(number__icontains=search)
                | Q(customer__name_fa__icontains=search)
                | Q(party_name__icontains=search)
            )
        return qs.order_by("-issued_at", "-number")


# --------------------------------------------------------------------------
# ورود از آرپا — upload an export, and rule on فروش سوری
# --------------------------------------------------------------------------
MAX_UPLOAD = 25 * 1024 * 1024


class ArpaImportView(GatedAPIView):
    """
    GET  — the upload history.
    POST — `file`, `book`, `commit`. Without `commit=1` it is a preview: the
    import runs and is rolled back, so the counts shown before «ثبت» are
    exactly what «ثبت» does.
    """

    permission_classes = [SystemAdminOnly]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        from apps.crm.models import ImportBatch, Review

        rows = [
            {
                "id": b.pk, "file_name": b.file_name, "book": b.book,
                "book_display": b.get_book_display(), "at": b.created_at.isoformat(),
                "by": getattr(b.uploaded_by, "display_name_fa", "") or getattr(b.uploaded_by, "username", ""),
                "rows": b.rows, "created": b.created, "updated": b.updated,
                "unchanged": b.unchanged, "skipped": b.skipped, "suspect": b.suspect,
                "customers_created": b.customers_created, "amount": float(b.amount_rial),
                "date_from": jalali_str(b.date_from) if b.date_from else "",
                "date_to": jalali_str(b.date_to) if b.date_to else "",
            }
            for b in ImportBatch.objects.filter(source=ImportBatch.Source.ARPA).select_related("uploaded_by")[:40]
        ]
        return Response({
            "imports": rows,
            "pending_suspect": SalesInvoice.objects.filter(review=Review.SUSPECT).count(),
        })

    def post(self, request):
        from apps.crm.arpa_file import ArpaFileError
        from apps.crm.arpa_import import run

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "فایلی انتخاب نشده است."}, status=400)
        if upload.size > MAX_UPLOAD:
            return Response({"detail": "حجم فایل بیش از ۲۵ مگابایت است."}, status=400)
        commit = str(request.data.get("commit", "")).lower() in {"1", "true", "yes"}
        try:
            result = run(
                upload.read(), upload.name, request.data.get("book") or "main",
                user=request.user, commit=commit,
            )
        except ArpaFileError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(result)


class SuspectInvoiceView(GatedAPIView):
    """
    فروش سوری: invoices whose «مسوول فروش» was not a sales group.

    GET  — `state` = suspect (default) | real | fake, optional `search`.
    POST — `ids`, `decision` = real | fake | suspect, and `channel` when
    ruling real: the sales group is what was missing, so the person who
    says «it is real» also says whose.
    """

    permission_classes = [SystemAdminOnly]
    VALID_CHANNELS = {"team", "organizational", "b2b"}

    def get(self, request):
        from apps.crm.models import Review

        state = request.query_params.get("state") or Review.SUSPECT
        qs = SalesInvoice.objects.filter(review=state).select_related(
            "customer", "owner", "reviewed_by",
        )
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(number__icontains=search) | Q(party_name__icontains=search)
                | Q(customer__name_fa__icontains=search)
            )
        counts = {
            r["review"]: {"count": r["n"], "amount": float(r["a"] or 0)}
            for r in SalesInvoice.objects.exclude(review="").values("review")
            .annotate(n=Count("id"), a=Sum("amount_rial")).order_by()
        }
        rows = [
            {
                "id": i.pk, "number": i.number, "kind": i.kind,
                "book": i.book, "book_display": i.get_book_display(),
                "issued_jalali": jalali_str(i.issued_at),
                "customer_id": i.customer_id,
                "customer": i.customer.name_fa if i.customer_id else i.party_name,
                "amount": float(i.amount_rial),
                "owner": i.owner.full_name_fa if i.owner_id else "",
                "created_by": i.created_by_name,
                "responsible": i.sales_responsible,
                "payment_terms": i.payment_terms,
                "channel": i.channel,
                "reviewed_by": getattr(i.reviewed_by, "username", "") if i.reviewed_by_id else "",
                "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None,
            }
            for i in qs.order_by("-issued_at", "-number")[:500]
        ]
        if request.query_params.get("export") == "1":
            from apps.crm.export import sheets_workbook

            label = dict(Review.choices).get(state, state)
            sheet = {
                "name": "فروش سوری", "title": f"فروش سوری — {label}",
                "subtitle": f"{len(rows):,} فاکتور",
                "columns": [
                    {"key": "number", "label": "شماره برگه", "fmt": "text"},
                    {"key": "issued_jalali", "label": "تاریخ", "fmt": "text"},
                    {"key": "book_display", "label": "دفتر", "fmt": "text"},
                    {"key": "customer", "label": "مشتری", "fmt": "text"},
                    {"key": "owner", "label": "بازاریاب", "fmt": "text"},
                    {"key": "created_by", "label": "ایجادکننده", "fmt": "text"},
                    {"key": "responsible", "label": "مسوول فروش", "fmt": "text"},
                    {"key": "payment_terms", "label": "شرایط تسویه", "fmt": "text"},
                    {"key": "amount", "label": "مبلغ فروش (ریال)", "fmt": "rial"},
                ],
                "rows": rows,
                "total": {"number": "جمع کل", "amount": sum(r["amount"] for r in rows)},
            }
            return xlsx_response(sheets_workbook("فروش سوری", [sheet], []), "فروش سوری")
        return Response({"state": state, "rows": rows, "counts": counts})

    def post(self, request):
        from apps.crm.models import Review

        ids = [int(x) for x in request.data.get("ids") or [] if str(x).isdigit()]
        decision = request.data.get("decision")
        channel = request.data.get("channel") or ""
        if not ids or decision not in Review.values:
            return Response({"detail": "فاکتور و تصمیم را مشخص کنید."}, status=400)
        if decision == Review.REAL and channel not in self.VALID_CHANNELS:
            return Response({"detail": "برای فروش واقعی، گروه فروش را انتخاب کنید."}, status=400)
        # Only invoices that came in as suspect can be ruled on here; an
        # ordinary sale is not turned into a «سوری» one through this door.
        qs = SalesInvoice.objects.filter(pk__in=ids).exclude(review="")
        update = {"review": decision, "reviewed_by": request.user, "reviewed_at": timezone.now()}
        if decision == Review.REAL:
            update["channel"] = channel
        elif decision == Review.SUSPECT:
            update.update(reviewed_by=None, reviewed_at=None, channel="")
        from apps.crm.arpa_import import sync_deal

        targets = list(qs)
        with transaction.atomic():
            done = qs.update(**update)
            # «واقعی» gives the invoice its won deal; «سوری» takes it away.
            for invoice in SalesInvoice.objects.filter(pk__in=[i.pk for i in targets]):
                sync_deal(invoice)
        return Response({"updated": done})


class DidarImportView(GatedAPIView):
    """
    ورود از دیدار — people, companies, deals, activities, notes; never
    invoices. GET is the history; POST takes any number of `files` and
    `commit` (without it, a preview that is rolled back).
    """

    permission_classes = [SystemAdminOnly]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        from apps.crm.models import ImportBatch

        return Response({"imports": [
            {
                "id": b.pk, "file_name": b.file_name, "at": b.created_at.isoformat(),
                "by": getattr(b.uploaded_by, "username", ""), "rows": b.rows,
                "created": b.created, "updated": b.updated, "unchanged": b.unchanged,
                "skipped": b.skipped, "customers_created": b.customers_created,
            }
            for b in ImportBatch.objects.filter(source=ImportBatch.Source.DIDAR)
            .select_related("uploaded_by")[:40]
        ]})

    def post(self, request):
        from apps.crm.arpa_file import ArpaFileError
        from apps.crm.didar_import import run

        uploads = request.FILES.getlist("files")
        if not uploads:
            return Response({"detail": "فایلی انتخاب نشده است."}, status=400)
        if sum(u.size for u in uploads) > MAX_UPLOAD * 2:
            return Response({"detail": "حجم فایل‌ها بیش از ۵۰ مگابایت است."}, status=400)
        commit = str(request.data.get("commit", "")).lower() in {"1", "true", "yes"}
        try:
            result = run([(u.name, u.read()) for u in uploads], user=request.user, commit=commit)
        except ArpaFileError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(result)


class CrmWipeView(GatedAPIView):
    """
    پاک‌سازی داده. GET — what would go and what stays. POST with
    `confirm` equal to the phrase — do it. Customers and products stay; see
    `apps.crm.wipe`.
    """

    permission_classes = [SystemAdminOnly]

    def get(self, request):
        from apps.crm import wipe

        return Response(wipe.counts())

    def post(self, request):
        from apps.crm import wipe

        if (request.data.get("confirm") or "").strip() != wipe.CONFIRM:
            return Response(
                {"detail": f"برای تأیید، عبارت «{wipe.CONFIRM}» را دقیق بنویسید."}, status=400,
            )
        removed = wipe.wipe()
        return Response({"removed": removed, **wipe.counts()})


class TeamyarImportView(GatedAPIView):
    """
    ورود مشتریان از تیم‌یار. Rows land on the customer CRM already has, by
    the آرپا/دیدار code in «آخرین توضیحات» or an id no one else shares —
    see `apps.crm.teamyar_import`. Same preview-then-commit as the others.
    """

    permission_classes = [SystemAdminOnly]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        from apps.crm.models import ImportBatch

        return Response({"imports": [
            {
                "id": b.pk, "file_name": b.file_name, "at": b.created_at.isoformat(),
                "by": getattr(b.uploaded_by, "username", ""), "rows": b.rows,
                "created": b.created, "updated": b.updated, "unchanged": b.unchanged,
                "skipped": b.skipped,
            }
            for b in ImportBatch.objects.filter(source=ImportBatch.Source.TEAMYAR)
            .select_related("uploaded_by")[:40]
        ]})

    def post(self, request):
        from apps.crm.arpa_file import ArpaFileError
        from apps.crm.teamyar_import import run

        uploads = request.FILES.getlist("files")
        if not uploads:
            return Response({"detail": "فایلی انتخاب نشده است."}, status=400)
        commit = str(request.data.get("commit", "")).lower() in {"1", "true", "yes"}
        try:
            result = run([(u.name, u.read()) for u in uploads], user=request.user, commit=commit)
        except ArpaFileError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(result)


class CrmChecksView(GatedAPIView):
    """کنترل داده — every check, its count and the first records behind it."""

    permission_classes = [SystemAdminOnly]

    def get(self, request):
        from apps.crm import checks

        return Response(checks.run())


def _dashboard_sheets(data: dict) -> list[dict]:
    """The dashboard as tables: every tile with its previous period, then every widget."""
    unit = {"rial": "ریال", "count": "تعداد", "percent": "درصد", "days": "روز"}
    cards = []
    for c in data["cards"]:
        prev = c.get("prev")
        change = None
        if prev not in (None, 0) and c["unit"] != "percent":
            change = round((float(c["value"]) - float(prev)) / abs(float(prev)) * 100, 1)
        cards.append({"label": c["label"], "value": c["value"], "unit": unit.get(c["unit"], ""),
                      "prev": prev, "change": change})

    lbl = {"key": "label", "label": "عنوان", "fmt": "text"}
    amt = {"key": "amount", "label": "مبلغ (ریال)", "fmt": "rial"}
    cnt = {"key": "count", "label": "تعداد", "fmt": "count"}

    def t(name, rows, cols):
        return {"name": name, "columns": cols, "rows": rows}

    return [
        t("شاخص‌ها", cards, [
            {"key": "label", "label": "شاخص", "fmt": "text"},
            {"key": "value", "label": "مقدار", "fmt": "count"},
            {"key": "unit", "label": "واحد", "fmt": "text"},
            {"key": "prev", "label": "دوره قبل", "fmt": "count"},
            {"key": "change", "label": "تغییر (٪)", "fmt": "pct"},
        ]),
        t("روند فروش", data["trend"], [lbl, amt, {"key": "profit", "label": "سود (ریال)", "fmt": "rial"}, cnt]),
        t("فرصت‌های جدید", data["incoming_trend"], [
            lbl, {"key": "won_count", "label": "موفق", "fmt": "count"},
            {"key": "open_count", "label": "جاری", "fmt": "count"},
            {"key": "lost_count", "label": "ناموفق", "fmt": "count"}]),
        t("فروشندگان", data["top_sellers"], [lbl, amt, cnt]),
        t("قیف فروش", data["funnel"], [lbl, cnt, amt]),
        t("دلایل از دست رفتن", data["lost_reasons"], [lbl, cnt, amt]),
        t("فعالیت‌ها", data["activities_by_kind"], [lbl, cnt]),
        t("منابع سرنخ", data["sources"], [lbl, amt, {"key": "conversion_pct", "label": "نرخ تبدیل", "fmt": "pct"}]),
        t("استان‌ها", data["provinces"], [
            lbl, {"key": "owner_label", "label": "کارشناس", "fmt": "text"}, amt,
            {"key": "target", "label": "تارگت (ریال)", "fmt": "rial"},
            {"key": "achievement_pct", "label": "تحقق", "fmt": "pct"}]),
        t("گروه مشتری", data["by_group"], [lbl, amt, cnt]),
        t("مشتریان جدید", data["new_customers_by_user"], [lbl, cnt]),
    ]


class CrmDashboardExportView(GatedAPIView):
    """داشبورد → اکسل: every tile (with the previous period) and every widget."""

    def get(self, request):
        from apps.crm.export import sheets_workbook

        data = rpt.dashboard(query_filters(request))
        wb = sheets_workbook("داشبورد CRM", _dashboard_sheets(data), export_context(request))
        return xlsx_response(wb, "داشبورد CRM")


class CrmChecksExportView(GatedAPIView):
    """کنترل داده → اکسل: a summary, then a sheet per check that found something."""

    permission_classes = [SystemAdminOnly]

    def get(self, request):
        from apps.crm import checks
        from apps.crm.export import sheets_workbook

        result = checks.run()
        sev = {"high": "جدی", "medium": "مهم", "low": "تکمیلی"}
        sheets = [{
            "name": "خلاصه", "title": "کنترل داده‌ی CRM",
            "columns": [
                {"key": "label", "label": "بررسی", "fmt": "text"},
                {"key": "severity", "label": "اهمیت", "fmt": "text"},
                {"key": "count", "label": "تعداد", "fmt": "count"},
                {"key": "why", "label": "توضیح", "fmt": "text"},
            ],
            "rows": [{**c, "severity": sev[c["severity"]]} for c in result["checks"]],
        }]
        for i, c in enumerate(r for r in result["checks"] if r["count"]):
            shown = len(c["rows"])
            sheets.append({
                # Sheet names must be unique and at most 31 characters.
                "name": f"{i + 1}. {c['label']}"[:31], "title": c["label"],
                "subtitle": f"{c['count']:,} مورد" + (f" — {shown} مورد اول" if c["count"] > shown else ""),
                "columns": [
                    {"key": "title", "label": "رکورد", "fmt": "text"},
                    {"key": "customer", "label": "مشتری", "fmt": "text"},
                    {"key": "detail", "label": "جزئیات", "fmt": "text"},
                    {"key": "id", "label": "شناسه", "fmt": "text"},
                ],
                "rows": c["rows"],
            })
        return xlsx_response(sheets_workbook("کنترل داده", sheets, []), "کنترل داده CRM")
