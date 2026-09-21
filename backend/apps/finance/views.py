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
from decimal import Decimal, InvalidOperation

from apps.finance.models import (
    BankAccount,
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetAmountChange,
    BudgetLine,
    BudgetPeriod,
    BudgetStatus,
    CashCategory,
    CashMovement,
    CreditLine,
    Direction,
    FinanceSetting,
)
from apps.finance.permissions import (
    BudgetActualAccess,
    BudgetPlanAccess,
    CategoryAccess,
    FinanceAccess,
    assert_finance_visible,
    is_ceo,
    is_finance,
)
from apps.finance.serializers import (
    BankAccountSerializer,
    BudgetLineSerializer,
    BudgetSerializer,
    CashCategorySerializer,
    CashMovementSerializer,
    CreditLineSerializer,
    FinanceSettingSerializer,
)
from apps.finance.services import balance_trend, cash_report
from apps.finance.services import budget as budget_service
from apps.finance.services import executive as executive_service
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
    # Finance keeps them for the cash report; the CEO adds سرفصل‌ها while
    # defining a budget.
    permission_classes = [CategoryAccess]
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
        # Leaves only: a parent is a roll-up, never a column someone types into.
        categories = list(CashCategory.enterable())
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

        # What this sheet may write into: the days of *its* period, the leaf
        # categories on offer, and accounts / facilities that exist. Anything
        # else used to be stored as sent — a parent category counted twice
        # in every roll-up, a day from another month, an account id that
        # pointed at nothing.
        sheet = self._period(request.data.get("period"))
        day_ids = {d.id for d in leaves_of(sheet)}
        categories = {c.id: c for c in CashCategory.enterable()}
        account_ids = set(BankAccount.objects.values_list("id", flat=True))
        line_ids = set(CreditLine.objects.values_list("id", flat=True))

        for day in request.data.get("days", []):
            period_id = day.get("period_id")
            if not period_id:
                continue
            if _int(period_id) not in day_ids:
                raise ValidationError({"detail": "روز ارسال‌شده متعلق به این دوره نیست."})
            period_id = _int(period_id)
            for direction in (Direction.IN, Direction.OUT):
                for raw_category_id, rows in (day.get(direction) or {}).items():
                    category = categories.get(_int(raw_category_id))
                    if category is None or not category.allows(direction):
                        raise ValidationError({
                            "detail": "سرفصل ارسال‌شده قابل ثبت نیست؛ صفحه را تازه کنید."
                        })
                    raw_category_id = category.id
                    # A cell is a list of rows, one per account. Older clients
                    # sent a single object; accept both rather than 500.
                    if isinstance(rows, dict):
                        rows = [rows]
                    elif not isinstance(rows, list):
                        rows = [{"amount_rial": rows}]

                    kept_ids = []
                    for row in rows:
                        account_id = row.get("account") or None
                        line_id = row.get("credit_line") or None
                        note = row.get("note", "")
                        if account_id is not None and _int(account_id) not in account_ids:
                            raise ValidationError({"detail": "حساب بانکی انتخاب‌شده وجود ندارد."})
                        if line_id is not None and _int(line_id) not in line_ids:
                            raise ValidationError({"detail": "تسهیلات انتخاب‌شده وجود ندارد."})
                        try:
                            amount = Decimal(str(row.get("amount_rial") or 0))
                        except (InvalidOperation, ValueError):
                            raise ValidationError({
                                "detail": f"مبلغ «{category.name_fa}» عدد معتبری نیست."
                            })
                        if amount < 0:
                            raise ValidationError({
                                "detail": f"مبلغ «{category.name_fa}» نمی‌تواند منفی باشد؛ "
                                          "برداشت را در ستون برداشت وارد کنید."
                            })

                        existing = CashMovement.objects.filter(
                            period_id=period_id, direction=direction,
                            category_id=raw_category_id,
                            credit_line_id=line_id, account_id=account_id,
                        ).first()
                        # Never stored and still zero: leave it alone rather
                        # than filling the table with empty days.
                        if existing is None and not _nonzero(amount):
                            continue
                        values = {"amount_rial": amount or 0, "note": note or ""}
                        # Saving the sheet again must not walk an approved
                        # figure back to پیش‌نویس. Only an explicit submit
                        # moves the status of a row that already exists.
                        if submit or existing is None:
                            values["status"] = status
                            values["submitted_by"] = request.user if submit else None
                        movement, _ = CashMovement.objects.update_or_create(
                            period_id=period_id, direction=direction,
                            category_id=raw_category_id,
                            credit_line_id=line_id, account_id=account_id,
                            defaults=values,
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

        period = sheet
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


# --------------------------------------------------------------------------
# بودجه
# --------------------------------------------------------------------------

class BudgetViewSet(viewsets.ModelViewSet):
    """
    The plans themselves, plus approving one of their months.

    Approval is an action on a month rather than on the budget: اسفند is still
    being argued about while شهریور is settled, which is how the finance team
    actually works.
    """

    queryset = Budget.objects.select_related("start_period", "end_period")
    serializer_class = BudgetSerializer
    # The plan is the CEO's: finance reads it and reports against it.
    permission_classes = [BudgetPlanAccess]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["jalali_year", "is_active"]

    def perform_create(self, serializer):
        budget = serializer.save(created_by=self.request.user)
        _sync_budget_months(budget)
        audit_log(self.request.user, budget, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        budget = serializer.save()
        _sync_budget_months(budget)
        audit_log(self.request.user, budget, AuditLog.Action.UPDATE)

    @extend_schema(
        parameters=[OpenApiParameter("period", int, required=True)], responses=dict
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        Adopt one month: stamp every figure's baseline, mark it approved.

        Figures stay editable afterwards — that was the requirement — but the
        baseline is written once, so «عدد مصوب چه بود؟» keeps an answer.
        """
        budget = self.get_object()
        month = _month_param(
            request.data.get("period") or request.query_params.get("period")
        )
        bp, _ = BudgetPeriod.objects.get_or_create(budget=budget, period=month)
        stamped = bp.approve(request.user)
        audit_log(request.user, budget, AuditLog.Action.UPDATE,
                  {"approved": {"before": None, "after": month.label}})
        return Response({
            "status": bp.status,
            "status_label": BudgetStatus(bp.status).label,
            "approved_at": bp.approved_at.isoformat() if bp.approved_at else None,
            "stamped": stamped,
        })


class BudgetLineViewSet(viewsets.ModelViewSet):
    """The lines of a plan. Validation lives on the model — see the serializer."""

    queryset = BudgetLine.objects.select_related(
        "category", "category__parent", "credit_line"
    )
    serializer_class = BudgetLineSerializer
    permission_classes = [BudgetPlanAccess]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["budget", "direction", "is_active"]


def _month_param(value) -> DimPeriod:
    try:
        period = DimPeriod.objects.get(pk=value)
    except (DimPeriod.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})
    if period.kind != PeriodKind.MONTH:
        period = month_of(period)
    return period


def _budget_param(value) -> Budget:
    try:
        return Budget.objects.get(pk=value)
    except (Budget.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"budget": "بودجه انتخاب نشده یا معتبر نیست."})


def _sync_budget_months(budget: Budget) -> None:
    """
    Make sure every month in the budget's span has a row.

    Without this a plan created over seven months would have figures only for
    the months someone happened to open, and the dashboard's cumulative line
    would have holes in it.
    """
    start = (budget.start_period.jalali_year, budget.start_period.jalali_month)
    end = (budget.end_period.jalali_year, budget.end_period.jalali_month)
    months = DimPeriod.objects.filter(
        kind=PeriodKind.MONTH,
        jalali_year__gte=budget.start_period.jalali_year,
        jalali_year__lte=budget.end_period.jalali_year,
    ).order_by("jalali_year", "jalali_month")
    for month in months:
        if start <= (month.jalali_year, month.jalali_month) <= end:
            BudgetPeriod.objects.get_or_create(budget=budget, period=month)


class BudgetGridView(APIView):
    """
    The planning grid: every line of a budget against every month of it.

    One row per line, one column per month — the shape a cash plan is argued
    in. POST writes the cells that changed and records who moved what.
    Only the CEO writes it; finance reads it.
    """

    permission_classes = [BudgetPlanAccess]

    @extend_schema(
        parameters=[OpenApiParameter("budget", int, required=True)], responses=dict
    )
    def get(self, request):
        assert_finance_visible(request.user)
        budget = _budget_param(request.query_params.get("budget"))
        _sync_budget_months(budget)

        periods = list(
            BudgetPeriod.objects.filter(budget=budget)
            .select_related("period")
            .order_by("period__jalali_year", "period__jalali_month")
        )
        lines = list(
            BudgetLine.objects.filter(budget=budget, is_active=True)
            .select_related("category", "category__parent", "credit_line")
            .order_by("direction", "sort_order", "category__sort_order")
        )
        stored = {
            (a.budget_period_id, a.line_id): a
            for a in BudgetAmount.objects.filter(budget_period__budget=budget)
        }

        def cell(bp_id: int, line_id: int) -> dict:
            row = stored.get((bp_id, line_id))
            return {
                "amount_rial": str(row.amount_rial) if row else "0",
                "baseline_rial": (
                    str(row.baseline_rial)
                    if row and row.baseline_rial is not None
                    else None
                ),
                "variance_note": row.variance_note if row else "",
            }

        return Response({
            "budget": BudgetSerializer(budget).data,
            "months": [
                {
                    "budget_period_id": bp.id,
                    "period_id": bp.period_id,
                    "label": bp.period.label,
                    "status": bp.status,
                    "status_label": BudgetStatus(bp.status).label,
                    "approved_at": bp.approved_at.isoformat() if bp.approved_at else None,
                    "days": bp.period.days,
                }
                for bp in periods
            ],
            "lines": [
                {
                    **BudgetLineSerializer(line).data,
                    "cells": {str(bp.id): cell(bp.id, line.id) for bp in periods},
                }
                for line in lines
            ],
            "unit": FinanceSettingSerializer(FinanceSetting.get()).data,
            "can_edit": is_ceo(request.user),
        })

    @transaction.atomic
    def post(self, request):
        written = 0
        for cell in request.data.get("cells", []):
            try:
                bp = BudgetPeriod.objects.get(pk=cell.get("budget_period_id"))
                line = BudgetLine.objects.get(pk=cell.get("line_id"))
            except (BudgetPeriod.DoesNotExist, BudgetLine.DoesNotExist, ValueError, TypeError):
                continue
            if bp.budget_id != line.budget_id:
                raise ValidationError({"detail": "سرفصل و ماه به دو بودجهٔ متفاوت تعلق دارند."})

            row, created = BudgetAmount.objects.get_or_create(
                budget_period=bp, line=line
            )
            if "amount_rial" in cell:
                try:
                    amount = Decimal(str(cell.get("amount_rial") or 0))
                except (InvalidOperation, ValueError):
                    raise ValidationError({"detail": f"مبلغ «{line}» عدد معتبری نیست."})
                # The direction of a سرفصل already says in or out; a minus
                # sign on top would flip it silently in every total.
                if amount < 0:
                    raise ValidationError({"detail": f"مبلغ «{line}» نمی‌تواند منفی باشد."})
                if created:
                    row.amount_rial = amount
                    row.save(update_fields=["amount_rial", "updated_at"])
                    written += 1
                elif row.amount_rial != amount:
                    # The price of «always editable»: a figure that moved after
                    # approval has to leave a trace, or next month's meeting is
                    # an argument about memory.
                    BudgetAmountChange.objects.create(
                        amount=row,
                        old_rial=row.amount_rial,
                        new_rial=amount,
                        after_approval=bp.status == BudgetStatus.APPROVED,
                        reason=str(cell.get("reason") or "")[:250],
                        changed_by=request.user,
                    )
                    row.amount_rial = amount
                    row.save(update_fields=["amount_rial", "updated_at"])
                    written += 1

            if "variance_note" in cell:
                row.variance_note = str(cell.get("variance_note") or "")
                row.save(update_fields=["variance_note", "updated_at"])

        return Response({"written": written})


class BudgetVarianceView(APIView):
    """انحراف بودجه — plan beside ledger, rolled up the category tree."""

    permission_classes = [FinanceAccess]

    @extend_schema(
        parameters=[
            OpenApiParameter("budget", int, required=True),
            OpenApiParameter("period", int, required=True, description="ماه"),
        ],
        responses=dict,
    )
    def get(self, request):
        assert_finance_visible(request.user)
        budget = _budget_param(request.query_params.get("budget"))
        try:
            period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        except (DimPeriod.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})
        return Response(budget_service.build(budget, period))


class BudgetSeriesView(APIView):
    """Month by month for the dashboard, including the cumulative cash line."""

    permission_classes = [FinanceAccess]

    @extend_schema(
        parameters=[OpenApiParameter("budget", int, required=True)], responses=dict
    )
    def get(self, request):
        assert_finance_visible(request.user)
        budget = _budget_param(request.query_params.get("budget"))
        return Response(budget_service.series(budget))


class BudgetWaterfallView(APIView):
    """
    The bridge from planned net cash to actual net cash, one step per line.

    The chart that answers «چرا پول‌مان با انتظار فرق کرد؟» — a question two
    total rows leave entirely to the reader.
    """

    permission_classes = [FinanceAccess]

    @extend_schema(
        parameters=[
            OpenApiParameter("budget", int, required=True),
            OpenApiParameter("period", int, required=True),
        ],
        responses=dict,
    )
    def get(self, request):
        assert_finance_visible(request.user)
        budget = _budget_param(request.query_params.get("budget"))
        try:
            period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        except (DimPeriod.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})
        return Response(budget_service.waterfall(budget, period))


# --------------------------------------------------------------------------
# ورود ارقام واقعی بودجه
# --------------------------------------------------------------------------

def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _entry_period_param(value) -> DimPeriod:
    """The month figures belong to: a week or a day sent is read as its month."""
    try:
        period = DimPeriod.objects.get(pk=value)
    except (DimPeriod.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})
    return period if period.kind == PeriodKind.MONTH else month_of(period)


def _require_month_in_budget(budget: Budget, period: DimPeriod) -> None:
    month = period if period.kind == PeriodKind.MONTH else month_of(period)
    if not BudgetPeriod.objects.filter(budget=budget, period=month).exists():
        raise ValidationError({"period": "این دوره در بازهٔ این بودجه نیست."})


class BudgetActualEntryView(APIView):
    """
    ورود ارقام واقعی بودجه — the finance team's monthly sheet.

    Every سرفصل of the budget, its plan for the month and the actual keyed
    against it. The CEO defines the plan; finance reports against it here and
    cannot move it.
    """

    permission_classes = [BudgetActualAccess]

    @extend_schema(
        parameters=[
            OpenApiParameter("budget", int, required=True),
            OpenApiParameter("period", int, required=True, description="ماه"),
        ],
        responses=dict,
    )
    def get(self, request):
        budget = _budget_param(request.query_params.get("budget"))
        period = _entry_period_param(request.query_params.get("period"))
        _require_month_in_budget(budget, period)
        sheet = budget_service.entry_sheet(budget, period)
        sheet["can_edit"] = is_finance(request.user)
        sheet["unit"] = FinanceSettingSerializer(FinanceSetting.get()).data
        return Response(sheet)

    @transaction.atomic
    def post(self, request):
        budget = _budget_param(request.data.get("budget"))
        period = _entry_period_param(request.data.get("period"))
        _require_month_in_budget(budget, period)
        lines = {ln.id: ln for ln in BudgetLine.objects.filter(budget=budget, is_active=True)}
        written = 0
        for cell in request.data.get("cells", []):
            line = lines.get(_int(cell.get("line_id")))
            if line is None:
                continue
            try:
                amount = Decimal(str(cell.get("amount_rial") or 0))
            except (InvalidOperation, ValueError):
                raise ValidationError({"detail": f"مبلغ «{line}» عدد معتبری نیست."})
            if amount < 0:
                raise ValidationError({"detail": f"مبلغ «{line}» نمی‌تواند منفی باشد."})
            note = str(cell.get("note") or "")[:250]

            existing = BudgetActual.objects.filter(line=line, period=period).first()
            # Never keyed and still blank: leave it out rather than filling
            # the table with zeros nobody entered.
            if existing is None and not amount and not note:
                continue
            if existing and existing.amount_rial == amount and existing.note == note:
                continue
            BudgetActual.objects.update_or_create(
                line=line, period=period,
                defaults={"amount_rial": amount, "note": note, "entered_by": request.user},
            )
            written += 1

        if written:
            audit_log(request.user, budget, AuditLog.Action.UPDATE, {
                "budget_actuals": {"before": None, "after": f"{period.label}: {written} سرفصل"},
            })
        return Response({"written": written})


class BudgetNoteView(APIView):
    """
    علت انحراف — written by the finance team, who know why an actual moved.

    Kept apart from the plan grid, which is the CEO's: explaining a variance
    must not require the right to change the budget.
    """

    permission_classes = [BudgetActualAccess]

    def post(self, request):
        try:
            bp = BudgetPeriod.objects.get(pk=request.data.get("budget_period_id"))
            line = BudgetLine.objects.get(pk=request.data.get("line_id"))
        except (BudgetPeriod.DoesNotExist, BudgetLine.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"detail": "سرفصل یا ماه معتبر نیست."})
        if bp.budget_id != line.budget_id:
            raise ValidationError({"detail": "سرفصل و ماه به دو بودجهٔ متفاوت تعلق دارند."})
        row, _ = BudgetAmount.objects.get_or_create(budget_period=bp, line=line)
        row.variance_note = str(request.data.get("variance_note") or "")
        row.save(update_fields=["variance_note", "updated_at"])
        return Response({"variance_note": row.variance_note})


# --------------------------------------------------------------------------
# charts and the CEO's financial picture
# --------------------------------------------------------------------------

def _period_param(value) -> DimPeriod:
    try:
        return DimPeriod.objects.get(pk=value)
    except (DimPeriod.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"period": "دوره انتخاب نشده یا معتبر نیست."})


class ExecutiveFinanceView(APIView):
    """نمای مالی on the CEO's overview: cash, credit and budget for one month."""

    permission_classes = [FinanceAccess]

    @extend_schema(parameters=[OpenApiParameter("period", int, required=True)], responses=dict)
    def get(self, request):
        assert_finance_visible(request.user)
        return Response(executive_service.summary(_period_param(request.query_params.get("period"))))


class BudgetHeatmapView(APIView):
    """Top-level groups × months: how far each strayed from plan."""

    permission_classes = [FinanceAccess]

    @extend_schema(parameters=[OpenApiParameter("budget", int, required=True)], responses=dict)
    def get(self, request):
        assert_finance_visible(request.user)
        return Response(budget_service.heatmap(_budget_param(request.query_params.get("budget"))))

