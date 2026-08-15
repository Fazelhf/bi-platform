"""
Load the sales invoices out of آرپا and check them against آرپا's own totals.

    python manage.py import_arpa_invoices --dir "C:/Users/Asus/Downloads" --check
    python manage.py import_arpa_invoices --dir "C:/Users/Asus/Downloads"

Two workbooks per period, joined here: «فروش کل» is one row per invoice and
«جزئیات فروش» one row per line. Both are read for every year found in the
folder, so adding 1403's export later is a matter of dropping the files in.

The point of separation, restated because it is the thing most likely to be
undone later: **an invoice never touches `Deal.amount_rial`.** A معامله is a
pipeline opportunity valued by دیدار, and دیدار's own reports — which the
دیدار importer checks itself against — are built on that number. Writing
billed amounts over it would break that check and destroy the only question
this merge exists to answer: how much of the pipeline actually turned into
invoices.

Three shapes in the source that decide the code:

* **The export carries a totals row.** One row per file with no نوع برگه whose
  amount is the sum of every other row. Read naively it doubles revenue
  exactly, which is the kind of error that looks like a good quarter.
* **Returns already carry their sign.** «مرجوع از فروش» arrives with a
  negative مبلغ فروش, so a plain SUM is net of returns and no report has to
  remember to subtract.
* **Invoice numbers restart each year.** «شماره برگه» repeats across 1404 and
  1405 and even «شماره ثابت سند» is not unique (868 distinct for 1,098 rows).
  The key that is unique on all 1,098 is (نوع برگه, شماره برگه, تاریخ برگه),
  and that is what identifies an invoice here.
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.core import jalali
from apps.crm.jalali import period_for
from apps.crm.matching import fold, name_key
from apps.crm.models import (
    Customer, CustomerExternalRef, Dataset, ExternalSource, Product,
    SalesInvoice, SalesInvoiceItem,
)
from apps.sales.models import DimEmployee, SalesChannel

HEAD_GLOB = "*فروش کل*.xlsx"
LINE_GLOB = "*جزئیات فروش*.xlsx"

KIND = {
    "فاکتور فروش": SalesInvoice.Kind.SALE,
    "مرجوع از فروش": SalesInvoice.Kind.RETURN,
}

#: «مسوول فروش» does not name a person — it names the channel. The two
#: organisational labels are one channel here: SalesChannel.ORGANIZATIONAL is
#: documented as «فروش سازمانی: key-account / بانکی».
CHANNEL = {
    "گروه فروش همکار": SalesChannel.TEAM,
    "گروه فروش بانکی": SalesChannel.ORGANIZATIONAL,
    "گروه فروش سازمانی": SalesChannel.ORGANIZATIONAL,
}

#: A placeholder in the بازاریاب column, not a colleague. 425 of 1,098
#: invoices carry it; mapped to nobody rather than to an invented employee.
NO_REP = "بازاریاب بدون پورسانت"

#: Colleagues whose two spellings no rule can bridge, because it is the name
#: that differs and not its spelling: a different surname in one case, a
#: different given name in the other. Both confirmed by the sales manager as
#: one person. They are written down rather than inferred precisely because a
#: rule loose enough to catch them would also fuse people who merely share a
#: surname.
REP_ALIASES = {
    "محسن بوساک": "پیام بوساک",
    "سارا مسگرقمی": "سارا مسگرچیان",
}


def dec(value) -> Decimal:
    text = re.sub(r"[^\d.\-]", "", str(value or "0"))
    try:
        return Decimal(text or "0")
    except InvalidOperation:
        return Decimal(0)


def jdate(value):
    parts = fold(value).split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
    except ValueError:
        return None
    return jalali.to_gregorian(y, m, d) if y > 1000 else None


class Command(BaseCommand):
    help = "وارد کردن فاکتورهای فروش از نرم‌افزار حسابداری آرپا"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "data" / "arpa"))
        parser.add_argument(
            "--check", action="store_true", help="فقط گزارش بده؛ چیزی ننویس."
        )

    # -- entry -----------------------------------------------------------
    def handle(self, *args, **options):
        directory = Path(options["dir"].rstrip("/\\"))
        heads = self._read_all(directory, HEAD_GLOB)
        lines = self._read_all(directory, LINE_GLOB)
        if not heads:
            self.stdout.write(self.style.WARNING(
                f"هیچ فایل «فروش کل» در «{directory}» نبود — وارد کردن رد شد."
            ))
            return

        # The totals row: no نوع برگه, and an amount equal to every other row
        # added together. Dropped before anything counts it.
        real = [r for r in heads if fold(r.get("نوع برگه"))]
        self.stdout.write(
            f"سربرگ: {len(real)} فاکتور ({len(heads) - len(real)} ردیف جمع حذف شد)"
            f"  |  اقلام: {len(lines)}"
        )

        self._prepare()
        grouped = self._group_lines(lines)
        plan = [(row, self._resolve(row)) for row in real]
        self._report(plan, grouped)

        if options["check"]:
            self.stdout.write(self.style.WARNING("\n--check بود: چیزی نوشته نشد."))
            self._compare(real, written=False)
            return

        with transaction.atomic():
            self._write(plan, grouped)
        self._compare(real, written=True)

    # -- reading ---------------------------------------------------------
    def _read_all(self, directory: Path, pattern: str) -> list[dict]:
        import openpyxl

        out: list[dict] = []
        for path in sorted(directory.glob(pattern)):
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.worksheets[0]
            stream = ws.iter_rows(values_only=True)
            header = [fold(h) for h in next(stream)]
            out.extend(dict(zip(header, r)) for r in stream)
            wb.close()
            self.stdout.write(f"  خوانده شد: {path.name}")
        return out

    @staticmethod
    def _key(kind: str, number: str, date: str) -> tuple[str, str, str]:
        return (kind, number, date)

    def _group_lines(self, lines) -> dict[tuple, list[dict]]:
        """
        Attach every line to its invoice.

        The detail sheet has no نوع برگه; it has «نام برگه» — «فاکتور فروش 1»
        — whose leading words are the document type. Splitting the trailing
        number off is what makes the two sheets joinable.
        """
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        stray = 0
        for row in lines:
            title = fold(row.get("نام برگه"))
            if not title:
                stray += 1  # the detail sheet's own totals row
                continue
            kind = title.rsplit(" ", 1)[0]
            grouped[self._key(
                kind, fold(row.get("شماره برگه")), fold(row.get("تاریخ برگه"))
            )].append(row)
        if stray:
            self.stdout.write(f"  {stray} ردیف بدون «نام برگه» (جمع) رد شد")
        return grouped

    # -- lookups ---------------------------------------------------------
    def _prepare(self) -> None:
        self.customers = {
            external_id: customer_id
            for external_id, customer_id in CustomerExternalRef.objects.filter(
                source=ExternalSource.ARPA, dataset=Dataset.REAL
            ).values_list("external_id", "customer_id")
        }
        self.employees = {
            name_key(e.full_name_fa): e for e in DimEmployee.objects.all()
        }
        self.products = {
            p.code: p for p in Product.objects.filter(dataset=Dataset.REAL)
        }
        self.unknown_reps: dict[str, int] = defaultdict(int)
        self.orphans: list[tuple[str, str, Decimal]] = []

    def _rep(self, name: str):
        """
        آرپا's «بازاریاب» onto a colleague, without inventing one.

        The two files spell the same person differently — «هانیه خواجه منزه»
        against «هانیه منزه», «حامد بهشتی زواره» against «حامد بهشتی» — so an
        equality test loses a third of the invoices' ownership. A name whose
        every word appears in the other is the same person.

        It stops there. «سارا مسگرقمی» and «سارا مسگرچیان» differ in the
        surname, «محسن بوساک» and «پیام بوساک» in the given name; each pair is
        either two people or a typo, and creating a colleague to resolve it
        would put a second row for a real person in the employee list, which
        halves that person's numbers wherever they are reported.
        """
        if not fold(name) or fold(name) == NO_REP:
            return None
        clean = name_key(REP_ALIASES.get(fold(name), name))
        direct = self.employees.get(clean)
        if direct:
            return direct

        words = set(clean.split())
        for other, employee in self.employees.items():
            theirs = set(other.split())
            if theirs and (theirs <= words or words <= theirs):
                return employee

        self.unknown_reps[fold(name)] += 1
        return None

    def _resolve(self, row) -> dict:
        """Everything an invoice needs that is not simply a column."""
        code = fold(row.get("کد طرف حساب"))
        issued = jdate(row.get("تاریخ برگه"))
        return {
            "customer_id": self.customers.get(code),
            "party_code": code,
            "issued_at": issued,
            "kind": KIND.get(fold(row.get("نوع برگه"))),
            "owner": self._rep(row.get("نام بازاریاب")),
            "channel": CHANNEL.get(fold(row.get("مسوول فروش نام")), ""),
        }

    # -- reporting -------------------------------------------------------
    def _report(self, plan, grouped) -> None:
        # Tallied here rather than while writing, so `--check` can state the
        # same reconciliation the real run will produce.
        self.skipped: dict[str, list] = defaultdict(lambda: [0, Decimal(0)])
        for row, meta in plan:
            if meta["customer_id"] and meta["issued_at"] and meta["kind"]:
                continue
            bucket = self.skipped[meta["kind"] or "?"]
            bucket[0] += 1
            bucket[1] += dec(row.get("مبلغ فروش"))

        missing = [(r, m) for r, m in plan if not m["customer_id"]]
        undated = [(r, m) for r, m in plan if not m["issued_at"]]
        no_lines = sum(
            1 for r, m in plan
            if m["kind"] and self._key(
                fold(r.get("نوع برگه")), fold(r.get("شماره برگه")),
                fold(r.get("تاریخ برگه")),
            ) not in grouped
        )
        self.stdout.write(f"\n  فاکتور بدون قلم: {no_lines}")
        if undated:
            self.stdout.write(self.style.ERROR(f"  بدون تاریخ معتبر: {len(undated)}"))

        if missing:
            total = sum(dec(r.get("مبلغ فروش")) for r, _m in missing)
            self.stdout.write(self.style.WARNING(
                f"\n  {len(missing)} فاکتور مشتری‌اش در CRM نیست — "
                f"{total:,.0f} ریال. رد می‌شوند."
            ))
            self.stdout.write(
                "  (طرف‌حساب‌هایی که زیر بازبینی‌اند هنوز شناسه نگرفته‌اند؛ "
                "بعد از بازبینی این دستور را دوباره اجرا کن.)"
            )
            seen = set()
            for row, _m in missing:
                name = fold(row.get("نام طرف حساب"))
                if name in seen or len(seen) >= 6:
                    continue
                seen.add(name)
                self.stdout.write(f"    {name[:44]}")

        if self.unknown_reps:
            self.stdout.write(self.style.WARNING(
                "\n  بازاریاب‌هایی که در فهرست کارمندان نیستند "
                "(فاکتورشان بدون مالک می‌ماند):"
            ))
            for name, n in sorted(
                self.unknown_reps.items(), key=lambda kv: -kv[1]
            ):
                self.stdout.write(f"    {n:>4}  {name}")

    # -- writing ---------------------------------------------------------
    def _write(self, plan, grouped) -> None:
        made = items = skipped = matched = 0
        for row, meta in plan:
            if not meta["customer_id"] or not meta["issued_at"] or not meta["kind"]:
                self.orphans.append((
                    fold(row.get("نام طرف حساب")),
                    fold(row.get("شماره برگه")),
                    dec(row.get("مبلغ فروش")),
                ))
                skipped += 1
                continue

            number = fold(row.get("شماره برگه"))
            key = self._key(
                fold(row.get("نوع برگه")), number, fold(row.get("تاریخ برگه"))
            )
            invoice = SalesInvoice.objects.update_or_create(
                # The invoice number alone repeats across years, so the code
                # carries the date too — «arpa-inv-sale-241-14050524».
                code=self._code(meta["kind"], number, meta["issued_at"]),
                defaults={
                    "number": number[:30],
                    "kind": meta["kind"],
                    "customer_id": meta["customer_id"],
                    "issued_at": meta["issued_at"],
                    "period": period_for(meta["issued_at"]),
                    # مبلغ فروش: net of discount, before VAT, and already
                    # negative on a return.
                    "amount_rial": dec(row.get("مبلغ فروش")),
                    "discount_rial": dec(row.get("تخفیف کل")),
                    "vat_rial": dec(row.get("جمع مالیات و عوارض")),
                    "total_rial": dec(row.get("مبلغ برگه")),
                    "settled_rial": dec(row.get("مبلغ تسویه شده")),
                    "unsettled_rial": dec(row.get("مبلغ تسویه نشده")),
                    "payment_terms": fold(row.get("شرایط تسویه"))[:40],
                    "due_date": jdate(row.get("موعد تسویه")),
                    "grace_date": jdate(row.get("مهلت تسویه")),
                    "shipping_method": fold(row.get("روش حمل"))[:60],
                    "owner": meta["owner"],
                    "created_by_name": fold(row.get("ایجاد کننده"))[:60],
                    "channel": meta["channel"],
                    "branch": fold(row.get("شعبه"))[:60],
                    "tax_ref": fold(row.get("شناسه سامانه مودیان"))[:40],
                    "note": fold(row.get("توضیحات برگه"))[:400],
                },
            )[0]
            made += 1

            # Rewritten wholesale: a corrected export may have fewer lines
            # than the one before it, and updating in place would leave the
            # removed ones behind where they would still be summed.
            invoice.items.all().delete()
            for line in grouped.get(key, ()):
                product = self._product(line)
                matched += product is not None
                SalesInvoiceItem.objects.create(
                    invoice=invoice,
                    product=product,
                    product_code=fold(line.get("کد کالا"))[:40],
                    product_name=fold(line.get("نام کالا"))[:200],
                    quantity=dec(line.get("تعداد")),
                    equivalent=dec(line.get("معادل")),
                    sub_unit=fold(line.get("نام واحد فرعی"))[:20],
                    unit_price_rial=dec(line.get("فی")),
                    amount_rial=dec(line.get("مبلغ")),
                    accounting_group=fold(line.get("گروه حسابداری کالا"))[:40],
                )
                items += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nنوشته شد: {made} فاکتور با {items} قلم "
            f"({matched} قلم به محصول وصل شد)"
            + (f" — {skipped} رد شد" if skipped else "")
        ))

    @staticmethod
    def _code(kind: str, number: str, issued) -> str:
        stamp = "".join(str(p) for p in jalali.from_gregorian(issued))
        return f"arpa-inv-{kind}-{slugify(number) or 'x'}-{stamp}"[:50]

    def _product(self, line):
        """
        آرپا's کد کالا against the catalogue دیدار built.

        Nullable by design: the two catalogues are separate lists that only
        partly overlap, and a line whose product is unknown is still revenue.
        Dropping it — or refusing the invoice — would understate the very
        figure this import exists to establish.
        """
        code = fold(line.get("کد کالا"))
        if not code:
            return None
        return (
            self.products.get(f"pr-{code}")
            or self.products.get(f"pr-{slugify(code, allow_unicode=False)}")
        )

    # -- verification ----------------------------------------------------
    def _compare(self, real, written: bool) -> None:
        """
        Hold the result up against the source file's own arithmetic.

        The failure worth designing against is not a crash — it is an import
        that loads every row and still disagrees in aggregate, because one
        document type was mapped wrong or a totals row slipped through. Only
        this comparison catches that.
        """
        want: dict[str, tuple[int, Decimal]] = {}
        for row in real:
            kind = KIND.get(fold(row.get("نوع برگه")))
            if not kind:
                continue
            count, total = want.get(kind, (0, Decimal(0)))
            want[kind] = (count + 1, total + dec(row.get("مبلغ فروش")))

        # Skipped rows are not a discrepancy — they are a known, counted
        # exclusion, and the check that matters is that source minus skipped
        # lands exactly on the database. Comparing against the raw source
        # instead reports a failure on every run until the review queue is
        # empty, and a check that always cries wolf stops being read.
        self.stdout.write("\nمقایسه با فایل آرپا:")
        ok = True
        for kind, (n_src, v_src) in sorted(want.items()):
            n_skip, v_skip = self.skipped.get(kind, (0, Decimal(0)))
            qs = SalesInvoice.objects.filter(kind=kind, dataset=Dataset.REAL)
            n_db, v_db = qs.count(), sum((i.amount_rial for i in qs), Decimal(0))
            n_want, v_want = n_src - n_skip, v_src - v_skip
            match = "✔" if written and (n_want, v_want) == (n_db, v_db) else (
                "…" if not written else "✗"
            )
            ok = ok and match == "✔"
            note = f" (منهای {n_skip} ردشده)" if n_skip else ""
            self.stdout.write(
                f"  {match} {kind}: فایل {n_src} / {v_src:,.0f}{note}"
                + (f" → انتظار {n_want} / {v_want:,.0f}" if n_skip else "")
                + f" — دیتابیس {n_db} / {v_db:,.0f}"
            )
        if not written:
            return
        total_skipped = sum(v for _n, v in self.skipped.values())
        if ok and total_skipped:
            self.stdout.write(self.style.SUCCESS(
                f"تراز است: هرچه وارد شد با مبدأ می‌خواند، و "
                f"{total_skipped:,.0f} ریال ردشده هم شمرده شده."
            ))
        elif ok:
            self.stdout.write(self.style.SUCCESS("همه‌چیز با مبدأ می‌خواند."))
        else:
            self.stdout.write(self.style.ERROR("اختلاف دارد — بالا را ببینید."))
