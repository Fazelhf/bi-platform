"""
«ورود از آرپا» — one آرپا «فاکتور فروش» export, uploaded from the site.

The export is one row per invoice, 52 columns, two header rows («تخفیف برگه»
splits into درصد/مبلغ and «مسوول فروش» into نام/کد under it) and a totals row
at the bottom. Every column is kept on the invoice as read (`arpa_row`); the
ones the reports use are mapped onto fields the same way the old
`import_arpa_invoices` command (since removed) did, so the invoices it loaded
on the server and the same invoices uploaded here are one row, not two.

Three rules carry the design:

* **Idempotent.** An invoice is (book, type, number, date). Its 52 cells are
  fingerprinted, so a second upload of the same file reports every row as
  «قبلاً خوانده شده» and writes nothing; a row آرپا has since changed (a
  payment settled it) is updated, not duplicated.
* **فروش سوری.** «مسوول فروش» must be one of the three sales groups. Anything
  else — usually empty — holds the invoice out of every report until a
  manager rules «واقعی» (and picks the group) or «سوری». A ruling survives
  re-uploads; only آرپا filling the column in releases it on its own.
* **No hand work in the database.** A party not seen before becomes a
  customer, from what the invoice row carries, and every invoice that was
  waiting for it is attached.
* **An invoice is the won deal.** Every invoice that counts is a «معامله‌ی
  موفق» of its own (`sync_deal`), so won deals, conversion and «مشتری جدید»
  rest on what was billed — دیدار brings only the deals still open and the
  ones lost. A فروش سوری invoice has no deal until it is ruled real.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.dispatch import Signal
from django.utils import timezone
from django.utils.text import slugify

from apps.core import jalali
from apps.crm.arpa_file import ArpaFileError, read_sheet
from apps.crm.channels import RESPONSIBLE, ChannelResolver
from apps.crm.jalali import period_for
from apps.crm.matching import fold
from apps.crm.merge import ImportTwins
from apps.crm.models import (
    ImportBatch, Book, Customer, CustomerExternalRef, Dataset, Deal, ExternalSource,
    NOT_COUNTED, DealItem, Product, Review, SalesInvoice, SalesInvoiceItem,
)
from apps.crm.party_sync import INTERCOMPANY_MARKERS, PartyWriter
from apps.crm.people import RepMatcher

logger = logging.getLogger(__name__)
from apps.sales.models import DimEmployee

KIND = {
    "فاکتور فروش": SalesInvoice.Kind.SALE,
    "مرجوع از فروش": SalesInvoice.Kind.RETURN,
}


def dec(value) -> Decimal:
    """آرپا's amounts, separators and all; a return keeps its minus sign."""
    text = re.sub(r"[^\d.\-]", "", str(value or "0"))
    try:
        return Decimal(text or "0")
    except InvalidOperation:
        return Decimal(0)


def jdate(value):
    """«1405/07/11» → a date, or None."""
    parts = fold(value).split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
    except ValueError:
        return None
    return jalali.to_gregorian(y, m, d) if y > 1000 else None

#: Without these it is not a sales-invoice export, whatever else it holds.
REQUIRED = ("کد طرف حساب", "نام طرف حساب", "نوع برگه", "تاریخ برگه", "شماره برگه", "مبلغ فروش")

#: The line export («ریز فاکتور»): one row per product line, the document's
#: type and number together in «نام برگه» («فاکتور فروش 512»). Recognised by
#: these; folded into one document row per invoice by `_documents`.
LINE_REQUIRED = ("نام برگه", "تاریخ برگه", "شماره برگه", "کد طرف حساب", "نام طرف حساب", "کد کالا", "مبلغ")

#: Header columns of the line export, copied from the invoice's first line
#: under the name the document export uses. A column absent here is absent
#: from the document too, and `Importer.row` then leaves the stored value be.
LINE_HEADER = {
    "تاریخ برگه": "تاریخ برگه", "شماره برگه": "شماره برگه",
    "کد طرف حساب": "کد طرف حساب", "نام طرف حساب": "نام طرف حساب",
    "مبلغ برگه": "مبلغ برگه", "شرایط تسویه": "شرایط تسویه", "مهلت تسویه": "مهلت تسویه",
    "توضیحات برگه": "توضیحات برگه", "شناسه سامانه مودیان": "شناسه سامانه مودیان",
    "نام بازاریاب": "نام بازاریاب", "کد ملی": "کد ملی", "کد اقتصادی": "کد اقتصادی",
    "آدرس": "آدرس", "شماره تلفن": "تلفن", "موبایل": "موبایل",
    "نام مسول فروش": "مسوول فروش نام", "کد مسول فروش": "مسوول فروش کد",
    "دسته بندی": "دسته بندی",
}


def _size(name: str) -> tuple[str, str]:
    """Width (mm) and length (m) off a roll's name: «79 - 36 - ساده» → 79, 36."""
    nums = re.findall(r"\d+(?:[./]\d+)?", fold(name))
    if len(nums) < 2:
        return "", ""
    return nums[0].replace("/", "."), nums[1].replace("/", ".")

RESPONSIBLE_NAME = "مسوول فروش نام"
RESPONSIBLE_CODE = "مسوول فروش کد"


@dataclass
class Result:
    """What an upload did — or, in a preview, would do."""

    rows: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: list = field(default_factory=list)
    suspect: int = 0
    suspect_amount: Decimal = Decimal(0)
    customers_created: int = 0
    queued_for_review: int = 0
    amount: Decimal = Decimal(0)
    by_channel: dict = field(default_factory=lambda: defaultdict(Decimal))
    by_kind: dict = field(default_factory=lambda: defaultdict(lambda: [0, Decimal(0)]))
    unknown_reps: Counter = field(default_factory=Counter)
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    columns: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rows": self.rows,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "suspect": self.suspect,
            "suspect_amount": float(self.suspect_amount),
            "customers_created": self.customers_created,
            "queued_for_review": self.queued_for_review,
            "amount": float(self.amount),
            "by_channel": {k: float(v) for k, v in self.by_channel.items()},
            "by_kind": {k: {"count": n, "amount": float(a)} for k, (n, a) in self.by_kind.items()},
            "unknown_reps": [{"name": n, "count": c} for n, c in self.unknown_reps.most_common()],
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "columns": len(self.columns),
            "nothing_new": self.rows > 0 and not self.created and not self.updated,
        }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _headers(rows: list[list]) -> tuple[list[str], int]:
    """
    Column names, with the sub-header folded in: «مسوول فروش» over «نام» and
    «کد» becomes «مسوول فروش نام» / «مسوول فروش کد». Returns the names and
    the index of the first data row.
    """
    top = [fold(v) for v in rows[0]]
    sub = [fold(v) for v in rows[1]] if len(rows) > 1 else []
    # The document type sits in «نوع برگه», or in «نام برگه» on the line export.
    kind_col = next((top.index(c) for c in ("نوع برگه", "نام برگه") if c in top), None)
    # The second row is a sub-header when it has labels but no document type.
    is_sub = bool(sub) and any(sub) and (kind_col is None or not sub[kind_col])
    names, parent = [], ""
    for i, name in enumerate(top):
        label = sub[i] if is_sub and i < len(sub) else ""
        if name:
            parent = name
            names.append(f"{name} {label}".strip() if label else name)
        else:
            names.append(f"{parent} {label}".strip() if label else f"ستون {i + 1}")
    return names, (2 if is_sub else 1)


def _documents(lines: list[dict]) -> list[dict]:
    """
    The line export folded into the document export's shape: one row per
    invoice, its sums worked out from its lines exactly as آرپا's document
    report adds them (checked against 574 invoices already loaded from it),
    and the lines themselves under `__lines`.
    """
    docs: dict[tuple, dict] = {}
    for line in lines:
        title = fold(line.get("نام برگه"))
        number = fold(line.get("شماره برگه"))
        if not number:
            continue  # a totals or spacer row
        key = (title, number, fold(line.get("تاریخ برگه")))
        doc = docs.get(key)
        if doc is None:
            doc = docs[key] = {target: line.get(src) for src, target in LINE_HEADER.items() if src in line}
            # «فاکتور فروش 512» → «فاکتور فروش»
            doc["نوع برگه"] = re.sub(r"\s*\d+$", "", title)
            doc.update({"مبلغ فروش": Decimal(0), "تخفیف کل": Decimal(0), "جمع مالیات و عوارض": Decimal(0)})
            paid = dec(line.get("مبلغ پرداختی"))
            doc["مبلغ تسویه شده"] = paid
            doc["مبلغ تسویه نشده"] = dec(line.get("مبلغ برگه")) - paid
            doc["__lines"] = []
        for src, target in LINE_HEADER.items():  # first non-blank wins
            if src in line and not fold(doc.get(target)) and fold(line.get(src)):
                doc[target] = line.get(src)
        doc["مبلغ فروش"] += dec(line.get("مبلغ"))
        doc["تخفیف کل"] += dec(line.get("تخفیف ردیف")) + dec(line.get("سهم از تخفیف کل"))
        doc["جمع مالیات و عوارض"] += dec(line.get("مالیات")) + dec(line.get("عوارض"))
        doc["__lines"].append({
            "code": fold(line.get("کد کالا"))[:40],
            "name": fold(line.get("نام کالا"))[:200],
            "quantity": str(dec(line.get("تعداد"))),
            "equivalent": str(dec(line.get("معادل"))),
            "unit": fold(line.get("نام واحد"))[:20],
            "price": str(dec(line.get("فی"))),
            "amount": str(dec(line.get("مبلغ"))),
            "group": fold(line.get("نام گروه کالا"))[:40],
            "net": str(dec(line.get("مبلغ خالص"))),
            "cost": str(dec(line.get("بهای تمام شده"))),
            "discount": str(dec(line.get("تخفیف ردیف")) + dec(line.get("سهم از تخفیف کل"))),
            "vat": str(dec(line.get("مالیات")) + dec(line.get("عوارض"))),
            "warehouse": fold(line.get("نام انبار"))[:80],
            "paper": fold(line.get("نوع کاغذ"))[:60],
            "print": fold(line.get("نوع چاپ"))[:60],
            "carton": fold(line.get("نوع کارتن"))[:60],
            "size": _size(line.get("نام ثابت کالا") or line.get("نام کالا")),
            "note": fold(line.get("شرح ردیف"))[:200],
        })
    for doc in docs.values():
        for k in ("مبلغ فروش", "تخفیف کل", "جمع مالیات و عوارض", "مبلغ تسویه شده", "مبلغ تسویه نشده"):
            doc[k] = str(doc[k])
    return list(docs.values())


def parse(data: bytes, filename: str) -> tuple[list[str], list[dict]]:
    rows = read_sheet(data, filename)
    if len(rows) < 2:
        raise ArpaFileError("فایل خالی است.")
    names, first = _headers(rows)
    if all(c in names for c in LINE_REQUIRED):
        # آرپا repeats some headers («نوع چاپ», «عرض» …); the first copy holds
        # the data, so a later one is renamed rather than allowed to overwrite it.
        seen: dict[str, int] = {}
        unique = []
        for n in names:
            seen[n] = seen.get(n, 0) + 1
            unique.append(n if seen[n] == 1 else f"{n} {seen[n]}")
        lines = [
            {unique[i]: v for i, v in enumerate(r) if i < len(unique)}
            for r in rows[first:] if any(v not in (None, "") for v in r)
        ]
        return names, _documents(lines)
    missing = [c for c in REQUIRED if c not in names]
    if missing:
        raise ArpaFileError(
            "این فایل خروجی «فاکتور فروش» آرپا نیست؛ ستون‌های "
            + "، ".join(f"«{c}»" for c in missing) + " را ندارد."
        )
    out = []
    for r in rows[first:]:
        if not any(v not in (None, "") for v in r):
            continue
        out.append({names[i]: v for i, v in enumerate(r) if i < len(names)})
    return names, out


def _num_or_none(text: str):
    try:
        value = Decimal(text) if text else None
    except InvalidOperation:
        return None
    # Out of range for the field is a name that only looked like a size.
    return value if value is not None and 0 < value < 100000 else None


def _clean(v):
    """A cell as stored: text folded, numbers as numbers, blanks as ""."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return v
    return fold(v)


def fingerprint(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def invoice_code(book: str, kind: str, number: str, issued: dt.date) -> str:
    """
    The main book keeps the format the old command minted, so invoices
    already on the server are found again rather than duplicated. رول مارکت gets its own prefix: its numbers
    restart independently and collide with the main book's.
    """
    stamp = "".join(str(p) for p in jalali.from_gregorian(issued))
    prefix = "arpa-inv" if book == Book.MAIN else "arpa2-inv"
    return f"{prefix}-{kind}-{slugify(number) or 'x'}-{stamp}"[:50]


# ---------------------------------------------------------------------------
# The won deal behind an invoice
# ---------------------------------------------------------------------------
def deal_code(invoice: SalesInvoice) -> str:
    return f"deal-{invoice.code}"[:50]


#: آرپا's unit names onto the catalogue's.
UNITS = {"رول": Product.Unit.ROLL, "بسته": Product.Unit.PACK, "تن": Product.Unit.TON, "برگ": Product.Unit.SHEET}


def category_for(group: str):
    """The catalogue category of آرپا's «گروه کالا», added when missing."""
    from apps.crm.models import ProductCategory

    group = fold(group)
    if not group:
        return None
    return ProductCategory.objects.get_or_create(
        code=f"pc-{slugify(group, allow_unicode=True)}"[:50],
        defaults={"name_fa": group[:100], "dataset": Dataset.REAL},
    )[0]


def product_for(code: str, name: str, unit: str, cache: dict, group: str = "") -> int | None:
    """
    The catalogue product of آرپا's کد کالا, added when the catalogue does not
    have it yet. The catalogue *is* آرپا's («pr-<کد کالا>»), so a line's code
    is a product, not a guess; without one the line cannot reach the deal
    behind its invoice, and the product report would be missing that sale.
    """
    if not code:
        return None
    key = f"pr-{slugify(code)}"[:50]
    if key not in cache:
        product, _ = Product.objects.get_or_create(
            code=key, defaults={"name_fa": (name or code)[:150], "unit": UNITS.get(fold(unit), Product.Unit.ROLL),
                                "dataset": Dataset.REAL},
        )
        # A product with no category takes آرپا's product group — so the
        # catalogue groups the way the invoices do.
        if not product.category_id and group:
            product.category = category_for(group)
            product.save(update_fields=["category", "updated_at"])
        cache[key] = product.pk
    return cache[key]


def mirror_lines(invoice: SalesInvoice, deal: Deal) -> None:
    """
    The invoice's product lines as the deal's lines, so the deal page and
    «فروش بر محور محصول» show what was sold. Replaced whole, like the
    invoice's own lines. The price is the line's own (amount ÷ quantity);
    the cost is the catalogue's at the time, as the deal form takes it.
    """
    from apps.sales2.pricing import accounting_cost

    lines = list(invoice.items.select_related("product").exclude(product__isnull=True))
    if not lines:
        return
    deal.items.all().delete()
    rows = []
    for ln in lines:
        qty = ln.quantity if ln.quantity else Decimal(1)
        # The cost, best source first: آرپا's own «بهای تمام شده» on the line,
        # then accounting's فی حسابداری for that month, then the catalogue.
        cost = (ln.unit_cost_rial or accounting_cost(ln.product, None, invoice.issued_at)
                or ln.product.unit_cost_rial)
        rows.append(DealItem(
            dataset=deal.dataset, deal=deal, product=ln.product, quantity=qty,
            unit_price_rial=(ln.amount_rial / qty).quantize(Decimal(1)),
            unit_cost_rial=cost or 0,
        ))
    DealItem.objects.bulk_create(rows)
    cost = sum((r.quantity * r.unit_cost_rial for r in rows), Decimal(0)).quantize(Decimal(1))
    Deal.objects.filter(pk=deal.pk).update(cost_rial=cost, profit_rial=deal.amount_rial - cost)


def sync_deal(invoice: SalesInvoice) -> Deal | None:
    """
    Make the invoice's «معامله‌ی موفق» agree with it — or take it away.

    A sale that counts has exactly one won deal: same customer, salesperson,
    department, amount and day. A return, an invoice still waiting as فروش
    سوری, or one ruled fake has none. آرپا records no cost price, so the
    deal's profit stays zero rather than being guessed.
    """
    code = deal_code(invoice)
    wanted = (
        invoice.kind == SalesInvoice.Kind.SALE
        and invoice.review not in NOT_COUNTED
        and invoice.customer_id
    )
    deal = Deal.objects.filter(code=code).first()
    if not wanted:
        if deal:
            SalesInvoice.objects.filter(pk=invoice.pk).update(deal=None)
            deal.delete()
        return None

    when = timezone.make_aware(dt.datetime.combine(invoice.issued_at, dt.time(12, 0)))
    values = {
        "title": f"فاکتور {invoice.number} — {invoice.party_name}"[:250],
        "customer_id": invoice.customer_id,
        "owner_id": invoice.owner_id,
        "channel": invoice.channel or "team",
        "status": Deal.Status.WON,
        "amount_rial": invoice.amount_rial,
        "opened_at": when,
        "closed_at": when,
        "period_id": invoice.period_id,
        "close_period_id": invoice.period_id,
        "dataset": Dataset.REAL,
    }
    if deal is None:
        deal = Deal.objects.create(code=code, **values)
    elif any(getattr(deal, k) != v for k, v in values.items()):
        for k, v in values.items():
            setattr(deal, k, v)
        deal.save()
    if invoice.deal_id != deal.pk:
        SalesInvoice.objects.filter(pk=invoice.pk).update(deal=deal)
        invoice.deal_id = deal.pk
    mirror_lines(invoice, deal)
    # «مشتری جدید» counts the month of a customer's first win.
    Customer.objects.filter(pk=invoice.customer_id).filter(
        models.Q(first_deal_won_at__isnull=True) | models.Q(first_deal_won_at__gt=when)
    ).update(first_deal_won_at=when)
    return deal


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
class Importer:
    def __init__(self, book: str, user=None):
        self.book = book
        self.user = user
        self.result = Result()
        self.refs = dict(
            CustomerExternalRef.objects.filter(
                source=ExternalSource.ARPA, dataset=Dataset.REAL,
            ).values_list("external_id", "customer_id")
        )
        self.customers = {
            c.pk: c for c in Customer.objects.filter(pk__in=set(self.refs.values()))
        }
        self.reps = RepMatcher()
        self.channels = ChannelResolver()
        self.writer = PartyWriter(with_sales=None)
        self.twins = ImportTwins(Dataset.REAL)
        # آرپا's کد کالا is the catalogue's code behind its «pr-» prefix.
        self.products = dict(Product.objects.filter(code__startswith="pr-").values_list("code", "pk"))
        self.products_before = len(self.products)

    # -- people -------------------------------------------------------------
    def rep(self, name) -> DimEmployee | None:
        """آرپا's «نام بازاریاب» onto a colleague — see `apps.crm.people`."""
        return self.reps.match(name)

    def customer(self, row: dict, rep: DimEmployee | None) -> Customer:
        """The CRM customer for the row's party, created if this is the first sighting."""
        code = fold(row.get("کد طرف حساب"))
        name = fold(row.get("نام طرف حساب"))
        known = self.refs.get(code)
        if known:
            return self.customers.get(known) or Customer.objects.get(pk=known)

        party = {
            "کد": code, "نام": name, "کد ملی": row.get("کد ملی"),
            "کد اقتصادی": row.get("کد اقتصادی"), "کد پستی": row.get("کد پستی"),
            "آدرس": fold(row.get("آدرس")), "شماره تلفن": row.get("تلفن"), "موبایل": row.get("موبایل"),
            "نام گروه": fold(row.get("گروه طرف حساب")),
            # No استان: the export has none, and a province read off the
            # address is a guess. Left blank, the salesperson fills it in.
        }
        customer = self.writer.create(party)
        self.twins.check(customer)
        customer.owner = rep
        customer.channel = self.channels.customer(rep.pk if rep else None, party["نام گروه"])
        customer.status = Customer.Status.ACTIVE
        customer.save(update_fields=["owner", "channel", "status"])
        PartyWriter.link(customer, party)
        self.refs[code] = customer.pk
        self.customers[customer.pk] = customer
        self.result.customers_created += 1
        self.result.queued_for_review = self.twins.queued
        return customer

    # -- one row ------------------------------------------------------------
    def row(self, raw: dict, batch: ImportBatch | None) -> None:
        r = self.result
        kind = KIND.get(fold(raw.get("نوع برگه")))
        issued = jdate(raw.get("تاریخ برگه"))
        number = fold(raw.get("شماره برگه"))
        if not kind:
            # The totals row has no type — expected, and not worth a warning.
            if fold(raw.get("کد طرف حساب")) or fold(raw.get("شماره برگه")):
                r.skipped.append({"number": number, "reason": f"نوع برگه ناشناخته: «{fold(raw.get('نوع برگه'))}»"})
            return
        r.rows += 1
        if not issued or not number:
            r.skipped.append({"number": number, "reason": "تاریخ یا شماره برگه نامعتبر"})
            return

        # The lines count toward «changed?» but are kept as rows, not in arpa_row.
        stored = {k: _clean(v) for k, v in raw.items() if k != "__lines"}
        digest = fingerprint({**stored, "__lines": raw.get("__lines")} if "__lines" in raw else stored)
        amount = dec(raw.get("مبلغ فروش"))
        code = invoice_code(self.book, kind, number, issued)
        existing = SalesInvoice.objects.filter(code=code).first()

        responsible = fold(raw.get(RESPONSIBLE_NAME))
        group_channel = RESPONSIBLE.get(responsible)
        rep = self.rep(raw.get("نام بازاریاب"))

        # The ruling a manager already made outlives a re-upload; only a
        # filled-in «مسوول فروش» releases an invoice by itself.
        if group_channel:
            review, channel = "", group_channel
        elif existing and existing.review in (Review.REAL, Review.FAKE):
            review, channel = existing.review, existing.channel
        else:
            # Which group sold it is exactly what is unknown, so it stays
            # blank until the manager who rules it «واقعی» says.
            review, channel = Review.SUSPECT, ""

        r.amount += amount
        r.by_kind[kind][0] += 1
        r.by_kind[kind][1] += amount
        r.date_from = min(filter(None, (r.date_from, issued)))
        r.date_to = max(filter(None, (r.date_to, issued)))
        if review == Review.SUSPECT:
            r.suspect += 1
            r.suspect_amount += amount
        elif review != Review.FAKE:
            r.by_channel[channel] += amount

        if existing and existing.row_hash == digest and existing.review == review and (
            "__lines" not in raw or existing.items.exists()
        ):
            r.unchanged += 1
            if not existing.deal_id or (existing.items.exists() and not existing.deal.items.exists()):
                sync_deal(existing)  # loaded before invoices became deals, or before deals had lines
            return

        customer = self.customer(raw, rep)
        name = fold(raw.get("نام طرف حساب"))
        fields = {
            "number": number[:30],
            "kind": kind,
            "book": self.book,
            "customer": customer,
            "party_code": fold(raw.get("کد طرف حساب"))[:64],
            "party_name": name[:200],
            "is_intercompany": customer.is_intercompany or any(m in name for m in INTERCOMPANY_MARKERS),
            "issued_at": issued,
            "period": period_for(issued),
            "amount_rial": amount,
            "discount_rial": dec(raw.get("تخفیف کل")),
            "vat_rial": dec(raw.get("جمع مالیات و عوارض")),
            "total_rial": dec(raw.get("مبلغ برگه")),
            "settled_rial": dec(raw.get("مبلغ تسویه شده")),
            "unsettled_rial": dec(raw.get("مبلغ تسویه نشده")),
            "payment_terms": fold(raw.get("شرایط تسویه"))[:40],
            "due_date": jdate(raw.get("موعد تسویه")),
            "grace_date": jdate(raw.get("مهلت تسویه")),
            "shipping_method": fold(raw.get("روش حمل"))[:60],
            "owner": rep,
            "created_by_name": fold(raw.get("ایجاد کننده"))[:60],
            "channel": channel,
            "branch": fold(raw.get("شعبه"))[:60],
            "tax_ref": fold(raw.get("شناسه سامانه مودیان"))[:40],
            "category": fold(raw.get("دسته بندی"))[:20],
            "note": fold(raw.get("توضیحات برگه"))[:400],
            "sales_responsible": responsible[:60],
            "sales_responsible_code": fold(raw.get(RESPONSIBLE_CODE))[:20],
            "arpa_row": stored,
            "row_hash": digest,
            "review": review,
            "import_batch": batch,
            "dataset": Dataset.REAL,
        }
        # The line export has no موعد تسویه, روش حمل, شعبه or ایجاد کننده:
        # what the document export stored for those stays.
        if existing:
            for field_name, column in (("due_date", "موعد تسویه"), ("shipping_method", "روش حمل"),
                                       ("branch", "شعبه"), ("created_by_name", "ایجاد کننده")):
                if column not in raw:
                    fields.pop(field_name)
        self._fill_contact(customer, raw)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save()
            r.updated += 1
            invoice = existing
        else:
            invoice = SalesInvoice.objects.create(code=code, **fields)
            r.created += 1
        if "__lines" in raw:
            self._write_lines(invoice, raw["__lines"])
        sync_deal(invoice)

    @staticmethod
    def _fill_contact(customer, raw) -> None:
        """آرپا's phone and mobile onto a customer that has none — never over
        a number someone typed."""
        changed = []
        for field_name, column in (("phone", "تلفن"), ("mobile", "موبایل")):
            value = fold(raw.get(column))
            if value and not getattr(customer, field_name):
                setattr(customer, field_name, value[: Customer._meta.get_field(field_name).max_length])
                changed.append(field_name)
        if changed:
            customer.save()

    def _write_lines(self, invoice, lines) -> None:
        """The invoice's product lines, replaced wholesale: آرپا's lines are
        the record, and an edited invoice is re-sent whole."""
        invoice.items.all().delete()
        SalesInvoiceItem.objects.bulk_create([
            SalesInvoiceItem(
                dataset=invoice.dataset, invoice=invoice,
                product_id=product_for(ln["code"], ln["name"], ln["unit"], self.products, ln.get("group", "")),
                product_code=ln["code"], product_name=ln["name"],
                quantity=Decimal(ln["quantity"]), equivalent=Decimal(ln["equivalent"]),
                sub_unit=ln["unit"], unit_price_rial=Decimal(ln["price"]),
                amount_rial=Decimal(ln["amount"]), accounting_group=ln["group"],
                net_rial=Decimal(ln.get("net") or ln["amount"]), discount_rial=Decimal(ln.get("discount") or 0),
                unit_cost_rial=Decimal(ln.get("cost") or 0).quantize(Decimal(1)),
                vat_rial=Decimal(ln.get("vat") or 0), warehouse=ln.get("warehouse", ""),
                paper_type=ln.get("paper", ""), print_type=ln.get("print", ""), carton_type=ln.get("carton", ""),
                width_mm=_num_or_none((ln.get("size") or ("", ""))[0]),
                length_m=_num_or_none((ln.get("size") or ("", ""))[1]), note=ln.get("note", ""),
            )
            for ln in lines
        ])


#: Sent after an آرپا import is committed. فروش ۲ listens and copies the new
#: invoices over; CRM itself does not depend on فروش ۲.
arpa_imported = Signal()


def run(data: bytes, filename: str, book: str, user=None, commit: bool = False) -> dict:
    """
    Read and import one export. With `commit=False` it is a preview: the
    same work, inside a transaction that is rolled back, so the numbers shown
    before «ثبت» are exactly what «ثبت» will do.
    """
    if book not in Book.values:
        raise ArpaFileError("دفتر نامعتبر است.")
    names, rows = parse(data, filename)
    sha = hashlib.sha256(data).hexdigest()
    previous = ImportBatch.objects.filter(
        source=ImportBatch.Source.ARPA, file_sha256=sha, book=book,
    ).first()

    importer = Importer(book, user)
    importer.result.columns = names
    with transaction.atomic():
        batch = ImportBatch.objects.create(
            source=ImportBatch.Source.ARPA, file_name=filename[:255], file_sha256=sha, book=book, uploaded_by=user,
        )
        for raw in rows:
            importer.row(raw, batch)
        res = importer.result
        for k in ("rows", "created", "updated", "unchanged", "suspect", "customers_created"):
            setattr(batch, k, getattr(res, k))
        batch.skipped = len(res.skipped)
        batch.amount_rial = res.amount
        batch.date_from, batch.date_to = res.date_from, res.date_to
        batch.notes = {
            "skipped": res.skipped[:50],
            "unknown_reps": dict(importer.reps.unknown.most_common(30)),
            "suspect_amount": float(res.suspect_amount),
        }
        batch.save()
        if not commit:
            transaction.set_rollback(True)

    res.unknown_reps = importer.reps.unknown
    out = res.as_dict()
    out["committed"] = commit
    out["book"] = book
    out["file_name"] = filename
    out["batch_id"] = batch.pk if commit else None
    out["previous"] = (
        {"at": previous.created_at.isoformat(), "by": getattr(previous.uploaded_by, "username", "")}
        if previous else None
    )
    if commit:
        # Robust: the import is already saved; a listener failing must not
        # turn it into an error on screen.
        for _, reply in arpa_imported.send_robust(sender=Importer):
            if isinstance(reply, Exception):
                logger.exception("arpa_imported listener failed", exc_info=reply)
            elif isinstance(reply, dict):
                out.update(reply)
    return out
