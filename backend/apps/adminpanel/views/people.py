"""Users (1), roles & permissions (2), teams (3)."""
from __future__ import annotations

import secrets

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.adminpanel.models import (
    AppRole,
    PasswordPolicy,
    Team,
    TeamMembership,
    UserRoleAssignment,
    UserSecurity,
)
from apps.adminpanel.permissions import (
    PERMISSION_CATALOG,
    effective_permissions,
    require,
)
from apps.adminpanel.serializers import (
    AdminUserSerializer,
    AppRoleSerializer,
    TeamMembershipSerializer,
    TeamSerializer,
)
from apps.adminpanel.services import security as sec_service
from apps.adminpanel.views.base import AdminModelViewSet
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog


# ==========================================================================
# 1 · User management
# ==========================================================================
class AdminUserViewSet(AdminModelViewSet):
    """
    Full user administration. Every destructive action is permission-checked
    and audited, and three guard rails are enforced regardless of permissions:
    you cannot delete or lock yourself, and only a superuser may touch another
    superuser.
    """

    queryset = (
        User.objects.select_related("security")
        .prefetch_related("admin_roles__role", "team_memberships__team")
        .order_by("id")
    )
    serializer_class = AdminUserSerializer
    read_permission = "users.view"
    write_permission = "users.edit"
    filterset_fields = ["role", "department", "is_active", "is_superuser", "admin_access"]
    search_fields = ["username", "display_name_fa", "email", "phone", "job_title_fa"]
    ordering_fields = ["id", "username", "display_name_fa", "last_login", "date_joined"]
    export_title = "کاربران"
    export_columns = [
        ("username", "نام کاربری"), ("name", "نام"), ("role_label", "نقش"),
        ("department_label", "بخش"), ("is_active", "فعال"),
        ("is_admin_panel_user", "دسترسی پنل"), ("last_login", "آخرین ورود"),
        ("date_joined", "تاریخ ایجاد"),
    ]

    # -- guard rails -----------------------------------------------------
    def _guard(self, target: User, *, action_label: str, allow_self: bool = False):
        if not allow_self and target.pk == self.request.user.pk:
            raise PermissionDenied(f"{action_label} روی حساب خودتان مجاز نیست.")
        if target.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("تنها ادمین ارشد می‌تواند حساب ادمین ارشد را تغییر دهد.")

    def create(self, request, *args, **kwargs):
        require(request.user, "users.create")
        return super().create(request, *args, **kwargs)

    def perform_destroy(self, instance):
        require(self.request.user, "users.delete")
        self._guard(instance, action_label="حذف")
        audit_log(self.request.user, instance, AuditLog.Action.DELETE,
                  {"username": {"before": instance.username, "after": None}})
        instance.delete()

    def perform_update(self, serializer):
        target = serializer.instance
        if target.pk == self.request.user.pk:
            # Nobody may quietly take away their own panel access or role.
            for field in ("admin_access", "role", "is_active"):
                if field in serializer.validated_data and getattr(
                    target, field
                ) != serializer.validated_data[field]:
                    raise PermissionDenied(
                        "تغییر نقش، فعال‌بودن یا دسترسی ادمینِ حساب خودتان مجاز نیست."
                    )
        elif target.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("ویرایش ادمین ارشد فقط توسط ادمین ارشد ممکن است.")
        return super().perform_update(serializer)

    # -- password --------------------------------------------------------
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        """Set a password, or generate one. The plaintext is returned once."""
        require(request.user, "users.password")
        user = self.get_object()
        if user.is_superuser and not request.user.is_superuser:
            raise PermissionDenied("تغییر رمز ادمین ارشد فقط توسط ادمین ارشد ممکن است.")

        password = request.data.get("password") or ""
        generated = False
        if not password:
            password = secrets.token_urlsafe(9)
            generated = True

        errors = PasswordPolicy.get().validate(password)
        if errors and not generated:
            raise ValidationError({"password": errors})

        user.set_password(password)
        user.save(update_fields=["password"])

        state = UserSecurity.get(user)
        state.password_changed_at = timezone.now()
        state.must_change_password = bool(request.data.get("must_change", True))
        state.failed_attempts = 0
        state.locked_until = None
        state.save()

        if request.data.get("force_logout", True):
            sec_service.force_logout(user)

        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"password": {"before": "***", "after": "reset"}})
        return Response({
            "ok": True,
            "password": password if generated else None,
            "must_change_password": state.must_change_password,
            "message": "رمز عبور بازنشانی شد."
                       + (" رمز جدید فقط همین یک بار نمایش داده می‌شود." if generated else ""),
        })

    # -- activation / lock ----------------------------------------------
    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        require(request.user, "users.edit")
        user = self.get_object()
        self._guard(user, action_label="فعال/غیرفعال کردن")
        user.is_active = bool(request.data.get("is_active", True))
        user.save(update_fields=["is_active"])
        if not user.is_active:
            sec_service.force_logout(user)
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"is_active": {"before": str(not user.is_active), "after": str(user.is_active)}})
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        require(request.user, "users.lock")
        user = self.get_object()
        self._guard(user, action_label="قفل کردن")
        state = UserSecurity.get(user)
        state.is_locked = True
        state.lock_reason = (request.data.get("reason") or "")[:200]
        state.save(update_fields=["is_locked", "lock_reason", "updated_at"])
        sec_service.force_logout(user)
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"locked": {"before": "False", "after": "True"}})
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        require(request.user, "users.lock")
        user = self.get_object()
        state = UserSecurity.get(user)
        state.is_locked = False
        state.lock_reason = ""
        state.locked_until = None
        state.failed_attempts = 0
        state.save()
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"locked": {"before": "True", "after": "False"}})
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"], url_path="force-logout")
    def force_logout(self, request, pk=None):
        require(request.user, "security.sessions")
        user = self.get_object()
        sec_service.force_logout(user)
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"session": {"before": "active", "after": "revoked"}})
        return Response({"ok": True, "message": "همه نشست‌های این کاربر پایان یافت."})

    # -- assignments -----------------------------------------------------
    @action(detail=True, methods=["post"], url_path="assign-roles")
    def assign_roles(self, request, pk=None):
        """Replace the user's admin roles with the given set."""
        require(request.user, "roles.assign")
        user = self.get_object()
        role_ids = request.data.get("role_ids")
        if not isinstance(role_ids, list):
            raise ValidationError({"role_ids": "آرایه‌ای از شناسه نقش لازم است."})
        roles = list(AppRole.objects.filter(id__in=role_ids))
        before = sorted(a.role.code for a in user.admin_roles.all())
        with transaction.atomic():
            user.admin_roles.all().delete()
            UserRoleAssignment.objects.bulk_create([
                UserRoleAssignment(user=user, role=r, granted_by=request.user)
                for r in roles
            ])
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"admin_roles": {"before": "، ".join(before),
                                   "after": "، ".join(sorted(r.code for r in roles))}})
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["post"], url_path="assign-teams")
    def assign_teams(self, request, pk=None):
        require(request.user, "teams.members")
        user = self.get_object()
        team_ids = request.data.get("team_ids")
        if not isinstance(team_ids, list):
            raise ValidationError({"team_ids": "آرایه‌ای از شناسه تیم لازم است."})
        teams = list(Team.objects.filter(id__in=team_ids))
        with transaction.atomic():
            user.team_memberships.all().delete()
            TeamMembership.objects.bulk_create([
                TeamMembership(user=user, team=t) for t in teams
            ])
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"teams": {"before": None, "after": "، ".join(t.code for t in teams)}})
        return Response(self.get_serializer(user).data)

    # -- history ---------------------------------------------------------
    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        """This user's audit trail + login history, for the profile drawer."""
        require(request.user, "audit.view")
        user = self.get_object()
        from apps.adminpanel.serializers import LoginEventSerializer
        from apps.core.models import AuditLog as AL
        from apps.core.serializers import AuditLogSerializer

        return Response({
            "audit": AuditLogSerializer(
                AL.objects.filter(user=user).select_related("user")[:50], many=True
            ).data,
            "logins": LoginEventSerializer(
                user.login_events.all()[:50], many=True
            ).data,
            "permissions": sorted(effective_permissions(user)),
        })

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts for the users page header chips."""
        from django.db.models import Count

        qs = User.objects.all()
        return Response({
            "total": qs.count(),
            "active": qs.filter(is_active=True).count(),
            "inactive": qs.filter(is_active=False).count(),
            "locked": qs.filter(security__is_locked=True).count(),
            "admins": qs.filter(admin_access=True).count()
                      + qs.filter(role="admin").exclude(admin_access=True).count(),
            "by_role": {
                row["role"]: row["n"]
                for row in qs.values("role").annotate(n=Count("id"))
            },
        })


# ==========================================================================
# 2 · Roles & permissions
# ==========================================================================
class AppRoleViewSet(AdminModelViewSet):
    queryset = AppRole.objects.select_related("created_by").all()
    serializer_class = AppRoleSerializer
    read_permission = "roles.view"
    write_permission = "roles.manage"
    filterset_fields = ["is_active", "is_system"]
    search_fields = ["code", "name_fa", "description"]
    export_title = "نقش‌ها"
    export_columns = [
        ("code", "کد"), ("name_fa", "نام"), ("description", "توضیح"),
        ("user_count", "تعداد کاربر"), ("is_system", "سیستمی"), ("is_active", "فعال"),
    ]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        audit_log(self.request.user, instance, AuditLog.Action.CREATE,
                  {"permissions": {"before": None,
                                   "after": str(len(instance.permissions))}})
        return instance

    def perform_destroy(self, instance):
        if instance.is_system:
            raise PermissionDenied("نقش‌های سیستمی قابل حذف نیستند (می‌توانید غیرفعالشان کنید).")
        if instance.assignments.exists():
            raise PermissionDenied(
                f"این نقش به {instance.assignments.count()} کاربر داده شده؛ ابتدا آن‌ها را جدا کنید."
            )
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def clone(self, request, pk=None):
        """Duplicate a role — the fastest way to build a variant."""
        require(request.user, "roles.manage")
        source = self.get_object()
        code = request.data.get("code") or f"{source.code}-copy"
        if AppRole.objects.filter(code=code).exists():
            raise ValidationError({"code": "این کد قبلاً استفاده شده است."})
        clone = AppRole.objects.create(
            code=code,
            name_fa=request.data.get("name_fa") or f"{source.name_fa} (کپی)",
            description=source.description,
            permissions=list(source.permissions or []),
            color=source.color,
            is_system=False,
            created_by=request.user,
        )
        audit_log(request.user, clone, AuditLog.Action.CREATE,
                  {"cloned_from": {"before": None, "after": source.code}})
        return Response(self.get_serializer(clone).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def catalog(self, request):
        """The permission vocabulary + the caller's own effective codes."""
        return Response({
            "catalog": PERMISSION_CATALOG,
            "mine": sorted(effective_permissions(request.user)),
            "is_superuser": request.user.is_superuser,
        })

    @action(detail=False, methods=["get"])
    def matrix(self, request):
        """Roles × permissions grid for the permission-matrix screen."""
        require(request.user, "roles.view")
        roles = list(AppRole.objects.all())
        return Response({
            "catalog": PERMISSION_CATALOG,
            "roles": [
                {
                    "id": r.id, "code": r.code, "name_fa": r.name_fa,
                    "color": r.color, "is_system": r.is_system,
                    "is_active": r.is_active,
                    "permissions": r.permissions or [],
                    "user_count": r.assignments.count(),
                }
                for r in roles
            ],
        })

    @action(detail=True, methods=["get"])
    def users(self, request, pk=None):
        from apps.adminpanel.serializers import UserBriefSerializer

        role = self.get_object()
        members = User.objects.filter(admin_roles__role=role)
        return Response(UserBriefSerializer(members, many=True).data)


# ==========================================================================
# 3 · Teams
# ==========================================================================
class TeamViewSet(AdminModelViewSet):
    queryset = Team.objects.select_related("manager", "parent").prefetch_related(
        "memberships__user"
    )
    serializer_class = TeamSerializer
    read_permission = "teams.view"
    write_permission = "teams.manage"
    filterset_fields = ["department", "is_active", "parent"]
    search_fields = ["code", "name_fa", "description"]
    export_title = "تیم‌ها"
    export_columns = [
        ("name_fa", "تیم"), ("code", "کد"), ("department_label", "بخش"),
        ("manager_name", "مدیر"), ("parent_name", "تیم بالادست"),
        ("member_count", "تعداد اعضا"), ("is_active", "فعال"),
    ]

    @action(detail=True, methods=["post"], url_path="add-member")
    def add_member(self, request, pk=None):
        require(request.user, "teams.members")
        team = self.get_object()
        user_id = request.data.get("user_id")
        user = User.objects.filter(pk=user_id).first()
        if not user:
            raise ValidationError({"user_id": "کاربر یافت نشد."})
        membership, created = TeamMembership.objects.get_or_create(
            user=user, team=team,
            defaults={"is_lead": bool(request.data.get("is_lead"))},
        )
        if not created and "is_lead" in request.data:
            membership.is_lead = bool(request.data["is_lead"])
            membership.save(update_fields=["is_lead"])
        audit_log(request.user, team, AuditLog.Action.UPDATE,
                  {"member_added": {"before": None, "after": user.username}})
        return Response(TeamMembershipSerializer(membership).data)

    @action(detail=True, methods=["post"], url_path="remove-member")
    def remove_member(self, request, pk=None):
        require(request.user, "teams.members")
        team = self.get_object()
        deleted, _ = TeamMembership.objects.filter(
            team=team, user_id=request.data.get("user_id")
        ).delete()
        audit_log(request.user, team, AuditLog.Action.UPDATE,
                  {"member_removed": {"before": str(request.data.get("user_id")),
                                      "after": None}})
        return Response({"removed": deleted})

    @action(detail=False, methods=["get"])
    def tree(self, request):
        """Nested hierarchy for the org-chart view."""
        teams = list(self.get_queryset())
        by_parent: dict[int | None, list] = {}
        for t in teams:
            by_parent.setdefault(t.parent_id, []).append(t)

        def build(parent_id):
            return [
                {
                    "id": t.id, "code": t.code, "name_fa": t.name_fa,
                    "department": t.department, "is_active": t.is_active,
                    "manager_name": str(t.manager) if t.manager else "",
                    "member_count": t.member_count,
                    "children": build(t.id),
                }
                for t in by_parent.get(parent_id, [])
            ]

        return Response(build(None))
