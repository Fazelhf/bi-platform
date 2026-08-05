from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Message, Note, User
from apps.accounts.serializers import (
    MessageSerializer,
    NoteSerializer,
    UserCardSerializer,
    UserSerializer,
)
from apps.adminpanel.permissions import IsAdminPanelUser
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog


class UserViewSet(viewsets.ModelViewSet):
    """
    Legacy user-management endpoint. The full-featured version lives in the
    Admin Panel (/api/admin/users/); this one is kept for existing clients and
    is restricted to the same audience — administrators only, not the CEO.
    """

    queryset = User.objects.order_by("id")
    serializer_class = UserSerializer
    permission_classes = [IsAdminPanelUser]
    filterset_fields = ["role", "department", "is_active"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        user = serializer.save()
        audit_log(self.request.user, user, AuditLog.Action.CREATE,
                  {"role": {"before": None, "after": user.role},
                   "department": {"before": None, "after": user.department}})

    def perform_update(self, serializer):
        before = {f: str(getattr(serializer.instance, f))
                  for f in ("role", "department", "is_active", "display_name_fa")}
        user = serializer.save()
        after = {f: str(getattr(user, f))
                 for f in ("role", "department", "is_active", "display_name_fa")}
        changes = {k: {"before": before[k], "after": after[k]}
                   for k in before if before[k] != after[k]}
        audit_log(self.request.user, user, AuditLog.Action.UPDATE, changes)

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise PermissionDenied("حساب کاربری خودتان را نمی‌توانید حذف کنید.")
        if instance.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("حذف ادمین سیستم مجاز نیست.")
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()


class MeView(APIView):
    """The current user's identity + capabilities, for role-aware UI."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(self._payload(request.user))

    def patch(self, request):
        """Self-service profile edit — a user may change their own display
        name, job title, phone and avatar colour (never role/department)."""
        u = request.user
        for field in ("display_name_fa", "job_title_fa", "phone", "avatar_color"):
            if field in request.data:
                setattr(u, field, request.data[field] or "")
        if "avatar_image" in request.data:
            img = request.data["avatar_image"] or ""
            # Accept a small data-URL only (client resizes to ~160px first).
            if img and (not img.startswith("data:image/") or len(img) > 300_000):
                return Response({"avatar_image": "تصویر نامعتبر یا بزرگ است."}, status=400)
            u.avatar_image = img
        u.save(update_fields=[
            "display_name_fa", "job_title_fa", "phone", "avatar_color", "avatar_image",
        ])
        return Response(self._payload(u))

    @staticmethod
    def _payload(u):
        return {
            "username": u.get_username(),
            "display_name_fa": u.display_name_fa,
            "job_title_fa": u.job_title_fa,
            "phone": u.phone,
            "initials": u.initials,
            "avatar_color": u.avatar_color,
            "avatar_image": u.avatar_image,
            "role": u.role,
            "department": u.department,
            "is_superuser": u.is_superuser,
            "can_enter_data": u.can_enter_data,
            "can_approve": u.can_approve,
            # Drives the "پنل مدیریت" entry in the sidebar.
            "is_admin_panel_user": u.is_admin_panel_user,
            # Whether figures are shown in ریال or تومان is an install-wide
            # display choice, not a finance secret — but it used to be
            # readable only from /api/finance/settings/, which is gated to the
            # finance department. Every other section rendered its money with
            # the default divisor and silently showed the wrong unit. It is
            # served here because every section needs it; writing it still
            # belongs to finance alone.
            **_display_unit(),
        }


def _display_unit() -> dict:
    from apps.finance.models import FinanceSetting

    setting = FinanceSetting.get()
    return {
        "unit": setting.unit,
        "unit_label": setting.get_unit_display(),
        "unit_divisor": 10 if setting.unit == "toman" else 1,
    }


class HeartbeatView(APIView):
    """Frontend pings this every ~30s so the user shows as online."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.touch_presence()
        return Response({"ok": True})


class TeamViewSet(viewsets.ReadOnlyModelViewSet):
    """Directory of system users with live online status — for the team card,
    profile popovers, and the chat contact list."""

    queryset = User.objects.filter(is_active=True).order_by("display_name_fa")
    serializer_class = UserCardSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["role", "department"]


class NoteViewSet(viewsets.ModelViewSet):
    """Personal notes and notes attached to a colleague's profile."""

    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["subject"]

    def get_queryset(self):
        # A user sees notes they authored, plus notes about them.
        return Note.objects.filter(
            Q(author=self.request.user) | Q(subject=self.request.user)
        ).select_related("author")

    def perform_create(self, serializer):
        note = serializer.save(author=self.request.user)
        audit_log(self.request.user, note, AuditLog.Action.CREATE)

    def perform_destroy(self, instance):
        if instance.author_id != self.request.user.pk and not self.request.user.is_superuser:
            raise PermissionDenied("فقط نویسنده می‌تواند یادداشت را حذف کند.")
        instance.delete()


class MessageViewSet(viewsets.ModelViewSet):
    """1:1 chat between system users."""

    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        me = self.request.user
        qs = Message.objects.filter(Q(sender=me) | Q(recipient=me))
        other = self.request.query_params.get("with")
        if other:
            qs = qs.filter(Q(sender_id=other) | Q(recipient_id=other))
        return qs.select_related("sender", "recipient")

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)

    @action(detail=False, methods=["get"])
    def conversation(self, request):
        """Full thread with ?with=<user_id>; marks their messages read."""
        other = request.query_params.get("with")
        if not other:
            return Response({"detail": "پارامتر with الزامی است."}, status=400)
        me = request.user
        thread = Message.objects.filter(
            Q(sender=me, recipient_id=other) | Q(sender_id=other, recipient=me)
        ).order_by("created_at")
        Message.objects.filter(sender_id=other, recipient=me, is_read=False).update(
            is_read=True
        )
        return Response(MessageSerializer(thread, many=True).data)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        counts = {}
        rows = Message.objects.filter(recipient=request.user, is_read=False).values_list(
            "sender_id", flat=True
        )
        for sid in rows:
            counts[sid] = counts.get(sid, 0) + 1
        return Response({"total": sum(counts.values()), "by_sender": counts})
