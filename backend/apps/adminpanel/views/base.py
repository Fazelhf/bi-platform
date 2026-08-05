"""
Shared plumbing for every Admin-Panel viewset.

`AdminModelViewSet` gives each resource, for free:
  * the two-gate permission check (panel access + a declared permission code),
  * search / ordering / pagination,
  * an audit-log entry with a before→after diff on every write,
  * a `bulk_delete` action and an `export` action (xlsx / csv / print-PDF).
"""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.adminpanel.permissions import AdminPanelPermission, require
from apps.adminpanel.services import exporters
from apps.core.audit import diff, log as audit_log, snapshot
from apps.core.models import AuditLog


class AdminAuditMixin:
    """Records create / update / delete with a field-level diff."""

    def perform_create(self, serializer):
        instance = serializer.save()
        audit_log(self.request.user, instance, AuditLog.Action.CREATE,
                  {"created": {"before": None, "after": str(instance)[:150]}})
        return instance

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        audit_log(self.request.user, instance, AuditLog.Action.UPDATE,
                  diff(before, snapshot(instance)))
        return instance

    def perform_destroy(self, instance):
        audit_log(self.request.user, instance, AuditLog.Action.DELETE,
                  snapshot(instance))
        instance.delete()


class AdminModelViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    permission_classes = [AdminPanelPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    #: columns used by the generic `export` action: [(field, label), ...]
    export_columns: list[tuple[str, str]] = []
    export_title: str = "export"

    # -- bulk ------------------------------------------------------------
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """Delete many rows in one call. Every row is audited individually."""
        code = getattr(self, "write_permission", None) or getattr(
            self, "required_permission", None
        )
        if code:
            require(request.user, code)
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "فهرست شناسه‌ها خالی است."}, status=400)
        deleted, errors = 0, []
        for pk in ids:
            instance = self.get_queryset().filter(pk=pk).first()
            if not instance:
                errors.append({"id": pk, "error": "یافت نشد"})
                continue
            try:
                self.perform_destroy(instance)
                deleted += 1
            except Exception as exc:
                errors.append({"id": pk, "error": str(exc)[:200]})
        return Response({"deleted": deleted, "errors": errors})

    @action(detail=False, methods=["patch"], url_path="bulk-update")
    def bulk_update(self, request):
        """Apply the same field changes to many rows (e.g. deactivate 12 users)."""
        code = getattr(self, "write_permission", None) or getattr(
            self, "required_permission", None
        )
        if code:
            require(request.user, code)
        ids = request.data.get("ids") or []
        payload = request.data.get("changes") or {}
        if not ids or not payload:
            return Response({"detail": "شناسه‌ها و تغییرات الزامی است."}, status=400)
        updated, errors = 0, []
        for instance in self.get_queryset().filter(pk__in=ids):
            serializer = self.get_serializer(instance, data=payload, partial=True)
            if not serializer.is_valid():
                errors.append({"id": instance.pk, "error": serializer.errors})
                continue
            self.perform_update(serializer)
            updated += 1
        return Response({"updated": updated, "errors": errors})

    # -- export ----------------------------------------------------------
    @action(detail=False, methods=["get"])
    def export(self, request):
        """?format=xlsx|csv|pdf — respects the current filters and search."""
        if not self.export_columns:
            return Response({"detail": "خروجی برای این بخش تعریف نشده است."}, status=400)
        fmt = request.query_params.get("format", "xlsx")
        queryset = self.filter_queryset(self.get_queryset())
        rows = self.get_serializer(queryset, many=True).data
        try:
            return exporters.as_response(
                fmt, self.export_columns, list(rows), self.export_title
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)


class AdminReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AdminPanelPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    export_columns: list[tuple[str, str]] = []
    export_title: str = "export"

    @action(detail=False, methods=["get"])
    def export(self, request):
        """
        ?fmt=xlsx|csv|pdf — honours the current filters, search and ordering.

        The parameter is `fmt`, not `format`: DRF reserves `format` for content
        negotiation and answers 404 for a value it has no renderer for.
        """
        if not self.export_columns:
            return Response({"detail": "خروجی برای این بخش تعریف نشده است."}, status=400)
        queryset = self.filter_queryset(self.get_queryset())
        rows = self.get_serializer(queryset, many=True).data
        try:
            return exporters.as_response(
                request.query_params.get("fmt", "xlsx"),
                self.export_columns, list(rows), self.export_title,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
