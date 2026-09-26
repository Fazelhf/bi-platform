"""
فروش ۲ — the sales documents themselves, issued here rather than imported.

Everything else in the platform *reads* sales: `sales.FactSalesMonthly` is a
figure a manager types once a month, and `crm.SalesInvoice` is a copy of what
آرپا already issued. This module is where a sale is *made*: a پیش‌فاکتور is
written and sent, becomes a فاکتور, leaves the warehouse on a حواله, and is
paid off by a دریافت. Built beside the existing sales section, for admins
only, to be merged into it once it has earned that.

The rules that shape the models:

* **The customer and product files are CRM's.** A second customer list is
  how two records of one company start to disagree, so documents point at
  `crm.Customer` and `crm.Product`. What CRM lacks — a credit limit, a sale
  price, a cost — lives here, one-to-one beside the row it describes, so the
  merge later is a column move rather than a de-duplication.

* **An issued document does not change.** A فاکتور is a legal record: once it
  has a number it is printed, sent and booked, and a figure on it that moved
  afterwards would disagree with the paper in the customer's hands. So a
  document is freely editable as a draft and frozen at issue — the customer's
  name and codes, each line's price and cost are copied onto it, and its
  totals are stored. (This is the opposite of بازرگانی, which computes totals
  on read; there nothing is ever issued to anyone.) Mistakes are undone by
  ابطال or a مرجوعی, never by editing.

* **Numbers are handed out at issue, never to drafts.** Invoice numbers must
  run without gaps; a draft that is abandoned must not burn one.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import DimPeriod, TimeStampedModel

ZERO = Decimal(0)
#: مالیات بر ارزش افزوده. Each document keeps its own copy of the rate, so the
#: day the rate changes last year's invoices do not change with it.
DEFAULT_VAT_PCT = Decimal(10)
#: How long a received cheque may stay unregistered in سامانه صیاد before it
#: stops counting as payment — the company's rule, not the law's.
SAYAD_GRACE = timedelta(hours=48)


class Sales2Setting(TimeStampedModel):
    """
    One row: the company's letterhead and the module's policies.

    The header is printed on every پیش‌فاکتور and فاکتور, so it is data the
    admin edits rather than text baked into a template.
    """

    class CreditPolicy(models.TextChoices):
        BLOCK = "block", "جلوگیری از صدور"
        WARN = "warn", "فقط هشدار"
        OFF = "off", "بدون کنترل"

    company_name = models.CharField(max_length=200, blank=True)
    economic_code = models.CharField(max_length=20, blank=True)
    national_id = models.CharField(max_length=20, blank=True)
    registration_no = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=400, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    vat_pct = models.DecimalField(max_digits=5, decimal_places=2, default=DEFAULT_VAT_PCT)
    #: How long a پیش‌فاکتور holds its prices unless the document says otherwise.
    proforma_valid_days = models.PositiveSmallIntegerField(default=7)
    credit_policy = models.CharField(
        max_length=6, choices=CreditPolicy.choices, default=CreditPolicy.BLOCK
    )
    #: Printed under every document: delivery terms, bank account, etc.
    print_terms = models.TextField(blank=True)
    default_warehouse = models.ForeignKey(
        "Warehouse", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "تنظیمات فروش ۲"

    @classmethod
    def load(cls) -> "Sales2Setting":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Warehouse(TimeStampedModel):
    """انبار — where a حواله takes the goods from."""

    code = models.CharField(max_length=20, unique=True)
    name_fa = models.CharField(max_length=120)
    address = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "انبار"

    def __str__(self) -> str:
        return self.name_fa


class DocumentSequence(models.Model):
    """
    The last number issued in a series, per Jalali year.

    A stored counter rather than «highest number + 1»: that shortcut hands a
    cancelled document's number to the next one, and an invoice number exists
    precisely so that never happens.
    """

    prefix = models.CharField(max_length=8)
    jalali_year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("prefix", "jalali_year")

    def __str__(self) -> str:
        return f"{self.prefix}-{self.jalali_year}: {self.last_value}"


class ProductProfile(TimeStampedModel):
    """
    A CRM product as sales sees it: whether it is offered at all, its sale
    floor, and — for a roll — its size as data.

    The size used to be read out of the product's name («79 - 36 - ساده»),
    which works until a name is typed «79 -35 چاپي». Now it is filled once from
    the names and edited here; the price formula reads these fields.

    Price and cost do not live here: the price comes from the month's price
    list (`PriceSheet` for rolls, `PriceListItem` for the rest) and the cost
    from `AccountingCost`. One source each.
    """

    product = models.OneToOneField(
        "crm.Product", on_delete=models.CASCADE, related_name="sales2_profile"
    )
    #: Off: the product stays in CRM but leaves every sales dropdown.
    is_sellable = models.BooleanField(default=True)
    #: Below this a line is flagged — the floor a salesperson may discount to.
    min_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    #: A roll has both; anything else (labels) has neither.
    width_mm = models.PositiveSmallIntegerField(null=True, blank=True)
    length_m = models.PositiveSmallIntegerField(null=True, blank=True)
    is_printed = models.BooleanField(default=False)

    class Meta:
        verbose_name = "کالا در فروش"

    @property
    def is_roll(self) -> bool:
        return bool(self.width_mm and self.length_m)

    def __str__(self) -> str:
        return str(self.product)


class CustomerAccount(TimeStampedModel):
    """
    The credit side of a customer: how much they may owe, and whether sales
    to them are stopped. Beside `crm.Customer` rather than on it — CRM is a
    sales-team tool and a credit limit is a finance decision.
    """

    customer = models.OneToOneField(
        "crm.Customer", on_delete=models.CASCADE, related_name="sales2_account"
    )
    #: None means no limit has been set; zero means cash only.
    credit_limit_rial = models.DecimalField(
        max_digits=20, decimal_places=0, null=True, blank=True
    )
    credit_days = models.PositiveSmallIntegerField(default=0)
    #: توقف فروش — nothing may be invoiced to this customer.
    on_hold = models.BooleanField(default=False)
    note = models.CharField(max_length=300, blank=True)
    #: مانده‌ی اول دوره — what the customer owed on the cut-over day, carried
    #: from accounting. Counts as billed in every balance; invoices before
    #: that day are not brought over one by one.
    opening_balance_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    opening_as_of = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "حساب اعتباری مشتری"


class SalesDocument(TimeStampedModel):
    """
    پیش‌فاکتور، فاکتور فروش یا مرجوعی — one table, three kinds.

    They share every column that matters (customer, lines, prices, VAT) and
    each is born from the one before it: a فاکتور from a پیش‌فاکتور, a
    مرجوعی from a فاکتور. One table makes that chain a single `source` link
    and lets the customer's page list their whole history in one query.
    """

    class Kind(models.TextChoices):
        PROFORMA = "proforma", "پیش‌فاکتور"
        INVOICE = "invoice", "فاکتور فروش"
        RETURN = "return", "مرجوعی"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        ISSUED = "issued", "صادر شده"
        CANCELLED = "cancelled", "ابطال"

    class ReturnType(models.TextChoices):
        #: Goods that went out and came back (capped by what was delivered).
        GOODS = "goods", "مرجوعی کالا"
        #: The undelivered part written off — money only, no goods move.
        UNDELIVERED = "undelivered", "کسر تحویل‌نشده"

    class Settlement(models.TextChoices):
        CASH = "cash", "نقدی"
        CREDIT = "credit", "اعتباری"
        CHEQUE = "cheque", "چک"
        MIXED = "mixed", "ترکیبی"

    PREFIX = {Kind.PROFORMA: "PF", Kind.INVOICE: "INV", Kind.RETURN: "RET"}

    kind = models.CharField(max_length=10, choices=Kind.choices)
    number = models.CharField(max_length=24, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    source = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="derived"
    )

    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="sales2_documents"
    )
    salesperson = models.ForeignKey(
        "sales.DimEmployee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sales2_documents",
    )
    channel = models.CharField(max_length=16, blank=True)
    deal = models.ForeignKey(
        "crm.Deal", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sales2_documents",
    )
    warehouse = models.ForeignKey(
        Warehouse, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )

    doc_date = models.DateField()
    #: پیش‌فاکتور only — prices hold until this day.
    valid_until = models.DateField(null=True, blank=True)
    #: فاکتور only — when the money is due.
    due_date = models.DateField(null=True, blank=True)
    settlement = models.CharField(
        max_length=8, choices=Settlement.choices, default=Settlement.CASH
    )
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    #: فاکتور رسمی — carries VAT and goes to سامانه مودیان.
    is_official = models.BooleanField(default=True)
    vat_pct = models.DecimalField(max_digits=5, decimal_places=2, default=DEFAULT_VAT_PCT)

    # ---- Customer as printed, frozen at issue -------------------------------
    customer_name = models.CharField(max_length=200, blank=True)
    customer_national_id = models.CharField(max_length=20, blank=True)
    customer_economic_code = models.CharField(max_length=20, blank=True)
    customer_address = models.CharField(max_length=400, blank=True)
    customer_postal_code = models.CharField(max_length=10, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)

    # ---- Totals, recomputed from the lines while a draft ---------------------
    subtotal_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    discount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    net_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    vat_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    total_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    cost_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    # ---- The issue ---------------------------------------------------------
    #: What the checks found when the document was issued, and whether each
    #: was overridden. Kept so «why was this sold at a loss?» has an answer.
    issue_checks = models.JSONField(default=list, blank=True)
    override_reason = models.CharField(max_length=400, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=400, blank=True)
    #: پیش‌فاکتور only — its remainder closed by hand. How far a proforma has
    #: been invoiced is never stored; it is counted from the invoices (see
    #: `services.invoicing_state`), so only this human decision is kept.
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=400, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    #: مرجوعی only.
    return_type = models.CharField(
        max_length=12, choices=ReturnType.choices, default=ReturnType.GOODS
    )

    note = models.TextField(blank=True)
    #: Where a document came from when it was brought over rather than written
    #: here — «arpa:<code>» or «deal:<id>». Makes the move repeatable: a
    #: second run skips what the first one brought.
    external_ref = models.CharField(max_length=80, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-doc_date", "-id")
        verbose_name = "سند فروش"
        indexes = [
            models.Index(fields=["kind", "status", "doc_date"]),
            models.Index(fields=["customer", "kind", "status"]),
            models.Index(fields=["salesperson", "doc_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "number"],
                condition=~models.Q(number=""),
                name="sales2_unique_number_per_kind",
            ),
        ]

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    @property
    def profit_rial(self) -> Decimal:
        return (self.net_rial or ZERO) - (self.cost_rial or ZERO)

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.number or f'#{self.pk}'}"


class SalesDocumentLine(TimeStampedModel):
    """
    One row of a document. The product's name, unit and cost are copied onto
    it so an issued document reads the same after the catalogue changes.
    """

    document = models.ForeignKey(
        SalesDocument, on_delete=models.CASCADE, related_name="lines"
    )
    #: The proforma line an invoice line came from, or the invoice line a
    #: return line gives back — how «چقدر از این ردیف برگشت خورد» is answered.
    source_line = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="derived"
    )
    product = models.ForeignKey(
        "crm.Product", on_delete=models.PROTECT, related_name="sales2_lines"
    )
    product_name = models.CharField(max_length=200, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    #: 48 or 55 gsm for a roll — the same size is two different products in
    #: price and in فی حسابداری. Null for products without one.
    grammage = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Stored for the same reason as the document's totals.
    gross_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    discount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    net_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    vat_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    total_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    unit_cost_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    #: Below-floor price as it was when the line was priced; see ProductProfile.
    min_price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "ردیف سند فروش"

    def __str__(self) -> str:
        return f"{self.product_name} × {self.quantity}"


class Delivery(TimeStampedModel):
    """
    حواله خروج — goods leaving the warehouse against an invoice.

    An invoice may go out in several loads, so delivery is its own document
    with its own lines rather than a flag on the invoice. There is no stock
    ledger yet; this records what left and who carried it, and caps it at
    what was invoiced.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        ISSUED = "issued", "خارج شده"
        CANCELLED = "cancelled", "ابطال"

    number = models.CharField(max_length=24, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    invoice = models.ForeignKey(
        SalesDocument, on_delete=models.PROTECT, related_name="deliveries"
    )
    warehouse = models.ForeignKey(
        Warehouse, null=True, blank=True, on_delete=models.SET_NULL, related_name="deliveries"
    )
    delivery_date = models.DateField()
    receiver_name = models.CharField(max_length=150, blank=True)
    driver_name = models.CharField(max_length=150, blank=True)
    driver_phone = models.CharField(max_length=40, blank=True)
    vehicle_plate = models.CharField(max_length=40, blank=True)
    waybill_no = models.CharField("شماره بارنامه", max_length=40, blank=True)
    shipping_address = models.CharField(max_length=400, blank=True)
    #: As on a document: what the checks found at issue, and the reason given
    #: for going past one (a customer on hold, a credit limit exceeded).
    issue_checks = models.JSONField(default=list, blank=True)
    override_reason = models.CharField(max_length=400, blank=True)
    note = models.CharField(max_length=400, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=400, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-delivery_date", "-id")
        verbose_name = "حواله خروج"

    def __str__(self) -> str:
        return f"حواله {self.number or f'#{self.pk}'}"


class DeliveryLine(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(
        SalesDocumentLine, on_delete=models.PROTECT, related_name="delivery_lines"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        unique_together = ("delivery", "invoice_line")


class Receipt(TimeStampedModel):
    """
    دریافت — money in from a customer, by any means.

    A cheque is a receipt with more to say, so its fields sit on this row
    rather than in a table of their own: one form, one list, one balance. What
    a cheque adds is a *life* — in hand, deposited, cleared or bounced — and a
    bounced cheque stops counting as paid.
    """

    class Method(models.TextChoices):
        CASH = "cash", "نقد"
        TRANSFER = "transfer", "واریز / حواله بانکی"
        POS = "pos", "کارتخوان"
        CHEQUE = "cheque", "چک"
        #: What accounting had already settled on an invoice brought over at
        #: cut-over. How it was paid is not known, only that it was.
        ARPA = "arpa", "تسویه در آرپا"

    class Status(models.TextChoices):
        ISSUED = "issued", "ثبت شده"
        CANCELLED = "cancelled", "ابطال"

    class FinanceStatus(models.TextChoices):
        PENDING = "pending", "در انتظار تأیید مالی"
        CONFIRMED = "confirmed", "تأیید مالی"
        REJECTED = "rejected", "رد مالی"

    class ChequeStatus(models.TextChoices):
        IN_HAND = "in_hand", "نزد صندوق"
        DEPOSITED = "deposited", "واگذار به بانک"
        CLEARED = "cleared", "وصول شد"
        BOUNCED = "bounced", "برگشتی"
        RETURNED = "returned", "عودت به مشتری"

    number = models.CharField(max_length=24, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)
    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="sales2_receipts"
    )
    received_on = models.DateField()
    period = models.ForeignKey(
        DimPeriod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.TRANSFER)
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    bank_account = models.ForeignKey(
        "finance.BankAccount", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sales2_receipts",
    )
    reference_no = models.CharField("شماره پیگیری", max_length=60, blank=True)
    external_ref = models.CharField(max_length=80, blank=True, db_index=True)

    # ---- Cheque ------------------------------------------------------------
    cheque_no = models.CharField(max_length=30, blank=True)
    sayad_no = models.CharField("شناسه صیاد", max_length=16, blank=True)
    cheque_bank = models.CharField(max_length=100, blank=True)
    cheque_due_date = models.DateField(null=True, blank=True)
    cheque_drawer = models.CharField("صادرکننده", max_length=150, blank=True)
    cheque_status = models.CharField(
        max_length=10, choices=ChequeStatus.choices, blank=True
    )
    #: ثبت در سامانه صیاد. A cheque that is in the drawer but was never
    #: registered is not yet a cheque in law; it gets `SAYAD_GRACE` to be
    #: registered and after that stops counting as paid (see `is_lapsed`).
    sayad_registered = models.BooleanField(default=False)
    sayad_registered_at = models.DateTimeField(null=True, blank=True)

    note = models.CharField(max_length=400, blank=True)
    cancel_reason = models.CharField(max_length=400, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    #: Sales records a receipt; finance confirms the money really arrived.
    #: Until then it pays nothing (see `counts_as_paid`).
    finance_status = models.CharField(
        max_length=10, choices=FinanceStatus.choices, default=FinanceStatus.PENDING
    )
    finance_note = models.CharField(max_length=300, blank=True)
    finance_at = models.DateTimeField(null=True, blank=True)
    finance_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-received_on", "-id")
        verbose_name = "دریافت"
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["method", "cheque_status", "cheque_due_date"]),
        ]

    @property
    def sayad_deadline(self):
        """When an unregistered cheque stops counting. None when it is not one."""
        if self.method != self.Method.CHEQUE or self.sayad_registered or not self.created_at:
            return None
        return self.created_at + SAYAD_GRACE

    @property
    def is_lapsed(self) -> bool:
        """
        An unregistered cheque past its 48 hours. It leaves مطالبات entirely:
        its amount is owed again, as if it had never been handed over.
        Computed from the clock rather than written by a job, so it cannot
        be late and there is nothing to schedule.
        """
        deadline = self.sayad_deadline
        return bool(deadline and timezone.now() >= deadline)

    @property
    def counts_as_paid(self) -> bool:
        """
        A cancelled receipt, a cheque that bounced or went back, or one never
        registered in صیاد within its grace, paid nothing.
        """
        if self.status != self.Status.ISSUED or self.is_lapsed:
            return False
        if self.finance_status != self.FinanceStatus.CONFIRMED:
            return False
        return self.cheque_status not in (
            self.ChequeStatus.BOUNCED, self.ChequeStatus.RETURNED
        )

    def __str__(self) -> str:
        return f"دریافت {self.number or f'#{self.pk}'}"


class ReceiptAllocation(models.Model):
    """تسویه — which invoice a receipt paid, and how much of it."""

    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(
        SalesDocument, on_delete=models.PROTECT, related_name="allocations"
    )
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    class Meta:
        unique_together = ("receipt", "invoice")


# ===========================================================================
# لیست قیمت — the company's price workbook, as data
# ===========================================================================
#
# The workbook the sales manager sends out each week is four sheets (48 and
# 55 gsm, رسمی and غیر رسمی) of one formula:
#
#     price per roll = width_mm × length_m × base_fi × waste ÷ 1000 + اجرت برش
#
# with the 200-roll price as the base and +3% / +6% for 50 and 10 rolls. Only
# the base fi changes week to week; every size follows from it. So the base
# and the per-size fees are stored, the prices are computed, and changing one
# number reprices a sheet — which is what the workbook already did.
class Grammage(models.IntegerChoices):
    G48 = 48, "۴۸ گرم"
    G55 = 55, "۵۵ گرم"


def default_qty_tiers() -> list:
    """The workbook's three columns: 200 rolls at base, 50 at +3%, 10 at +6%."""
    return [{"min_qty": 200, "pct": 0}, {"min_qty": 50, "pct": 3}, {"min_qty": 0, "pct": 6}]


class PriceSheet(TimeStampedModel):
    name = models.CharField(max_length=60)
    grammage = models.PositiveSmallIntegerField(choices=Grammage.choices)
    is_official = models.BooleanField()
    #: «فی 02» — the base the whole sheet is priced from.
    base_fi_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    #: The 103% in the formula: paper lost to trimming and cores.
    waste_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(103))
    qty_tiers = models.JSONField(default=default_qty_tiers)
    #: The month this sheet is the price list of. It holds until a later
    #: month has its own sheet of the same weight and kind — the rule
    #: `AccountingCost` follows — so a document is always priced from the
    #: list of the month it was written in.
    jalali_year = models.PositiveSmallIntegerField()
    jalali_month = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ("-jalali_year", "-jalali_month", "grammage", "-is_official")
        verbose_name = "برگه لیست قیمت"
        unique_together = ("grammage", "is_official", "jalali_year", "jalali_month")

    @property
    def month_key(self) -> int:
        return self.jalali_year * 100 + self.jalali_month

    def __str__(self) -> str:
        return self.name


class PriceSheetRow(models.Model):
    sheet = models.ForeignKey(PriceSheet, on_delete=models.CASCADE, related_name="rows")
    width_mm = models.PositiveSmallIntegerField()
    length_m = models.PositiveSmallIntegerField()
    cut_fee_rial = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    #: Added for a printed (چاپی) roll; the workbook lists it beside the size.
    print_fee_rial = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    #: A few rows use 101% instead of the sheet's waste; null means the sheet's.
    waste_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=60, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "width_mm", "length_m")

    def __str__(self) -> str:
        return f"{self.width_mm}×{self.length_m}"


class PriceListItem(TimeStampedModel):
    """
    A fixed price in a month's price list — for what the roll formula does not
    price (labels and the like). Same month rule as `PriceSheet`.
    """

    product = models.ForeignKey(
        "crm.Product", on_delete=models.CASCADE, related_name="sales2_list_prices"
    )
    jalali_year = models.PositiveSmallIntegerField()
    jalali_month = models.PositiveSmallIntegerField()
    price_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    is_official = models.BooleanField(default=True)

    class Meta:
        unique_together = ("product", "is_official", "jalali_year", "jalali_month")
        ordering = ("-jalali_year", "-jalali_month")
        verbose_name = "قیمت ثابت لیست"

    @property
    def month_key(self) -> int:
        return self.jalali_year * 100 + self.jalali_month


class AccountingCost(TimeStampedModel):
    """
    فی حسابداری — what accounting says one unit costs, per product and paper
    weight, from a Jalali month on. Commission margin and the loss check are
    both measured against it. `grammage` is 0 for products without one.

    A row is valid from its month until the product's next row: there is no
    «valid to» column to keep in step. A month's import adds rows and never
    overwrites an earlier month, so last month's profit and commission read
    the same after this month's costs arrive; a product missing from the new
    file simply keeps its last cost.
    """

    product = models.ForeignKey(
        "crm.Product", on_delete=models.CASCADE, related_name="sales2_costs"
    )
    grammage = models.PositiveSmallIntegerField(default=0)
    jalali_year = models.PositiveSmallIntegerField()
    jalali_month = models.PositiveSmallIntegerField()
    cost_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    source = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = ("product", "grammage", "jalali_year", "jalali_month")
        ordering = ("-jalali_year", "-jalali_month")
        verbose_name = "فی حسابداری"

    @property
    def month_key(self) -> int:
        return self.jalali_year * 100 + self.jalali_month


# ===========================================================================
# پورسانت
# ===========================================================================
class CommissionTier(models.Model):
    """
    One step of the table: a line sold at least `min_margin_pct` above its
    فی حسابداری earns `rate_pct`. Read off the finance workbook — it
    reproduces 189 of Mordad's 199 lines; the rest were set by hand, which is
    what `CommissionOverride` is for.
    """

    min_margin_pct = models.DecimalField(max_digits=6, decimal_places=2)
    rate_pct = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ("min_margin_pct",)

    def __str__(self) -> str:
        return f"≥{self.min_margin_pct}% → {self.rate_pct}%"


class CommissionOverride(TimeStampedModel):
    """A rate set by hand for one line, with the reason finance gave."""

    line = models.OneToOneField(
        SalesDocumentLine, on_delete=models.CASCADE, related_name="commission_override"
    )
    rate_pct = models.DecimalField(max_digits=5, decimal_places=2)
    reason = models.CharField(max_length=300)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )


class CommissionRun(TimeStampedModel):
    """
    One month's commission sheet. Live while open; on approval its figures are
    frozen into `snapshot`, so a late receipt or a cost correction next month
    does not quietly change what was already paid.
    """

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        APPROVED = "approved", "تأیید شده"

    jalali_year = models.PositiveSmallIntegerField()
    jalali_month = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    snapshot = models.JSONField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        unique_together = ("jalali_year", "jalali_month")
        ordering = ("-jalali_year", "-jalali_month")
