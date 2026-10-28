"""
B2B's own workbooks into CRM — پیش‌فاکتورها, قیف بازاریابی, پلن توسعه.

The B2B unit kept its pipeline in Excel: one sheet of quotes a month, a funnel
table of companies, a plan of open quotes with odds and next steps. This
reads those sheets and files each quote as a deal on B2B's own pipeline
(`apps.crm.b2b`).

Rules, because a second run and a person's later edits must both be safe:
  • A quote is identified by customer + date + amount (Rial). The Mehr
    detail file and the monthly sheet both list Mehr; they meet on that key.
  • A deal already in CRM is not overwritten — only its blank tender fields
    are filled. What a rep changed since stays changed.
  • A customer is linked only on an exact name match within B2B. Otherwise a
    new B2B customer is made and look-alikes are queued for review
    (`merge.ImportTwins`); nothing is merged automatically.
  • The invoice sheets are not stored: آرپا is the source of invoices. They
    are only checked against it, and the match rate reported.
  • Products are matched by width × length, never created.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.crm import b2b
from apps.crm.jalali import jalali_to_gregorian, period_for
from apps.crm.matching import fold, name_key
from apps.crm.merge import ImportTwins
from apps.crm.models import (
    Activity, Customer, Deal, DealItem, DealStageEvent, ImportBatch, LostReason,
    PipelineStage, Product, SalesInvoice, Task,
)

DATASET = "real"
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
#: The unit head in the sheets; filed under `default_owner`.
HEAD = "مدیر واحد"
#: A slot in his template, not a person.
PLACEHOLDER = re.compile(r"^کارشناس\s*\d+$")


# ---------------------------------------------------------------- parsing
def _text(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def _num(v) -> Decimal | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = fold(v).replace(",", "").replace("٬", "").strip()
    try:
        return Decimal(s)
    except Exception:
        return None


def _date(v) -> date | None:
    """A Jalali date as he types it — 1405/07/04, 1405-7-4, Persian digits."""
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, date):
        # Excel read a Jalali string as a Gregorian date: 1405-07-04.
        return jalali_to_gregorian(v.year, v.month, v.day) if v.year < 1500 else v
    parts = re.findall(r"\d+", fold(v or ""))
    if len(parts) != 3:
        return None
    y, m, d = (int(p) for p in parts)
    if not (1300 < y < 1500 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    try:
        return jalali_to_gregorian(y, m, d)
    except ValueError:
        return None


def _at(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, time(10)))


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


@dataclass
class Sheet:
    title: str
    kind: str                 # detail | quotes | invoices | funnel | plan
    cols: dict[str, int]      # header text → 1-based column
    rows: list[dict] = field(default_factory=list)
    stamp: date | None = None  # «تاریخ بروزرسانی»

    @property
    def month(self) -> int:
        """The sheet's Jalali month from its title, for ordering; 0 if none."""
        return next((i + 1 for i, m in enumerate(MONTHS) if m in self.title), 0)


#: Which header marks which table. Matched against the stripped header text.
KINDS = [
    ("detail", "وضعیت (اصلی)"),
    ("plan", "احتمال موفقیت (٪)"),
    ("funnel", "مرحله فعلی"),
    ("invoices", "وضعیت تسویه"),
    ("quotes", "نتیجه / توضیحات"),
]


def read_workbook(path) -> list[Sheet]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        stamp = None
        for r in grid[:3]:
            for i, v in enumerate(r):
                if "تاریخ بروزرسانی" in _text(v):
                    stamp = next((_date(x) for x in r[i + 1:] if _date(x)), None)
        for h, row in enumerate(grid[:60]):
            heads = [_text(v) for v in row]
            if not ({"نام مجموعه", "نام شرکت"} & set(heads)):
                continue
            kind = next((k for k, mark in KINDS if mark in heads), None)
            if not kind:
                break
            cols = {}
            for i, t in enumerate(heads):
                if t and t not in cols:
                    cols[t] = i
            sheet = Sheet(ws.title, kind, cols, stamp=stamp)
            name_col = cols.get("نام مجموعه", cols.get("نام شرکت"))
            for r in grid[h + 1:]:
                if name_col < len(r) and _text(r[name_col]):
                    sheet.rows.append({t: (r[i] if i < len(r) else None) for t, i in cols.items()})
            out.append(sheet)
            break
    wb.close()
    return out


def col(row: dict, *names, default=None):
    """The first of `names` (or a header starting with it) that has a value."""
    for n in names:
        for head, v in row.items():
            if (head == n or head.startswith(n)) and v not in (None, ""):
                return v
    return default


# ---------------------------------------------------------------- import
@dataclass
class Report:
    dry_run: bool = False
    sheets: list = field(default_factory=list)
    quotes_read: int = 0
    deals_created: int = 0
    deals_kept: int = 0
    funnel_rows: int = 0
    funnel_deals: int = 0
    plan_rows: int = 0
    plan_matched: int = 0
    tasks: int = 0
    notes: int = 0
    customers_created: int = 0
    customers_linked: int = 0
    twins_queued: int = 0
    products_matched: int = 0
    products_missing: Counter = field(default_factory=Counter)
    owners_unknown: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)
    invoices_read: int = 0
    invoices_in_arpa: int = 0
    invoices_missing: list = field(default_factory=list)

    def lines(self) -> list[str]:
        L = [("آزمایشی — چیزی ذخیره نشد" if self.dry_run else "ذخیره شد")]
        L += [f"  شیت «{t}»: {k}، {n} ردیف" for t, k, n in self.sheets]
        L += [
            f"پیش‌فاکتور خوانده‌شده: {self.quotes_read} — معامله‌ی جدید: {self.deals_created}، "
            f"از قبل بود (دست نخورد): {self.deals_kept}",
            f"قیف: {self.funnel_rows} شرکت — معامله‌ی جدید از قیف: {self.funnel_deals}",
            f"پلن: {self.plan_rows} ردیف — به پیش‌فاکتور وصل شد: {self.plan_matched}",
            f"کار پیگیری: {self.tasks} — یادداشت: {self.notes}",
            f"مشتری جدید B2B: {self.customers_created} — وصل به مشتری موجود: {self.customers_linked} "
            f"— مشکوک به تکراری در صف بازبینی: {self.twins_queued}",
            f"محصول پیدا شد: {self.products_matched} — پیدا نشد: {sum(self.products_missing.values())}",
            f"فاکتورهای اکسل: {self.invoices_read} — در آرپا پیدا شد: {self.invoices_in_arpa}",
        ]
        for title, counter in (("محصول پیدا نشد", self.products_missing),
                               ("کارشناس ناشناخته (بی‌کارشناس ماند)", self.owners_unknown),
                               ("ردیف رد شد", self.skipped)):
            if counter:
                L.append(f"{title}:")
                L += [f"  {k}: {n}" for k, n in counter.most_common()]
        if self.invoices_missing:
            L.append("فاکتورهای اکسل که در آرپا پیدا نشد:")
            L += [f"  {x}" for x in self.invoices_missing]
        return L


class Importer:
    def __init__(self, default_owner=None, user=None):
        from apps.crm.people import RepMatcher, sales_roster

        self.stages = b2b.ensure_stages(PipelineStage, LostReason, DATASET)
        self.cancelled = LostReason.objects.get(code=b2b.CANCELLED[0])
        self.to_competitor = (
            LostReason.objects.filter(dataset=DATASET, name_fa="خرید از رقبا").first()
            or LostReason.objects.get_or_create(
                code="bought-from-competitor",
                defaults=dict(name_fa="خرید از رقبا", is_controllable=False, dataset=DATASET),
            )[0]
        )
        self.default_owner = default_owner
        self.reps = RepMatcher(sales_roster([b2b.CHANNEL]))
        self.user = user
        self.twins = ImportTwins(DATASET)
        self.report = Report()
        self.customers: dict[str, Customer] = {}
        self.touched: set[int] = set()
        self.products = self._products()

    # -- lookups ----------------------------------------------------------
    @staticmethod
    def _products() -> dict[tuple[str, str], Product]:
        """(width, length) → the plain («ساده») roll of that size."""
        out = {}
        for p in Product.objects.filter(dataset=DATASET, is_active=True).order_by("id"):
            name = fold(p.name_fa)
            nums = re.findall(r"\d+(?:[./]\d+)?", name)
            if len(nums) >= 2 and "ساده" in name and "چاپی" not in name:
                k = (nums[0], nums[1].replace("/", "."))
                # The shortest name is the plain roll, not a «بنکیت» or «وینکور».
                if k not in out or len(p.name_fa) < len(out[k].name_fa):
                    out[k] = p
        return out

    def owner(self, name):
        raw = _text(name)
        if not raw or fold(raw) == fold(HEAD):
            return self.default_owner
        if PLACEHOLDER.match(fold(raw)):
            self.report.owners_unknown[raw] += 1
            return None
        found = self.reps.match(raw)
        if not found:
            self.report.owners_unknown[raw] += 1
        return found

    def customer(self, name: str, when: date, city: str = "", contact: str = "") -> Customer:
        key = name_key(name)
        if key in self.customers:
            c = self.customers[key]
        else:
            found = list(Customer.objects.filter(
                dataset=DATASET, channel=b2b.CHANNEL, name_key=key, merged_into__isnull=True,
            ).order_by("id")[:2])
            if found:
                c = found[0]
                self.report.customers_linked += 1
            else:
                c = Customer.objects.create(
                    dataset=DATASET, code=f"xl-b2b-c-{_key(key)}", name_fa=_text(name),
                    channel=b2b.CHANNEL, first_contact_at=_at(when), city=city[:100],
                    contact_name=contact[:150],
                )
                self.report.customers_created += 1
                self.twins.check(c)
                self.report.twins_queued = self.twins.queued
            self.customers[key] = c
        # Fill blanks only: what CRM already holds is not his to overwrite.
        changed = [f for f, v in (("city", city), ("contact_name", contact)) if v and not getattr(c, f)]
        for f in changed:
            setattr(c, f, {"city": city[:100], "contact_name": contact[:150]}[f])
        if changed:
            c.save(update_fields=changed + ["updated_at"])
        self.touched.add(c.pk)
        return c

    # -- quotes -----------------------------------------------------------
    def quote(self, row: dict, detail: bool) -> None:
        name = _text(col(row, "نام مجموعه"))
        when = _date(col(row, "تاریخ پیش‌فاکتور", "تاریخ"))
        amount = _num(col(row, "مبلغ"))
        if not when or not amount:
            self.report.skipped["پیش‌فاکتور بدون تاریخ یا مبلغ"] += 1
            return
        toman = 10 if detail else 1  # The Mehr detail file is in Toman.
        rial = int(amount * toman)
        self.report.quotes_read += 1
        status = fold(_text(col(row, "وضعیت")))
        note = _text(col(row, "توضیحات اصلی", "نتیجه / توضیحات"))
        competitor = _text(col(row, "رقیب برنده")) if detail else ""
        tender = {"سامانه": "system", "مستقیم": "direct"}.get(_text(col(row, "کانال دریافت سفارش")), "")
        rank = _num(col(row, "رتبه در سامانه"))
        price = _num(col(row, "قیمت پیشنهادی ما"))
        rival = _num(col(row, "قیمت برنده"))
        tender_fields = {
            "tender_channel": tender,
            "tender_rank": int(rank) if rank and 0 < rank < 1000 else None,
            "competitor": competitor[:120],
            "competitor_unit_price_rial": int(rival * toman) if rival else None,
        }

        cust = self.customer(name, when)
        code = f"xl-b2b-{_key(cust.name_key, when.isoformat(), rial)}"
        deal = Deal.objects.filter(code=code).first()
        if deal:
            blanks = [f for f, v in tender_fields.items() if v and not getattr(deal, f)]
            for f in blanks:
                setattr(deal, f, tender_fields[f])
            if blanks:
                deal.save(update_fields=blanks + ["updated_at"])
            # The Mehr detail row of a quote the monthly sheet already made.
            if detail and not deal.items.exists():
                self._item(deal, row, price, toman, rial)
            if note and not deal.lost_reason_id:
                self._note(deal, note, deal.opened_at)
            self.report.deals_kept += 1
            return

        if status.startswith("تایید"):
            stage, reason = self.stages["b2b-won"], None
        elif status.startswith("رد"):
            stage, reason = self.stages["b2b-lost"], self.to_competitor
        elif status.startswith("ابطال"):
            stage, reason = self.stages["b2b-lost"], self.cancelled
        else:
            stage, reason = self.stages["b2b-4"], None
        product = _text(col(row, "کالا / محصول"))
        opened = _at(when)
        closed = opened if stage.kind != "open" else None
        deal = Deal.objects.create(
            dataset=DATASET, code=code, customer=cust, channel=b2b.CHANNEL,
            title=(f"پیش‌فاکتور {product}" if product else f"پیش‌فاکتور {cust.name_fa}")[:250],
            owner=self.owner(col(row, "کارشناس فروش")), stage=stage, status=stage.kind,
            amount_rial=rial, opened_at=opened, period=period_for(opened),
            closed_at=closed, close_period=period_for(closed) if closed else None,
            lost_reason=reason, lost_note=(note if reason else "")[:400], **tender_fields,
        )
        self.report.deals_created += 1
        self._events(deal, [self.stages["b2b-4"]] + ([stage] if stage.kind != "open" else []), opened)
        if detail:
            self._item(deal, row, price, toman, rial)
        if note and not reason:
            self._note(deal, note, opened)

    def _item(self, deal, row, price, toman, rial) -> None:
        w, l = _num(col(row, "عرض")), _num(col(row, "طول"))
        rolls = _num(col(row, "تعداد رول"))
        if not (w and l and price):
            return
        size = (str(int(w)) if w == int(w) else str(w), str(int(l)) if l == int(l) else str(l))
        product = self.products.get(size)
        if not product:
            self.report.products_missing[f"{size[0]}×{size[1]}"] += 1
            return
        unit = int(price * toman)
        qty = rolls if rolls else Decimal(rial) / unit
        gross = qty * unit
        if rial > gross:  # Billed above list × rolls: the rolls were more.
            qty, gross = Decimal(rial) / unit, Decimal(rial)
        discount = (Decimal(1) - Decimal(rial) / gross) * 100 if gross else Decimal(0)
        DealItem.objects.create(
            dataset=DATASET, deal=deal, product=product, quantity=qty.quantize(Decimal("0.01")),
            unit_price_rial=unit, discount_pct=discount.quantize(Decimal("0.01")),
        )
        self.report.products_matched += 1

    def _events(self, deal, stages, at) -> None:
        prev = None
        for st in stages:
            DealStageEvent.objects.create(dataset=DATASET, deal=deal, from_stage=prev, to_stage=st, at=at)
            prev = st

    def _note(self, deal, text, at) -> None:
        _, made = Activity.objects.get_or_create(
            dataset=DATASET, external_key=f"xl-b2b-n-{deal.pk}-{_key(text)}",
            defaults=dict(kind=Activity.Kind.QUOTE, customer=deal.customer, deal=deal,
                          owner=deal.owner, at=at, note=text[:500], period=period_for(at)),
        )
        self.report.notes += made

    def _task(self, deal, title, due, note="") -> None:
        title = _text(title)
        if not title or deal.status != Deal.Status.OPEN:
            return
        _, made = Task.objects.get_or_create(
            dataset=DATASET, external_key=f"xl-b2b-t-{deal.pk}-{_key(title)}",
            defaults=dict(title=title[:250], customer=deal.customer, deal=deal, owner=deal.owner,
                          due_at=_at(due), note=note[:500]),
        )
        self.report.tasks += made

    # -- funnel -------------------------------------------------------------
    def funnel(self, row: dict, sheet: Sheet) -> None:
        name = _text(col(row, "نام شرکت"))
        when = sheet.stamp or timezone.localdate()
        self.report.funnel_rows += 1
        cust = self.customer(name, when, city=_text(col(row, "شهر / استان")),
                             contact=_text(col(row, "شخص تماس")))
        step = _num(col(row, "ردیف مرحله"))
        n = int(step) if step else 1
        stage = (self.stages["b2b-lost"] if n >= 9 else self.stages["b2b-won"] if n >= 7
                 else self.stages[f"b2b-{max(n, 1)}"])
        about = _text(col(row, "توضیحات"))
        if about and not cust.note:
            cust.note = about
            cust.save(update_fields=["note", "updated_at"])

        deal = (Deal.objects.filter(customer=cust, status=Deal.Status.OPEN, code__startswith="xl-b2b-")
                .order_by("-opened_at").first())
        if deal is None and stage.kind == "open":
            code = f"xl-b2b-f-{_key(cust.name_key)}"
            deal = Deal.objects.filter(code=code).first()
            if deal is None:
                opened = _at(when)
                deal = Deal.objects.create(
                    dataset=DATASET, code=code, customer=cust, channel=b2b.CHANNEL,
                    title=f"قیف — {cust.name_fa}"[:250], owner=self.owner(col(row, "مسئول پیگیری")),
                    stage=stage, status="open", amount_rial=int(_num(col(row, "مبلغ برآوردی")) or 0),
                    opened_at=opened, period=period_for(opened),
                )
                self._events(deal, [self.stages[f"b2b-{i}"] for i in range(1, n + 1)], opened)
                self.report.funnel_deals += 1
        elif deal and stage.kind == "open" and stage.order > (deal.stage.order if deal.stage else 0):
            # Further along in his funnel than the quote says: follow him.
            DealStageEvent.objects.create(dataset=DATASET, deal=deal, from_stage=deal.stage, to_stage=stage, at=_at(when))
            deal.stage = stage
            deal.save(update_fields=["stage", "updated_at"])
        if deal:
            due = _date(col(row, "تاریخ پیگیری بعدی"))
            self._task(deal, col(row, "اقدام بعدی", "پیگیری"), due or when,
                       "" if due else "تاریخ پیگیری در اکسل نبود")

    # -- plan ---------------------------------------------------------------
    def plan(self, row: dict) -> None:
        self.report.plan_rows += 1
        when = _date(col(row, "تاریخ پیش‌فاکتور"))
        amount = _num(col(row, "مبلغ"))
        if not when or not amount:
            return
        code = f"xl-b2b-{_key(name_key(col(row, 'نام مجموعه')), when.isoformat(), int(amount))}"
        deal = Deal.objects.filter(code=code).first()
        if not deal:
            return
        self.report.plan_matched += 1
        pct = _num(col(row, "احتمال موفقیت"))
        if pct is not None and 0 <= pct <= 100 and deal.probability_pct is None and deal.status == "open":
            deal.probability_pct = int(pct)
            deal.save(update_fields=["probability_pct", "updated_at"])
        if deal.owner is None:
            owner = self.owner(col(row, "مسئول پیگیری"))
            if owner:
                deal.owner = owner
                deal.save(update_fields=["owner", "updated_at"])
        due = _date(col(row, "تاریخ پیگیری بعدی"))
        self._task(deal, col(row, "اقدام بعدی"), due or when,
                   _text(col(row, "توضیحات")) or ("" if due else "تاریخ پیگیری در اکسل نبود"))

    # -- invoices: checked, not stored ---------------------------------------
    def invoices(self, rows: list[dict]) -> None:
        wanted = []
        for row in rows:
            when, amount = _date(col(row, "تاریخ")), _num(col(row, "مبلغ"))
            if when and amount:
                wanted.append((name_key(col(row, "نام مجموعه")), when, amount, _text(col(row, "نام مجموعه"))))
        self.report.invoices_read = len(wanted)
        if not wanted:
            return
        lo = min(w[1] for w in wanted) - timedelta(days=7)
        hi = max(w[1] for w in wanted) + timedelta(days=8)
        arpa: dict[str, list] = {}
        every = []
        for k, at, amt in SalesInvoice.objects.filter(
            dataset=DATASET, issued_at__gte=lo, issued_at__lt=hi,
        ).values_list("customer__name_key", "issued_at", "amount_rial"):
            arpa.setdefault(k, []).append((at, amt))
            every.append((at, amt))

        def near(at, amt, when, amount):
            # His figure with or without the 10% VAT, within a week.
            return abs((at - when).days) <= 7 and any(
                abs(Decimal(amt) - amount * f) <= amount * Decimal("0.01") for f in (1, Decimal("1.1")))

        for key, when, amount, label in wanted:
            # By name first; آرپا spells customers its own way («امام رضا (ع)»),
            # so failing that the same amount in the same week counts.
            hit = (any(near(at, amt, when, amount) for at, amt in arpa.get(key, []))
                   or any(near(at, amt, when, amount) for at, amt in every))
            if hit:
                self.report.invoices_in_arpa += 1
            else:
                self.report.invoices_missing.append(f"{label} — {when.isoformat()} — {int(amount):,}")

    # -- the whole run -------------------------------------------------------
    def run(self, sheets: list[Sheet]) -> Report:
        for s in sheets:
            self.report.sheets.append((s.title, s.kind, len(s.rows)))
        # Monthly sheets first, the Mehr detail file last: the same quote is
        # then created from the plain row and its tender detail filled in.
        for s in sheets:
            if s.kind == "quotes":
                for row in s.rows:
                    self.quote(row, detail=False)
        for s in sheets:
            if s.kind == "detail":
                for row in s.rows:
                    self.quote(row, detail=True)
        for s in sorted((s for s in sheets if s.kind == "funnel"), key=lambda s: s.month):
            for row in s.rows:
                self.funnel(row, s)
        for s in sheets:
            if s.kind == "plan":
                for row in s.rows:
                    self.plan(row)
        self.invoices([r for s in sheets if s.kind == "invoices" for r in s.rows])
        Customer.refresh_rollups(list(self.touched))
        return self.report


def import_files(paths, *, dry_run=False, default_owner=None, user=None) -> Report:
    sheets, sha, names = [], hashlib.sha256(), []
    for p in paths:
        with open(p, "rb") as fh:
            sha.update(fh.read())
        names.append(str(p).replace("\\", "/").rsplit("/", 1)[-1])
        sheets += read_workbook(p)
    with transaction.atomic():
        imp = Importer(default_owner=default_owner, user=user)
        report = imp.run(sheets)
        report.dry_run = dry_run
        ImportBatch.objects.create(
            source=ImportBatch.Source.EXCEL, file_name=" + ".join(names)[:255],
            file_sha256=sha.hexdigest(), uploaded_by=user,
            rows=report.quotes_read + report.funnel_rows + report.plan_rows,
            created=report.deals_created + report.funnel_deals, unchanged=report.deals_kept,
            skipped=sum(report.skipped.values()), suspect=report.twins_queued,
            customers_created=report.customers_created, notes={"report": report.lines()},
        )
        if dry_run:
            transaction.set_rollback(True)
    return report
