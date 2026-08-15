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
class Dataset(models.TextChoices):
    """
    Which body of data a row belongs to.

    The company's real customer file lives beside a fabricated one. The demo
    set is a showroom — it can be shown to an outsider, projected in a
    meeting, or used to learn the screens, without a single real customer's
    name or mobile number leaving the room. It is meant to be temporary, and
    deleting it later is `manage.py seed_crm --clear`, not a migration.

    Every row carries its own tag rather than the two sets living in separate
    tables or databases: a customer and a deal point at DimEmployee, DimPeriod
    and DimProvince, which belong to other apps, and a cross-database foreign
    key is not a thing Django can follow.
    """

    REAL = "real", "داده واقعی"
    DEMO = "demo", "داده نمایشی"


class DatasetModel(TimeStampedModel):
    """Mixin for everything that exists once per dataset."""

    dataset = models.CharField(
        max_length=4, choices=Dataset.choices, default=Dataset.REAL,
        db_index=True,
    )

    class Meta:
        abstract = True


class CustomerGroup(DatasetModel):
    """گروه مشتری — the market segment a customer belongs to."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "گروه مشتری"

    def __str__(self) -> str:
        return self.name_fa


class Tag(DatasetModel):
    """برچسب — free-form label attachable to customers and deals."""

    name_fa = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name_fa",)

    def __str__(self) -> str:
        return self.name_fa


class LeadSource(DatasetModel):
    """منبع سرنخ — how the customer first found us. Drives the
    "بهترین منابع سرنخ" report: which channels actually convert."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "منبع سرنخ"

    def __str__(self) -> str:
        return self.name_fa


class LostReason(DatasetModel):
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


class ProductCategory(DatasetModel):
    """دسته محصول — e.g. کاغذ حرارتی، کاغذ کربن‌لس، رول بانکی."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "دسته محصول"

    def __str__(self) -> str:
        return self.name_fa


class Product(DatasetModel):
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


class PipelineStage(DatasetModel):
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
class Customer(DatasetModel):
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
    # شناسه ملی (حقوقی) / کد ملی (حقیقی). Didar has neither — every one of its
    # 2,717 rows is blank — so this is filled only from the accounting export.
    national_id = models.CharField(max_length=20, blank=True)
    # کد اقتصادی is a *different* number from شناسه ملی and the two used to
    # share this one field. They disagree often enough in the آرپا export
    # (517 economic codes against 551 national ids) that merging them loses
    # the only two identifiers a legal entity actually has.
    economic_code = models.CharField(max_length=20, blank=True)
    registration_no = models.CharField(max_length=20, blank=True)  # شماره ثبت
    postal_code = models.CharField(max_length=10, blank=True)
    note = models.TextField(blank=True)

    # ---- Commercial terms, straight from accounting ------------------------
    # «نقدی» / «30روزه» / «45 روزه» … kept as text rather than a choice list:
    # the accounting system mints new terms without asking, and an import that
    # fails on an unrecognised one is worse than one that carries it through.
    payment_terms = models.CharField(max_length=40, blank=True)
    is_good_payer = models.BooleanField(default=False)  # خوش حساب
    # غیر فعال in آرپا. Distinct from `status`: a customer can be راکد (no
    # recent activity, still worth calling) without the account being closed.
    is_active = models.BooleanField(default=True)
    # تاریخ اعتبار گواهی ارزش افزوده — an invoice issued after this date
    # cannot legally carry VAT, so it belongs beside the customer, not buried
    # in the accounting system.
    vat_cert_expires_at = models.DateField(null=True, blank=True)

    # Sales to a sister company are real invoices and belong in the ledger,
    # but they are not the sales team's work and must not land in a target or
    # a conversion rate. «آرال رول آریا - فی ما بین» alone is 250bn Rial —
    # large enough to distort every figure it is counted into.
    is_intercompany = models.BooleanField(default=False)

    # Set when this row was folded into another during a source merge. Kept
    # rather than deleted so the deals and activities already attached to it
    # survive, and so an incorrect merge can be undone.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="merged_from",
    )

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


class DemoProvinceTarget(TimeStampedModel):
    """
    Province targets **for the demo only**.

    The provinces report compares CRM sales against the CEO's plan, which
    lives in `sales.SalesTarget`. Real targets are read from there and must
    never be written by the demo — an earlier version of the seed wrote its
    generated numbers straight into the platform's province facts, which is
    exactly the kind of contamination that makes a demo dangerous to install
    next to production data.

    So the seed fills this table instead, and the report falls back to it only
    where no real target exists. Deleting every row here removes every trace
    of the demo's targets.
    """

    period = models.ForeignKey(
        DimPeriod, on_delete=models.CASCADE, related_name="crm_demo_targets"
    )
    province = models.ForeignKey(
        DimProvince, on_delete=models.CASCADE, related_name="crm_demo_targets"
    )
    channel = models.CharField(
        max_length=16, choices=SalesChannel.choices, default=SalesChannel.TEAM
    )
    target_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    class Meta:
        unique_together = ("period", "province", "channel")
        verbose_name = "تارگت استانی (دمو)"

    def __str__(self) -> str:
        return f"{self.province} · {self.period} (دمو)"


class CustomerFeedback(DatasetModel):
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
class Deal(DatasetModel):
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


class DealItem(DatasetModel):
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


class DealStageEvent(DatasetModel):
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
class Activity(DatasetModel):
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


class Task(DatasetModel):
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


# --------------------------------------------------------------------------
# Identity across source systems
#
# The customer file arrives from two places that have never agreed on a key:
# دیدار (the old CRM) and آرپا (accounting). Matching them is not a detail of
# the import — it is the hard part, and it cannot be done by `code` alone,
# because `Customer.code` encodes *where a row came from* («didar-co-…») and
# so can only ever name one source.
#
# Measured on the real exports before designing this:
#
#   * دیدار carries **no** شناسه ملی at all — 0 of 2,717 rows. The one key
#     that would have been unambiguous does not exist.
#   * Matching on phone produces false pairs. «پلی کلینیک سوم خرداد خرمشهر»
#     and «شبکه بهداشت و درمان خرمشهر» share a switchboard; so do a hospital
#     and a person. 55 of 138 active buyers match this way and they cannot be
#     trusted unreviewed.
#   * Fuzzy name matching pairs «بانک کشاورزی ایلام» with «بانک کشاورزی
#     گیلان» at 86% similarity — two branches in different provinces.
#
# So: an exact normalised name is the only signal strong enough to merge on
# its own. Everything weaker becomes a CustomerMatchCandidate for a human.
# --------------------------------------------------------------------------
class ExternalSource(models.TextChoices):
    DIDAR = "didar", "دیدار"
    ARPA = "arpa", "آرپا (حسابداری)"
    # Not a source system: a duplicate raised from inside the CRM, by someone
    # looking at two rows on the customer list that are plainly one company.
    # It rides in the same queue because it is the same question and deserves
    # the same care — the دیدار import alone left 35 pairs sharing a name.
    CRM = "crm", "داخل CRM"


class CustomerExternalRef(DatasetModel):
    """
    One customer's id in one source system.

    A customer may hold several — its دیدار id and its آرپا کد طرف حساب — which
    is what makes both imports re-runnable against the same row instead of
    each minting its own.
    """

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="external_refs"
    )
    source = models.CharField(max_length=8, choices=ExternalSource.choices)
    external_id = models.CharField(max_length=64)
    # What the source calls this customer. Kept so the review screen can show
    # both spellings side by side, and so a later export that renames a party
    # is visible as a change rather than silently overwriting.
    external_name = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "شناسه در سامانه مبدأ"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"], name="crm_extref_unique_source_id"
            ),
        ]
        indexes = [models.Index(fields=["customer", "source"])]

    def __str__(self) -> str:
        return f"{self.get_source_display()}:{self.external_id} → {self.customer}"


class CustomerMatchCandidate(TimeStampedModel):
    """
    A suspected — not confirmed — pairing between a source party and a customer.

    The row deliberately holds the *source* side as raw text rather than as a
    second Customer. Creating a customer in order to merge it away would leave
    a real duplicate in the table for as long as the queue is unreviewed, and
    would make «رد» mean deleting a row someone might already have touched.

    `payload` keeps the whole source record so the review screen can show
    address, city and group without re-reading the workbook.
    """

    class Method(models.TextChoices):
        NATIONAL_ID = "nid", "شناسه/کد ملی"
        # Same شناسه ملی, different place. Every branch of a bank carries the
        # head office's number, so the id proves one legal entity — not one
        # customer. Whether two branches are one account is a judgement about
        # how the company sells, not something an id can answer.
        BRANCH = "branch", "شناسه ملی یکسان، شعبه‌ی متفاوت"
        PHONE = "phone", "تلفن"
        NAME = "name", "نام یکسان"
        # The source name matches a customer exactly — and matches a second
        # one too. The duplicate is inside the CRM, and it has to be settled
        # before this party can be filed against either half.
        AMBIGUOUS = "ambig", "نام یکسان با چند مشتری"
        FUZZY = "fuzzy", "نام مشابه"
        MANUAL = "manual", "دستی"

    class State(models.TextChoices):
        PENDING = "pending", "در انتظار بازبینی"
        ACCEPTED = "accepted", "تایید شد — همان مشتری"
        REJECTED = "rejected", "رد شد — مشتری دیگری است"

    source = models.CharField(max_length=8, choices=ExternalSource.choices)
    external_id = models.CharField(max_length=64)
    external_name = models.CharField(max_length=200)
    external_phone = models.CharField(max_length=40, blank=True)
    external_city = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="match_candidates"
    )
    # Set only when both sides are CRM rows. The source side of this model is
    # normally raw text — a party read out of a workbook — but a duplicate
    # raised from the customer list has a real row behind it, and pointing at
    # it beats copying its fields into `payload` where they would go stale
    # while the pair sits in the queue.
    duplicate = models.ForeignKey(
        Customer, null=True, blank=True,
        on_delete=models.CASCADE, related_name="duplicate_candidates",
    )
    method = models.CharField(max_length=8, choices=Method.choices)
    score = models.DecimalField(max_digits=5, decimal_places=4, default=0)

    state = models.CharField(
        max_length=8, choices=State.choices, default=State.PENDING, db_index=True
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_match_decisions",
    )

    class Meta:
        ordering = ("state", "-score")
        verbose_name = "پیشنهاد تطبیق مشتری"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id", "customer"],
                name="crm_matchcand_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.external_name} ≟ {self.customer}"


# --------------------------------------------------------------------------
# Invoices — what was actually billed
#
# Deliberately *not* folded into Deal. A معامله is a pipeline opportunity and
# its `amount_rial` comes straight from دیدار, which is also what دیدار's own
# reports are built on; the import checks itself against those totals. Writing
# invoice money onto the same field would break that check and leave no way to
# tell which of the two systems a given figure came from.
#
# One invoice → one customer → optionally one deal. The link to Deal is what
# eventually answers «چقدر از کاریز واقعاً فاکتور شد».
# --------------------------------------------------------------------------
class SalesInvoice(DatasetModel):
    """
    فاکتور فروش یا مرجوعی، از نرم‌افزار حسابداری.

    Money is stored **excluding VAT**: `amount_rial` is آرپا's «مبلغ فروش»,
    which is net of discount and carries tax separately in `vat_rial`. That
    is the figure comparable with a deal's ارزش, and the one the sales team
    is measured on.

    Returns keep the negative sign آرپا gives them, so a plain SUM over a
    period is already net of returns and nothing has to remember to subtract.
    """

    class Kind(models.TextChoices):
        SALE = "sale", "فاکتور فروش"
        RETURN = "return", "مرجوع از فروش"

    code = models.SlugField(unique=True)
    number = models.CharField(max_length=30)  # شماره برگه
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.SALE)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="invoices"
    )
    deal = models.ForeignKey(
        Deal, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="invoices",
    )

    issued_at = models.DateField()
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="crm_invoices",
    )

    # ---- Money (Rial, excluding VAT unless the name says otherwise) --------
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    discount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    vat_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    # مبلغ برگه — what the customer owes, VAT included. Stored because it is
    # what a receivable is actually collected against.
    total_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    settled_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    unsettled_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    # ---- Terms -------------------------------------------------------------
    payment_terms = models.CharField(max_length=40, blank=True)
    due_date = models.DateField(null=True, blank=True)     # موعد تسویه
    grace_date = models.DateField(null=True, blank=True)   # مهلت تسویه
    shipping_method = models.CharField(max_length=60, blank=True)

    # ---- People ------------------------------------------------------------
    # «بازاریاب» — the salesperson, filled on every invoice. Not «ایجاد کننده»,
    # which is whoever typed it, and not «مسوول فروش», which despite its name
    # holds the channel («گروه فروش بانکی») rather than a person.
    owner = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="invoices",
    )
    created_by_name = models.CharField(max_length=60, blank=True)
    channel = models.CharField(
        max_length=16, choices=SalesChannel.choices, blank=True
    )
    branch = models.CharField(max_length=60, blank=True)   # شعبه
    tax_ref = models.CharField(max_length=40, blank=True)  # شناسه سامانه مودیان
    note = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ("-issued_at", "-number")
        verbose_name = "فاکتور فروش"
        indexes = [
            models.Index(fields=["customer", "issued_at"]),
            models.Index(fields=["period", "kind"]),
            models.Index(fields=["owner", "issued_at"]),
        ]

    @property
    def is_settled(self) -> bool:
        return self.unsettled_rial <= 0

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.number} · {self.customer}"


class SalesInvoiceItem(DatasetModel):
    """
    ردیف فاکتور.

    `product` is nullable and the source's own کد/نام کالا are kept beside it.
    The accounting catalogue and دیدار's catalogue are separate lists that
    only partly line up, and a line whose product cannot be mapped is still a
    real sale — dropping it, or refusing the whole invoice, would quietly
    understate revenue. The raw columns also let the mapping improve later
    without re-importing.
    """

    invoice = models.ForeignKey(
        SalesInvoice, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        Product, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="invoice_items",
    )
    product_code = models.CharField(max_length=40, blank=True)
    product_name = models.CharField(max_length=200, blank=True)

    quantity = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    # «معادل» — the same quantity in the catalogue's base unit. Kept because
    # tonnage reporting cannot be derived from `quantity`, whose unit differs
    # per product line.
    equivalent = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    sub_unit = models.CharField(max_length=20, blank=True)

    unit_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    accounting_group = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ("id",)
        verbose_name = "ردیف فاکتور"
        indexes = [models.Index(fields=["invoice"])]

    def __str__(self) -> str:
        return f"{self.product_name or self.product_code} × {self.quantity}"
