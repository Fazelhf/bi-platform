"""Treasury API: the daily entry grid, the cash report, and credit lines."""
from __future__ import annotations

from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.core.models import AuditLog, DimPeriod, PeriodKind
from apps.core.notify import notify_submitted
from apps.core.periods import leaves_of, month_of
from decimal import Decimal

from apps.finance.models import (
    BankAccount,
    CashCategory,
    CashMovement,
    CreditLine,
    Direction,
    FinanceSetting,
)
from apps.finance.permissions import FinanceAccess, assert_finance_visible, is_finance
from apps.finance.serializers import (
    BankAccountSerializer,
    CashCategorySerializer,
    CashMovementSerializer,
    CreditLineSerializer,
    FinanceSettingSerializer,
)
from apps.finance.services import balance_trend, cash_report
from apps.sales.models import ApprovalStatus


def _nonzero(value) -> bool:
    try:
        return bool(value) and float(value) != 0
    except (TypeError, ValueError):
        return False


class BankAccountViewSet(viewsets.ModelViewSet):
    """The accounts every movement is attributed to."""

    queryset = BankAccount.objects.all()
    serializer_class = BankAccountSerializer
    permission_classes = [FinanceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["kind", "is_active"]
    search_fields = ["title", "bank_name", "account_no", "iban", "note"]
    ordering_fields = ["sort_order", "title", "opening_balance_rial"]

    def perform_create(self, serializer):
        account = serializer.save()
        audit_log(self.request.user, account, AuditLog.Action.CREATE,
                  {"opening": {"before": None,
                               "after": str(account.opening_balance_rial)}})

    def perform_destroy(self, instance):
        if instance.movements.exists():
            raise ValidationError({
                "detail": "این حساب گردش ثبت‌شده دارد؛ به‌جای حذف، غیرفعالش کنید."
            })
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()

    @action(detail=False, methods=["get"])
    def balances(self, request):
        """Each account's balance right now — opening plus everything since."""
        from apps.finance.services import balance_trend

        opening = balance_trend._opening_before(None)
        current = dict(opening)
        for movement in CashMovement.objects.all().only(
            "account_id", "direction", "amount_rial"
        ):
            current[movement.account_id] = current.get(
                movement.account_id, 0
            ) + balance_trend._signed(movement)

        rows = []
        for account in BankAccount.objects.all():
            rows.append({
                "id": account.id,
                "title": account.title,
                "label": account.label,
                "kind": account.kind,
                "color": account.color,
                "opening_rial": str(account.opening_balance_rial),
                "balance_rial": str(current.get(account.id, 0)),
                "is_active": account.is_active,
            })
        unassigned = current.get(None, 0)
        return Response({
            "accounts": rows,
            "total_rial": str(sum(Decimal(r["balance_rial"]) for r in rows) + unassigned),
            # Surfaced rather than hidden: rows recorded before accounts
            # existed would otherwise silently not belong anywhere.
            "unassigned_rial": str(unassigned),
        })


class CashCategoryViewSet(viewsets.ModelViewSet):
    """Categories are data — the finance team adds their own without a deploy."""

    queryset = CashCategory.objects.all()
    serializer_class = CashCategorySerializer
    permission_classes = [FinanceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["direction", "is_active"]
    search_fields = ["code", "name_fa", "note"]

    def perform_destroy(self, instance):
        if instance.movements.exists():
            raise ValidationError({
                "detail": "این دسته در گزارش‌ها استفاده شده؛ به‌جای حذف، غیرفعالش کنید."
            })
        super().perform_destroy(instance)


class CreditLineViewSet(viewsets.ModelViewSet):
    """تسهیلات، قرض و جاری شرکا — one resource, filtered by kind."""

    queryset = CreditLine.objects.prefetch_related("movements")
    serializer_class = CreditLineSerializer
    permission_classes = [FinanceAccess]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["kind", "status"]
    search_fields = ["title", "counterparty", "note"]
    ordering_fields = ["opened_on", "due_on", "principal_rial"]

    def perform_create(self, serializer):
        line = serializer.save(created_by=self.request.user)
        audit_log(self.request.user, line, AuditLog.Action.CREATE,
                  {"principal": {"before": None, "after": str(line.principal_rial)}})

    def perform_destroy(self, instance):
        if instance.movements.exists():
            raise ValidationError({
                "detail": "این مورد گردش مالی ثبت‌شده دارد؛ وضعیتش را «لغوشده» کنید."
            })
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()

    @action(detail=True, methods=["get"])
    def movements(self, request, pk=None):
        """The ledger behind this line's balance."""
        line = self.get_object()
        rows = line.movements.select_related("period", "category").order_by(
            "period__start_date", "id"
        )
        return Response(CashMovementSerializer(rows, many=True).data)


class CashMovementViewSet(viewsets.ModelViewSet):
    """Individual movements — used for corrections and for credit-line entries."""

    queryset = CashMovement.objects.select_related("period", "category", "credit_line")
    serializer_class = CashMovementSerializer
    permission_classes = [FinanceAccess]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["period", "direction", "category", "credit_line", "status"]
    ordering_fields = ["period__start_date", "amount_rial"]

    def perform_create(self, serializer):
        instance = serializer.save(status=ApprovalStatus.DRAFT)
        audit_log(self.request.user, instance, AuditLog.Action.CREATE)


class CashEntryView(APIView):
    """
    The daily grid, shaped like the finance colleague's own sheet: one row per
    day of the month, one column per category, واریز above برداشت.

    GET returns the grid for a month (every day listed, unfilled ones as
    zeros). POST writes it back, skipping days that were never touched so an
    untouched month does not create hundreds of empty rows.
    """

    permission_classes = [FinanceAccess]

    @extend_schema(
        parameters=[OpenApiParameter("period", int, required=True)],
        responses=dict,
    )
    def get(self, request):
        period = self._period(request.query_params.get("period"))
        days = sorted(
            leaves_of(period), key=lambda p: (p.start_date or p.id, p.id)
        )
        categories = list(CashCategory.objects.filter(is_active=True))
        # A day/category can now span several accounts, so a cell holds a
        # list of rows rather than one figure. Days entered before accounts
        # existed come back as a single row with no account, which the form
        # then asks the user to assign.
        stored: dict[tuple, list] = {}
        for m in CashMovement.objects.filter(
            period_id__in=[d.id for d in days]
        ).select_related("account"):
            stored.setdefault((m.period_id, m.direction, m.category_id), []).append(m)

        def cell(day, direction, category):
            rows = stored.get((day.id, direction, category.id), [])
            return [
                {
                    "movement_id": m.id,
                    "amount_rial": str(m.amount_rial),
                    "account": m.account_id,
                    "credit_line": m.credit_line_id,
                    "note": m.note,
                }
                for m in rows
            ]

        return Response({
            "period": {"id": period.id, "label": period.label},
            "is_month": period.kind == PeriodKind.MONTH,
            "categories": {
                "in": CashCategorySerializer(
                    [c for c in categories if c.allows(Direction.IN)], many=True
                ).data,
                "out": CashCategorySerializer(
                    [c for c in categories if c.allows(Direction.OUT)], many=True
                ).data,
            },
            "days": [
                {
                    "period_id": d.id,
                    "label": d.label,
                    "date": d.start_date.isoformat() if d.start_date else None,
                    "in": {
                        str(c.id): cell(d, Direction.IN, c)
                        for c in categories if c.allows(Direction.IN)
                    },
                    "out": {
                        str(c.id): cell(d, Direction.OUT, c)
                        for c in categories if c.allows(Direction.OUT)
                    },
                }
                for d in days
            ],
            "accounts": BankAccountSerializer(
                BankAccount.objects.filter(is_active=True), many=True
            ).data,
            "unit": FinanceSettingSerializer(FinanceSetting.get()).data,
            "can_edit": is_finance(request.user),
        })

    @transaction.atomic
    def post(self, request):
        if not is_finance(request.user):
            raise ValidationError({"detail": "فقط واحد مالی می‌تواند ثبت کند."})

        submit = bool(request.data.get("submit"))
        status = ApprovalStatus.SUBMITTED if submit else ApprovalStatus.DRAFT
        written = 0
        removed = 0

        for day in request.data.get("days", []):
            period_id = day.get("period_id")
            if not period_id:
                continue
            for direction in (Direction.IN, Direction.OUT):
                for raw_category_id, rows in (day.get(direction) or {}).items():
                    # A cell is a list of rows, one per account. Older clients
                    # sent a single object; accept both rather than 500.
                    if isinstance(rows, dict):
                        rows = [rows]
                    elif not isinstance(rows, list):
                        rows = [{"amount_rial": rows}]

                    kept_ids = []
                    for row in rows:
                        amount = row.get("amount_rial")
                        account_id = row.get("account") or None
                        line_id = row.get("credit_line") or None
                        note = row.get("note", "")

                        existing = CashMovement.objects.filter(
                            period_id=period_id, direction=direction,
                            category_id=raw_category_id,
                            credit_line_id=line_id, account_id=account_id,
                        ).first()
                        # Never stored and still zero: leave it alone rather
                        # than filling the table with empty days.
                        if existing is None and not _nonzero(amount):
                            continue
                        movement, _ = CashMovement.objects.update_or_create(
                            period_id=period_id, direction=direction,
                            category_id=raw_category_id,
                            credit_line_id=line_id, account_id=account_id,
                            defaults={
                                "amount_rial": amount or 0,
                                "note": note or "",
                                "status": status,
                                "submitted_by": request.user if submit else None,
                            },
                        )
                        kept_ids.append(movement.id)
                        written += 1

                    # A row the user deleted from the cell is deleted here —
                    # otherwise removing an account's line from a day would
                    # leave its money silently in the totals.
                    stale = CashMovement.objects.filter(
                        period_id=period_id, direction=direction,
                        category_id=raw_category_id,
                    ).exclude(id__in=kept_ids)
                    removed += stale.count()
                    stale.delete()

        period = self._period(request.data.get("period"))
        audit_log(request.user, period, AuditLog.Action.UPDATE,
                  {"cash_entry": {"before": None, "after": f"{written} حرکت"}})

        if submit:
            first = CashMovement.objects.filter(
                period_id__in=[d.id for d in leaves_of(period)]
            ).first()
            if first:
                notify_submitted(request.user, first, "finance",
                                 f"نقدینگی · {period.label}")

        return Response({
            "ok": True, "submitted": submit,
            "movements": written, "removed": removed,
        })

    @staticmethod
    def _period(raw) -> DimPeriod:
        try:
            return DimPeriod.objects.get(pk=raw)
        except (DimPeriod.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})


class CashReportView(APIView):
    """گزارش نقدینگی — the grid, the totals, the running balance, the warnings."""

    permission_classes = [FinanceAccess]

    @extend_schema(
        parameters=[
            OpenApiParameter("period", int, description="یک ماه یا هفته"),
            OpenApiParameter("from", int, description="ماه شروع (بازه)"),
            OpenApiParameter("to", int, description="ماه پایان (بازه)"),
        ],
        responses=dict,
    )
    def get(self, request):
        assert_finance_visible(request.user)
        params = request.query_params

        if params.get("from") and params.get("to"):
            try:
                start = month_of(DimPeriod.objects.get(pk=params["from"]))
                end = month_of(DimPeriod.objects.get(pk=params["to"]))
            except (DimPeriod.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"detail": "بازه انتخاب‌شده معتبر نیست."})
            return Response(cash_report.build_range(start, end))

        try:
            period = DimPeriod.objects.get(pk=params.get("period"))
        except (DimPeriod.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})
        return Response(cash_report.build(period))


class BalanceTrendView(APIView):
    """
    میانگین موجودی — the average of daily closing balances.

    `?period=<month>` gives that month week by week; `?year=1405` gives every
    month of the year. Both split the figure by account, which is what makes
    the chart's columns stackable.
    """

    permission_classes = [FinanceAccess]

    @extend_schema(
        parameters=[
            OpenApiParameter("period", int, description="یک ماه — تفکیک هفتگی"),
            OpenApiParameter("year", int, description="سال جلالی — تفکیک ماهانه"),
        ],
        responses=dict,
    )
    def get(self, request):
        assert_finance_visible(request.user)
        params = request.query_params

        if params.get("period"):
            try:
                period = month_of(DimPeriod.objects.get(pk=params["period"]))
            except (DimPeriod.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"period": "دوره معتبر نیست."})
            return Response(balance_trend.for_month(period))

        year = params.get("year")
        if not year:
            latest = DimPeriod.objects.filter(kind=PeriodKind.MONTH).order_by(
                "-jalali_year"
            ).first()
            if latest is None:
                return Response({"year": None, "years": [], "rows": [],
                                 "year_average_rial": "0", "accounts": []})
            year = latest.jalali_year
        try:
            return Response(balance_trend.for_year(int(year)))
        except (TypeError, ValueError):
            raise ValidationError({"year": "سال معتبر نیست."})


class FinanceSettingView(APIView):
    """The opening balance and the low-cash threshold."""

    permission_classes = [FinanceAccess]

    def get(self, request):
        assert_finance_visible(request.user)
        return Response(FinanceSettingSerializer(FinanceSetting.get()).data)

    def patch(self, request):
        if not is_finance(request.user):
            raise ValidationError({"detail": "فقط واحد مالی می‌تواند تغییر دهد."})
        setting = FinanceSetting.get()
        serializer = FinanceSettingSerializer(setting, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = str(setting.opening_balance_rial)
        saved = serializer.save()
        audit_log(request.user, saved, AuditLog.Action.UPDATE,
                  {"opening_balance": {
                      "before": before, "after": str(saved.opening_balance_rial)}})
        return Response(serializer.data)
