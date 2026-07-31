"""9 · Notification centre, 10 · File management, 15 · Content management."""
from __future__ import annotations

import base64
import binascii
from urllib.parse import quote

from django.http import HttpResponse
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.adminpanel.models import (
    AdminFile,
    Announcement,
    Broadcast,
    ContentCategory,
    ContentTag,
    ContentTemplate,
    Folder,
    StaticPage,
    Team,
)
from apps.adminpanel.permissions import AdminPanelPermission, require
from apps.adminpanel.serializers import (
    AdminFileSerializer,
    AnnouncementSerializer,
    BroadcastSerializer,
    ContentCategorySerializer,
    ContentTagSerializer,
    ContentTemplateSerializer,
    FolderSerializer,
    StaticPageSerializer,
)
from apps.adminpanel.views.base import AdminModelViewSet
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog, Notification


# ==========================================================================
# 9 · Notification centre
# ==========================================================================
def resolve_audience(audience: str, values: list) -> list[User]:
    """Turn an audience selector into the concrete list of recipients."""
    qs = User.objects.filter(is_active=True)
    if audience == Broadcast.Audience.ROLE:
        return list(qs.filter(role__in=values or []))
    if audience == Broadcast.Audience.DEPARTMENT:
        return list(qs.filter(department__in=values or []))
    if audience == Broadcast.Audience.TEAM:
        return list(qs.filter(team_memberships__team_id__in=values or []).distinct())
    if audience == Broadcast.Audience.USERS:
        return list(qs.filter(pk__in=values or []))
    return list(qs)


class BroadcastViewSet(AdminModelViewSet):
    """
    Send one message to many people. Creating a broadcast fans it out into
    core.Notification rows, so it lands in the bell every user already has.
    """

    queryset = Broadcast.objects.select_related("sent_by")
    serializer_class = BroadcastSerializer
    read_permission = "notify.view"
    write_permission = "notify.send"
    filterset_fields = ["audience", "level"]
    search_fields = ["title", "body"]
    http_method_names = ["get", "post", "delete", "head", "options"]
    export_title = "اعلان‌های ارسالی"
    export_columns = [
        ("created_at", "زمان"), ("title", "عنوان"), ("audience_label", "مخاطب"),
        ("recipient_count", "تعداد گیرنده"), ("sent_by_name", "ارسال توسط"),
    ]

    def perform_create(self, serializer):
        broadcast = serializer.save(sent_by=self.request.user)
        recipients = resolve_audience(broadcast.audience, broadcast.audience_value or [])
        Notification.objects.bulk_create([
            Notification(
                recipient=user,
                actor=self.request.user,
                verb=broadcast.level,
                message=f"{broadcast.title} — {broadcast.body}"[:300],
                target_label="adminpanel.Broadcast",
                target_id=str(broadcast.pk),
            )
            for user in recipients
        ])
        broadcast.recipient_count = len(recipients)
        broadcast.save(update_fields=["recipient_count"])
        audit_log(self.request.user, broadcast, AuditLog.Action.CREATE,
                  {"recipients": {"before": None, "after": str(len(recipients))}})
        return broadcast

    @action(detail=False, methods=["post"])
    def preview(self, request):
        """How many people would receive this, before sending it."""
        require(request.user, "notify.send")
        recipients = resolve_audience(
            request.data.get("audience", "all"), request.data.get("audience_value") or []
        )
        return Response({
            "count": len(recipients),
            "sample": [
                {"id": u.id, "name": str(u), "username": u.username}
                for u in recipients[:25]
            ],
        })

    @action(detail=False, methods=["get"])
    def audiences(self, request):
        """The selectable audiences, with their options."""
        from apps.accounts.serializers import DEPT_LABEL

        return Response({
            "roles": [
                {"value": "admin", "label": "ادمین سیستم"},
                {"value": "executive", "label": "مدیرعامل"},
                {"value": "manager", "label": "مدیر بخش"},
                {"value": "operator", "label": "اپراتور"},
                {"value": "viewer", "label": "بیننده"},
            ],
            "departments": [
                {"value": k, "label": v} for k, v in DEPT_LABEL.MAP.items() if k
            ],
            "teams": [
                {"value": t.id, "label": t.name_fa}
                for t in Team.objects.filter(is_active=True)
            ],
            "users": [
                {"value": u.id, "label": str(u), "username": u.username}
                for u in User.objects.filter(is_active=True).order_by("display_name_fa")
            ],
        })


# ==========================================================================
# 10 · File management
# ==========================================================================
class FolderViewSet(AdminModelViewSet):
    queryset = Folder.objects.select_related("parent")
    serializer_class = FolderSerializer
    read_permission = "files.view"
    write_permission = "files.manage"
    filterset_fields = ["parent"]
    search_fields = ["name"]

    def perform_create(self, serializer):
        return serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        if instance.files.exists() or instance.children.exists():
            raise ValidationError({"detail": "پوشه خالی نیست."})
        super().perform_destroy(instance)


class AdminFileViewSet(AdminModelViewSet):
    """
    Files are stored as data-URLs in the database (no media volume needed on
    the cPanel/Passenger deploy). Re-uploading a name keeps the old row as a
    version instead of overwriting it.
    """

    queryset = AdminFile.objects.select_related("folder", "uploaded_by")
    serializer_class = AdminFileSerializer
    read_permission = "files.view"
    write_permission = "files.manage"
    filterset_fields = ["folder", "visibility", "is_current"]
    search_fields = ["name", "mime"]
    ordering_fields = ["created_at", "size_bytes", "name"]
    export_title = "فایل‌ها"
    export_columns = [
        ("name", "نام"), ("folder_path", "پوشه"), ("mime", "نوع"),
        ("size_bytes", "حجم (بایت)"), ("version", "نسخه"),
        ("uploaded_by_name", "آپلود توسط"), ("created_at", "زمان"),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list" and self.request.query_params.get(
            "include_versions"
        ) != "1":
            qs = qs.filter(is_current=True)
        return qs

    def perform_create(self, serializer):
        content = serializer.validated_data.get("content", "")
        name = serializer.validated_data.get("name")
        folder = serializer.validated_data.get("folder")

        previous = AdminFile.objects.filter(
            name=name, folder=folder, is_current=True
        ).first()
        version = (previous.version + 1) if previous else 1

        instance = serializer.save(
            uploaded_by=self.request.user,
            size_bytes=len(content or ""),
            version=version,
            is_current=True,
            replaces=previous,
        )
        if previous:
            previous.is_current = False
            previous.save(update_fields=["is_current", "updated_at"])
        audit_log(self.request.user, instance, AuditLog.Action.CREATE,
                  {"version": {"before": str(version - 1) if previous else None,
                               "after": str(version)}})
        return instance

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Decode the stored data-URL back into a real file download."""
        item = self.get_object()
        header, _, payload = (item.content or "").partition(",")
        try:
            blob = base64.b64decode(payload)
        except (binascii.Error, ValueError):
            raise ValidationError({"detail": "محتوای فایل قابل بازخوانی نیست."})
        response = HttpResponse(
            blob, content_type=item.mime or "application/octet-stream"
        )
        response["Content-Disposition"] = (
            f"attachment; filename=file; filename*=UTF-8''{quote(item.name)}"
        )
        return response

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        """The version chain for one file, newest first."""
        item = self.get_object()
        chain, node = [], item
        while node:
            chain.append(node)
            node = node.replaces
        return Response(self.get_serializer(chain, many=True).data)

    @action(detail=False, methods=["get"])
    def usage(self, request):
        """Storage consumption, by folder and in total."""
        from django.db.models import Sum

        total = AdminFile.objects.aggregate(t=Sum("size_bytes"))["t"] or 0
        by_folder = [
            {
                "folder": f.path,
                "files": f.files.filter(is_current=True).count(),
                "bytes": f.files.aggregate(t=Sum("size_bytes"))["t"] or 0,
            }
            for f in Folder.objects.all()
        ]
        root = AdminFile.objects.filter(folder__isnull=True)
        by_folder.append({
            "folder": "/",
            "files": root.filter(is_current=True).count(),
            "bytes": root.aggregate(t=Sum("size_bytes"))["t"] or 0,
        })
        return Response({
            "total_bytes": total,
            "file_count": AdminFile.objects.filter(is_current=True).count(),
            "version_count": AdminFile.objects.filter(is_current=False).count(),
            "by_folder": sorted(by_folder, key=lambda f: f["bytes"], reverse=True),
        })


# ==========================================================================
# 15 · Content management
# ==========================================================================
class ContentCategoryViewSet(AdminModelViewSet):
    queryset = ContentCategory.objects.select_related("parent")
    serializer_class = ContentCategorySerializer
    read_permission = "content.view"
    write_permission = "content.manage"
    filterset_fields = ["is_active", "parent"]
    search_fields = ["name", "slug", "description"]


class ContentTagViewSet(AdminModelViewSet):
    queryset = ContentTag.objects.all()
    serializer_class = ContentTagSerializer
    read_permission = "content.view"
    write_permission = "content.manage"
    search_fields = ["name"]


class ContentTemplateViewSet(AdminModelViewSet):
    queryset = ContentTemplate.objects.all()
    serializer_class = ContentTemplateSerializer
    read_permission = "content.view"
    write_permission = "content.manage"
    filterset_fields = ["kind", "is_active"]
    search_fields = ["name", "subject", "body"]

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        """Fill {{placeholders}} with supplied values — a live preview."""
        template = self.get_object()
        values = request.data.get("values") or {}
        body, subject = template.body, template.subject
        for key, value in values.items():
            token = "{{" + str(key) + "}}"
            body = body.replace(token, str(value))
            subject = subject.replace(token, str(value))
        return Response({"subject": subject, "body": body})


class AnnouncementViewSet(AdminModelViewSet):
    queryset = Announcement.objects.select_related("category", "created_by").prefetch_related("tags")
    serializer_class = AnnouncementSerializer
    read_permission = "content.view"
    write_permission = "content.manage"
    filterset_fields = ["level", "is_published", "category"]
    search_fields = ["title", "body"]
    export_title = "اطلاعیه‌ها"
    export_columns = [
        ("title", "عنوان"), ("level", "سطح"), ("is_published", "منتشرشده"),
        ("starts_at", "از"), ("ends_at", "تا"), ("created_by_name", "ایجاد توسط"),
    ]

    def perform_create(self, serializer):
        return serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        require(request.user, "content.manage")
        item = self.get_object()
        item.is_published = not item.is_published
        item.save(update_fields=["is_published", "updated_at"])
        audit_log(request.user, item, AuditLog.Action.UPDATE,
                  {"is_published": {"before": str(not item.is_published),
                                    "after": str(item.is_published)}})
        return Response(self.get_serializer(item).data)


class StaticPageViewSet(AdminModelViewSet):
    queryset = StaticPage.objects.select_related("updated_by")
    serializer_class = StaticPageSerializer
    read_permission = "content.view"
    write_permission = "content.manage"
    filterset_fields = ["is_published"]
    search_fields = ["slug", "title", "body"]

    def perform_create(self, serializer):
        return serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
        return serializer.instance


class LiveAnnouncementView(APIView):
    """
    Read-only feed of currently-visible announcements for the *main* app.
    Open to any signed-in user — this is the one admin-authored surface that
    ordinary users are meant to see.
    """

    permission_classes = []  # falls back to DEFAULT_PERMISSION_CLASSES (IsAuthenticated)

    def get(self, request):
        live = [a for a in Announcement.objects.filter(is_published=True) if a.is_live]
        return Response([
            {"id": a.id, "title": a.title, "body": a.body, "level": a.level,
             "starts_at": a.starts_at, "ends_at": a.ends_at}
            for a in live
        ])
