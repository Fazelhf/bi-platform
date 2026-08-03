"""
Treasury — cash in, cash out, and the credit relationships behind some of it.

Reverse-engineered from the finance colleague's گزارش نقدینگی: a daily ledger
with one column per category, split into واریز and برداشت, summed by day and
by category.

Three ideas the workbook does not have, added because the section is meant to
grow:

* **Categories are data, not code.** His sheet has a «نامشخص» column — proof
  that the list is still settling. A new category must be a row someone types,
  not a deploy.
* **Movements are the only source of cash truth.** Daily/weekly/monthly
  reports are derived from them, the way the sales dashboards derive from
  FactSalesMonthly. Nothing stores a total that could drift from its parts.
* **Facilities, lending and partner accounts are one model.** تسهیلات received,
  قرض given out and جاری شرکا are the same object — a counterparty, a
  principal and a running balance — differing only in direction. One model
  means one balance calculation instead of three that disagree.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import DimPeriod, TimeStampedModel
from apps.sales.models import ApprovalStatus

ZERO = Decimal(0)


class Direction(models.TextChoices):
    """Which way money moved."""

    IN = "in", "واریز"
    OUT = "out", "برداشت"


class FinanceSetting(TimeStampedModel):
    """
    Singleton. Exists for one number the workbook does not have: what the
    company held before the ledger starts.

    Without it a cash report can only show *flow* — his week netted −۳٫۸
    میلیارد, which says the direction but not whether that is survivable.
    With an opening balance the same report answers «چقدر پول داریم؟».
    """

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    opening_balance_rial = models.DecimalField(
        max_digits=20, decimal_places=0, default=0,
        help_text="موجودی نقد در ابتدای اولین روزِ ثبت‌شده",
    )
    opening_on = models.DateField(
        null=True, blank=True, help_text="تاریخی که موجودی بالا به آن تعلق دارد"
    )
    #: Warn when the running balance drops under this.
    low_balance_rial = models.DecimalField(
        max_digits=20, decimal_places=0, default=0,
        help_text="آستانه هشدار کمبود نقدینگی — صفر یعنی بدون هشدار",
    )

    @classmethod
    def get(cls) -> "FinanceSetting":
        obj, _ = cls.objects.get_or_create(singleton=True)
        return obj

    def __str__(self) -> str:
        return f"تنظیمات مالی (موجودی اولیه {self.opening_balance_rial})"


class CashCategory(TimeStampedModel):
    """
    A line on the cash report — فروش, تامین کننده, تنخواه and so on.

    `direction` is what the category is *allowed* to be used for. جاری شرکا
    legitimately appears on both sides of his sheet, hence BOTH.
    """

    class Allowed(models.TextChoices):
        IN = "in", "فقط واریز"
        OUT = "out", "فقط برداشت"
        BOTH = "both", "هر دو"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    direction = models.CharField(
        max_length=5, choices=Allowed.choices, default=Allowed.BOTH
    )
    #: Categories that describe a credit relationship (تسهیلات / قرض / شرکا)
    #: expect their movements to name one, so a balance can be kept.
    expects_credit_line = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ("sort_order", "name_fa")
        verbose_name = "cash category (دسته نقدینگی)"
        verbose_name_plural = "cash categories"

    def allows(self, direction: str) -> bool:
        return self.direction == self.Allowed.BOTH or self.direction == direction

    def __str__(self) -> str:
        return self.name_fa


class CreditLine(TimeStampedModel):
    """
    A standing money relationship with a running balance.

    One model, three kinds:

    * FACILITY — a bank lends the company (تسهیلات). Drawing it down is cash
      in; each instalment is cash out.
    * LENDING — the company lends someone (قرض). Paying it out is cash out;
      being repaid is cash in.
    * PARTNER — جاری شرکا. Flows both ways; the balance says whether the
      partner currently owes the company or the other way round.

    The balance is never stored. It is the signed sum of the movements that
    point here, so it cannot disagree with the ledger.
    """

    class Kind(models.TextChoices):
        FACILITY = "facility", "تسهیلات دریافتی"
        LENDING = "lending", "قرض پرداختی"
        PARTNER = "partner", "جاری شرکا"

    class Status(models.TextChoices):
        ACTIVE = "active", "جاری"
        SETTLED = "settled", "تسویه‌شده"
        OVERDUE = "overdue", "معوق"
        CANCELLED = "cancelled", "لغوشده"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=150)
    counterparty = models.CharField(
        max_length=150, help_text="بانک، شرکت یا شخص طرف حساب"
    )
    #: What was agreed. Zero for a partner account, which has no ceiling.
    principal_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    rate_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="نرخ سود سالانه (٪) — برای قرض‌الحسنه صفر",
    )
    opened_on = models.DateField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    installments = models.PositiveSmallIntegerField(
        default=0, help_text="تعداد اقساط — صفر یعنی بدون زمان‌بندی"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("kind", "counterparty", "title")
        verbose_name = "credit line (تسهیلات / قرض / جاری)"

    # -- derived ---------------------------------------------------------
    def totals(self) -> dict:
        """Money in and out against this line, from the ledger alone."""
        rows = self.movements.values("direction").annotate(
            total=models.Sum("amount_rial")
        )
        received = ZERO
        paid = ZERO
        for row in rows:
            if row["direction"] == Direction.IN:
                received += row["total"] or ZERO
            else:
                paid += row["total"] or ZERO
        return {"received": received, "paid": paid}

    @property
    def balance_rial(self) -> Decimal:
        """
        What is still outstanding, signed from the company's point of view.

        Positive means the company is owed (it lent, or a partner is in
        debit); negative means the company owes (a facility not yet repaid).
        """
        t = self.totals()
        return t["paid"] - t["received"]

    @property
    def is_settled(self) -> bool:
        return self.balance_rial == ZERO

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.counterparty} — {self.title}"


class CashMovement(TimeStampedModel):
    """
    One day's money in or out of one category — the grain the finance
    colleague already works at.

    Not one row per bank transaction: he reports a daily figure per category,
    and asking him to key every transfer would be a different job. If that
    changes, this table takes the finer rows without a reshape, because the
    grain is "a movement", not "a day".
    """

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="cash_movements",
        help_text="روزِ گزارش (برگ روز از درخت دوره‌ها)",
    )
    direction = models.CharField(max_length=3, choices=Direction.choices)
    category = models.ForeignKey(
        CashCategory, on_delete=models.PROTECT, related_name="movements"
    )
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    #: Set when the movement belongs to a facility, a loan or a partner
    #: account — this is what gives those their balance.
    credit_line = models.ForeignKey(
        CreditLine, null=True, blank=True,
        on_delete=models.PROTECT, related_name="movements",
    )
    note = models.CharField(max_length=250, blank=True)

    # Same submit → approve path as every other figure in the platform, so
    # the CEO's کارتابل is one queue rather than one per department.
    status = models.CharField(
        max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        # One figure per day per category per direction — the shape of his
        # sheet, and what makes re-entering a day idempotent.
        unique_together = ("period", "direction", "category", "credit_line")
        ordering = ("period", "direction", "category__sort_order")
        indexes = [
            models.Index(fields=["period", "direction"]),
            models.Index(fields=["status"]),
        ]

    @property
    def signed_rial(self) -> Decimal:
        """+ for money in, − for money out, so a period nets by summing."""
        return self.amount_rial if self.direction == Direction.IN else -self.amount_rial

    def __str__(self) -> str:
        return f"{self.period} · {self.get_direction_display()} · {self.category}"
