"""
بازرگانی داخلی — buying the factory's consumables, and remembering how.

The department's work is a short loop: the factory needs something, several
suppliers are asked what they would charge, one is chosen, the goods are
ordered. Today only the last step leaves a trace — a payment. What is lost is
the part that has value later: **who else quoted, at what price, and why we
did not buy from them.**

Three ideas shape the models:

* **A quote is worth keeping even when it loses.** `is_selected` lives on
  Quote, not on the request, so every supplier in an استعلام carries its own
  outcome and its own reason. A losing quote is the raw material of the next
  negotiation and of every supplier statistic on the dashboard.
* **Nothing stores a total.** An order's مبلغ کل is `quantity × unit_price`,
  computed on read, the way `finance.CreditLine.balance_rial` is. A stored
  total is a number that can drift away from its parts.
* **Reasons and categories are data.** «سایر» exists because the list is still
  settling; a new reason must be a row someone types, not a deploy. Same rule
  the finance section follows for its cash categories.

مصرف is derived from purchase orders rather than recorded separately: what the
factory consumed in a month is, for now, what بازرگانی bought for it. If real
consumption ever needs to be keyed on its own, it becomes a new model beside
these rather than a reshape of them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction

from apps.core.models import DimPeriod, TimeStampedModel

ZERO = Decimal(0)
#: Rial has no sub-unit. Quantity carries two decimal places (half a kilo is
#: real), so every product of the two has to be brought back to whole Rial or
#: the API starts emitting «۱۰٬۰۰۰٬۰۰۰٫۰۰ ریال».
RIAL = Decimal(1)


class MaterialUnit(models.TextChoices):
    """How a consumable is counted. Purchases and quotes are per one of these."""

    KILO = "kg", "کیلوگرم"
    TON = "ton", "تن"
    PIECE = "pcs", "عدد"
    ROLL = "roll", "رول"
    METER = "m", "متر"
    LITER = "lit", "لیتر"
    PACK = "pack", "بسته"
    CARTON = "ctn", "کارتن"


class MaterialCategory(TimeStampedModel):
    """A grouping of consumables — بسته‌بندی, مواد اولیه, قطعات یدکی and so on."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "name_fa")
        verbose_name = "material category (دسته کالا)"
        verbose_name_plural = "material categories"

    def __str__(self) -> str:
        return self.name_fa


class Material(TimeStampedModel):
    """
    A consumable the factory uses — نوار شیرینگ, چسب, کارتن, پالت.

    Deliberately *not* `crm.Product`. That model is a thing the company sells,
    carrying a list price and a unit cost; this is a thing the company buys.
    Folding them together would give one table two meanings and make «قیمت»
    ambiguous on every screen that showed it.
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=150)
    category = models.ForeignKey(
        MaterialCategory, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="materials",
    )
    unit = models.CharField(
        max_length=6, choices=MaterialUnit.choices, default=MaterialUnit.PIECE
    )
    #: Warn when stock falls under this. Zero means nobody set a floor yet.
    min_stock = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "material (کالای مصرفی)"

    @property
    def unit_label(self) -> str:
        return self.get_unit_display()

    def __str__(self) -> str:
        return self.name_fa


class Supplier(TimeStampedModel):
    """
    A company the department buys from, or has at least asked for a price.

    A supplier that never won anything is still worth a row: its quotes are
    what make «آیا این قیمت خوب است؟» answerable.

    One table for both halves of بازرگانی. A foreign mill and a local packaging
    shop are the same kind of thing — a company that quotes and delivers — and
    `origin` only says which side of the border it sits on. Two tables would
    duplicate any company that does both and give «تامین‌کننده» two meanings.
    """

    class Origin(models.TextChoices):
        DOMESTIC = "domestic", "داخلی"
        FOREIGN = "foreign", "خارجی"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=200)
    #: Foreign mills are known by their Latin name on every document.
    name_en = models.CharField(max_length=200, blank=True)
    origin = models.CharField(
        max_length=8, choices=Origin.choices, default=Origin.DOMESTIC
    )
    country = models.CharField(max_length=80, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    mobile = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=400, blank=True)
    #: نوع فعالیت — free text, because the department's own vocabulary for
    #: this is still forming and a choices list would fight it.
    activity = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "supplier (تامین‌کننده)"

    def __str__(self) -> str:
        return self.name_fa


class QuoteReason(TimeStampedModel):
    """
    Why a quote won or lost.

    Data rather than choices: «سایر» is seeded precisely because the list is
    not finished, and the department must be able to add «شرایط پرداخت بهتر»
    without waiting for a release.
    """

    class Kind(models.TextChoices):
        WIN = "win", "دلیل انتخاب"
        LOSE = "lose", "دلیل عدم انتخاب"
        SAMPLE = "sample", "دلیل رد نمونه"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("kind", "sort_order", "name_fa")
        verbose_name = "quote reason (دلیل انتخاب/رد)"

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.name_fa}"


class PaymentMethod(models.TextChoices):
    """*How* the money moves. Separate from *when* — see PaymentTerm."""

    CASH = "cash", "نقدی"
    CHEQUE = "cheque", "چک"
    TRANSFER = "transfer", "حواله بانکی"
    LC = "lc", "اعتبار اسنادی داخلی"
    OTHER = "other", "سایر"


class PaymentTerm(TimeStampedModel):
    """
    شرایط پرداخت — when the money leaves, as a schedule rather than a sentence.

    «۵۰٪ پیش‌پرداخت، مابقی ۶۰ روزه» typed into a note field is unusable: it
    cannot be compared, sorted or summed. Split into a percentage and a number
    of days, the comparison table can finally answer the question that decides
    most purchases — whether the cheaper quote is actually cheaper once its
    terms are counted. A supplier asking for everything up front at 2٪ less is
    lending the factory nothing; one offering ninety days at 3٪ more is.

    Data, not choices, for the reason the whole app uses: the department must
    be able to add «۴۰٪ پیش‌پرداخت، مابقی چک ۴ ماهه» without a deploy.
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    #: درصد پیش‌پرداخت — what has to be paid before anything arrives.
    advance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    #: مهلت تسویه مابقی, counted from delivery. Zero means on delivery.
    days = models.PositiveSmallIntegerField(default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ("sort_order", "name_fa")
        verbose_name = "payment term (شرایط پرداخت)"

    @property
    def deferred_pct(self) -> Decimal:
        """The share that is genuinely credit — the part worth comparing."""
        return max(ZERO, Decimal(100) - (self.advance_pct or ZERO))

    def __str__(self) -> str:
        return self.name_fa


class PurchaseRequest(TimeStampedModel):
    """
    A stated need — «۲۰ رول نوار شیرینگ», keyed by بازرگانی on the factory's
    behalf.

    One material per request. The comparison table only means something when
    every row priced the same thing, and the department's own example is
    single-item. A multi-line request becomes `PurchaseRequestLine` beside
    this model if it is ever needed — not a reshape of it.
    """

    class Status(models.TextChoices):
        OPEN = "open", "ثبت‌شده"
        QUOTING = "quoting", "در حال استعلام"
        AWARDED = "awarded", "تامین‌کننده انتخاب شد"
        ORDERED = "ordered", "سفارش ثبت شد"
        CANCELLED = "cancelled", "لغو شده"

    request_no = models.CharField(max_length=24, unique=True, blank=True)
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name="requests"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    #: Which part of the factory asked. Free text for now — the production
    #: department does not yet raise its own requests in the system.
    requester_unit = models.CharField(max_length=120, blank=True)
    requested_on = models.DateField()
    needed_by = models.DateField(null=True, blank=True)
    #: The month this request is reported under, so بازرگانی shares the
    #: platform's period tree instead of inventing its own calendar.
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.PROTECT, related_name="purchase_requests",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-requested_on", "-id")
        verbose_name = "purchase request (درخواست خرید)"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["requested_on"]),
        ]

    # -- derived ---------------------------------------------------------
    @property
    def selected_quote(self) -> "Quote | None":
        return self.quotes.filter(is_selected=True).first()

    @property
    def quote_count(self) -> int:
        return self.quotes.count()

    @property
    def best_price_rial(self) -> Decimal:
        """The cheapest quote received — not necessarily the chosen one."""
        low = self.quotes.aggregate(v=models.Min("unit_price_rial"))["v"]
        return low if low is not None else ZERO

    def save(self, *args, **kwargs):
        if not self.request_no:
            self.request_no = _next_number("PR", self.requested_on)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.request_no} · {self.material} × {self.quantity}"


class Quote(TimeStampedModel):
    """
    One supplier's answer to one request.

    The outcome lives here rather than on the request because the department
    wants a reason on *every* supplier, not only on the winner: «چرا از این
    نخریدیم» is the question the price file is kept for.
    """

    request = models.ForeignKey(
        PurchaseRequest, on_delete=models.CASCADE, related_name="quotes"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="quotes"
    )
    unit_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    quoted_on = models.DateField(null=True, blank=True)
    delivery_days = models.PositiveSmallIntegerField(
        default=0, help_text="زمان تحویل به روز"
    )
    validity_days = models.PositiveSmallIntegerField(
        default=0, help_text="اعتبار قیمت به روز"
    )
    # -- what the price is actually worth -------------------------------
    # Terms belong on the quote, not only on the order: they are part of the
    # offer and part of what is being compared. Recording them only once a
    # purchase is placed throws away the reason the losing quote lost.
    payment_term = models.ForeignKey(
        PaymentTerm, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="quotes",
    )
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, blank=True
    )
    payment_note = models.CharField(max_length=250, blank=True)

    is_selected = models.BooleanField(default=False)
    reason = models.ForeignKey(
        QuoteReason, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="quotes",
    )
    decision_note = models.CharField(max_length=300, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        # One price per supplier per استعلام. Re-quoting overwrites rather
        # than stacking two prices that would both look current.
        unique_together = ("request", "supplier")
        ordering = ("unit_price_rial", "id")
        verbose_name = "quote (استعلام قیمت)"
        indexes = [models.Index(fields=["is_selected"])]

    @property
    def total_rial(self) -> Decimal:
        """What this quote would cost for the whole requested quantity."""
        raw = (self.unit_price_rial or ZERO) * (self.request.quantity or ZERO)
        return raw.quantize(RIAL)

    def __str__(self) -> str:
        return f"{self.supplier} · {self.unit_price_rial}"


class PurchaseOrder(TimeStampedModel):
    """
    A purchase that was actually placed.

    Usually born from a winning quote, but it does not have to be: an urgent
    buy with no استعلام is still a purchase, and refusing to record it would
    push the department back into a spreadsheet for exactly the cases the
    reports most need.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تایید"
        BUYING = "buying", "در حال خرید"
        SHIPPED = "shipped", "ارسال شده"
        DELIVERED = "delivered", "تحویل شد"
        CANCELLED = "cancelled", "لغو شد"

    order_no = models.CharField(max_length=24, unique=True, blank=True)
    request = models.ForeignKey(
        PurchaseRequest, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="orders",
    )
    quote = models.ForeignKey(
        Quote, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="orders",
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="orders"
    )
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name="orders"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    ordered_on = models.DateField()
    delivered_on = models.DateField(null=True, blank=True)
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True,
        on_delete=models.PROTECT, related_name="purchase_orders",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    #: The terms actually agreed, which are not always the ones quoted — that
    #: gap is worth being able to see.
    payment_term = models.ForeignKey(
        PaymentTerm, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="orders",
    )
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, blank=True
    )
    payment_note = models.CharField(max_length=250, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-ordered_on", "-id")
        verbose_name = "purchase order (سفارش خرید)"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["ordered_on"]),
            models.Index(fields=["material", "ordered_on"]),
        ]

    @property
    def total_rial(self) -> Decimal:
        """
        مبلغ کل. Computed, never stored — a saved total is a figure that can
        quietly disagree with the quantity and price printed beside it.
        """
        raw = (self.quantity or ZERO) * (self.unit_price_rial or ZERO)
        return raw.quantize(RIAL)

    @property
    def counts_as_purchase(self) -> bool:
        """A cancelled order bought nothing, so reports must leave it out."""
        return self.status != self.Status.CANCELLED

    @property
    def delivery_days(self) -> int | None:
        """Actual lead time, once delivered — the check on a promise."""
        if not self.delivered_on or not self.ordered_on:
            return None
        return (self.delivered_on - self.ordered_on).days

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = _next_number("PO", self.ordered_on)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.order_no} · {self.material} از {self.supplier}"


class Sample(TimeStampedModel):
    """
    نمونه — what the supplier sent before anyone committed to buying it.

    A sample is deliberately **not** a field on Quote. The two do not line up:

    * A supplier is often asked for a sample before any استعلام exists — the
      department is still deciding whether the company is worth quoting.
    * One استعلام can involve two samples, when the first was rejected and the
      supplier sent a corrected one.
    * A sample approved for a material stays meaningful for the *next*
      purchase of that material, long after its استعلام is closed.

    The approval is a **dated decision by a named person**, not a boolean.
    When a delivered batch does not match what was tested, the question asked
    is «چه کسی این نمونه را تایید کرد و کِی؟», and a checkbox cannot answer it.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "درخواست شد"
        RECEIVED = "received", "دریافت شد"
        TESTING = "testing", "در حال آزمایش"
        APPROVED = "approved", "تایید شد"
        REJECTED = "rejected", "رد شد"

    #: Statuses where a verdict has been reached and the clock stops.
    DECIDED = {Status.APPROVED, Status.REJECTED}

    sample_no = models.CharField(max_length=24, unique=True, blank=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="samples"
    )
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name="samples"
    )
    #: Both optional, for the reasons in the class docstring.
    request = models.ForeignKey(
        PurchaseRequest, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="samples",
    )
    quote = models.ForeignKey(
        Quote, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="samples",
    )

    quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    #: What was asked for — «۴۸ گرم، عرض ۸۰», the yardstick the test judges by.
    spec = models.CharField(max_length=300, blank=True)

    requested_on = models.DateField()
    received_on = models.DateField(null=True, blank=True)
    decided_on = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED
    )
    #: Only meaningful on a rejection. Data, like every other reason here.
    reason = models.ForeignKey(
        QuoteReason, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="samples",
    )
    lab_note = models.TextField("نتیجه آزمایش", blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
        help_text="تاییدکننده / ردکننده",
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-requested_on", "-id")
        verbose_name = "sample (نمونه)"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["supplier", "material"]),
            models.Index(fields=["requested_on"]),
        ]

    # -- derived ---------------------------------------------------------
    @property
    def is_decided(self) -> bool:
        return self.status in self.DECIDED

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    def waiting_days(self, today: "date | None" = None) -> int | None:
        """
        Days this sample has been outstanding.

        Stops on the verdict, so a sample approved last year does not report a
        year of waiting and drown the ones actually holding a purchase up.
        """
        if self.is_decided:
            return None
        start = self.received_on or self.requested_on
        if not start:
            return None
        return max(0, ((today or date.today()) - start).days)

    def turnaround_days(self) -> int | None:
        """Arrival to verdict — how long the lab actually takes."""
        if not self.received_on or not self.decided_on:
            return None
        return (self.decided_on - self.received_on).days

    def save(self, *args, **kwargs):
        if not self.sample_no:
            self.sample_no = _next_number("SM", self.requested_on)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.sample_no} · {self.material} از {self.supplier}"


class DocumentCounter(models.Model):
    """
    The last number handed out in a document series, per Jalali year.

    A stored counter rather than «highest existing number + 1». That shortcut
    reuses numbers: delete the newest درخواست and the next one created takes
    the number just freed, so two different documents end up sharing
    PR-1405-0002 in whatever file or email they were quoted in. A document
    number exists precisely to stop that.

    Scoped to the year so the sequence restarts each سال instead of growing
    forever.
    """

    prefix = models.CharField(max_length=8)
    jalali_year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("prefix", "jalali_year")
        verbose_name = "document counter (شمارنده اسناد)"

    def __str__(self) -> str:
        return f"{self.prefix}-{self.jalali_year}: {self.last_value}"


# =======================================================================
# بازرگانی خارجی — importing, and the waiting that dominates it
# =======================================================================
#
# The domestic half is about price: who quoted what, and why we bought from
# one of them. The foreign half is about **time**. Reading the department's
# own workbook, almost every column that matters counts days: روز انتظار
# تخصیص, تعداد روز رسیده, روزهای مصرف‌شده از Free Days, مهلت خرید ارز. A file
# does not usually fail because someone paid too much; it fails because it sat
# in a queue nobody was watching until a deadline passed or a container
# started charging دموراژ.
#
# So the models below are shaped to make *elapsed time* a first-class,
# computed thing rather than a number someone retypes into a spreadsheet each
# Sunday. Nothing stores «۲۹۵ روز» — it is derived from the dates, which means
# it cannot be stale.


class Currency(models.TextChoices):
    """Currencies the company actually buys in."""

    USD = "USD", "دلار"
    EUR = "EUR", "یورو"
    AED = "AED", "درهم"
    CNY = "CNY", "یوان"


class RateKind(models.TextChoices):
    """
    The three prices a single currency has on any given day in Iran.

    They are genuinely different numbers used for different purposes — the
    customs rate values the goods for duty, the exchange-centre rate is what
    an allocation is actually settled at, the free rate is what the market
    says. A single «نرخ دلار» field would silently pick one and make every
    figure derived from it unauditable.
    """

    FREE = "free", "آزاد"
    CENTRE = "centre", "مرکز مبادله"
    CUSTOMS = "customs", "گمرکی"


class FxRate(TimeStampedModel):
    """One currency, one kind of rate, one day."""

    currency = models.CharField(max_length=3, choices=Currency.choices)
    kind = models.CharField(max_length=8, choices=RateKind.choices)
    on_date = models.DateField()
    rate_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    #: Where the figure came from. A rate typed by hand and one pulled from a
    #: feed are both legitimate, but only one of them is worth re-fetching.
    is_manual = models.BooleanField(default=True)
    source = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ("currency", "kind", "on_date")
        ordering = ("-on_date", "currency", "kind")
        verbose_name = "fx rate (نرخ ارز)"
        indexes = [models.Index(fields=["currency", "kind", "-on_date"])]

    @classmethod
    def latest_for(cls, currency: str, kind: str, on: "date | None" = None):
        """
        The rate in force on a date — the most recent one *at or before* it.

        Not «the rate with that exact date»: nobody records a rate on a Friday,
        and a report for Friday must not silently show zero.
        """
        qs = cls.objects.filter(currency=currency, kind=kind)
        if on:
            qs = qs.filter(on_date__lte=on)
        return qs.order_by("-on_date").first()

    def __str__(self) -> str:
        return f"{self.currency} {self.get_kind_display()} {self.on_date}: {self.rate_rial}"


class Bank(TimeStampedModel):
    """
    A بانک عامل — the bank a ثبت سفارش is filed through.

    Data, not choices: which banks the company works through changes with
    policy, and the allocation-queue report is broken down by this.
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    #: Drawn in the queue-share chart, so each bank keeps one colour.
    color = models.CharField(max_length=7, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ("sort_order", "name_fa")
        verbose_name = "bank (بانک عامل)"

    def __str__(self) -> str:
        return self.name_fa


class ForeignOrder(TimeStampedModel):
    """
    One import file: a proforma, its ثبت سفارش, and the currency behind it.

    The workbook keys this by شماره PI and hangs everything off it — the
    registration number, the bank, the allocation dates, and then several
    containers underneath. That is the grain here too: a file is the unit a
    person owns and chases, and a container is a thing that moves.

    The dates are the point. Each one marks a gate the file has to pass, and
    the gap between them is what the reports are made of.
    """

    class Status(models.TextChoices):
        """
        The stages the workbook keeps as five separate tables, in one list.
        Separate tables meant a file had to be cut and pasted between them to
        move forward, which is why several of them disagree with each other.
        """

        DRAFT = "draft", "پیش‌نویس"
        AWAITING_PERMIT = "permit", "منتظر مجوز صنعت و معدن"
        REGISTERED = "registered", "ثبت سفارش شده"
        QUEUED = "queued", "در صف تخصیص ارز"
        ALLOCATED = "allocated", "تخصیص ارز"
        REMITTED = "remitted", "حواله ارز"
        PURCHASED = "purchased", "خرید انجام شد"
        SHIPPING = "shipping", "در حال حمل"
        CUSTOMS = "customs", "گمرک"
        CLEARED = "cleared", "ترخیص شد"
        CLOSED = "closed", "بسته شده"
        CANCELLED = "cancelled", "لغو شده"

    class Readiness(models.TextChoices):
        """
        The workbook's own «R» / «Q» columns for بیمه and بازرسی — done, or
        still waited on. Kept because a file cannot be allocated without them
        and «چرا این پرونده جلو نمی‌رود» is often answered by one of these two.
        """

        PENDING = "Q", "در انتظار"
        DONE = "R", "انجام شده"

    #: Statuses where the file is finished and must drop out of every
    #: «چقدر معطل مانده» count. A closed file waiting forever is not a problem.
    SETTLED = {Status.CLEARED, Status.CLOSED, Status.CANCELLED}

    file_no = models.CharField(max_length=24, unique=True, blank=True)
    #: شماره پروفرما — the number the seller and the bank both quote.
    pi_no = models.CharField(max_length=60, db_index=True)
    #: The 8-digit ثبت سفارش permit number.
    registration_no = models.CharField(max_length=30, blank=True, db_index=True)
    #: شماره ثبت آماری, where the goods go through statistical registration.
    statistical_no = models.CharField(max_length=30, blank=True)

    supplier = models.ForeignKey(
        Supplier, null=True, blank=True,
        on_delete=models.PROTECT, related_name="foreign_orders",
    )
    country = models.CharField(max_length=80, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    material = models.ForeignKey(
        Material, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="foreign_orders",
    )
    #: What the file is for, in the department's own words — «کاغذ حرارتی ۵۵
    #: گرم Oriental». The material FK is optional because imports are not
    #: always for something already on the domestic materials list.
    goods_desc = models.CharField(max_length=200, blank=True)
    weight_ton = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.USD
    )
    amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        help_text="ارزش ارزی پرونده",
    )
    bank = models.ForeignKey(
        Bank, null=True, blank=True,
        on_delete=models.PROTECT, related_name="orders",
    )

    # -- the gates -------------------------------------------------------
    registered_on = models.DateField(
        null=True, blank=True, help_text="تاریخ ثبت سفارش"
    )
    valid_until = models.DateField(
        null=True, blank=True, help_text="تاریخ اعتبار ثبت سفارش"
    )
    queued_on = models.DateField(
        null=True, blank=True, help_text="تاریخ ورود به صف تخصیص ارز"
    )
    allocated_on = models.DateField(
        null=True, blank=True, help_text="تاریخ تایید تخصیص ارز"
    )
    purchase_deadline = models.DateField(
        null=True, blank=True, help_text="مهلت خرید ارز"
    )
    proforma_expires_on = models.DateField(
        null=True, blank=True, help_text="تاریخ انقضای پروفرما"
    )
    #: «حداکثر انتظار» in the workbook, where it is 100 days. The real wait is
    #: judged against this rather than against nothing, and the workbook's
    #: «زمان باقی مانده» column is this minus the days already waited.
    expected_queue_days = models.PositiveSmallIntegerField(default=100)

    # -- the two gates that quietly hold a file back --------------------
    insurance = models.CharField(
        "بیمه", max_length=1, choices=Readiness.choices, default=Readiness.PENDING
    )
    inspection = models.CharField(
        "بازرسی", max_length=1, choices=Readiness.choices, default=Readiness.PENDING
    )

    # -- what happened after the goods landed ---------------------------
    arrived_on = models.DateField(
        null=True, blank=True, help_text="رسیدن بار به بندر"
    )
    factory_entry_on = models.DateField(
        null=True, blank=True, help_text="ورود کالا به کارخانه"
    )
    production_cert_on = models.DateField(
        null=True, blank=True, help_text="تاریخ گواهی تولید"
    )
    customs_declared_on = models.DateField(
        null=True, blank=True, help_text="تاریخ اظهار گمرکی"
    )
    #: Recorded on the file as well as on its containers, because the
    #: workbook's clearance table is keyed by PI and several older rows have
    #: no بارنامه at all — without this their clearance date is simply lost.
    cleared_on = models.DateField(
        null=True, blank=True, help_text="تاریخ ترخیص"
    )
    customs_value_rial = models.DecimalField(
        max_digits=22, decimal_places=0, default=0,
        help_text="مبلغ اظهار گمرکی",
    )
    #: Free text, because the workbook's «آخرین وضعیت» is a sentence, not a
    #: code — «رفع تعهد بانکی انجام شده», «۹۰٪ ترخیص شده».
    last_status_note = models.CharField(max_length=250, blank=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
        help_text="مسئول پرونده",
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-registered_on", "-id")
        verbose_name = "foreign order (پرونده واردات)"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["registered_on"]),
            models.Index(fields=["bank", "status"]),
        ]

    # -- derived: everything the reports count ---------------------------
    @property
    def is_settled(self) -> bool:
        return self.status in self.SETTLED

    def days_in_queue(self, today: "date | None" = None) -> int | None:
        """
        How long this file has been waiting for its currency allocation.

        Stops counting on the day the allocation came through — otherwise a
        file allocated last year would report a two-year wait and drown the
        ones actually stuck.
        """
        if not self.queued_on:
            return None
        end = self.allocated_on or (today or date.today())
        return max(0, (end - self.queued_on).days)

    @property
    def is_waiting_allocation(self) -> bool:
        return bool(self.queued_on) and not self.allocated_on and not self.is_settled

    @property
    def last_action_on(self) -> "date | None":
        """
        The most recent thing anyone recorded against this file.

        Falls back through the gates when no event has been logged, so a file
        imported from the spreadsheet is not instantly reported as stalled for
        the whole of its life.
        """
        latest = self.events.order_by("-at", "-id").values_list("at", flat=True).first()
        if latest:
            return latest
        for candidate in (self.allocated_on, self.queued_on, self.registered_on):
            if candidate:
                return candidate
        return None

    def idle_days(self, today: "date | None" = None) -> int | None:
        """Days since anything happened. This is what «راکد» means."""
        last = self.last_action_on
        if not last or self.is_settled:
            return None
        return max(0, ((today or date.today()) - last).days)

    def days_until(self, deadline: "date | None", today: "date | None" = None):
        """Days left before a deadline; negative once it has passed."""
        if not deadline or self.is_settled:
            return None
        return (deadline - (today or date.today())).days

    def amount_rial(self, kind: str = RateKind.CENTRE, on: "date | None" = None):
        """
        The file's value in Rial at a stated rate.

        The rate kind is an argument, never a default buried in a template:
        the same file is worth materially different amounts at the customs and
        the free rate, and a figure that does not say which is not an answer.
        """
        rate = FxRate.latest_for(self.currency, kind, on or self.registered_on)
        if not rate:
            return None
        return (self.amount or ZERO) * rate.rate_rial

    def save(self, *args, **kwargs):
        if not self.file_no:
            self.file_no = _next_number("FO", self.registered_on or date.today())
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.file_no} · {self.pi_no}"


class OrderEvent(TimeStampedModel):
    """
    Something that happened to a file.

    This is what makes «سفارش راکد» honest. Without a timeline, "stalled" can
    only mean "status has not changed", which is wrong in both directions: a
    file can sit at «در صف تخصیص» for months while someone chases it weekly,
    and another can look busy because its status was corrected once.

    `blocked_reason` is the field the department asked for by name — علت توقف.
    """

    order = models.ForeignKey(
        ForeignOrder, on_delete=models.CASCADE, related_name="events"
    )
    at = models.DateField()
    title = models.CharField(max_length=200)
    #: Set when this event is the department recording *why* nothing is
    #: moving, rather than recording progress.
    blocked_reason = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-at", "-id")
        verbose_name = "order event (اقدام پرونده)"
        indexes = [models.Index(fields=["order", "-at"])]

    def __str__(self) -> str:
        return f"{self.at} · {self.title}"


class Shipment(TimeStampedModel):
    """
    One container on its way, or sitting in a port costing money.

    Separate from the file because the workbook proves they are separate: one
    PI regularly ships as four containers, each with its own بارنامه, ETA and
    تاریخ ترخیص, and one of them can be stuck while the others are already at
    the factory. Folding them into the file would lose exactly the container
    that is bleeding دموراژ.
    """

    class Status(models.TextChoices):
        READY = "ready", "آماده بارگیری"
        DEPARTED = "departed", "حرکت کرده"
        AT_SEA = "at_sea", "روی دریا"
        AT_PORT = "at_port", "بندر مقصد"
        CUSTOMS = "customs", "گمرک"
        CLEARED = "cleared", "ترخیص شد"
        DELIVERED = "delivered", "تحویل کارخانه"
        CANCELLED = "cancelled", "لغو شده"

    #: Before this, the container is not yet the company's problem to store.
    AT_DESTINATION = {Status.AT_PORT, Status.CUSTOMS}
    FINISHED = {Status.CLEARED, Status.DELIVERED, Status.CANCELLED}

    order = models.ForeignKey(
        ForeignOrder, on_delete=models.CASCADE, related_name="shipments"
    )
    #: «-1», «-2» — the suffix the department already writes after the PI.
    lot_no = models.CharField(max_length=20, blank=True)
    bl_no = models.CharField("شماره بارنامه", max_length=60, blank=True, db_index=True)
    container_no = models.CharField(max_length=40, blank=True, db_index=True)
    carrier = models.CharField("شرکت حمل", max_length=120, blank=True)
    origin_port = models.CharField(max_length=120, blank=True)
    destination_port = models.CharField(max_length=120, blank=True)

    goods_desc = models.CharField(max_length=200, blank=True)
    weight_ton = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    value_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        help_text="ارزش این محموله به ارز پرونده",
    )
    # -- what is still owed, and what the delay is costing ---------------
    # The workbook tracks these per بارنامه: a shipment is often paid in
    # instalments, and once a due date passes the seller charges interest that
    # grows the same way دموراژ does. Kept here rather than netted into
    # `value_amount`, because «چقدر ارزش داشت» and «چقدر هنوز بدهکاریم» are
    # different questions and only one of them changes over time.
    paid_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    due_on = models.DateField(
        null=True, blank=True, help_text="سررسید پرداخت به فروشنده"
    )
    interest_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        help_text="سود دیرکرد اعلامی فروشنده",
    )

    etd = models.DateField(null=True, blank=True)
    eta = models.DateField(null=True, blank=True)
    arrived_on = models.DateField(
        null=True, blank=True, help_text="رسیدن بار به بندر"
    )
    released_on = models.DateField(
        null=True, blank=True, help_text="تاریخ آزادسازی بار"
    )
    declared_on = models.DateField(
        null=True, blank=True, help_text="تاریخ اظهار گمرکی"
    )
    cleared_on = models.DateField(
        null=True, blank=True, help_text="تاریخ ترخیص"
    )

    # -- the money that grows while nobody looks -------------------------
    free_days = models.PositiveSmallIntegerField(
        default=0, help_text="روزهای رایگان نگهداری کانتینر"
    )
    demurrage_daily_rial = models.DecimalField(
        max_digits=18, decimal_places=0, default=0,
        help_text="دموراژ روزانه پس از پایان Free Days",
    )
    storage_daily_rial = models.DecimalField(
        max_digits=18, decimal_places=0, default=0,
        help_text="انبارداری روزانه",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.READY
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("-eta", "-id")
        verbose_name = "shipment (محموله)"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["eta"]),
            models.Index(fields=["arrived_on"]),
        ]

    # -- derived ---------------------------------------------------------
    @property
    def is_finished(self) -> bool:
        return self.status in self.FINISHED

    def _clock_stops_on(self, today: "date | None" = None) -> "date | None":
        """
        The day charges stop accruing: when the container was cleared, else
        today. Nothing accrues before it arrived.
        """
        if not self.arrived_on:
            return None
        return self.cleared_on or self.released_on or (today or date.today())

    def days_at_port(self, today: "date | None" = None) -> int | None:
        """How long the container has been sitting at the destination."""
        end = self._clock_stops_on(today)
        if end is None:
            return None
        return max(0, (end - self.arrived_on).days)

    def free_days_used(self, today: "date | None" = None) -> int | None:
        days = self.days_at_port(today)
        if days is None:
            return None
        return min(days, self.free_days)

    def free_days_left(self, today: "date | None" = None) -> int | None:
        days = self.days_at_port(today)
        if days is None:
            return None
        return max(0, self.free_days - days)

    @property
    def has_tariff(self) -> bool:
        """
        Whether anyone has told us what this container costs to sit.

        A row with no Free Days *and* no daily rate is not a container with
        zero free days — it is one nobody has entered terms for. Treating the
        blank as zero would report every such box as running up demurrage
        from the day it landed, and then bill it at nothing, which is wrong
        in both directions at once.
        """
        return bool(self.free_days or self.demurrage_daily_rial or self.storage_daily_rial)

    def demurrage_days(self, today: "date | None" = None) -> int:
        """Days charged at the demurrage rate — only those past the free ones."""
        days = self.days_at_port(today)
        if days is None or not self.has_tariff:
            return 0
        return max(0, days - self.free_days)

    def demurrage_rial(self, today: "date | None" = None) -> Decimal:
        return self.demurrage_days(today) * (self.demurrage_daily_rial or ZERO)

    def storage_rial(self, today: "date | None" = None) -> Decimal:
        """
        Storage is charged from arrival, not from the end of the free days —
        free days are the shipping line's container allowance, which is a
        different thing from the port's warehouse charging rent.
        """
        days = self.days_at_port(today)
        if days is None:
            return ZERO
        return days * (self.storage_daily_rial or ZERO)

    def accruing_rial(self, today: "date | None" = None) -> Decimal:
        return self.demurrage_rial(today) + self.storage_rial(today)

    @property
    def is_accruing(self) -> bool:
        """Still at the destination and still costing money every day."""
        return (
            self.status in self.AT_DESTINATION
            and bool(self.arrived_on)
            and not self.cleared_on
        )

    @property
    def outstanding_amount(self) -> Decimal:
        """What is still owed the seller on this shipment."""
        return max(ZERO, (self.value_amount or ZERO) - (self.paid_amount or ZERO))

    def overdue_days(self, today: "date | None" = None) -> int | None:
        """
        Days past the payment due date, while money is still owed.

        None once it is paid: an instalment settled late is history, and
        leaving it counting would make the overdue total grow forever.
        """
        if not self.due_on or self.outstanding_amount <= ZERO:
            return None
        return max(0, ((today or date.today()) - self.due_on).days)

    @property
    def price_per_ton(self) -> Decimal | None:
        """What this container cost per tonne — the comparable unit."""
        if not self.weight_ton:
            return None
        return (self.value_amount or ZERO) / self.weight_ton

    def transit_days(self) -> int | None:
        if not self.etd or not self.arrived_on:
            return None
        return (self.arrived_on - self.etd).days

    def clearance_days(self) -> int | None:
        """Arrival to clearance — the number the customs report is judged on."""
        if not self.arrived_on or not self.cleared_on:
            return None
        return (self.cleared_on - self.arrived_on).days

    def __str__(self) -> str:
        label = self.container_no or self.bl_no or self.lot_no or str(self.id)
        return f"{self.order.pi_no} · {label}"


class ShipmentCost(TimeStampedModel):
    """
    One line of what a container ended up costing.

    Estimates and actuals live in the same table with a flag, because the
    department's question before clearance — «چقدر باید کنار بگذاریم؟» — and
    after it — «چقدر شد؟» — are the same question at two points in time, and
    keeping them apart guarantees the estimate is never compared to reality.
    """

    class Kind(models.TextChoices):
        GOODS = "goods", "بهای کالا"
        FREIGHT = "freight", "کرایه حمل"
        INSURANCE = "insurance", "بیمه"
        DUTY = "duty", "حقوق و عوارض گمرکی"
        CLEARANCE = "clearance", "ترخیصیه و سپرده"
        TRANSIT = "transit", "حمل داخلی و ترانزیت"
        DEMURRAGE = "demurrage", "دموراژ / حق توقف"
        STORAGE = "storage", "انبارداری"
        OTHER = "other", "سایر"

    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name="costs"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    #: Set when the cost was agreed in foreign currency (freight usually is).
    amount_fx = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(
        max_length=3, choices=Currency.choices, blank=True
    )
    is_estimate = models.BooleanField(default=True)
    due_on = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ("shipment", "kind")
        verbose_name = "shipment cost (هزینه محموله)"
        indexes = [models.Index(fields=["shipment", "kind"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.amount_rial}"


# -- helpers -------------------------------------------------------------
def _next_number(prefix: str, on_date) -> str:
    """Human-readable document number: «PO-1405-0007»."""
    from apps.core import jalali

    year = jalali.from_gregorian(on_date)[0] if on_date else 0
    with transaction.atomic():
        counter, _ = DocumentCounter.objects.select_for_update().get_or_create(
            prefix=prefix, jalali_year=year
        )
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
    return f"{prefix}-{year}-{counter.last_value:04d}"
