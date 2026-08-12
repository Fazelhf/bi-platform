"""7 · Audit logs and 8 · Security."""
from __future__ import annotations

import hashlib
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.adminpanel.models import ApiToken, IPRule, LoginEvent, PasswordPolicy, UserSecurity
from apps.adminpanel.permissions import AdminPanelPermission, require
from apps.adminpanel.serializers import (
    ApiTokenSerializer,
    IPRuleSerializer,
    LoginEventSerializer,
    PasswordPolicySerializer,
)
from apps.adminpanel.services import security as sec_service
from apps.adminpanel.views.base import AdminModelViewSet, AdminReadOnlyViewSet
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.core.serializers import AuditLogSerializer


# ==========================================================================
# 7 · Audit log
# ==========================================================================
class AdminAuditLogViewSet(AdminReadOnlyViewSet):
    """Append-only history with search, date filtering and export."""

    queryset = AuditLog.objects.select_related("user")
    serializer_class = AuditLogSerializer
    read_permission = "audit.view"
    filterset_fields = ["action", "model_label", "user"]
    search_fields = ["object_repr", "model_label", "object_id", "user__username"]
    ordering_fields = ["created_at"]
    export_title = "رخدادها"
    export_columns = [
        ("created_at", "زمان"), ("display_name", "کاربر"), ("username", "نام کاربری"),
        ("action", "عملیات"), ("model_label", "موجودیت"),
        ("object_repr", "رکورد"), ("changes", "تغییرات"),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("from"):
            qs = qs.filter(created_at__gte=params["from"])
        if params.get("to"):
            qs = qs.filter(created_at__lte=params["to"])
        if params.get("days"):
            try:
                since = timezone.now() - timedelta(days=int(params["days"]))
                qs = qs.filter(created_at__gte=since)
            except ValueError:
                pass
        return qs

    # Re-decorated: overriding the base method would otherwise drop the
    # @action metadata the router needs to register the route.
    @action(detail=False, methods=["get"])
    def export(self, request, *args, **kwargs):
        """Exporting the audit trail is its own permission, not just `view`."""
        require(request.user, "audit.export")
        return super().export(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts by action / model / user for the audit page charts."""
        days = int(request.query_params.get("days", 30) or 30)
        since = timezone.now() - timedelta(days=days)
        qs = AuditLog.objects.filter(created_at__gte=since)
        return Response({
            "window_days": days,
            "total": qs.count(),
            "by_action": list(qs.values("action").annotate(n=Count("id")).order_by("-n")),
            "by_model": list(
                qs.values("model_label").annotate(n=Count("id")).order_by("-n")[:15]
            ),
            "by_user": [
                {
                    "user": row["user__username"] or "سیستم",
                    "name": row["user__display_name_fa"] or "",
                    "n": row["n"],
                }
                for row in qs.values("user__username", "user__display_name_fa")
                .annotate(n=Count("id")).order_by("-n")[:15]
            ],
            "models": list(
                AuditLog.objects.values_list("model_label", flat=True).distinct()
            ),
        })


class LoginEventViewSet(AdminReadOnlyViewSet):
    queryset = LoginEvent.objects.select_related("user")
    serializer_class = LoginEventSerializer
    read_permission = "security.view"
    filterset_fields = ["success", "user", "reason"]
    search_fields = ["username_attempted", "ip_address", "user_agent"]
    ordering_fields = ["created_at"]
    export_title = "تاریخچه ورود"
    export_columns = [
        ("created_at", "زمان"), ("username_attempted", "نام کاربری"),
        ("success", "موفق"), ("reason_fa", "علت"), ("ip_address", "IP"),
        ("user_agent", "مرورگر"),
    ]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        days = int(request.query_params.get("days", 7) or 7)
        since = timezone.now() - timedelta(days=days)
        qs = LoginEvent.objects.filter(created_at__gte=since)
        return Response({
            "window_days": days,
            "total": qs.count(),
            "success": qs.filter(success=True).count(),
            "failed": qs.filter(success=False).count(),
            "by_reason": list(
                qs.filter(success=False).values("reason")
                .annotate(n=Count("id")).order_by("-n")
            ),
            "top_ips": list(
                qs.filter(success=False).exclude(ip_address=None)
                .values("ip_address").annotate(n=Count("id")).order_by("-n")[:10]
            ),
        })


# ==========================================================================
# 8 · Security
# ==========================================================================
class PasswordPolicyView(APIView):
    permission_classes = [AdminPanelPermission]
    read_permission = "security.view"
    write_permission = "security.manage"

    def get(self, request):
        return Response(PasswordPolicySerializer(PasswordPolicy.get()).data)

    def patch(self, request):
        require(request.user, "security.manage")
        policy = PasswordPolicy.get()
        serializer = PasswordPolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = PasswordPolicySerializer(policy).data
        saved = serializer.save()
        after = PasswordPolicySerializer(saved).data
        audit_log(request.user, saved, AuditLog.Action.UPDATE, {
            k: {"before": str(before[k]), "after": str(after[k])}
            for k in after if before.get(k) != after.get(k)
        })
        return Response(after)


class IPRuleViewSet(AdminModelViewSet):
    queryset = IPRule.objects.select_related("created_by")
    serializer_class = IPRuleSerializer
    read_permission = "security.view"
    write_permission = "security.manage"
    filterset_fields = ["mode", "is_active"]
    search_fields = ["cidr", "note"]
    export_title = "قواعد IP"
    export_columns = [("mode", "نوع"), ("cidr", "آدرس"), ("note", "توضیح"),
                      ("is_active", "فعال")]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        audit_log(self.request.user, instance, AuditLog.Action.CREATE,
                  {"cidr": {"before": None, "after": instance.cidr}})
        return instance


class SessionView(APIView):
    """
    Live sessions and force-logout. The platform authenticates with JWTs, so a
    "session" is an account with a fresh presence heartbeat; ending one bumps
    `tokens_valid_from`, which invalidates every token already issued.
    """

    permission_classes = [AdminPanelPermission]
    read_permission = "security.sessions"
    write_permission = "security.sessions"

    def get(self, request):
        return Response(sec_service.active_sessions())

    def post(self, request):
        require(request.user, "security.sessions")
        user_ids = request.data.get("user_ids")
        if request.data.get("all"):
            targets = User.objects.exclude(pk=request.user.pk)
        elif isinstance(user_ids, list) and user_ids:
            targets = User.objects.filter(pk__in=user_ids)
        else:
            raise ValidationError({"user_ids": "فهرست کاربران یا all=true لازم است."})
        count = 0
        for user in targets:
            sec_service.force_logout(user)
            count += 1
        audit_log(request.user, request.user, AuditLog.Action.UPDATE,
                  {"force_logout": {"before": None, "after": str(count)}})
        return Response({"logged_out": count})


class ApiTokenViewSet(AdminModelViewSet):
    """
    Machine tokens. The plaintext is returned exactly once, on create — the
    database only ever holds its SHA-256 hash.
    """

    queryset = ApiToken.objects.select_related("user")
    serializer_class = ApiTokenSerializer
    read_permission = "security.tokens"
    write_permission = "security.tokens"
    filterset_fields = ["is_active", "user"]
    search_fields = ["name", "prefix"]

    def create(self, request, *args, **kwargs):
        require(request.user, "security.tokens")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw, prefix, digest = ApiToken.generate()
        token = serializer.save(prefix=prefix, key_hash=digest)
        audit_log(request.user, token, AuditLog.Action.CREATE,
                  {"token": {"before": None, "after": prefix + "…"}})
        data = self.get_serializer(token).data
        data["token"] = raw
        data["warning"] = "این توکن فقط همین یک بار نمایش داده می‌شود."
        return Response(data, status=201)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        require(request.user, "security.tokens")
        token = self.get_object()
        token.is_active = False
        token.save(update_fields=["is_active", "updated_at"])
        audit_log(request.user, token, AuditLog.Action.UPDATE,
                  {"is_active": {"before": "True", "after": "False"}})
        return Response(self.get_serializer(token).data)

    @action(detail=False, methods=["post"])
    def verify(self, request):
        """Check a token string without storing it — useful when debugging."""
        require(request.user, "security.tokens")
        raw = request.data.get("token") or ""
        digest = hashlib.sha256(raw.encode()).hexdigest()
        token = ApiToken.objects.filter(key_hash=digest).first()
        if not token:
            return Response({"valid": False, "reason": "یافت نشد"})
        return Response({
            "valid": token.is_active and not token.is_expired,
            "name": token.name,
            "user": str(token.user),
            "expired": token.is_expired,
            "active": token.is_active,
        })


class SecurityOverviewView(APIView):
    """Everything the security page shows above the tables."""

    permission_classes = [AdminPanelPermission]
    read_permission = "security.view"

    def get(self, request):
        policy = PasswordPolicy.get()
        day_ago = timezone.now() - timedelta(days=1)
        week_ago = timezone.now() - timedelta(days=7)
        return Response({
            "policy": PasswordPolicySerializer(policy).data,
            "locked_users": [
                {
                    "id": s.user_id, "username": s.user.username,
                    "name": str(s.user), "reason": s.lock_reason,
                    "locked_until": s.locked_until, "is_locked": s.is_locked,
                }
                for s in UserSecurity.objects.select_related("user").filter(
                    Q(is_locked=True) | Q(locked_until__gt=timezone.now())
                )
            ],
            "twofa_enabled": User.objects.filter(
                two_factor_enabled=True, is_active=True
            ).exclude(phone="").count(),
            "must_change_password": UserSecurity.objects.filter(
                must_change_password=True
            ).count(),
            "failed_24h": LoginEvent.objects.filter(
                success=False, created_at__gte=day_ago
            ).count(),
            "failed_7d": LoginEvent.objects.filter(
                success=False, created_at__gte=week_ago
            ).count(),
            "active_sessions": len(sec_service.active_sessions()),
            "ip_rules": {
                "enforced": policy.enforce_ip_rules,
                "allow": IPRule.objects.filter(mode="allow", is_active=True).count(),
                "deny": IPRule.objects.filter(mode="deny", is_active=True).count(),
            },
            "tokens": {
                "active": ApiToken.objects.filter(is_active=True).count(),
                "expired": ApiToken.objects.filter(
                    is_active=True, expires_at__lt=timezone.now()
                ).count(),
            },
        })


class TwoFactorView(APIView):
    """
    2FA administration, over the SMS two-factor the login flow enforces.

    An administrator can only ever turn 2FA **off** here. Turning it on takes
    a code delivered to the account's own phone, which is the whole point of
    the second factor — the user proves the number is theirs — and a switch
    that skipped that step would lock out anyone whose number is stale or
    missing, from a screen where nobody would notice.

    An earlier version of this view drove UserSecurity.twofa_enabled and a
    TOTP secret nothing verified. Those columns are left alone here; the login
    path reads User.two_factor_enabled, so that is what the panel reports and
    changes.
    """

    permission_classes = [AdminPanelPermission]
    read_permission = "security.view"
    write_permission = "security.manage"

    def get(self, request):
        rows = User.objects.filter(two_factor_enabled=True).exclude(phone="")
        return Response({
            "enforced_at_login": True,
            "users": [
                {"id": u.id, "username": u.username, "name": str(u),
                 "enabled_at": u.two_factor_enabled_at}
                for u in rows
            ],
        })

    def post(self, request):
        require(request.user, "security.manage")

        user = User.objects.filter(pk=request.data.get("user_id")).first()
        if not user:
            raise ValidationError({"user_id": "کاربر یافت نشد."})
        enable = bool(request.data.get("enabled"))
        if enable:
            raise ValidationError({"enabled": (
                "فعال‌سازی ورود دو مرحله‌ای فقط توسط خود کاربر و با تأیید کد "
                "پیامکی ممکن است. از این بخش تنها می‌توان آن را غیرفعال کرد."
            )})
        was_enabled = user.two_factor_enabled
        user.two_factor_enabled = False
        user.two_factor_enabled_at = None
        user.save(update_fields=["two_factor_enabled", "two_factor_enabled_at"])
        audit_log(request.user, user, AuditLog.Action.UPDATE,
                  {"twofa": {"before": str(was_enabled), "after": "False"}})
        return Response({
            "ok": True,
            "user_id": user.id,
            "twofa_enabled": user.two_factor_active,
        })
