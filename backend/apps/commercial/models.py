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
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=200)
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

    kind = models.CharField(max_length=4, choices=Kind.choices)
    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("kind", "sort_order", "name_fa")
        verbose_name = "quote reason (دلیل انتخاب/رد)"

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.name_fa}"


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
