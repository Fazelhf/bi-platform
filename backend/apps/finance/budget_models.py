"""
Budget — what the company expected, beside what actually happened.

Budgets are defined by hand, in the platform: the finance team names the
lines, keys the expected figure for each month, and approves month by month.

Four ideas the design rests on:

* **There is no «actual» table.** A budget line names a `CashCategory` leaf,
  and its actual is the sum of the `CashMovement` rows already recorded
  against that leaf. The finance team keys a number once, in the place they
  key it today, and variance falls out. A second actuals table would mean
  double entry and, within a quarter, two figures that disagree.

* **Budget is monthly, comparison is weekly.** Approval happens on a month —
  that is the grain the plan is argued at. Actuals arrive weekly, on the
  leaves of `DimPeriod`. A weekly budget figure is *never stored*; it is the
  month pro-rated by days, because weeks are not all the same length. Storing
  both would double count exactly the way the period tree warns about.

* **Editable, but the approved figure survives.** The team wanted budgets to
  stay editable after approval. Full versioning would answer «what was
  approved?» at the cost of a table nobody enjoys. One extra column answers it
  instead: approving copies `amount_rial` into `baseline_rial`, which nothing
  writes again.

* **A variance without a reason is not finished.** The field that turns the
  monthly meeting from «why is this number like this?» into «what do we do?»
  is a sentence from the person who knows. It lives on the figure, not in an
  email.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import DimPeriod, PeriodKind, TimeStampedModel
from apps.sales.models import SalesChannel

from .models import CashCategory, CreditLine, Direction, FinanceSetting

ZERO = Decimal(0)


class BudgetStatus(models.TextChoices):
    """
    Where a month of a budget stands.

    Deliberately not the platform's ApprovalStatus: that one models a figure
    submitted by one person and approved by another. A budget month is argued
    over and then adopted — there is no «rejected» state, only a draft that
    has not been approved yet.
    """

    DRAFT = "draft", "پیش‌نویس"
    APPROVED = "approved", "مصوب"
    CLOSED = "closed", "بسته‌شده"


class Budget(TimeStampedModel):
    """
    One named plan — «بودجهٔ ۱۴۰۴» — spanning a run of months.

    More than one may be active at a time: a base plan and a revised one, or
    next year's draft beside this year's. Which one a report means is always
    explicit rather than «the current budget», because the two disagreeing is
    the normal state of affairs, not an error.
    """

    title = models.CharField(max_length=150)
    jalali_year = models.PositiveSmallIntegerField()
    start_period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="budgets_starting",
        help_text="اولین ماه بودجه",
    )
    end_period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="budgets_ending",
        help_text="آخرین ماه بودجه",
    )
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-jalali_year", "title")
        verbose_name = "budget (بودجه)"
        verbose_name_plural = "budgets"

    def clean(self) -> None:
        for field in ("start_period", "end_period"):
            period = getattr(self, f"{field}_id") and getattr(self, field)
            if period and period.kind != PeriodKind.MONTH:
                raise ValidationError({field: "بازهٔ بودجه باید ماه باشد."})
        if self.start_period_id and self.end_period_id:
            start, end = self.start_period, self.end_period
            if (start.jalali_year, start.jalali_month) > (end.jalali_year, end.jalali_month):
                raise ValidationError({"end_period": "ماه پایان پیش از ماه شروع است."})

    def __str__(self) -> str:
        return self.title


class BudgetLine(TimeStampedModel):
    """
    One budgeted line — «خرید جمبو», «بازپرداخت اصل تسهیلات پارسیان».

    A line is a `CashCategory` **leaf** plus, optionally, a `CreditLine`. That
    second part is what lets پارسیان and کارآفرین be separate lines without
    being separate categories: they are the same kind of payment to different
    counterparties, and the counterparty already has a model.

    Nothing here stores a total. The tree of categories provides the
    hierarchy; a parent's budget is the sum of the lines beneath it, computed
    the same way its actuals are.
    """

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    category = models.ForeignKey(
        CashCategory, on_delete=models.PROTECT, related_name="budget_lines",
        help_text="دستهٔ نقدینگی — باید برگ باشد، چون حرکت‌ها فقط روی برگ ثبت می‌شوند",
    )
    #: Which facility / loan / partner account this line is about. Required
    #: when the category's branch expects one, so a تسهیلات line always says
    #: whose instalment it is.
    credit_line = models.ForeignKey(
        CreditLine, null=True, blank=True,
        on_delete=models.PROTECT, related_name="budget_lines",
    )
    #: A category may be BOTH (جاری شرکا). A *line* never is — money planned
    #: to come in and money planned to go out are two different plans, and the
    #: sign of a variance means the opposite thing for each.
    direction = models.CharField(max_length=3, choices=Direction.choices)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        unique_together = ("budget", "category", "credit_line", "direction")
        ordering = ("sort_order", "category__sort_order")
        verbose_name = "budget line (قلم بودجه)"
        verbose_name_plural = "budget lines"
        indexes = [models.Index(fields=["budget", "direction"])]

    def clean(self) -> None:
        if self.category_id:
            if not self.category.is_leaf:
                raise ValidationError(
                    {"category": "فقط دستهٔ برگ (بدون زیرمجموعه) قابل بودجه‌بندی است."}
                )
            if self.direction and not self.category.allows(self.direction):
                raise ValidationError(
                    {"direction": "این جهت برای دستهٔ انتخاب‌شده مجاز نیست."}
                )
            if self.category.needs_credit_line and not self.credit_line_id:
                raise ValidationError(
                    {"credit_line": "برای این دسته باید طرف‌حساب مشخص شود."}
                )

    @property
    def is_favourable_when_over(self) -> bool:
        """
        Whether exceeding the budget is good news.

        The whole reason variance cannot be coloured by the sign of a number:
        spending more than planned is bad, collecting more than planned is
        good. Read this, never `amount > budget`.
        """
        return self.direction == Direction.IN

    def __str__(self) -> str:
        who = f" · {self.credit_line.counterparty}" if self.credit_line_id else ""
        return f"{self.category.name_fa}{who}"


class BudgetPeriod(TimeStampedModel):
    """
    One month of one budget, and its approval.

    Approval is per month rather than per budget because that is how the
    finance team works: اسفند is still being argued about while شهریور is
    settled. Approving stamps every figure in the month with its baseline.
    """

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="periods")
    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="budget_periods",
        help_text="ماه — بودجه هرگز روی هفته ذخیره نمی‌شود",
    )
    status = models.CharField(
        max_length=10, choices=BudgetStatus.choices, default=BudgetStatus.DRAFT
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        unique_together = ("budget", "period")
        ordering = ("period__jalali_year", "period__jalali_month")
        verbose_name = "budget month (ماه بودجه)"
        verbose_name_plural = "budget months"

    def clean(self) -> None:
        if self.period_id and self.period.kind != PeriodKind.MONTH:
            raise ValidationError({"period": "بودجه فقط در سطح ماه ثبت می‌شود."})

    def approve(self, user=None) -> int:
        """
        Adopt this month: stamp every figure's baseline, then mark approved.

        Figures stay editable afterwards — that was the requirement — but
        `baseline_rial` is written once and never again, so «چقدر از مصوب
        فاصله گرفتیم؟» keeps an answer however many times someone edits.
        """
        from django.utils import timezone

        stamped = 0
        for amount in self.amounts.all():
            if amount.baseline_rial is None:
                amount.baseline_rial = amount.amount_rial
                amount.save(update_fields=["baseline_rial", "updated_at"])
                stamped += 1
        for forecast in self.sales_forecasts.all():
            if forecast.baseline_rial is None:
                forecast.baseline_rial = forecast.amount_rial
                forecast.save(update_fields=["baseline_rial", "updated_at"])
                stamped += 1
        self.status = BudgetStatus.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        return stamped

    def __str__(self) -> str:
        return f"{self.budget.title} · {self.period.label}"


class BudgetAmount(TimeStampedModel):
    """
    The figure: one line, one month.

    `amount_rial` is the live plan and stays editable. `baseline_rial` is what
    was approved, or NULL while the month is still a draft — the two together
    give a three-way read (مصوب / جاری / واقعی) without a versions table.

    The actual is not here. It is computed from `CashMovement` at read time,
    so it can never drift from the ledger it is supposed to describe.
    """

    budget_period = models.ForeignKey(
        BudgetPeriod, on_delete=models.CASCADE, related_name="amounts"
    )
    line = models.ForeignKey(
        BudgetLine, on_delete=models.CASCADE, related_name="amounts"
    )
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    #: Stamped once, at approval. NULL means this month was never approved.
    baseline_rial = models.DecimalField(
        max_digits=20, decimal_places=0, null=True, blank=True,
        help_text="مبلغ در لحظهٔ تصویب — پس از آن تغییر نمی‌کند",
    )
    #: Why the actual differed. Written after the fact, by whoever knows.
    variance_note = models.TextField(
        blank=True, help_text="علت انحراف — برای انحراف‌های مهم"
    )

    class Meta:
        unique_together = ("budget_period", "line")
        ordering = ("line__sort_order",)
        verbose_name = "budget amount (مبلغ بودجه)"
        verbose_name_plural = "budget amounts"
        indexes = [models.Index(fields=["budget_period", "line"])]

    def clean(self) -> None:
        if (
            self.budget_period_id
            and self.line_id
            and self.budget_period.budget_id != self.line.budget_id
        ):
            raise ValidationError({"line": "این قلم به بودجهٔ دیگری تعلق دارد."})

    def for_week(self, week: DimPeriod) -> Decimal:
        """
        This month's plan, pro-rated onto one of its weeks by day count.

        Never stored — storing it would put figures on two levels of the
        period tree at once. Calendar pro-rating is honest for steady lines
        (اجاره, حقوق, سربار) and misleading for lumpy ones (اقساط, خرید
        جمبو), which is why the weekly view is labelled «رصد جریان نقد» and
        the monthly one «انحراف بودجه».
        """
        month_days = self.budget_period.period.days
        if not month_days or not week.days:
            return ZERO
        return (self.amount_rial * week.days / month_days).quantize(Decimal("1"))

    def __str__(self) -> str:
        return f"{self.line} · {self.budget_period.period.label}"


class BudgetAmountChange(TimeStampedModel):
    """
    Who changed a figure, when, from what to what.

    The price of «always editable». Without it, a budget that moved towards
    the actual after the fact is indistinguishable from one that was right all
    along, and next month's meeting is an argument about memory.
    """

    amount = models.ForeignKey(
        BudgetAmount, on_delete=models.CASCADE, related_name="changes"
    )
    old_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    new_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    #: True when the figure moved after its month had been approved — the
    #: edits worth reading.
    after_approval = models.BooleanField(default=False)
    reason = models.CharField(max_length=250, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "budget change (تغییر بودجه)"
        verbose_name_plural = "budget changes"
        indexes = [models.Index(fields=["amount", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.amount} · {self.old_rial} → {self.new_rial}"


def is_material(variance_rial: Decimal, budget_rial: Decimal) -> bool:
    """
    Whether a variance is worth surfacing, per the department's thresholds.

    Both bars must be cleared. Percent alone floods the grid with lines that
    moved 40% of a trivial figure; rial alone flags every large line that
    moved 1%. Neither is a signal by itself.
    """
    setting = FinanceSetting.get()
    size = abs(variance_rial)
    if setting.variance_threshold_rial and size < setting.variance_threshold_rial:
        return False
    if not budget_rial:
        return size > ZERO
    pct = size * 100 / abs(budget_rial)
    return pct >= setting.variance_threshold_pct


class BudgetSalesForecast(TimeStampedModel):
    """
    Expected sales for one channel in one month of a budget.

    Accrual, not cash, so it never enters the budget's in/out totals: the cash
    a sale turns into is planned separately, on وصول نقدی and وصول مطالبات.
    Counting both would plan the same rial twice.

    Kept on the budget rather than on SalesTarget because SalesTarget is set
    per salesperson or per province, and a cash plan is argued per channel.
    Its actual is the channel's recorded sales (FactSalesMonthly.revenue_rial),
    so the forecast gets a variance like any other line.
    """

    budget_period = models.ForeignKey(
        BudgetPeriod, on_delete=models.CASCADE, related_name="sales_forecasts"
    )
    channel = models.CharField(max_length=16, choices=SalesChannel.choices)
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    baseline_rial = models.DecimalField(
        max_digits=20, decimal_places=0, null=True, blank=True,
        help_text="مبلغ در لحظهٔ تصویب — پس از آن تغییر نمی‌کند",
    )

    class Meta:
        unique_together = ("budget_period", "channel")
        ordering = ("channel",)
        verbose_name = "sales forecast (پیش‌بینی فروش)"
        verbose_name_plural = "sales forecasts"

    def __str__(self) -> str:
        return f"{self.get_channel_display()} · {self.budget_period}"
