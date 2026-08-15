"""
Bring the accounting system's party list into the CRM customer file.

    python manage.py import_arpa_parties --dir "C:/Users/Asus/Downloads" --check
    python manage.py import_arpa_parties --dir "C:/Users/Asus/Downloads"

The customer file already exists — it came out of دیدار — so this is a merge,
not a load. What matters is that it *cannot silently fuse two customers*: a
wrong merge joins two companies' order histories into one and nothing on any
screen looks wrong afterwards. So only the tiers in `matching.AUTO` are
written, and everything weaker is filed as a CustomerMatchCandidate for a
person to accept or reject.

Two facts about the source shape the run:

* **The party list belongs to a group of companies, not to this one.** 3,498
  parties across 16 گروه, of which «آرال رول آریا تهران» is a sister firm's
  customer file — 1,495 parties and, checked against 1404's invoices, not one
  Rial of sales here. Excluded.
* **The sister company also appears as a customer of ours.** «شرکت آرال رول
  آریا - فی ما بین» sits in گروه «نمابر مهر سایر مشتریان», not in the آرال
  group, and billed 417bn Rial in 1404. Excluding by group would miss it, so
  it is flagged rather than dropped: real invoices, but not the sales team's
  work and not part of any target.

دیدار's name for a customer is left alone. The sales team knows accounts by
the name on their own screen, and a silent rename mid-quarter is its own kind
of data loss — آرپا's legal name is kept on the external ref instead.
"""
from __future__ import annotations


from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.crm.matching import CustomerIndex, Method, fold
from apps.crm.models import (
    Customer, CustomerExternalRef, CustomerMatchCandidate, Dataset,
    ExternalSource,
)
from apps.crm.party_sync import PartyWriter

FILE = "اشخاص کلی.xlsx"

#: A sister company's own customer file. Verified against 1404's invoices:
#: zero sales from this group, so nothing is lost by leaving it out.
EXCLUDED_GROUPS = frozenset({"آرال رول آریا تهران"})

#: Sister-company accounts, wherever they are filed. They do buy from us and
#: the invoices are real, so they are imported — flagged, so that no target,
#: conversion rate or per-rep figure counts them as sales work.




class Command(BaseCommand):
    help = "وارد کردن فهرست طرف‌حساب‌های نرم‌افزار حسابداری آرپا و تطبیق با مشتریان موجود"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "data" / "arpa"))
        parser.add_argument(
            "--check", action="store_true",
            help="فقط گزارش بده؛ چیزی ننویس.",
        )
        parser.add_argument(
            "--only-with-sales", action="store_true",
            help=(
                "فقط طرف‌حساب‌هایی که در فایل فروش فاکتور دارند. "
                "بدون این، کل فهرست (منهای آرال) وارد می‌شود."
            ),
        )

    # -- entry -----------------------------------------------------------
    def handle(self, *args, **options):
        self.check_only = options["check"]
        path = Path(options["dir"].rstrip("/\\"), FILE)
        if not path.exists():
            self.stdout.write(self.style.WARNING(
                f"فایل «{FILE}» در «{options['dir']}» پیدا نشد — وارد کردن رد شد."
            ))
            return

        rows = self._read(path)
        # Always known, whether or not it filters: the count of parties that
        # have never traded is the number the caller needs to see before
        # agreeing to import them.
        self.with_sales = self._codes_with_sales(options["dir"])
        keep, dropped = self._filter(rows, options)
        self.stdout.write(
            f"طرف‌حساب: {len(rows)} خوانده شد، {len(keep)} می‌ماند "
            f"({dropped} کنار گذاشته شد)"
        )

        # A party waiting on a reviewer is not available for the ladder to
        # decide. Without this hold the queue is advisory: run one files
        # «بانک صادرات کرمانشاه» for review, run two finds a rung that
        # answers and merges it anyway, and the reviewer's screen empties by
        # itself. Which decision was taken, and by what, becomes unknowable.
        self.pending = set(
            CustomerMatchCandidate.objects.filter(
                source=ExternalSource.ARPA,
                state=CustomerMatchCandidate.State.PENDING,
            ).values_list("external_id", flat=True)
        )

        index = self._index()
        plan = [(row, index.find(**self._keys(row))) for row in keep]
        self._summarise(plan, index)

        if self.check_only:
            self.stdout.write(self.style.WARNING(
                "\n--check بود: چیزی نوشته نشد."
            ))
            return

        with transaction.atomic():
            self._apply(plan, index)

    # -- reading ---------------------------------------------------------
    def _read(self, path: Path) -> list[dict]:
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        stream = ws.iter_rows(values_only=True)
        header = [fold(h) for h in next(stream)]
        rows = [dict(zip(header, r)) for r in stream]
        wb.close()
        return rows

    def _filter(self, rows, options) -> tuple[list[dict], int]:
        """Drop the sister firm's own book, and rows with nothing to key on."""
        wanted = self.with_sales if options["only_with_sales"] else None
        keep = []
        for row in rows:
            code, name = fold(row.get("کد")), fold(row.get("نام"))
            if not code or not name:
                continue
            # The group says whose book a party is filed in; an invoice from
            # our branch says whose customer it is. When they disagree the
            # invoice wins — «فروشگاه مثلث», «پور مسگری» and four others are
            # ordinary customers of ours that the shared ledger happens to
            # file under the sister firm, and excluding them by group alone
            # silently dropped 60.6bn Rial of 1405 sales.
            if (
                fold(row.get("نام گروه")) in EXCLUDED_GROUPS
                and code not in self.with_sales
            ):
                continue
            if wanted is not None and code not in wanted:
                continue
            keep.append(row)
        return keep, len(rows) - len(keep)

    def _codes_with_sales(self, directory: str) -> set[str]:
        """Party codes that appear on any invoice file sitting beside this one."""
        codes: set[str] = set()
        for path in sorted(Path(directory).glob("*.xlsx")):
            if "فروش کل" not in path.name:
                continue
            for row in self._read(path):
                code = fold(row.get("کد طرف حساب"))
                if code:
                    codes.add(code)
        self.stdout.write(f"  کد دارای فاکتور: {len(codes)}")
        return codes

    # -- the existing customer file --------------------------------------
    def _index(self) -> CustomerIndex:
        index = CustomerIndex()
        for pk, name, nid, eco, phone, mobile in Customer.objects.filter(
            dataset=Dataset.REAL, merged_into__isnull=True
        ).values_list(
            "pk", "name_fa", "national_id", "economic_code", "phone", "mobile"
        ):
            index.add(pk, name=name, nids=(nid, eco), phones=(phone, mobile))
        for source, external_id, customer_id in CustomerExternalRef.objects.filter(
            dataset=Dataset.REAL
        ).values_list("source", "external_id", "customer_id"):
            index.add_ref(source, external_id, customer_id)
        self.stdout.write(
            f"  مشتری موجود: {len(index.names)}  "
            f"(شناسه مبدأ: {len(index.by_ref)})"
        )
        return index

    @staticmethod
    def _keys(row) -> dict:
        return {
            "source": ExternalSource.ARPA,
            "external_id": fold(row.get("کد")),
            "name": fold(row.get("نام")),
            "nids": (row.get("شناسه ملی"), row.get("کد ملی"), row.get("کد اقتصادی")),
            "phones": (row.get("شماره تلفن"), row.get("موبایل")),
        }

    # -- reporting -------------------------------------------------------
    def _summarise(self, plan, index) -> None:
        tally: dict[str, int] = {}
        for _row, match in plan:
            tally[match.method] = tally.get(match.method, 0) + 1
        labels = {
            Method.EXISTING: "از قبل وصل بود",
            Method.NATIONAL_ID: "شناسه ملی — ادغام خودکار",
            Method.BRANCH: "شناسه ملی یکسان ولی شعبه‌ی دیگر — بازبینی",
            Method.NAME: "نام یکسان — ادغام خودکار",
            Method.AMBIGUOUS: "نام یکسان ولی چند مشتری — تکراری در خود CRM",
            Method.PHONE: "تلفن — نیازمند بازبینی",
            Method.FUZZY: "نام مشابه — نیازمند بازبینی",
            Method.NONE: "بی‌جفت — مشتری تازه",
        }
        self.stdout.write("\nنتیجه تطبیق:")
        for method, label in labels.items():
            if tally.get(method):
                self.stdout.write(f"  {tally[method]:>5}  {label}")

        # How many of the would-be new customers have ever actually bought.
        # The party list is a whole group's ledger and most of it has no
        # trading history here; adding 1,700 accounts nobody has sold to is a
        # decision, not a detail, so it is stated rather than performed.
        never = sum(
            1 for row, m in plan
            if m.method == Method.NONE and fold(row.get("کد")) not in self.with_sales
        )
        if never:
            self.stdout.write(
                f"\n  از این‌ها {never} مورد در هیچ فایل فروشی فاکتور ندارند."
                "\n  اگر نمی‌خواهی وارد شوند: --only-with-sales"
            )

        self.stdout.write("\nنمونه‌ی مواردی که به بازبینی می‌روند:")
        shown = 0
        for row, match in plan:
            if match.is_auto or not match.found or shown >= 8:
                continue
            self.stdout.write(
                f"  [{match.method} {match.score:.2f}] "
                f"{fold(row.get('نام'))[:34]:<34} ≟ {index.names.get(match.customer_id, '')[:34]}"
            )
            shown += 1

    # -- writing ---------------------------------------------------------
    def _apply(self, plan, index) -> None:
        # One writer, shared with the review screen: which fields
        # accounting owns is decided in exactly one place.
        self.writer = PartyWriter(self.with_sales)
        created = updated = queued = flagged = held = 0
        self.dormant = 0

        for row, match in plan:
            if fold(row.get("کد")) in self.pending:
                held += 1
                continue
            if match.is_auto and match.found:
                customer = Customer.objects.get(pk=match.customer_id)
                self.writer.apply(customer, row)
                updated += 1
            elif match.found:
                # A suggestion, not a decision. The party is not written into
                # the customer file at all until someone rules on it —
                # creating it now would put a duplicate in front of every user
                # for as long as the queue sits unreviewed.
                self._queue(row, match)
                queued += 1
                continue
            else:
                customer = self.writer.create(row)
                self.dormant += not customer.is_active
                created += 1

            self.writer.link(customer, row)
            if customer.is_intercompany:
                flagged += 1
            index.add_ref(ExternalSource.ARPA, fold(row.get("کد")), customer.pk)

        self.stdout.write(self.style.SUCCESS(
            f"\nنوشته شد: {created} مشتری تازه ({self.dormant} غیرفعال، "
            f"بدون فاکتور در فایل‌های موجود)، {updated} به‌روزرسانی، "
            f"{queued} در صف بازبینی، {flagged} برچسب فی‌مابین"
            + (f"، {held} دست‌نخورده چون زیر بازبینی است" if held else "")
        ))






    def _queue(self, row, match) -> None:
        CustomerMatchCandidate.objects.update_or_create(
            source=ExternalSource.ARPA,
            external_id=fold(row.get("کد"))[:64],
            customer_id=match.customer_id,
            defaults={
                "external_name": fold(row.get("نام"))[:200],
                "external_phone": fold(row.get("شماره تلفن"))[:40],
                "external_city": fold(row.get("شهر"))[:100],
                "method": match.method,
                "score": round(match.score, 4),
                # The whole row: the review screen needs address, group and
                # ids to judge, and re-opening the workbook to get them would
                # tie the screen to a file sitting on someone's laptop.
                "payload": {k: fold(v) for k, v in row.items() if fold(v)},
            },
        )
