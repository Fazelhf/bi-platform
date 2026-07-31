"""11 · Reports, 12 · Database utilities, 13 · Workflow admin, 14 · Monitoring."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.adminpanel.models import BackupRecord, RecycleBin, ScheduledReport, SystemConfig
from apps.adminpanel.permissions import AdminPanelPermission, require
from apps.adminpanel.serializers import BackupRecordSerializer, ScheduledReportSerializer
from apps.adminpanel.services import backup as backup_service
from apps.adminpanel.services import exporters, reports, stats
from apps.adminpanel.views.base import AdminModelViewSet
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.sales.models import ApprovalStatus, FactSalesMonthly
from apps.production.models import FactProduction


# ==========================================================================
# 11 · Reports
# ==========================================================================
class ReportViewSet(AdminModelViewSet):
    """Saved report definitions; `run` renders one on demand."""

    queryset = ScheduledReport.objects.select_related("created_by")
    serializer_class = ScheduledReportSerializer
    read_permission = "reports.view"
    write_permission = "reports.generate"
    filterset_fields = ["kind", "frequency", "is_active"]
    search_fields = ["name"]

    def perform_create(self, serializer):
        return serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"])
    def kinds(self, request):
        """What can be reported on, and in which formats."""
        return Response({
            "kinds": [
                {"value": v, "label": label} for v, label in ScheduledReport.Kind.choices
            ],
            "frequencies": [
                {"value": v, "label": label}
                for v, label in ScheduledReport.Frequency.choices
            ],
            "formats": [
                {"value": "xlsx", "label": "اکسل (xlsx)"},
                {"value": "csv", "label": "CSV"},
                {"value": "pdf", "label": "PDF (چاپ از مرورگر)"},
            ],
        })

    @action(detail=False, methods=["get"])
    def run(self, request):
        """Render a report immediately: ?kind=users&fmt=xlsx&days=30"""
        require(request.user, "reports.view")
        kind = request.query_params.get("kind", "users")
        fmt = request.query_params.get("fmt", "xlsx")
        params = {k: v for k, v in request.query_params.items()}
        try:
            columns, rows, title = reports.build(kind, params)
            return exporters.as_response(fmt, columns, rows, title)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})

    @action(detail=False, methods=["get"])
    def preview(self, request):
        """The first rows as JSON, so the UI can show the report on screen."""
        require(request.user, "reports.view")
        kind = request.query_params.get("kind", "users")
        params = {k: v for k, v in request.query_params.items()}
        try:
            columns, rows, title = reports.build(kind, params)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        return Response({
            "title": title,
            "columns": [{"key": k, "label": label} for k, label in columns],
            "total": len(rows),
            "rows": [
                {k: exporters.cell(row.get(k)) for k, _ in columns}
                for row in rows[:100]
            ],
        })

    @action(detail=True, methods=["get"], url_path="run-saved")
    def run_saved(self, request, pk=None):
        """Render a saved definition and stamp its last-run fields."""
        require(request.user, "reports.view")
        definition = self.get_object()
        try:
            columns, rows, title = reports.build(definition.kind, definition.params or {})
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        definition.last_run_at = timezone.now()
        definition.last_run_rows = len(rows)
        definition.save(update_fields=["last_run_at", "last_run_rows", "updated_at"])
        return exporters.as_response(
            request.query_params.get("fmt") or definition.fmt,
            columns, rows, definition.name,
        )


# ==========================================================================
# 12 · Database utilities
# ==========================================================================
class DatabaseView(APIView):
    """Health, size and per-table statistics."""

    permission_classes = [AdminPanelPermission]
    read_permission = "db.view"

    def get(self, request):
        return Response({
            "database": stats.database(),
            "storage": stats.storage(),
            "health": stats.api_health(),
        })


class BackupViewSet(AdminModelViewSet):
    queryset = BackupRecord.objects.select_related("created_by")
    serializer_class = BackupRecordSerializer
    read_permission = "db.view"
    write_permission = "db.backup"
    search_fields = ["filename", "note"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        """Take a snapshot now. `scope` limits which apps are dumped."""
        require(request.user, "db.backup")
        scope = request.data.get("scope", "full")
        try:
            record = backup_service.create(
                request.user, scope, request.data.get("note", "")
            )
        except ValueError as exc:
            raise ValidationError({"scope": str(exc)})
        audit_log(request.user, record, AuditLog.Action.CREATE,
                  {"backup": {"before": None, "after": record.filename}})
        return Response(self.get_serializer(record).data, status=201)

    def perform_destroy(self, instance):
        require(self.request.user, "db.backup")
        backup_service.delete_file(instance)
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """
        Load a snapshot back in. This overwrites current rows that share a
        primary key with the fixture, so the client must send confirm=true.
        """
        require(request.user, "db.restore")
        if not request.data.get("confirm"):
            raise ValidationError({
                "confirm": "بازگردانی، رکوردهای فعلی با همان شناسه را بازنویسی می‌کند. "
                           "برای ادامه confirm=true بفرستید."
            })
        record = self.get_object()
        try:
            backup_service.restore(record, request.user)
        except Exception as exc:
            raise ValidationError({"detail": f"بازگردانی ناموفق بود: {exc}"})
        audit_log(request.user, record, AuditLog.Action.UPDATE,
                  {"restored": {"before": None, "after": record.filename}})
        return Response(self.get_serializer(record).data)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        require(request.user, "db.backup")
        record = self.get_object()
        try:
            path = backup_service.path_for(record)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        return FileResponse(
            path.open("rb"), as_attachment=True, filename=record.filename
        )

    @action(detail=False, methods=["get"])
    def scopes(self, request):
        return Response({
            "scopes": [
                {"value": "full", "label": "کل پایگاه داده"},
                {"value": "business", "label": "داده‌های کسب‌وکار (فروش/تولید/شاخص‌ها)"},
                {"value": "accounts", "label": "کاربران"},
                {"value": "adminpanel", "label": "تنظیمات پنل مدیریت"},
            ],
            "orphan_files": backup_service.discover_orphans(),
        })


class DatabaseMaintenanceView(APIView):
    """Cleanup jobs and cache control. Every job reports what it removed."""

    permission_classes = [AdminPanelPermission]
    read_permission = "db.view"
    write_permission = "db.cleanup"

    JOBS = {
        "purge_recycle_bin": "پاک‌سازی دائمی سطل بازیافت",
        "purge_audit": "حذف رخدادهای قدیمی",
        "purge_logins": "حذف تاریخچه ورود قدیمی",
        "purge_notifications": "حذف اعلان‌های خوانده‌شده",
        "purge_file_versions": "حذف نسخه‌های قدیمی فایل‌ها",
        "clear_cache": "پاک‌سازی کش",
        "vacuum": "فشرده‌سازی پایگاه داده (SQLite)",
    }

    def get(self, request):
        """What each job would remove right now (a dry run)."""
        older_than = self._older_than(request.query_params.get("days", 90))
        from apps.adminpanel.models import AdminFile, LoginEvent
        from apps.core.models import AuditLog as AL, Notification

        return Response({
            "jobs": [{"key": k, "label": v} for k, v in self.JOBS.items()],
            "candidates": {
                "purge_recycle_bin": RecycleBin.objects.filter(
                    restored_at__isnull=True, deleted_at__lt=older_than
                ).count(),
                "purge_audit": AL.objects.filter(created_at__lt=older_than).count(),
                "purge_logins": LoginEvent.objects.filter(
                    created_at__lt=older_than
                ).count(),
                "purge_notifications": Notification.objects.filter(
                    is_read=True, created_at__lt=older_than
                ).count(),
                "purge_file_versions": AdminFile.objects.filter(
                    is_current=False
                ).count(),
            },
            "days": (timezone.now() - older_than).days,
        })

    def post(self, request):
        require(request.user, "db.cleanup")
        job = request.data.get("job")
        if job not in self.JOBS:
            raise ValidationError({"job": f"کار «{job}» تعریف نشده است."})
        older_than = self._older_than(request.data.get("days", 90))
        removed = getattr(self, f"_{job}")(older_than)
        AuditLog.objects.create(
            user=request.user,
            action=AuditLog.Action.DELETE,
            model_label="adminpanel.Maintenance",
            object_id=job,
            object_repr=self.JOBS[job],
            changes={"removed": {"before": str(removed), "after": "0"}},
        )
        return Response({
            "job": job, "label": self.JOBS[job], "removed": removed,
        })

    # -- jobs ------------------------------------------------------------
    @staticmethod
    def _older_than(days):
        try:
            days = max(1, min(int(days), 3650))
        except (TypeError, ValueError):
            days = 90
        return timezone.now() - timedelta(days=days)

    def _purge_recycle_bin(self, older_than):
        deleted, _ = RecycleBin.objects.filter(
            restored_at__isnull=True, deleted_at__lt=older_than
        ).delete()
        return deleted

    def _purge_audit(self, older_than):
        from apps.core.models import AuditLog as AL

        deleted, _ = AL.objects.filter(created_at__lt=older_than).delete()
        return deleted

    def _purge_logins(self, older_than):
        from apps.adminpanel.models import LoginEvent

        deleted, _ = LoginEvent.objects.filter(created_at__lt=older_than).delete()
        return deleted

    def _purge_notifications(self, older_than):
        from apps.core.models import Notification

        deleted, _ = Notification.objects.filter(
            is_read=True, created_at__lt=older_than
        ).delete()
        return deleted

    def _purge_file_versions(self, older_than):
        from apps.adminpanel.models import AdminFile

        deleted, _ = AdminFile.objects.filter(is_current=False).delete()
        return deleted

    def _clear_cache(self, older_than):
        from django.core.cache import cache

        cache.clear()
        return 1

    def _vacuum(self, older_than):
        from django.db import connection

        if connection.vendor != "sqlite":
            raise ValidationError(
                {"detail": "VACUUM فقط روی SQLite از این بخش اجرا می‌شود."}
            )
        with connection.cursor() as cursor:
            cursor.execute("VACUUM")
        return 1


# ==========================================================================
# 13 · Workflow administration
# ==========================================================================
STATUS_LABEL = {
    ApprovalStatus.DRAFT: "پیش‌نویس",
    ApprovalStatus.SUBMITTED: "در انتظار تایید",
    ApprovalStatus.APPROVED: "تاییدشده",
    ApprovalStatus.REJECTED: "ردشده",
    ApprovalStatus.NEEDS_REVISION: "نیازمند اصلاح",
}
STALE_DAYS = 7


class WorkflowView(APIView):
    """
    The approval pipeline at a glance: how many records sit in each state, and
    which ones have been waiting too long. "Restarting" a stuck record puts it
    back to draft so its owner can resubmit.
    """

    permission_classes = [AdminPanelPermission]
    read_permission = "workflow.view"
    write_permission = "workflow.manage"

    DOMAINS = {
        "sales": (FactSalesMonthly, "فروش ماهانه"),
        "production": (FactProduction, "تولید ماهانه"),
    }

    def get(self, request):
        stale_before = timezone.now() - timedelta(days=STALE_DAYS)
        domains = []
        for key, (model, label) in self.DOMAINS.items():
            counts = {
                row["status"]: row["n"]
                for row in model.objects.values("status").annotate(n=Count("id"))
            }
            stuck = model.objects.filter(
                status=ApprovalStatus.SUBMITTED, updated_at__lt=stale_before
            ).select_related("period")[:50]
            domains.append({
                "key": key,
                "label": label,
                "counts": [
                    {"status": s, "label": STATUS_LABEL[s], "n": counts.get(s, 0)}
                    for s in STATUS_LABEL
                ],
                "total": sum(counts.values()),
                "stuck": [
                    {
                        "id": row.id, "repr": str(row),
                        "period": row.period.label,
                        "waiting_days": (timezone.now() - row.updated_at).days,
                    }
                    for row in stuck
                ],
            })
        return Response({
            "domains": domains,
            "stale_after_days": STALE_DAYS,
            "rules": {
                "approver": SystemConfig.get_value(
                    "workflow_approver_role", "executive"
                ),
                "auto_approve_imports": bool(
                    SystemConfig.get_value("workflow_auto_approve_imports", False)
                ),
                "require_note_on_reject": bool(
                    SystemConfig.get_value("workflow_require_reject_note", True)
                ),
            },
        })

    def post(self, request):
        """action=restart|force_approve — both are audited."""
        require(request.user, "workflow.manage")
        domain = request.data.get("domain")
        if domain not in self.DOMAINS:
            raise ValidationError({"domain": "دامنه گردش‌کار معتبر نیست."})
        model, _ = self.DOMAINS[domain]
        ids = request.data.get("ids") or []
        action_name = request.data.get("action", "restart")
        if action_name not in {"restart", "force_approve"}:
            raise ValidationError({"action": "عملیات معتبر نیست."})

        target = (
            ApprovalStatus.DRAFT if action_name == "restart" else ApprovalStatus.APPROVED
        )
        changed = 0
        for row in model.objects.filter(pk__in=ids):
            before = row.status
            row.status = target
            if action_name == "force_approve":
                row.approved_by = request.user
            row.save(update_fields=["status", "approved_by", "updated_at"]
                     if action_name == "force_approve" else ["status", "updated_at"])
            audit_log(request.user, row, AuditLog.Action.UPDATE,
                      {"status": {"before": before, "after": target}})
            changed += 1
        return Response({"changed": changed, "status": target})


# ==========================================================================
# 14 · Monitoring
# ==========================================================================
class MonitoringView(APIView):
    permission_classes = [AdminPanelPermission]
    read_permission = "monitor.view"

    def get(self, request):
        return Response({
            "server": stats.server(),
            "api": stats.api_health(),
            "queues": stats.queues(),
            "errors": stats.error_summary(
                int(request.query_params.get("days", 7) or 7)
            ),
            "database": {
                k: v for k, v in stats.database().items() if k != "tables"
            },
            "checked_at": timezone.now().isoformat(),
        })
