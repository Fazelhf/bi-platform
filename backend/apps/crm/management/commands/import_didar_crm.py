"""
Load the company's real CRM out of دیدار and into this one.

Seven workbooks exported from دیدار, plus four of دیدار's own summary reports
which are used as **checksums**: after the import, the figures here have to
agree with the figures the old system printed, per month and per salesperson.
An import that loads without error but disagrees with the source is the
failure mode worth designing against, so it is checked rather than assumed.

    python manage.py import_didar_crm --dir "C:/Users/Asus/Downloads"
    python manage.py import_didar_crm --fresh     # wipe demo rows first
    python manage.py import_didar_crm --check     # verify only, write nothing

Everything is keyed on «کد دیدار», the source system's own id, so the command
is re-runnable: a later export with more columns filled in (استان is empty in
this one) updates the same rows instead of creating a second set.

Two shapes in the source deserve attention:

* **معاملات is one row per product line.** 1,192 rows are 967 deals; the deal's
  own fields repeat on every line. Grouping by کد دیدار معامله is what makes
  «چند معامله داشتیم» answerable.
* **ارزش معامله is authoritative, not derived.** دیدار's reports are built on
  it, and only 766 of 1,192 lines carry a product at all — so recomputing a
  deal's value from its items would quietly zero out a third of the pipeline.
  `Deal.recalculate()` is deliberately never called here.
"""
from __future__ import annotations

import html as _html
import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core import jalali
from apps.crm.jalali import period_for
from apps.crm.models import (
    Activity, Customer, CustomerFeedback, Deal, DealItem, DealStageEvent,
    LeadSource, LostReason, PipelineStage, Product,
    ProductCategory, Tag, Task,
)
from apps.sales.models import DimEmployee

FILES = {
    "companies": "شرکت ها.xlsx",
    "contacts": "اشخاص.xlsx",
    "deals": "معاملات.xlsx",
    "products": "محصولات.xlsx",
    "activities": "فعالیت ها .xlsx",
    "notes": "یاداشت ها.xlsx",
    "cases": "کارت ها.xlsx",
}

STATUS = {"موفق": "won", "ناموفق": "lost", "جاری": "open"}

#: دیدار's activity types onto ours. Anything unrecognised becomes a call —
#: the department's own vocabulary is overwhelmingly «تماس پیگیری» and a
#: mystery type is far more likely to be a call than a meeting.
ACTIVITY_KIND = {
    "تماس پیگیری": "call_out",
    "تماس خروجی": "call_out",
    "تماس ورودی": "call_in",
    "اعلام قیمت": "quote",
    "ارسال نمونه": "sample",
    "جلسه حضوری": "meeting",
    "ارسال پیام": "message",
    "ثبت سفارش": "order",
    "صدور فاکتور": "invoice",
    "پرداخت": "payment",
}
RESULT = {"انجام شده": "success", "انجام نشده": "no_answer"}

#: «برگ» is the only non-roll unit the catalogue actually uses. Left as roll
#: for everything else, which is what a paper mill sells by default.
UNIT = {"رول": "roll", "برگ": "sheet", "بسته": "pack", "تن": "ton"}


def norm(value) -> str:
    """Trim and fold the whitespace دیدار leaves around almost every name."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def plain(value) -> str:
    """
    Strip the HTML دیدار stores its note bodies in.

    Its editor is rich text, so «تماس گرفتم احوال پرسی کردم» arrives as
    `<p>…&nbsp;</p>`. Rendered as text that is what the user reads on the
    activity list, and rendered as HTML it would be an injection point — this
    is other people's typing. Tags out, entities decoded, whitespace folded.
    """
    text = re.sub(r"<br\s*/?>|</p>|</div>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def jdate(value):
    """«1405/03/13» → a date. Returns None for blanks and for anything odd."""
    text = norm(value)
    if not text:
        return None
    parts = re.split(r"[/\-]", text)
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
        return jalali.to_gregorian(y, m, d) if y > 1000 else None
    except (ValueError, TypeError):
        return None


def jaware(value):
    """Same, as an aware datetime — the CRM timestamps are DateTimeFields."""
    day = jdate(value)
    if not day:
        return None
    return timezone.make_aware(datetime.combine(day, time(9, 0)))


def dec(value) -> Decimal:
    text = re.sub(r"[^\d.\-]", "", str(value or "0"))
    try:
        return Decimal(text or "0")
    except InvalidOperation:
        return Decimal(0)


def code_for(prefix: str, value, fallback: str = "") -> str:
    """A stable slug from a دیدار id, or from a name when there is no id."""
    raw = norm(value)
    if raw and raw not in {"0", "None"}:
        return f"{prefix}-{slugify(raw, allow_unicode=False) or raw}"
    return f"{prefix}-{slugify(norm(fallback), allow_unicode=True)[:40] or 'x'}"


#: Every sheet the importer needs. Checked up front so a half-uploaded
#: folder fails with a list of what is missing, rather than a KeyError from
#: somewhere in the middle of the third pass.
REQUIRED_FILES = [
    "شرکت ها.xlsx", "اشخاص.xlsx", "معاملات.xlsx",
    "محصولات.xlsx", "فعالیت ها .xlsx", "یاداشت ها.xlsx", "کارت ها.xlsx",
]


class Command(BaseCommand):
    help = "Import the real CRM data exported from دیدار."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir", default=str(settings.BASE_DIR / "data" / "didar"),
            help="پوشه‌ی خروجی‌های دیدار",
        )
        parser.add_argument(
            "--if-empty", action="store_true",
            help=(
                "اگر داده‌ی واقعی از قبل هست، هیچ کاری نکن. "
                "همین گزینه است که اجرای این دستور در deploy را بی‌خطر می‌کند."
            ),
        )
        parser.add_argument(
            "--fresh", action="store_true",
            help="Delete the generated demo CRM rows before importing.",
        )
        parser.add_argument(
            "--check", action="store_true",
            help="Read and compare against دیدار's reports; write nothing.",
        )

    def handle(self, *args, **options):
        # The guard that makes this safe to call from deploy.sh.
        #
        # Without it, every deploy would re-run a command whose --fresh path
        # deletes every real CRM row — and the moment the sales team starts
        # entering data on the server, that is their work. A one-time load has
        # to be able to tell that it has already happened.
        #
        # «Has it happened» is asked by looking for rows this command wrote,
        # not for rows tagged real. The first version asked the latter and was
        # wrong on every database that already held the generated demo set:
        # the migration that introduced `dataset` defaults it to "real", so
        # the old seed arrived wearing the real label, the guard saw it, and
        # the import silently never ran. Codes are the honest signal — only
        # this command mints «didar-…».
        if options["if_empty"] and self._already_imported():
            self.stdout.write(
                "داده‌ی واقعی CRM از قبل وارد شده است — وارد کردن رد شد."
            )
            return

        self.dir = options["dir"].rstrip("/\\")

        # The export may not be on the server yet — it is uploaded by hand,
        # after the first deploy. Say so and stop, rather than raising: this
        # command runs from deploy.sh under `set -e`, where an exception would
        # abort the deploy before collectstatic and the app restart, leaving
        # the site down for a missing spreadsheet.
        missing = [n for n in REQUIRED_FILES if not Path(self.dir, n).exists()]
        if missing:
            short = "، ".join(missing[:4]) + (" …" if len(missing) > 4 else "")
            self.stdout.write(self.style.WARNING(
                f"فایل‌های دیدار در «{self.dir}» پیدا نشد — وارد کردن رد شد."
            ))
            self.stdout.write(f"  کم است: {short}")
            return
        sheets = self._read_all()
        if options["check"]:
            self._compare(sheets)
            return

        with transaction.atomic():
            if options["fresh"]:
                self._wipe()
            elif options["if_empty"]:
                self._clear_mislabelled()
            self._run(sheets)
        self._compare(sheets)

    @staticmethod
    def _already_imported() -> bool:
        """True only if a previous run of *this* command left rows behind."""
        return Customer.objects.filter(code__startswith="didar-").exists()

    def _clear_mislabelled(self) -> None:
        """
        Drop rows wearing the real label that this command did not write.

        On a database that held the generated demo set before `dataset`
        existed, migration 0004 tagged all of it "real". Those rows are not
        the company's customer file and must not sit in it — but they are also
        indistinguishable from anything typed by hand, so this only runs on
        the first-import path, and it says what it removed.
        """
        stale = Customer.objects.filter(dataset="real").exclude(
            code__startswith="didar-"
        )
        n = stale.count()
        if not n:
            return
        self.stdout.write(self.style.WARNING(
            f"{n} مشتری با برچسب «واقعی» پیدا شد که از دیدار نیامده — "
            "داده‌ی نمونه‌ی قدیمی است و پاک می‌شود."
        ))
        self._wipe()

    # -- reading ---------------------------------------------------------
    def _read_all(self) -> dict:
        import openpyxl

        out: dict[str, list[dict]] = {}
        for key, name in FILES.items():
            path = f"{self.dir}/{name}"
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for ws in wb.worksheets:
                rows = ws.iter_rows(values_only=True)
                header = [norm(h) for h in next(rows)]
                data = [dict(zip(header, r)) for r in rows]
                # یاداشت ها carries a second sheet; keep both under clear names.
                out[key if ws.title != "Note" else "notes_only"] = data
            wb.close()
        self.stdout.write(
            "خوانده شد: " + "، ".join(f"{k}={len(v)}" for k, v in out.items())
        )
        return out

    # -- removal ---------------------------------------------------------
    def _wipe(self) -> None:
        """
        Clear the previously imported real dataset.

        Scoped to `dataset="real"`, so re-importing a fresher export never
        touches the showroom sitting beside it. Everything real goes, including
        the reference lists: دیدار has its own مراحل کاریز and دلایل شکست, and
        keeping a second vocabulary beside them would leave two answers to the
        same question.
        """
        counts = {}
        for model in (
            DealStageEvent, DealItem, Activity, Task, CustomerFeedback,
            Deal, Customer, Product, ProductCategory, PipelineStage,
            LeadSource, LostReason, Tag,
        ):
            counts[model.__name__] = model.objects.filter(
                dataset="real"
            ).delete()[0]
        self.stdout.write(self.style.WARNING(
            "پاک شد: " + "، ".join(f"{k}={v}" for k, v in counts.items() if v)
        ))

    # -- writing ---------------------------------------------------------
    def _run(self, sheets: dict) -> None:
        deals = sheets["deals"]
        self.rebuilt = 0

        stages = self._stages(deals)
        sources = self._sources(deals)
        lost = self._lost(deals)
        employees = self._employees(sheets)
        products = self._products(sheets["products"])
        customers = self._customers(sheets, deals, employees)
        self._deals(deals, customers, employees, stages, sources, lost, products)
        self._activities(sheets, customers, employees)
        self._rollup()

    def _stages(self, deals) -> dict:
        """
        دیدار's own pipeline, in the order the work actually happens.

        Ordering comes from this list rather than from the export, which has
        no column for it — and a pipeline whose stages are alphabetical draws
        a funnel that flows backwards.
        """
        ORDER = [
            "ارتباط مشتری", "ارسال نمونه - اعلام قیمت", "پیگیری تایید",
            "ثبت سفارش در سیستم حسابداری", "اعلام به واحد تولید",
            "پیگیری دریافت بار", "هماهنگی ارسال با مشتری", "صدور فاکتور",
            "تسویه",
        ]
        seen = {norm(r.get("مرحله کاریز معامله")) for r in deals} - {""}
        ranked = [s for s in ORDER if s in seen] + sorted(seen - set(ORDER))
        out = {}
        for i, name in enumerate(ranked, start=1):
            out[name] = PipelineStage.objects.update_or_create(
                code=code_for("st", "", name),
                defaults={
                    "name_fa": name,
                    "order": i,
                    "kind": PipelineStage.Kind.OPEN,
                    "probability_pct": min(95, i * 100 // (len(ranked) + 1)),
                },
            )[0]
        return out

    def _sources(self, deals) -> dict:
        out = {}
        for name in sorted({norm(r.get("شیوه آشنایی معامله")) for r in deals} - {""}):
            out[name] = LeadSource.objects.update_or_create(
                code=code_for("ls", "", name), defaults={"name_fa": name},
            )[0]
        return out

    def _lost(self, deals) -> dict:
        # «قیمت» and «تاخیر در تحویل» are ours to fix; «خرید از رقبا» largely
        # is not. The flag is what makes the lost-reason report actionable
        # rather than a list of excuses.
        CONTROLLABLE = {"قیمت", "تاخیر در تحویل", "عدم کیفیت کالا"}
        out = {}
        for name in sorted({norm(r.get("دلیل شکست معامله")) for r in deals} - {""}):
            out[name] = LostReason.objects.update_or_create(
                code=code_for("lr", "", name),
                defaults={
                    "name_fa": name,
                    "is_controllable": name in CONTROLLABLE,
                },
            )[0]
        return out

    def _employees(self, sheets) -> dict:
        """
        Every name that owns anything, as a DimEmployee.

        Matched against existing rows by name before creating, so the four
        managers who already exist in the platform keep their single row and
        their login rather than gaining a second, account-less twin.
        """
        names: set[str] = set()
        for row in sheets["deals"]:
            names |= {norm(row.get("مسئول معامله")), norm(row.get("ثبت کننده معامله"))}
        for row in sheets["contacts"]:
            names.add(norm(row.get("مسئول مشتری")))
        for row in sheets["companies"]:
            names.add(norm(row.get("مسئول شرکت")))
        names -= {""}

        existing = {norm(e.full_name_fa): e for e in DimEmployee.objects.all()}
        out = {}
        created = 0
        for name in sorted(names):
            employee = existing.get(name)
            if not employee:
                employee = DimEmployee.objects.create(
                    code=code_for("emp", "", name), full_name_fa=name,
                )
                created += 1
            out[name] = employee
        self.stdout.write(f"  کارمند: {len(out)} ({created} تازه)")
        return out

    def _products(self, rows) -> dict:
        """
        Keyed by «کد محصول», which is what the deal lines actually reference.

        The export is at variant grain — 1,316 rows for a much smaller catalogue
        — so rows collapse onto that code and the first price seen wins.
        """
        categories: dict[str, ProductCategory] = {}
        out: dict[str, Product] = {}
        for row in rows:
            key = norm(row.get("کد محصول")) or norm(row.get("کد دیدار محصول"))
            title = norm(row.get("عنوان محصول"))
            if not key or not title or key in out:
                continue
            group = norm(row.get("گروه محصول")) or "بدون گروه"
            if group not in categories:
                categories[group] = ProductCategory.objects.update_or_create(
                    code=code_for("pc", "", group), defaults={"name_fa": group},
                )[0]
            out[key] = Product.objects.update_or_create(
                code=code_for("pr", key),
                defaults={
                    "name_fa": title,
                    "category": categories[group],
                    "unit": UNIT.get(norm(row.get("واحد محصول")), "roll"),
                    "list_price_rial": dec(row.get("قیمت هر واحد محصول")),
                    "is_active": norm(row.get("فعال/غیر فعال")) != "غیر فعال",
                },
            )[0]
        self.stdout.write(f"  محصول: {len(out)} در {len(categories)} گروه")
        return out

    def _customers(self, sheets, deals, employees) -> dict:
        """
        دیدار keeps شرکت and شخص apart; this CRM keeps one account per customer.

        A person attached to a company becomes that company's contact rather
        than a customer of their own — otherwise the same account appears
        twice and every per-customer figure is split between the two. A person
        with no company is a customer in their own right, which is most of
        this list.

        Returns a lookup keyed by both «کد دیدار شرکت» and «کد دیدار مشتری»,
        because a deal may name either.
        """
        earliest = self._first_deal_dates(deals)
        by_company: dict[str, Customer] = {}
        by_person: dict[str, Customer] = {}

        for row in sheets["companies"]:
            did = norm(row.get("کد دیدار شرکت"))
            name = norm(row.get("نام شرکت"))
            if not did or not name:
                continue
            code = code_for("didar-co", did)
            by_company[did] = Customer.objects.update_or_create(
                code=code,
                defaults={
                    "name_fa": name,
                    "kind": Customer.Kind.COMPANY,
                    "phone": norm(row.get("تلفن شرکت")),
                    "email": norm(row.get("ایمیل شرکت"))[:254],
                    "address": norm(row.get("آدرس"))[:400],
                    "national_id": norm(row.get("شناسه ملی"))[:20],
                    "city": norm(row.get("شهرستان"))[:100],
                    "owner": employees.get(norm(row.get("مسئول شرکت"))),
                    "note": plain(row.get("توضیحات شرکت")),
                    "first_contact_at": (
                        jaware(row.get("تاریخ ثبت شرکت"))
                        or earliest.get(("co", did))
                        or timezone.now()
                    ),
                },
            )[0]

        for row in sheets["contacts"]:
            did = norm(row.get("کد دیدار مشتری"))
            company_did = norm(row.get("کد دیدار شرکت"))
            full = norm(f"{row.get('نام مشتری') or ''} {row.get('نام خانوادگی مشتری') or ''}")
            if not did or not full:
                continue
            mobile = norm(row.get("تلفن همراه مشتری"))
            parent = by_company.get(company_did) if company_did not in ("", "0") else None
            if parent:
                # Fold into the company: the person is how you reach it.
                if not parent.contact_name:
                    parent.contact_name = full
                    parent.mobile = mobile
                    parent.save(update_fields=["contact_name", "mobile", "updated_at"])
                by_person[did] = parent
                continue
            by_person[did] = Customer.objects.update_or_create(
                code=code_for("didar-pe", did),
                defaults={
                    "name_fa": full,
                    "kind": Customer.Kind.PERSON,
                    "contact_name": full,
                    "mobile": mobile,
                    "phone": norm(row.get("تلفن ثابت مشتری")),
                    "email": norm(row.get("ایمیل مشتری"))[:254],
                    "national_id": norm(row.get("کد ملی مشتری"))[:20],
                    "city": norm(row.get("شهرستان"))[:100],
                    "owner": employees.get(norm(row.get("مسئول مشتری"))),
                    "note": plain(row.get("توضیحات شخص")),
                    "first_contact_at": (
                        jaware(row.get("تاریخ ثبت مشتری"))
                        or earliest.get(("pe", did))
                        or timezone.now()
                    ),
                },
            )[0]

        merged = sum(1 for c in by_person.values() if c.kind == Customer.Kind.COMPANY)
        self.stdout.write(
            f"  مشتری: {len(by_company)} شرکت + {len(by_person) - merged} شخص مستقل "
            f"({merged} شخص در شرکتشان ادغام شد)"
        )
        return {"co": by_company, "pe": by_person}

    def _from_deal_name(self, head, customers):
        """
        Rescue a deal whose counterparty is named but missing from the masters.

        دیدار lets a company be deleted while its deals keep pointing at the
        id, so «هایپر مارکت ماف پارس» arrives with a code that is in no export.
        The deal still carries the name, and dropping the row would silently
        lose a real (if lost) deal — so the customer is recreated from what
        the deal itself says, and flagged in its note as reconstructed.
        """
        name = norm(head.get("شرکت معامله")) or norm(
            f"{head.get('نام شخص معامله') or ''} {head.get('نام خانوادگی شخص معامله') or ''}"
        )
        if not name:
            return None
        did = norm(head.get("کد دیدار شرکت معامله")) or norm(
            head.get("کد دیدار شخص معامله")
        )
        is_company = bool(norm(head.get("شرکت معامله")))
        customer = Customer.objects.update_or_create(
            code=code_for("didar-x", did, name),
            defaults={
                "name_fa": name,
                "kind": Customer.Kind.COMPANY if is_company else Customer.Kind.PERSON,
                "mobile": norm(head.get("موبایل شخص معامله")),
                "phone": norm(head.get("شماره تلفن شرکت")),
                "note": "از روی معامله بازسازی شد — در فهرست اصلی دیدار نبود.",
                "first_contact_at": (
                    jaware(head.get("تاریخ ایجاد معامله")) or timezone.now()
                ),
            },
        )[0]
        bucket = "co" if is_company else "pe"
        if did:
            customers[bucket][did] = customer
        self.rebuilt += 1
        return customer

    @staticmethod
    def _first_deal_dates(deals) -> dict:
        """When each party first appears, for customers with no ثبت date."""
        out: dict[tuple[str, str], object] = {}
        for row in deals:
            at = jaware(row.get("تاریخ ایجاد معامله"))
            if not at:
                continue
            for prefix, col in (("pe", "کد دیدار شخص معامله"), ("co", "کد دیدار شرکت معامله")):
                key = (prefix, norm(row.get(col)))
                if key[1] in ("", "0"):
                    continue
                if key not in out or at < out[key]:
                    out[key] = at
        return out

    def _deals(self, rows, customers, employees, stages, sources, lost, products):
        """One Deal per کد دیدار معامله; every line with a product becomes an item."""
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            did = norm(row.get("کد دیدار معامله"))
            if did:
                grouped[did].append(row)

        made = items = orphan = 0
        for did, lines in grouped.items():
            head = lines[0]
            customer = (
                customers["pe"].get(norm(head.get("کد دیدار شخص معامله")))
                or customers["co"].get(norm(head.get("کد دیدار شرکت معامله")))
                or self._from_deal_name(head, customers)
            )
            if not customer:
                orphan += 1
                continue
            opened = jaware(head.get("تاریخ ایجاد معامله")) or timezone.now()
            closed = jaware(head.get("تاریخ انجام معامله"))
            status = STATUS.get(norm(head.get("وضعیت معامله")), "open")
            deal = Deal.objects.update_or_create(
                code=code_for("didar-d", did),
                defaults={
                    "title": norm(head.get("عنوان معامله")) or f"معامله {did}",
                    "customer": customer,
                    "owner": employees.get(norm(head.get("مسئول معامله"))),
                    "stage": stages.get(norm(head.get("مرحله کاریز معامله"))),
                    "status": status,
                    "lead_source": sources.get(norm(head.get("شیوه آشنایی معامله"))),
                    "lost_reason": lost.get(norm(head.get("دلیل شکست معامله"))),
                    "lost_note": plain(head.get("یادداشت شکست معامله"))[:400],
                    # Straight from دیدار, never recomputed from the items —
                    # a third of the deals have no item at all.
                    "amount_rial": dec(head.get("ارزش معامله")),
                    "opened_at": opened,
                    "closed_at": closed,
                    # Both periods, deliberately: «فرصت‌های جدید» counts the
                    # month a deal was opened and «فروش موفق» the month it was
                    # won, and a single period would silently merge the two.
                    "period": period_for(opened),
                    "close_period": period_for(closed) if closed else None,
                    "expected_close_date": jdate(head.get("تاریخ احتمالی انجام معامله")),
                },
            )[0]
            made += 1

            deal.items.all().delete()
            for line in lines:
                key = norm(line.get("کد محصول"))
                title = norm(line.get("عنوان محصول"))
                if not title:
                    continue
                DealItem.objects.create(
                    deal=deal,
                    product=products.get(key),
                    quantity=dec(line.get("تعداد محصول")) or Decimal(1),
                    unit_price_rial=dec(line.get("قیمت")),
                )
                items += 1

        self.stdout.write(
            f"  معامله: {made} با {items} قلم"
            + (f" — {self.rebuilt} مشتری از روی معامله بازسازی شد" if self.rebuilt else "")
            + (f" — {orphan} بدون مشتری رد شد" if orphan else "")
        )

    def _activities(self, sheets, customers, employees):
        """
        Calls, meetings and the rest. Notes join them as «پیام».

        An activity that was planned and **not** carried out is a Task, not an
        Activity: it is work still owed, and counting it among the calls that
        happened would inflate every activity figure by the ones nobody made.
        دیدار keeps both in one table with a وضعیت column; they part here.

        An activity has to belong to a customer, so the ones whose person and
        company are both unknown are counted and skipped rather than attached
        to something arbitrary.
        """
        deals = {d.code: d for d in Deal.objects.all()}
        rows = list(sheets.get("activities", []))
        notes = [
            {**n, "نوع فعالیت": "ارسال پیام",
             "متن فعالیت": n.get("یادداشت"),
             "تاریخ انجام شدن فعالیت": n.get("تاریخ برنامه ریزی یادداشت"),
             "اشخاص فعالیت": n.get("اشخاص یادداشت"),
             "کد اشخاص فعالیت": n.get("کد اشخاص یادداشت"),
             "کد شرکت های فعالیت": n.get("کد شرکت های یادداشت"),
             "کد معامله فعالیت": n.get("کد معامله یادداشت"),
             "مسئول اجرا فعالیت": n.get("ثبت کننده یادداشت"),
             "وضعیت اجرای فعالیت": "انجام شده"}
            for n in sheets.get("notes_only", [])
        ]

        made = tasks = skipped = 0
        for row in rows + notes:
            customer = (
                customers["pe"].get(norm(row.get("کد اشخاص فعالیت")))
                or customers["co"].get(norm(row.get("کد شرکت های فعالیت")))
            )
            planned = jaware(row.get("تاریخ برنامه ریزی شده اجرا فعالیت"))
            at = jaware(row.get("تاریخ انجام شدن فعالیت")) or planned
            if not customer or not at:
                skipped += 1
                continue
            kind = ACTIVITY_KIND.get(norm(row.get("نوع فعالیت")), "call_out")
            owner = employees.get(norm(row.get("مسئول اجرا فعالیت")))
            deal = deals.get(code_for("didar-d", norm(row.get("کد معامله فعالیت"))))
            title = plain(row.get("عنوان فعالیت"))
            body = plain(row.get("متن فعالیت"))
            # A title that only repeats the activity type tells the reader
            # nothing, so it is not worth keeping as the note.
            text = (body or (title if title != norm(row.get("نوع فعالیت")) else ""))[:2000]

            if norm(row.get("وضعیت اجرای فعالیت")) == "انجام نشده":
                Task.objects.create(
                    title=plain(row.get("عنوان فعالیت"))[:200] or "پیگیری",
                    customer=customer, deal=deal, owner=owner, kind=kind,
                    due_at=planned or at, note=text,
                )
                tasks += 1
                continue

            Activity.objects.create(
                kind=kind, customer=customer, deal=deal, owner=owner, at=at,
                result=RESULT.get(norm(row.get("وضعیت اجرای فعالیت")), ""),
                note=text,
                period=period_for(at),
            )
            made += 1

        self._cases(sheets, customers, employees)
        self.stdout.write(
            f"  فعالیت: {made} انجام‌شده + {tasks} کار باز"
            + (f" — {skipped} بدون مشتری یا تاریخ رد شد" if skipped else "")
        )

    def _cases(self, sheets, customers, employees):
        """کارت‌ها — دیدار's support cases. Seven rows, imported as tasks."""
        made = 0
        for row in sheets.get("cases", []):
            customer = customers["pe"].get(norm(row.get("کد دیدار شخص")))
            at = jaware(row.get("تاریخ انجام کارت")) or jaware(row.get("تاریخ ثبت کارت"))
            title = norm(row.get("عنوان کارت"))
            if not customer or not at or not title:
                continue
            Task.objects.create(
                title=plain(title)[:200], customer=customer,
                owner=employees.get(norm(row.get("مسئول کارت"))),
                due_at=at,
                done_at=at if norm(row.get("وضعیت کارت")) not in ("", "باز") else None,
                note=plain(row.get("توضیحات کارت"))[:2000],
            )
            made += 1
        if made:
            self.stdout.write(f"  کارت: {made}")

    def _rollup(self) -> None:
        """
        Fill the per-customer figures that are facts *about* the deals rather
        than fields in any export.

        دیدار has no «وضعیت مشتری» column: it knows who bought and when, and
        leaves the label to whoever reads it. Deriving it here rather than
        leaving all two thousand accounts as «سرنخ» is the difference between
        a customer list that can be segmented and one that cannot — and every
        input to the rule is in the data, so nothing is invented.

        * a won deal, and something happening in the last six months → فعال
        * a won deal, but silent since then → راکد
        * asked, never bought → سرنخ

        The window is counted from the newest activity in the file, not from
        today: this is an export with an end date, and judging it against a
        clock that keeps moving would mark the whole book راکد a year from now.
        """
        from django.db.models import Max, Min

        latest = Activity.objects.aggregate(m=Max("at"))["m"] or timezone.now()
        cutoff = latest - timedelta(days=182)

        won = dict(
            Deal.objects.filter(status="won", closed_at__isnull=False)
            .values("customer_id").annotate(first=Min("closed_at"))
            .values_list("customer_id", "first")
        )
        seen = dict(
            Activity.objects.values("customer_id").annotate(last=Max("at"))
            .values_list("customer_id", "last")
        )
        # The customer's own lead source is the one on their earliest deal —
        # how this relationship began, not how the newest deal was found.
        source = {}
        for deal in Deal.objects.exclude(lead_source=None).order_by("-opened_at"):
            source[deal.customer_id] = deal.lead_source_id

        updated = []
        for customer in Customer.objects.all():
            first_won = won.get(customer.pk)
            last_seen = seen.get(customer.pk)
            customer.first_deal_won_at = first_won
            customer.last_activity_at = last_seen
            customer.lead_source_id = source.get(customer.pk)
            if first_won:
                recent = max(filter(None, [last_seen, first_won]))
                customer.status = (
                    Customer.Status.ACTIVE if recent >= cutoff
                    else Customer.Status.DORMANT
                )
            else:
                customer.status = Customer.Status.LEAD
            updated.append(customer)
        Customer.objects.bulk_update(
            updated,
            ["first_deal_won_at", "last_activity_at", "lead_source", "status"],
            batch_size=500,
        )
        counts = {}
        for c in updated:
            counts[c.status] = counts.get(c.status, 0) + 1
        self.stdout.write(
            "  وضعیت مشتری: " + "، ".join(f"{k}={v}" for k, v in counts.items())
        )

    # -- verification ----------------------------------------------------
    def _compare(self, sheets) -> None:
        """
        Hold the result up against دیدار's own per-status totals.

        This is the check that matters: the import can succeed at every row
        and still be wrong in aggregate — a dropped deal, a status mapped the
        wrong way — and only a comparison against the source's own arithmetic
        catches it.
        """
        want: dict[str, tuple[int, Decimal]] = {}
        seen: set[str] = set()
        for row in sheets["deals"]:
            did = norm(row.get("کد دیدار معامله"))
            if not did or did in seen:
                continue
            seen.add(did)
            key = STATUS.get(norm(row.get("وضعیت معامله")), "open")
            count, total = want.get(key, (0, Decimal(0)))
            want[key] = (count + 1, total + dec(row.get("ارزش معامله")))

        self.stdout.write("\nمقایسه با فایل دیدار:")
        ok = True
        for status in ("won", "lost", "open"):
            n_src, v_src = want.get(status, (0, Decimal(0)))
            qs = Deal.objects.filter(status=status)
            n_db = qs.count()
            v_db = sum((d.amount_rial for d in qs), Decimal(0))
            match = "✔" if (n_src, v_src) == (n_db, v_db) else "✗"
            ok = ok and match == "✔"
            self.stdout.write(
                f"  {match} {status}: فایل {n_src} / {v_src:,.0f} — "
                f"دیتابیس {n_db} / {v_db:,.0f}"
            )
        self.stdout.write(
            self.style.SUCCESS("همه‌چیز با مبدأ می‌خواند.") if ok
            else self.style.ERROR("اختلاف دارد — بالا را ببینید.")
        )
