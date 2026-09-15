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


class CurrencyUnit(models.TextChoices):
    """
    How figures are shown. Everything is *stored* in Rial — the unit only
    changes presentation, so switching it can never alter a recorded amount.
    """

    RIAL = "rial", "ریال"
    TOMAN = "toman", "تومان"


class BankAccount(TimeStampedModel):
    """
    A bank account or cash box. Every movement names one, so «چقدر پول داریم؟»
    can be answered per account rather than only in total — which is the
    question that actually gets asked when a payment is due from a particular
    bank.

    Each account carries its own opening balance; the company's opening
    balance is their sum rather than a separate figure that could disagree.
    """

    class Kind(models.TextChoices):
        BANK = "bank", "حساب بانکی"
        CASH = "cash", "صندوق"
        PETTY = "petty", "تنخواه"

    title = models.CharField(max_length=120)
    bank_name = models.CharField(max_length=100, blank=True)
    account_no = models.CharField(max_length=40, blank=True)
    iban = models.CharField("شبا", max_length=34, blank=True)
    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.BANK)
    opening_balance_rial = models.DecimalField(
        max_digits=20, decimal_places=0, default=0,
        help_text="موجودی این حساب پیش از اولین روزِ ثبت‌شده",
    )
    #: Drawn in the stacked balance chart, so each account keeps one colour.
    color = models.CharField(max_length=7, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ("sort_order", "title")
        verbose_name = "bank account (حساب)"

    @property
    def label(self) -> str:
        return f"{self.title} — {self.bank_name}" if self.bank_name else self.title

    def __str__(self) -> str:
        return self.label


class FinanceSetting(TimeStampedModel):
    """
    Singleton for the few settings that belong to the department rather than
    to one account: the low-cash warning threshold and the display unit.

    The opening balance used to live here as a single figure. It moved onto
    BankAccount when movements gained an account, so the total is the sum of
    real accounts instead of a number kept beside them that could drift.
    """

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    opening_balance_rial = models.DecimalField(
        max_digits=20, decimal_places=0, default=0,
        help_text="منسوخ — موجودی اولیه اکنون روی هر حساب ثبت می‌شود",
    )
    opening_on = models.DateField(
        null=True, blank=True, help_text="تاریخی که موجودی بالا به آن تعلق دارد"
    )
    #: Warn when the running balance drops under this.
    low_balance_rial = models.DecimalField(
        max_digits=20, decimal_places=0, default=0,
        help_text="آستانه هشدار کمبود نقدینگی — صفر یعنی بدون هشدار",
    )
    unit = models.CharField(
        max_length=6, choices=CurrencyUnit.choices, default=CurrencyUnit.RIAL,
        help_text="واحد نمایش؛ ذخیره‌سازی همیشه ریال است",
    )

    # ---- budget variance --------------------------------------------------
    # A variance counts as worth looking at only when it clears BOTH bars.
    # Percent alone floods the screen with tiny lines that moved 40%; rial
    # alone flags every big line that moved 1%. Neither is a signal on its
    # own, so «مهم» is the intersection.
    variance_threshold_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("10"),
        help_text="انحراف از چند درصد به بالا مهم شمرده شود",
    )
    variance_threshold_rial = models.DecimalField(
        max_digits=20, decimal_places=0, default=0,
        help_text="انحراف از چه مبلغی به بالا مهم شمرده شود — صفر یعنی بدون کف مبلغی",
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

    **A tree, for the same reason `DimPeriod` is one.** Budgeting asks
    questions the flat list cannot answer — «از خرید جمبو چقدر انتظار داشتیم
    و چقدر شد؟» needs جمبو to be its own line, not a rial inside تامین
    کننده. So a category may have a parent, and the same invariant applies:

        Movements are stored **only on leaves**. A parent's figure is always
        the roll-up of its children, never written.

    Without that rule a month recorded against both تامین کننده and its child
    خرید جمبو would double count, silently. `clean()` and the entry grid both
    enforce it; `leaf_ids()` is how every report rolls a parent up.
    """

    class Allowed(models.TextChoices):
        IN = "in", "فقط واریز"
        OUT = "out", "فقط برداشت"
        BOTH = "both", "هر دو"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="children",
        help_text="دستهٔ والد — اگر خالی باشد، این دسته در سطح اول است",
    )
    direction = models.CharField(
        max_length=5, choices=Allowed.choices, default=Allowed.BOTH
    )
    #: Categories that describe a credit relationship (تسهیلات / قرض / شرکا)
    #: expect their movements to name one, so a balance can be kept. Children
    #: inherit it — every child of تسهیلات needs a credit line too — so read
    #: `needs_credit_line` rather than this field.
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

    # ---- tree -------------------------------------------------------------

    @property
    def is_leaf(self) -> bool:
        return not self.children.exists()

    @property
    def needs_credit_line(self) -> bool:
        """
        True when this category or any ancestor expects one. Set on تسهیلات
        once; every child of it inherits rather than repeating the flag and
        risking one of them being missed.
        """
        node = self
        while node is not None:
            if node.expects_credit_line:
                return True
            node = node.parent
        return False

    def leaves(self) -> list["CashCategory"]:
        """This category's leaves — or itself when it has none."""
        children = list(self.children.all())
        if not children:
            return [self]
        out: list["CashCategory"] = []
        for child in children:
            out.extend(child.leaves())
        return out

    def leaf_ids(self) -> list[int]:
        """The ids a report sums over to get this category's figure."""
        return [c.id for c in self.leaves()]

    @classmethod
    def enterable(cls):
        """
        The categories a figure may be recorded against — leaves only.

        Every grid that offers a column, and every query that lists what can
        be picked, goes through here. A parent shown as an enterable column is
        how the double counting the tree exists to prevent gets back in.
        """
        return cls.objects.filter(is_active=True, children__isnull=True)

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        # A cycle would make leaves() recurse forever.
        node = self.parent
        while node is not None:
            if node.pk == self.pk:
                raise ValidationError({"parent": "دستهٔ والد نمی‌تواند زیرمجموعهٔ خودش باشد."})
            node = node.parent

        # A parent's direction has to contain its children's, or a child
        # could take a movement its own branch is not allowed to report. A
        # BOTH parent contains everything; otherwise the child must match.
        if (
            self.parent
            and self.parent.direction != self.Allowed.BOTH
            and self.direction != self.parent.direction
        ):
            raise ValidationError(
                {"direction": "جهت این دسته با جهت مجاز دستهٔ والد نمی‌خواند."}
            )

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
    #: Which bank account or cash box the money moved through. Nullable only
    #: so the rows recorded before accounts existed keep working; the entry
    #: form requires one.
    account = models.ForeignKey(
        BankAccount, null=True, blank=True,
        on_delete=models.PROTECT, related_name="movements",
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
        # One figure per day per category per direction per account — the
        # shape of his sheet once accounts were added, and what makes
        # re-entering a day idempotent rather than duplicating it.
        unique_together = ("period", "direction", "category", "credit_line", "account")
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


# The budget models live in their own module — treasury and budgeting are
# different jobs — but Django only registers models that are imported when the
# app loads, so they are pulled in here rather than left for a caller to find.
from .budget_models import (  # noqa: E402,F401  (import position is required)
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetAmountChange,
    BudgetLine,
    BudgetPeriod,
    BudgetSalesForecast,
    BudgetStatus,
    is_material,
)
