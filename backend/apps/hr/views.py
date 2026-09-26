"""منابع انسانی API — the chart, the people, and the archive."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.hr.models import OrgUnit, Position
from apps.hr.permissions import HrAccess
from apps.hr.serializers import OrgUnitSerializer, PersonSerializer, PositionSerializer
from apps.hr.services import people as people_service
from apps.hr.services.names import normalize
from apps.hr.services.rosters import sync_rosters
from apps.sales.models import DimEmployee


class OrgUnitViewSet(viewsets.ModelViewSet):
    queryset = OrgUnit.objects.all()
    serializer_class = OrgUnitSerializer
    permission_classes = [HrAccess]
    pagination_class = None

    def perform_create(self, serializer):
        unit = serializer.save()
        audit_log(self.request.user, unit, AuditLog.Action.CREATE)
        sync_rosters()

    def perform_update(self, serializer):
        unit = serializer.save()
        audit_log(self.request.user, unit, AuditLog.Action.UPDATE)
        sync_rosters()

    def perform_destroy(self, instance):
        if instance.children.exists():
            raise ValidationError({"detail": "این واحد زیرواحد دارد؛ اول آن‌ها را حذف یا جابه‌جا کنید."})
        if instance.positions.filter(holder__isnull=False).exists():
            raise ValidationError({"detail": "در این واحد هنوز کسی سمت دارد؛ اول سمت‌ها را خالی کنید."})
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()
        sync_rosters()


class PositionViewSet(viewsets.ModelViewSet):
    queryset = Position.objects.select_related("unit", "holder")
    serializer_class = PositionSerializer
    permission_classes = [HrAccess]
    pagination_class = None

    def perform_create(self, serializer):
        position = serializer.save()
        audit_log(self.request.user, position, AuditLog.Action.CREATE)
        sync_rosters()

    def perform_update(self, serializer):
        before = serializer.instance.holder_id
        position = serializer.save()
        audit_log(self.request.user, position, AuditLog.Action.UPDATE,
                  {"holder": {"before": before, "after": position.holder_id}})
        sync_rosters()

    def perform_destroy(self, instance):
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()
        sync_rosters()


class PersonViewSet(viewsets.ModelViewSet):
    """
    افراد. `?status=active` (default) · `archived` · `unplaced` — active people
    who hold no position, the list that shows who the chart has forgotten.
    """

    serializer_class = PersonSerializer
    permission_classes = [HrAccess]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            DimEmployee.objects.select_related("user")
            .prefetch_related(
                Prefetch("positions", queryset=Position.objects.select_related("unit")),
                "memberships",
            )
            .annotate(sales_n=Count("sales", distinct=True))
            .order_by("full_name_fa")
        )
        if self.action != "list":
            return qs
        state = self.request.query_params.get("status", "active")
        if state == "archived":
            return qs.filter(is_active=False).order_by("-archived_at", "full_name_fa")
        qs = qs.filter(is_active=True)
        if state == "unplaced":
            qs = qs.filter(positions__isnull=True)
        return qs

    def create(self, request, *args, **kwargs):
        name = request.data.get("full_name_fa", "")
        existing = people_service.find_by_name(name, include_archived=True)
        if existing and not request.data.get("force"):
            return Response({
                "detail": f"«{existing.full_name_fa}» قبلا ثبت شده"
                          f"{' و در بایگانی است' if not existing.is_active else ''}.",
                "duplicate": PersonSerializer(existing).data,
            }, status=status.HTTP_409_CONFLICT)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        person = serializer.save(code=people_service.new_code())
        audit_log(self.request.user, person, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        person = serializer.save()
        audit_log(self.request.user, person, AuditLog.Action.UPDATE)

    # -- permanent delete: the main administrator only ---------------------
    @staticmethod
    def _assert_superuser(user):
        if not user.is_superuser:
            raise PermissionDenied("حذف دائمی فقط برای ادمین اصلی مجاز است.")

    @action(detail=True, methods=["get"], url_path="delete-preview")
    def delete_preview(self, request, pk=None):
        """What «حذف دائمی» would take with it — shown before anyone confirms."""
        self._assert_superuser(request.user)
        return Response(people_service.delete_impact(self.get_object()))

    def destroy(self, request, *args, **kwargs):
        """
        حذف دائمی, with or without data. Archive is the normal way out; this is
        for rows that should never have existed (a junk import, a test name).

        The caller must send the person's exact name as `confirm` — a stray
        DELETE, or a click on the wrong row, deletes nothing.
        """
        self._assert_superuser(request.user)
        person = self.get_object()
        confirm_name = str(request.data.get("confirm") or request.query_params.get("confirm") or "")
        if confirm_name.strip() != person.full_name_fa.strip():
            raise ValidationError({"confirm": "برای حذف دائمی، نام کامل فرد را دقیقا وارد کنید."})
        label, pk_value = str(person), person.pk
        impact = people_service.hard_delete(person)
        AuditLog.objects.create(
            user=request.user, action=AuditLog.Action.DELETE,
            model_label="sales.DimEmployee", object_id=str(pk_value),
            object_repr=label[:200], changes={"permanent_delete": impact},
        )
        return Response(impact, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        person = self.get_object()
        people_service.archive(person, str(request.data.get("note", "")))
        audit_log(request.user, person, AuditLog.Action.UPDATE,
                  {"is_active": {"before": True, "after": False}})
        return Response(PersonSerializer(self.get_queryset().get(pk=person.pk)).data)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        person = self.get_object()
        people_service.restore(person)
        audit_log(request.user, person, AuditLog.Action.UPDATE,
                  {"is_active": {"before": False, "after": True}})
        return Response(PersonSerializer(self.get_queryset().get(pk=person.pk)).data)

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """Fold this person (the duplicate) into `into` (the real one)."""
        source = self.get_object()
        target = DimEmployee.objects.filter(pk=request.data.get("into") or 0).first()
        if target is None:
            raise ValidationError({"into": "فردی که باید در او ادغام شود را انتخاب کنید."})
        label = str(source)
        moved = people_service.merge(source, target)
        audit_log(request.user, target, AuditLog.Action.UPDATE,
                  {"merged": {"before": label, "after": str(target)}})
        return Response({"moved": moved, "person": PersonSerializer(self.get_queryset().get(pk=target.pk)).data})

    @action(detail=True, methods=["post"])
    def account(self, request, pk=None):
        """
        ساخت حساب کاربری برای این فرد.

        Goes through the admin panel's own user serializer, so the password
        policy and the security record are exactly what «کاربر جدید» there
        applies — this is a shortcut to the same act, not a second way to
        make an account with weaker rules. Only an administrator may do it.
        """
        from apps.adminpanel.permissions import require
        from apps.adminpanel.serializers import AdminUserSerializer

        if not request.user.is_admin_panel_user:
            raise PermissionDenied("ساخت حساب کاربری فقط برای ادمین مجاز است.")
        require(request.user, "users.create")

        person = self.get_object()
        if person.user_id:
            raise ValidationError({"detail": "این فرد حساب کاربری دارد."})

        data = {
            "display_name_fa": person.full_name_fa,
            "phone": person.mobile,
            "role": "operator",
            "is_active": True,
            **{k: v for k, v in request.data.items() if k in {
                "username", "password", "role", "department",
                "display_name_fa", "job_title_fa", "phone", "email",
            }},
        }
        if not data.get("job_title_fa"):
            first = person.positions.select_related("unit").first()
            if first:
                data["job_title_fa"] = first.title_fa

        with transaction.atomic():
            serializer = AdminUserSerializer(data=data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
            person.user = user
            person.save(update_fields=["user", "updated_at"])
        audit_log(request.user, user, AuditLog.Action.CREATE,
                  {"employee": {"before": None, "after": person.full_name_fa}})
        return Response(
            PersonSerializer(self.get_queryset().get(pk=person.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="link-account")
    def link_account(self, request, pk=None):
        """
        وصل کردن حساب کاربری موجود به این فرد.

        For someone who already signs in — an account made in the admin panel
        before this person was on the chart. Creating a second login for them
        would split their records between two accounts, so the one they have
        is attached instead. Same gate as creating one: attaching a login
        decides whose CRM and sales records it opens.
        """
        from apps.adminpanel.permissions import require

        if not request.user.is_admin_panel_user:
            raise PermissionDenied("وصل کردن حساب کاربری فقط برای ادمین مجاز است.")
        require(request.user, "users.create")

        person = self.get_object()
        if person.user_id:
            raise ValidationError({"detail": "این فرد حساب کاربری دارد."})

        user = get_user_model().objects.filter(pk=request.data.get("user") or 0).first()
        if user is None:
            raise ValidationError({"user": "حساب کاربری را انتخاب کنید."})
        if not user.is_active:
            raise ValidationError({"user": "این حساب غیرفعال است؛ اول از پنل ادمین فعالش کنید."})
        taken = DimEmployee.objects.filter(user=user).exclude(pk=person.pk).first()
        if taken is not None:
            raise ValidationError({"user": f"این حساب به «{taken.full_name_fa}» وصل است."})

        person.user = user
        person.save(update_fields=["user", "updated_at"])
        audit_log(request.user, person, AuditLog.Action.UPDATE,
                  {"user": {"before": None, "after": user.username}})
        return Response(PersonSerializer(self.get_queryset().get(pk=person.pk)).data)

    @action(detail=False, methods=["get"])
    def duplicates(self, request):
        """Groups of people whose names match once spelling is ignored."""
        ids = [[e.id for e in group] for group in people_service.duplicate_groups()]
        by_id = {e.id: e for e in self.get_queryset().filter(id__in=[i for g in ids for i in g])}
        return Response([
            [PersonSerializer(by_id[i]).data for i in group if i in by_id] for group in ids
        ])

    @action(detail=False, methods=["get"])
    def accounts(self, request):
        """Login accounts, and who each is already attached to."""
        linked = dict(DimEmployee.objects.exclude(user=None).values_list("user_id", "full_name_fa"))
        return Response([
            {"id": u.id, "username": u.username, "name": u.display_name_fa or u.username,
             "linked_to": linked.get(u.id, "")}
            for u in get_user_model().objects.filter(is_active=True).order_by("username")
        ])


class ChartView(APIView):
    """The whole chart as a tree, with each seat and its holder."""

    permission_classes = [HrAccess]

    @extend_schema(responses=dict)
    def get(self, request):
        units = list(OrgUnit.objects.all())
        seats: dict[int, list[dict]] = {}
        for p in Position.objects.select_related("holder"):
            seats.setdefault(p.unit_id, []).append({
                "id": p.id, "title": p.title_fa, "is_head": p.is_head,
                "on_sales_sheet": p.on_sales_sheet, "note": p.note,
                "holder": p.holder_id, "holder_name": p.holder.full_name_fa if p.holder else "",
                "holder_user": p.holder.user_id if p.holder else None,
            })
        nodes = {
            u.id: {**OrgUnitSerializer(u).data, "positions": seats.get(u.id, []), "children": []}
            for u in units
        }
        roots = []
        for u in units:
            (nodes[u.parent_id]["children"] if u.parent_id in nodes else roots).append(nodes[u.id])

        all_seats = [s for rows in seats.values() for s in rows]
        return Response({
            "roots": roots,
            "stats": {
                "units": len(units),
                "positions": len(all_seats),
                "vacant": sum(1 for s in all_seats if not s["holder"]),
                "people": len({s["holder"] for s in all_seats if s["holder"]}),
                "unplaced": DimEmployee.objects.filter(is_active=True, positions__isnull=True).count(),
                "archived": DimEmployee.objects.filter(is_active=False).count(),
                "duplicates": len(people_service.duplicate_groups()),
            },
        })


class ChartImportView(APIView):
    """Load the company's chart into an empty one — the first-run button."""

    permission_classes = [HrAccess]

    @extend_schema(responses=dict)
    def post(self, request):
        return Response(people_service.import_chart(), status=status.HTTP_201_CREATED)


class RosterSyncView(APIView):
    permission_classes = [HrAccess]

    @extend_schema(responses=dict)
    def post(self, request):
        return Response(sync_rosters())


__all__ = ["normalize"]
