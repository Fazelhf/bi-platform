"""
CRM domain — the transactional layer under the monthly sales facts.

Why this exists: the v1 dashboards read `sales.FactSalesMonthly`, one
pre-aggregated row per salesperson per month. That answers "how much did
Mahsa sell in Tir?" but it can never answer "*which* deals, for *which*
customers, at *what* margin, and why did the rest fall through?" — which is
exactly what the sales manager asks of Didar every day.

So CRM stores the individual records (customer, deal, deal line, activity)
and every dashboard number is derived from them. That makes every figure
*drillable*: each aggregate row carries the filter that reproduces it, and
the UI re-queries the underlying records with that filter.

Grain summary:
    Customer   — one company/person we sell to
    Deal       — one sales opportunity (معامله), moves along a pipeline
    DealItem   — one product line inside a deal (this is where margin lives)
    Activity   — one touch: call, meeting, quote, sample, invoice, payment
    StageEvent — one movement between pipeline stages (funnel + velocity)

Everything is stamped with a DimPeriod (Jalali month) so CRM figures line up
with the existing monthly sales/production reporting calendar.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import DimPeriod, TimeStampedModel
from apps.sales.models import DimEmployee, DimProvince, SalesChannel


# --------------------------------------------------------------------------
# Reference / lookup tables (all CEO-editable, all used as report axes)
# --------------------------------------------------------------------------
class CustomerGroup(TimeStampedModel):
    """گروه مشتری — the market segment a customer belongs to."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "گروه مشتری"

    def __str__(self) -> str:
        return self.name_fa


class Tag(TimeStampedModel):
    """برچسب — free-form label attachable to customers and deals."""

    name_fa = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name_fa",)

    def __str__(self) -> str:
        return self.name_fa


class LeadSource(TimeStampedModel):
    """منبع سرنخ — how the customer first found us. Drives the
    "بهترین منابع سرنخ" report: which channels actually convert."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "منبع سرنخ"

    def __str__(self) -> str:
        return self.name_fa


class LostReason(TimeStampedModel):
    """دلیل از دست رفتن — why a deal was lost. Required when a deal is marked lost,
    which is what makes the "دلایل از دست رفتن فرصت" report trustworthy."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    # Losing on price is fixable by us; losing to a competitor is a market
    # signal. Grouping them keeps the report actionable.
    is_controllable = models.BooleanField(
        default=True, help_text="آیا این دلیل در کنترل ماست؟ (قیمت/تاخیر بله، نیاز مشتری خیر)"
    )

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "دلیل از دست رفتن"

    def __str__(self) -> str:
        return self.name_fa


class ProductCategory(TimeStampedModel):
    """دسته محصول — e.g. کاغذ حرارتی، کاغذ کربن‌لس، رول بانکی."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "دسته محصول"

    def __str__(self) -> str:
        return self.name_fa


class Product(TimeStampedModel):
    """
    محصول. `unit_cost_rial` is what makes profit reporting possible: margin is
    computed per deal line, so "سود فروش" can always be explained by *which*
    products were in the basket rather than being an opaque number.
    """

    class Unit(models.TextChoices):
        ROLL = "roll", "رول"
        PACK = "pack", "بسته"
        TON = "ton", "تن"
        SHEET = "sheet", "برگ"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=150)
    category = models.ForeignKey(
        ProductCategory, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="products",
    )
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.ROLL)
    list_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    unit_cost_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "محصول"

    @property
    def margin_pct(self) -> float:
        if not self.list_price_rial:
            return 0.0
        return float(
            (self.list_price_rial - self.unit_cost_rial) / self.list_price_rial * 100
        )

    def __str__(self) -> str:
        return self.name_fa


class PipelineStage(TimeStampedModel):
    """
    مرحله فروش — one column of the sales pipeline board.

    `kind` is what the reports key on, not the name: a stage is either still
    in play (OPEN), a win (WON) or a loss (LOST). That way the pipeline can be
    renamed/reordered by the sales manager without breaking a single report.
    """

    class Kind(models.TextChoices):
        OPEN = "open", "در جریان"
        WON = "won", "موفق"
        LOST = "lost", "ناموفق"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.OPEN)
    # Weighted-pipeline forecasting: amount x probability.
    probability_pct = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "مرحله فروش"

    def __str__(self) -> str:
        return self.name_fa


# --------------------------------------------------------------------------
# Customer
# --------------------------------------------------------------------------
class Customer(TimeStampedModel):
    """
    مشتری. `owner` is the salesperson accountable for the account — every
    per-rep report (new customers, active customers, satisfaction) hangs off
    it. `first_deal_won_at` is denormalised so "مشتری جدید" (a customer whose
    first win happened in this month) is a cheap query instead of a subquery
    over every deal.
    """

    class Kind(models.TextChoices):
        COMPANY = "company", "شرکت / سازمان"
        PERSON = "person", "شخص حقیقی"

    class Status(models.TextChoices):
        LEAD = "lead", "سرنخ"
        ACTIVE = "active", "مشتری فعال"
        DORMANT = "dormant", "راکد"
        LOST = "lost", "از دست رفته"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.COMPANY)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LEAD)

    group = models.ForeignKey(
        CustomerGroup, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customers",
    )
    province = models.ForeignKey(
        DimProvince, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_customers",
    )
    city = models.CharField(max_length=100, blank=True)
    lead_source = models.ForeignKey(
        LeadSource, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customers",
    )
    owner = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customers",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="customers")

    contact_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    mobile = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=400, blank=True)
    national_id = models.CharField(max_length=20, blank=True)  # شناسه ملی / کد اقتصادی
    note = models.TextField(blank=True)

    # Lifecycle markers used by the "مشتری جدید" and retention reports.
    first_contact_at = models.DateTimeField()
    first_deal_won_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    # Which sales channel owns this account. Only فروش همکار (team) is in
    # scope today; the field keeps بانکی/B2B open without a migration later.
    channel = models.CharField(
        max_length=16, choices=SalesChannel.choices, default=SalesChannel.TEAM
    )

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "مشتری"
        indexes = [
            models.Index(fields=["owner", "first_deal_won_at"]),
            models.Index(fields=["province"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.name_fa


class CustomerFeedback(TimeStampedModel):
    """
    نظرسنجی رضایت — feeds the "تعداد مشتری ناراضی از کارشناسان" widget. Score is
    1..5; anything <= 2 counts as unhappy, and the rep it is about is stored
    explicitly so the complaint follows the person, not just the account.
    """

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="feedback"
    )
    employee = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="feedback",
    )
    score = models.PositiveSmallIntegerField(default=5)  # 1..5
    note = models.CharField(max_length=400, blank=True)
    at = models.DateTimeField()
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_feedback",
    )

    class Meta:
        ordering = ("-at",)
        verbose_name = "بازخورد مشتری"

    @property
    def is_unhappy(self) -> bool:
        return self.score <= 2

    def __str__(self) -> str:
        return f"{self.customer} · {self.score}/5"


# --------------------------------------------------------------------------
# Deal (معامله) — the heart of the CRM
# --------------------------------------------------------------------------
class Deal(TimeStampedModel):
    """
    یک معامله. Money fields are denormalised from DealItem by
    :meth:`recalculate` so reports never have to join through the lines —
    but the lines remain the source of truth and the drill-down target when
    someone asks "سود این معامله از کجا آمده؟".
    """

    class Status(models.TextChoices):
        OPEN = "open", "جاری"
        WON = "won", "موفق"
        LOST = "lost", "ناموفق"

    code = models.SlugField(unique=True)
    title = models.CharField(max_length=250)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="deals"
    )
    owner = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deals",
    )
    stage = models.ForeignKey(
        PipelineStage, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deals",
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    channel = models.CharField(
        max_length=16, choices=SalesChannel.choices, default=SalesChannel.TEAM
    )

    lead_source = models.ForeignKey(
        LeadSource, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deals",
    )
    lost_reason = models.ForeignKey(
        LostReason, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deals",
    )
    lost_note = models.CharField(max_length=400, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="deals")

    # ---- Money (all Rials, all derived from DealItem) ---------------------
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    cost_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    profit_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    # Costs that belong to the deal rather than to a product line. They are
    # what turns a healthy gross margin into a thin net one, so the profit
    # report can show *where* the margin went.
    discount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    shipping_cost_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    other_cost_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    # ---- Dates ------------------------------------------------------------
    opened_at = models.DateTimeField()
    expected_close_date = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Two periods, deliberately: "فرصت‌های جدید" is counted in the month the
    # deal was *created*, "فروش موفق" in the month it was *won*. Reporting on
    # a single period would silently mix the two, which is the single most
    # common CRM reporting mistake.
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_deals_opened",
    )
    close_period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_deals_closed",
    )

    class Meta:
        ordering = ("-opened_at",)
        verbose_name = "معامله"
        indexes = [
            models.Index(fields=["status", "closed_at"]),
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["opened_at"]),
            models.Index(fields=["close_period", "status"]),
        ]

    # ---- Derived ----------------------------------------------------------
    @property
    def margin_pct(self) -> float:
        if not self.amount_rial:
            return 0.0
        return float(self.profit_rial / self.amount_rial * 100)

    @property
    def age_days(self) -> int:
        end = self.closed_at or self.updated_at
        return max((end - self.opened_at).days, 0)

    @property
    def weighted_rial(self) -> Decimal:
        """Forecast value: amount x stage probability (open deals only)."""
        if self.status != self.Status.OPEN or not self.stage:
            return Decimal(0)
        return self.amount_rial * Decimal(self.stage.probability_pct) / Decimal(100)

    def recalculate(self, save: bool = True) -> None:
        """Roll the deal lines up into the denormalised money fields."""
        gross = Decimal(0)
        cost = Decimal(0)
        for item in self.items.all():
            gross += item.line_total
            cost += item.line_cost
        self.amount_rial = gross - self.discount_rial
        self.cost_rial = cost + self.shipping_cost_rial + self.other_cost_rial
        self.profit_rial = self.amount_rial - self.cost_rial
        if save:
            self.save(
                update_fields=["amount_rial", "cost_rial", "profit_rial", "updated_at"]
            )

    def __str__(self) -> str:
        return f"{self.title} · {self.customer}"


class DealItem(TimeStampedModel):
    """
    ردیف محصول در معامله. The margin of the whole company is ultimately the
    sum of these rows, so the profit report drills down to exactly here:
    "سود مهسا از این معامله = فروش رول حرارتی با حاشیه ۲۲٪".
    """

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="deal_items"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=1)
    unit_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    # Snapshot of the product cost at sale time — costs drift, history must not.
    unit_cost_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ("id",)
        verbose_name = "ردیف معامله"

    @property
    def line_total(self) -> Decimal:
        gross = self.quantity * self.unit_price_rial
        return (gross * (Decimal(100) - self.discount_pct) / Decimal(100)).quantize(
            Decimal(1)
        )

    @property
    def line_cost(self) -> Decimal:
        return (self.quantity * self.unit_cost_rial).quantize(Decimal(1))

    @property
    def line_profit(self) -> Decimal:
        return self.line_total - self.line_cost

    def __str__(self) -> str:
        return f"{self.product} × {self.quantity}"


class DealStageEvent(TimeStampedModel):
    """
    Every movement of a deal between pipeline stages. Two reports need it and
    neither can be reconstructed from the deal alone: the funnel (how many
    deals ever reached each stage, not just how many sit there now) and
    "چرخه فروش" (days from creation to win/loss).
    """

    deal = models.ForeignKey(
        Deal, on_delete=models.CASCADE, related_name="stage_events"
    )
    from_stage = models.ForeignKey(
        PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_stage = models.ForeignKey(
        PipelineStage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    at = models.DateTimeField()
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    # Days the deal spent in `from_stage` — precomputed so stage-duration
    # reporting is a plain aggregate.
    days_in_previous = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("deal", "at")

    def __str__(self) -> str:
        return f"{self.deal_id}: {self.from_stage} → {self.to_stage}"


# --------------------------------------------------------------------------
# Activity (فعالیت)
# --------------------------------------------------------------------------
class Activity(TimeStampedModel):
    """
    یک فعالیت روی مشتری/معامله. Mirrors Didar's activity kinds so the
    "فعالیت‌های انجام شده" report is directly comparable.

    `result` is what makes "نرخ تماس موفق" possible — a call is not a success
    because it happened, it is a success because it produced something.
    """

    class Kind(models.TextChoices):
        CALL_OUT = "call_out", "تماس پیگیری"
        CALL_IN = "call_in", "تماس ورودی"
        QUOTE = "quote", "اعلام قیمت"
        SAMPLE = "sample", "ارسال نمونه"
        MEETING = "meeting", "جلسه حضوری"
        MESSAGE = "message", "ارسال پیام"
        ORDER = "order", "ثبت سفارش"
        INVOICE = "invoice", "صدور فاکتور"
        PAYMENT = "payment", "پرداخت"

    class Result(models.TextChoices):
        SUCCESS = "success", "موفق"
        NO_ANSWER = "no_answer", "بی‌پاسخ"
        FOLLOW_UP = "follow_up", "نیاز به پیگیری"
        FAILED = "failed", "ناموفق"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="activities"
    )
    deal = models.ForeignKey(
        Deal, null=True, blank=True, on_delete=models.CASCADE, related_name="activities"
    )
    owner = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activities",
    )
    at = models.DateTimeField()
    duration_min = models.PositiveIntegerField(default=0)
    result = models.CharField(
        max_length=12, choices=Result.choices, default=Result.SUCCESS
    )
    note = models.CharField(max_length=500, blank=True)
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_activities",
    )

    class Meta:
        ordering = ("-at",)
        verbose_name = "فعالیت"
        indexes = [
            models.Index(fields=["owner", "at"]),
            models.Index(fields=["kind", "result"]),
            models.Index(fields=["period"]),
        ]

    @property
    def is_call(self) -> bool:
        return self.kind in {self.Kind.CALL_OUT, self.Kind.CALL_IN}

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.customer}"


class Task(TimeStampedModel):
    """
    کار / یادآوری آینده. Activities record what already happened; a Task is
    what a rep still owes a customer. Overdue tasks are the leading indicator
    the sales manager actually acts on.
    """

    title = models.CharField(max_length=250)
    customer = models.ForeignKey(
        Customer, null=True, blank=True,
        on_delete=models.CASCADE, related_name="tasks",
    )
    deal = models.ForeignKey(
        Deal, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    owner = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks",
    )
    kind = models.CharField(
        max_length=12, choices=Activity.Kind.choices, default=Activity.Kind.CALL_OUT
    )
    due_at = models.DateTimeField()
    done_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("due_at",)
        verbose_name = "کار"

    @property
    def is_done(self) -> bool:
        return self.done_at is not None

    def __str__(self) -> str:
        return self.title
