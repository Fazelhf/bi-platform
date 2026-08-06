"""
The dashboard-builder API.

Four things the frontend needs, and nothing else:

  ``GET  /api/dashboards/catalog/``   what can be built, for this user
  ``GET  /api/dashboards/boards/``    the boards they may open
  ``PUT  /api/dashboards/boards/<id>/layout/``  one atomic save of an arrangement
  ``POST /api/dashboards/query/``     run one spec and return numbers

The layout save is deliberately a single call rather than one request per
dragged card: a board is edited as a whole, and half a saved arrangement is
worse than none.
"""
from django.db import transaction
from django.db.models import Prefetch
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.dashboards.catalog import (
    DATASETS,
    SECTIONS,
    WIDGET_KINDS,
    get_section,
)
from apps.dashboards.models import GRID_COLUMNS, Dashboard, Widget
from apps.dashboards.permissions import (
    BoardPermission,
    can_edit_boards,
    can_read_dataset,
    can_read_section,
)
from apps.dashboards.query import QueryError, month_periods, run_query
from apps.dashboards.serializers import (
    DashboardListSerializer,
    DashboardSerializer,
    LayoutWidgetSerializer,
    QuerySerializer,
    WidgetSerializer,
)


def _dataset_payload(dataset) -> dict:
    return {
        "key": dataset.key,
        "label": dataset.label,
        "section": dataset.section,
        "note": dataset.note,
        "has_period": bool(dataset.period_path),
        "has_status": bool(dataset.status_path),
        "dimensions": [
            {
                "key": d.key,
                "label": d.label,
                "kind": d.kind,
                "choices": [{"value": v, "label": lbl} for v, lbl in d.choices],
            }
            for d in dataset.dims
        ],
        "metrics": [
            {
                "key": m.key,
                "label": m.label,
                "unit": m.unit,
                "agg": m.agg,
                "description": m.description,
            }
            for m in dataset.metrics
        ],
    }


class CatalogView(APIView):
    """
    Everything the builder needs to draw its own form: the datasets this user
    may read, the widget kinds, the sections, and the period list the board's
    picker offers. One request, so opening the editor is instant.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        datasets = [
            _dataset_payload(d)
            for d in DATASETS
            if can_read_dataset(request.user, d, request)
        ]
        sections = [
            {
                "key": s.key,
                "label": s.label,
                "department": s.department,
                "default_board": Dashboard.objects.filter(
                    section=s.key, is_default=True
                ).values_list("id", flat=True).first(),
            }
            for s in SECTIONS
            if can_read_section(request.user, s, request)
        ]
        return Response({
            "datasets": datasets,
            "sections": sections,
            "widget_kinds": list(WIDGET_KINDS),
            "grid_columns": GRID_COLUMNS,
            "can_edit": can_edit_boards(request.user),
            "periods": [
                {"id": p.id, "label": p.label, "year": p.jalali_year,
                 "month": p.jalali_month}
                for p in month_periods()
            ],
        })


class BoardViewSet(viewsets.ModelViewSet):
    """CRUD for boards. Reading follows the section; writing is the manager's."""

    permission_classes = [IsAuthenticated, BoardPermission]
    serializer_class = DashboardSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Dashboard.objects.select_related("owner").prefetch_related(
            Prefetch("widgets", queryset=Widget.objects.all())
        )
        visible = [
            s.key for s in SECTIONS if can_read_section(user, s, self.request)
        ]
        qs = qs.filter(section__in=visible)
        section = self.request.query_params.get("section")
        if section:
            qs = qs.filter(section=section)
        if not can_edit_boards(user):
            qs = qs.filter(is_published=True)
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return DashboardListSerializer
        return DashboardSerializer

    def perform_create(self, serializer):
        section = serializer.validated_data.get("section")
        if get_section(section) is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"section": f"بخش ناشناخته: {section}"})
        board = serializer.save(owner=self.request.user, updated_by=self.request.user)
        audit_log(self.request.user, board, "create")

    def perform_update(self, serializer):
        board = serializer.save(updated_by=self.request.user)
        audit_log(self.request.user, board, "update")

    def perform_destroy(self, instance):
        audit_log(self.request.user, instance, "delete")
        instance.delete()

    # ---------------------------------------------------------------- layout
    @action(detail=True, methods=["put"])
    def layout(self, request, pk=None):
        """
        Replace this board's arrangement in one transaction.

        The client sends the widgets it now has; anything missing from that
        list was deleted in the editor. Ids are honoured so a widget keeps its
        identity (and its audit trail) across a move, and unknown ids are
        ignored rather than trusted — an id from another board would otherwise
        let an editor reparent someone else's widget by hand.
        """
        board = self.get_object()
        if not can_edit_boards(request.user):
            return Response(
                {"detail": "چیدمان داشبورد فقط توسط مدیر قابل تغییر است."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = LayoutWidgetSerializer(data=request.data.get("widgets", []), many=True)
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data

        existing = {w.id: w for w in board.widgets.all()}
        kept: set[int] = set()

        with transaction.atomic():
            for order, row in enumerate(rows):
                wid = row.pop("id", None)
                fields = {**row, "sort_order": order}
                widget = existing.get(wid) if wid else None
                if widget is None:
                    Widget.objects.create(dashboard=board, **fields)
                else:
                    for key, value in fields.items():
                        setattr(widget, key, value)
                    widget.save()
                    kept.add(widget.id)
            # Whatever the client no longer lists was deleted in the editor.
            # Scoped to ids that were already on this board, so a widget
            # created moments ago in the same transaction is never caught.
            removed = set(existing) - kept
            if removed:
                board.widgets.filter(id__in=removed).delete()
            board.updated_by = request.user
            board.save(update_fields=["updated_by", "updated_at"])

        audit_log(request.user, board, "update", {"widgets": {
            "before": str(len(existing)), "after": str(len(rows))
        }})
        board.refresh_from_db()
        return Response(DashboardSerializer(board, context={"request": request}).data)

    # ------------------------------------------------------------- duplicate
    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """Copy a board — the safe way to try a new arrangement on a live one."""
        board = self.get_object()
        if not can_edit_boards(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        widgets = list(board.widgets.all())
        board.pk = None
        board.title = f"{board.title} (رونوشت)"
        board.is_default = False
        board.owner = request.user
        board.updated_by = request.user
        board.save()
        Widget.objects.bulk_create([
            Widget(
                dashboard=board, kind=w.kind, title=w.title, subtitle=w.subtitle,
                x=w.x, y=w.y, w=w.w, h=w.h, config=w.config, options=w.options,
                sort_order=w.sort_order,
            )
            for w in widgets
        ])
        return Response(
            DashboardSerializer(board, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="make-default")
    def make_default(self, request, pk=None):
        board = self.get_object()
        if not can_edit_boards(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        board.is_default = True
        board.save()
        return Response(DashboardSerializer(board, context={"request": request}).data)


class WidgetViewSet(viewsets.ModelViewSet):
    """
    Single-widget edits, for the drawer's «ذخیره» button.

    The bulk layout save covers dragging; this covers changing what one card
    *asks*, which is the part a manager does one card at a time.
    """

    permission_classes = [IsAuthenticated, BoardPermission]
    serializer_class = WidgetSerializer

    def get_queryset(self):
        user = self.request.user
        visible = [s.key for s in SECTIONS if can_read_section(user, s, self.request)]
        return Widget.objects.select_related("dashboard").filter(
            dashboard__section__in=visible
        )

    def perform_create(self, serializer):
        board_id = self.request.data.get("dashboard")
        board = Dashboard.objects.filter(pk=board_id).first()
        if board is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"dashboard": "داشبورد یافت نشد."})
        if not can_read_section(self.request.user, board.section, self.request):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("به این بخش دسترسی ندارید.")
        serializer.save(dashboard=board)


class QueryView(APIView):
    """
    Run one widget spec.

    Used by every rendered widget and by the builder's live preview — the same
    code path, so what the manager sees while building is what the board shows.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = QuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = run_query(
                serializer.validated_data["config"],
                user=request.user,
                period_id=serializer.validated_data.get("period"),
                request=request,
            )
        except QueryError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)


class BatchQueryView(APIView):
    """
    Run several specs in one request.

    A board with fourteen cards would otherwise open fourteen connections and
    render in waves; this makes it one round trip. Each result carries its own
    error so one broken widget does not blank the page.
    """

    permission_classes = [IsAuthenticated]
    MAX_ITEMS = 40

    def post(self, request):
        items = request.data.get("items") or []
        if not isinstance(items, list):
            return Response({"detail": "items باید فهرست باشد."},
                            status=status.HTTP_400_BAD_REQUEST)
        period = request.data.get("period")
        out = []
        for item in items[: self.MAX_ITEMS]:
            key = (item or {}).get("key")
            try:
                data = run_query(
                    (item or {}).get("config") or {},
                    user=request.user,
                    period_id=period,
                    request=request,
                )
                out.append({"key": key, "data": data})
            except QueryError as exc:
                out.append({"key": key, "error": str(exc)})
            except Exception as exc:  # a catalog path that no longer resolves
                out.append({"key": key, "error": f"خطا در محاسبه: {exc}"})
        return Response({"results": out})
