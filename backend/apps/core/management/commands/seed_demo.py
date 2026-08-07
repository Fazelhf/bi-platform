"""
Fill مالی and بازرگانی with believable figures, for showing the platform to
people who have not used it yet.

A command, never a data migration — `deploy.sh` runs migrations by itself, and
inventing money on the CEO's dashboard is not something that should happen as a
side effect of deploying. Run it deliberately, on a demo database.

    python manage.py seed_demo                  # 8 months back from مرداد ۱۴۰۵
    python manage.py seed_demo --months 12
    python manage.py seed_demo --accounts 14
    python manage.py seed_demo --clear          # remove exactly what it added

Everything it writes is tagged (movements and records carry a marker in their
note), so --clear takes its own rows back out and leaves anything real alone.
The figures come from a seeded Random, so two runs of the same command produce
the same demo — a screenshot taken today still matches the screen tomorrow.

It reuses the reference data already in the database (cash categories, material
categories, quote reasons) rather than inventing its own, so the demo exercises
the real lists that the forms offer.
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.commercial.models import (
    Material,
    MaterialCategory,
    MaterialUnit,
    PurchaseOrder,
    PurchaseRequest,
    Quote,
    QuoteReason,
    Supplier,
)
from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import ensure_days, ensure_weeks
from apps.finance.models import (
    BankAccount,
    CashCategory,
    CashMovement,
    CreditLine,
    Direction,
    FinanceSetting,
)
from apps.sales.models import ApprovalStatus

# Every row this command creates carries this in a text field, which is how
# --clear finds them again without touching anything a person entered.
MARK = "[دمو]"

# --- Banks --------------------------------------------------------------
# Real bank names, invented accounts. Ordered so the first few are the ones a
# demo is most likely to click on.
BANKS = [
    ("جاری ملت — حساب اصلی", "بانک ملت", "bank", 48_500_000_000, "#2563eb"),
    ("جاری صادرات", "بانک صادرات", "bank", 21_300_000_000, "#0891b2"),
    ("جاری تجارت", "بانک تجارت", "bank", 16_750_000_000, "#7c3aed"),
    ("جاری سپه", "بانک سپه", "bank", 12_400_000_000, "#059669"),
    ("جاری پاسارگاد", "بانک پاسارگاد", "bank", 9_800_000_000, "#c2410c"),
    ("جاری سامان", "بانک سامان", "bank", 7_250_000_000, "#0284c7"),
    ("جاری پارسیان", "بانک پارسیان", "bank", 5_600_000_000, "#be123c"),
    ("جاری کشاورزی", "بانک کشاورزی", "bank", 4_150_000_000, "#15803d"),
    ("جاری ملی", "بانک ملی ایران", "bank", 18_900_000_000, "#1d4ed8"),
    ("جاری رفاه کارگران", "بانک رفاه", "bank", 3_300_000_000, "#7e22ce"),
    ("سپرده کوتاه‌مدت ملت", "بانک ملت", "bank", 65_000_000_000, "#1e40af"),
    ("صندوق مرکزی", "", "cash", 2_100_000_000, "#a16207"),
    ("تنخواه اداری", "", "petty", 480_000_000, "#ca8a04"),
    ("تنخواه کارخانه", "", "petty", 720_000_000, "#a3620a"),
]

CREDIT_LINES = [
    ("facility", "تسهیلات سرمایه در گردش — ملت", "بانک ملت", 40_000_000_000, 23, "active", 12),
    ("facility", "تسهیلات خرید دستگاه — صادرات", "بانک صادرات", 25_000_000_000, 21, "active", 24),
    ("facility", "اعتبار اسنادی داخلی — تجارت", "بانک تجارت", 15_000_000_000, 18, "settled", 6),
    ("facility", "وام مضاربه — سپه", "بانک سپه", 8_000_000_000, 20, "overdue", 9),
    ("lending", "قرض‌الحسنه به شرکت آریا پلیمر", "آریا پلیمر", 3_000_000_000, 0, "active", 6),
    ("lending", "مساعده به پیمانکار نصب", "مهندسی فرآیند نو", 1_200_000_000, 0, "settled", 3),
    ("partner", "جاری شریک — آقای عصاری", "امیر عصاری", 12_000_000_000, 0, "active", 0),
    ("partner", "جاری شریک — آقای سیفی", "رضا سیفی", 7_500_000_000, 0, "active", 0),
]

# --- Suppliers and materials -------------------------------------------
SUPPLIERS = [
    ("پتروشیمی جم", "مهدی رستمی", "مواد اولیه پلیمری"),
    ("کاغذسازی لطیف", "سعید کاظمی", "کاغذ و مقوا"),
    ("چسب سازان البرز", "حمید نوروزی", "چسب صنعتی"),
    ("جوهر و مرکب پارس", "الهام صادقی", "مرکب چاپ"),
    ("فیلم پلاست تهران", "کاوه امینی", "فیلم بسته‌بندی"),
    ("یدک ماشین صنعت", "بهروز کریمی", "قطعات یدکی ماشین‌آلات"),
    ("الکترو تابان", "نازنین فتحی", "تجهیزات برق صنعتی"),
    ("روغن صنعتی ایرانول", "جواد مقصودی", "روانکار و روغن"),
    ("پالت چوب شمال", "اکبر رحیمی", "پالت و بسته‌بندی چوبی"),
    ("نوار و چسب کاوه", "مریم دهقان", "نوار چسب"),
    ("ابزار دقیق راد", "فرهاد یزدانی", "ابزار دقیق و کالیبراسیون"),
    ("لوازم اداری مهر", "شیما براتی", "ملزومات اداری"),
    ("ایمنی کار پویا", "رسول احمدی", "تجهیزات ایمنی"),
    ("حمل و نقل بارثاب", "علی موحد", "حمل و نقل"),
]

MATERIALS = [
    ("رزین پلی‌اتیلن گرید فیلم", "raw-material", "kg", 4000),
    ("رزین پلی‌پروپیلن", "raw-material", "kg", 3000),
    ("مستربچ سفید", "raw-material", "kg", 800),
    ("مستربچ مشکی", "raw-material", "kg", 600),
    ("کاغذ حرارتی رول ۸۰", "raw-material", "roll", 500),
    ("مقوا پشت طوسی ۳۰۰ گرم", "raw-material", "kg", 2500),
    ("چسب هات‌ملت", "raw-material", "kg", 400),
    ("مرکب چاپ فلکسو — مشکی", "raw-material", "lit", 300),
    ("مرکب چاپ فلکسو — رنگی", "raw-material", "lit", 250),
    ("فیلم BOPP ۲۰ میکرون", "packaging", "kg", 1500),
    ("کارتن ۵ لایه", "packaging", "ctn", 2000),
    ("نوار چسب پهن", "packaging", "pcs", 1200),
    ("استرچ پالت", "packaging", "roll", 400),
    ("پالت چوبی استاندارد", "packaging", "pcs", 300),
    ("یاتاقان SKF 6204", "spare-parts", "pcs", 40),
    ("تسمه تایمینگ", "spare-parts", "pcs", 25),
    ("سنسور فتوالکتریک", "spare-parts", "pcs", 15),
    ("اینورتر ۵.۵ کیلووات", "spare-parts", "pcs", 5),
    ("المنت حرارتی", "spare-parts", "pcs", 30),
    ("روغن هیدرولیک ۶۸", "consumables", "lit", 600),
    ("گریس صنعتی", "consumables", "kg", 120),
    ("دستکش ضد برش", "consumables", "pack", 200),
    ("ماسک صنعتی", "consumables", "pack", 300),
    ("کاغذ A4", "office", "pack", 150),
    ("تونر پرینتر", "office", "pcs", 20),
]

UNITS = {u.value for u in MaterialUnit}


class Command(BaseCommand):
    help = "پر کردن بخش مالی و بازرگانی با داده‌ی نمایشی"

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=8,
                            help="چند ماه پر شود (پیش‌فرض ۸، رو به عقب از آخرین ماه)")
        parser.add_argument("--accounts", type=int, default=len(BANKS),
                            help=f"چند حساب بانکی ساخته شود (حداکثر {len(BANKS)})")
        parser.add_argument("--clear", action="store_true",
                            help="حذف داده‌ی نمایشی، بدون دست‌زدن به داده‌ی واقعی")

    def handle(self, *args, **opts):
        if opts["clear"]:
            return self.clear()

        rnd = random.Random(1405)  # fixed, so the demo is the same every run
        months = self.pick_months(opts["months"])
        if not months:
            self.stderr.write("هیچ ماهی در جدول دوره‌ها نیست — اول seed_periods را اجرا کنید.")
            return

        # One transaction per section, not one for the whole command. They
        # share nothing, and a single wrapper meant a failure while writing
        # بازرگانی rolled back مالی too — the demo lost both sections over a
        # problem in one of them.
        with transaction.atomic():
            people = self.seed_users()
            accounts = self.seed_accounts(opts["accounts"])
            lines = self.seed_credit_lines(months)
            moves = self.seed_cash(rnd, months, accounts, lines)

        sup: list = []
        mat: list = []
        reqs = quotes = orders = 0
        try:
            with transaction.atomic():
                sup, mat = self.seed_catalogue(rnd)
                reqs, quotes, orders = self.seed_purchasing(rnd, months, sup, mat)
        except Exception as exc:
            self.stderr.write(self.style.WARNING(
                f"\nبخش بازرگانی پر نشد: {exc}\n"
                "  مالی سالم نوشته شد. اگر خطا درباره‌ی ستونی است که در مدل "
                "نیست، جدول‌های این اپ از مدل جلوترند — یعنی مهاجرتی خارج از "
                "این درخت روی همین دیتابیس اجرا شده.\n"
            ))

        from apps.accounts.management.commands.seed_users import PASSWORD

        first, last = months[0], months[-1]
        who = "\n".join(
            f"    {u.username:12} / {PASSWORD}   ({u.job_title_fa})"
            for u, _ in people
        )
        self.stdout.write(self.style.SUCCESS(
            f"\nداده‌ی نمایشی ساخته شد — {first.label} تا {last.label}"
            f"  ({len(months)} ماه)\n"
            f"  مالی    : {len(accounts)} حساب، {len(lines)} تسهیلات/جاری، "
            f"{moves} تراکنش نقدی (~{moves // max(len(months), 1)} در ماه)\n"
            f"  بازرگانی: {len(sup)} تأمین‌کننده، {len(mat)} کالا، "
            f"{reqs} درخواست، {quotes} استعلام، {orders} سفارش خرید\n"
            f"\n  ورود به دو بخش:\n{who}\n"
            f"\nبرای حذف: python manage.py seed_demo --clear"
        ))

    # -- periods ---------------------------------------------------------
    def pick_months(self, count: int) -> list[DimPeriod]:
        """The `count` months ending with the current one.

        Not the last `count` rows in the table: the period table runs to the end
        of the Jalali year, so that would put the whole demo in months that have
        not happened yet — every dashboard opens on the newest month with data
        and would land on empty figures dated next winter.
        """
        months = list(
            DimPeriod.objects.filter(kind=PeriodKind.MONTH)
            .order_by("jalali_year", "jalali_month")
        )
        today = timezone.localdate()
        past = [m for m in months if m.start_date and m.start_date <= today]
        upto = past or months
        return upto[-count:] if count < len(upto) else upto

    def day_pool(self, month: DimPeriod) -> list[DimPeriod]:
        """Days of a month, created on demand.

        Cash lands on days rather than the month itself so the نقدینگی report
        has a curve to draw. ensure_weeks refuses a month that already carries
        figures of its own — that month simply stays monthly, and the movement
        hangs off the month, which is still valid.
        """
        try:
            weeks = ensure_weeks(month)
        except Exception:
            return [month]
        days: list[DimPeriod] = []
        for w in weeks:
            try:
                days.extend(ensure_days(w))
            except Exception:
                days.append(w)
        return days or [month]

    # -- people ----------------------------------------------------------
    def seed_users(self) -> list:
        """Someone to sign in as for each of the two sections.

        Both sections are department-scoped: what the sidebar offers and what
        the API allows follow `department`, so demoing مالی as the CEO shows
        the read-only dashboards and never the entry sheet. These two accounts
        exist to show the sections as the people who actually work in them see
        them.

        Password matches accounts/seed_users.py rather than inventing a second
        convention. It is a demo credential for a demo database — a real
        deployment changes it, which is what that command's own docstring says.
        """
        from apps.accounts.management.commands.seed_users import PASSWORD

        User = get_user_model()
        wanted = [
            ("finance", "مدیر مالی — دمو", "مدیر مالی", "finance"),
            ("commercial", "مدیر بازرگانی — دمو", "مدیر بازرگانی داخلی", "commercial"),
        ]
        out = []
        for username, display, title, dept in wanted:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"display_name_fa": display, "job_title_fa": title},
            )
            user.display_name_fa = display
            user.job_title_fa = title
            user.department = dept
            # manager, not operator: it is the role that both enters the
            # section's figures and sees its dashboards.
            user.role = "manager"
            user.is_active = True
            if created or not user.has_usable_password():
                user.set_password(PASSWORD)
            user.save()
            out.append((user, created))
        return out

    # -- finance ---------------------------------------------------------
    def seed_accounts(self, how_many: int) -> list[BankAccount]:
        FinanceSetting.objects.get_or_create(
            singleton=True,
            defaults={"opening_balance_rial": Decimal("120000000000")},
        )
        out = []
        for i, (title, bank, kind, opening, colour) in enumerate(BANKS[:how_many]):
            acc, _ = BankAccount.objects.update_or_create(
                title=title,
                defaults={
                    "bank_name": bank,
                    "kind": kind,
                    "account_no": f"{1000 + i * 37}-{800 + i}-{9 + i}",
                    "iban": f"IR{62_000_000_000_000_000_000_000 + i * 7919}",
                    "opening_balance_rial": Decimal(opening),
                    # Left blank on purpose. `color` exists so someone can
                    # pin a house colour to an account; when it is empty the
                    # chart assigns from the validated categorical ramp in
                    # fixed order. Fourteen invented hexes bypassed that ramp
                    # entirely and were never checked for colour-blind
                    # separation against each other.
                    "color": "",
                    "sort_order": i,
                    "is_active": True,
                    "note": MARK,
                },
            )
            out.append(acc)
        return out

    def seed_credit_lines(self, months) -> list[CreditLine]:
        opened = months[0].start_date
        out = []
        for kind, title, party, principal, rate, status, inst in CREDIT_LINES:
            line, _ = CreditLine.objects.update_or_create(
                title=title,
                defaults={
                    "kind": kind,
                    "counterparty": party,
                    "principal_rial": Decimal(principal),
                    "rate_pct": Decimal(rate),
                    "opened_on": opened,
                    "due_on": (months[-1].end_date + timedelta(days=180)) if inst else None,
                    "installments": inst,
                    "status": status,
                    "note": MARK,
                },
            )
            out.append(line)
        return out

    def seed_cash(self, rnd, months, accounts, lines) -> int:
        cats = {c.code: c for c in CashCategory.objects.all()}
        if not cats or not accounts:
            return 0

        # (category code, direction, how many a month, rial low, rial high)
        #
        # A busy month, on purpose. The cash pages are a ledger: a handful of
        # rows a month reads like a system nobody uses, and neither the daily
        # curve nor the per-account split says anything until there is real
        # traffic behind it. Roughly 110 movements a month, weighted the way a
        # factory's actually are — many sales receipts and supplier payments,
        # a steady drip of petty cash, and the occasional facility drawdown.
        plan = [
            ("sales", "in", 30, 400_000_000, 9_000_000_000),
            ("debt-returned", "in", 6, 300_000_000, 5_000_000_000),
            ("unclassified", "in", 5, 80_000_000, 900_000_000),
            ("facility", "in", 2, 5_000_000_000, 20_000_000_000),
            ("partner-account", "in", 4, 400_000_000, 4_000_000_000),
            ("supplier", "out", 26, 300_000_000, 8_000_000_000),
            ("payroll", "out", 8, 200_000_000, 2_500_000_000),
            ("petty-cash", "out", 14, 20_000_000, 500_000_000),
            ("facility", "out", 4, 600_000_000, 3_500_000_000),
            ("lending", "out", 3, 150_000_000, 1_500_000_000),
            ("partner-account", "out", 4, 400_000_000, 5_000_000_000),
        ]
        by_kind = {k: [ln for ln in lines if ln.kind == k] for k in ("facility", "lending", "partner")}

        # Traffic is not spread evenly over fourteen accounts. A company runs
        # most of its money through one or two, and the rest see a trickle.
        # Seeding it flat made every account roughly equal, which reads as
        # noise on the split chart — and made «سایر» larger than any named
        # account, so the fold looked like it was hiding the answer.
        weights = [max(1.0, 40.0 * (0.62 ** i)) for i in range(len(accounts))]
        # A movement is unique on (period, direction, category, credit_line,
        # account) — one ledger line per day per category per account, not one
        # row per transaction. So amounts are accumulated into that key rather
        # than appended: two supplier payments from the same account on the
        # same day are one line of the day's ledger, which is also how the
        # finance colleague writes them down.
        acc: dict[tuple, dict] = {}
        for month in months:
            days = self.day_pool(month)
            for code, direction, per_month, low, high in plan:
                cat = cats.get(code)
                if not cat:
                    continue
                for _ in range(per_month):
                    line = None
                    if cat.expects_credit_line or code == "partner-account":
                        pool = by_kind.get(
                            "partner" if code == "partner-account"
                            else ("lending" if code == "lending" else "facility"), []
                        )
                        line = rnd.choice(pool) if pool else None
                    key = (
                        rnd.choice(days).id,
                        Direction.IN if direction == "in" else Direction.OUT,
                        cat.id,
                        line.id if line else None,
                        rnd.choices(accounts, weights=weights)[0].id,
                    )
                    amount = Decimal(rnd.randrange(low, high, 1_000_000))
                    if key in acc:
                        acc[key]["amount"] += amount
                    else:
                        acc[key] = {
                            "amount": amount,
                            "line": line,
                            # Most of it approved: a demo that is all drafts
                            # shows empty dashboards, since the reports read
                            # approved rows.
                            "status": (ApprovalStatus.APPROVED if rnd.random() < 0.88
                                       else ApprovalStatus.SUBMITTED),
                        }

        rows = [
            CashMovement(
                period_id=period_id,
                direction=direction,
                category_id=cat_id,
                account_id=account_id,
                amount_rial=v["amount"],
                credit_line=v["line"],
                status=v["status"],
                note=MARK,
            )
            for (period_id, direction, cat_id, _line_id, account_id), v in acc.items()
        ]
        CashMovement.objects.bulk_create(rows, batch_size=500)
        return len(rows)

    # -- commercial ------------------------------------------------------
    def seed_catalogue(self, rnd):
        sups = []
        for i, (name, contact, activity) in enumerate(SUPPLIERS):
            s, _ = Supplier.objects.update_or_create(
                code=f"demo-sup-{i + 1:02d}",
                defaults={
                    "name_fa": name,
                    "contact_name": contact,
                    "mobile": f"0912{rnd.randrange(1000000, 9999999)}",
                    "phone": f"021{rnd.randrange(22000000, 88999999)}",
                    "activity": activity,
                    "is_active": True,
                    "note": MARK,
                },
            )
            sups.append(s)

        cats = {c.code: c for c in MaterialCategory.objects.all()}
        mats = []
        for i, (name, cat_code, unit, min_stock) in enumerate(MATERIALS):
            m, _ = Material.objects.update_or_create(
                code=f"demo-mat-{i + 1:02d}",
                defaults={
                    "name_fa": name,
                    "category": cats.get(cat_code) or cats.get("other"),
                    "unit": unit if unit in UNITS else MaterialUnit.PIECE,
                    "min_stock": Decimal(min_stock),
                    "is_active": True,
                    "note": MARK,
                },
            )
            mats.append(m)
        return sups, mats

    def seed_purchasing(self, rnd, months, sups, mats):
        wins = list(QuoteReason.objects.filter(kind="win"))
        loses = list(QuoteReason.objects.filter(kind="lose"))
        units = ["تولید", "کنترل کیفیت", "فنی و نگهداری", "اداری", "انبار", "بسته‌بندی"]

        n_req = n_quote = n_order = 0
        for month in months:
            for _ in range(rnd.randrange(5, 9)):
                mat = rnd.choice(mats)
                asked = month.start_date + timedelta(days=rnd.randrange(0, 25))
                req = PurchaseRequest.objects.create(
                    material=mat,
                    quantity=Decimal(rnd.randrange(10, 900)),
                    requester_unit=rnd.choice(units),
                    requested_on=asked,
                    needed_by=asked + timedelta(days=rnd.randrange(7, 45)),
                    period=month,
                    status="open",
                    note=MARK,
                )
                n_req += 1

                # Two to four suppliers quote; the cheapest usually wins, but
                # not always — a demo where price always decides teaches the
                # wrong thing about the reasons list.
                bidders = rnd.sample(sups, rnd.randrange(2, 5))
                base = rnd.randrange(200_000, 8_000_000, 10_000)
                bids = []
                for sup in bidders:
                    price = int(base * rnd.uniform(0.88, 1.28))
                    bids.append(Quote.objects.create(
                        request=req,
                        supplier=sup,
                        unit_price_rial=Decimal(price),
                        quoted_on=asked + timedelta(days=rnd.randrange(1, 8)),
                        delivery_days=rnd.randrange(3, 40),
                        validity_days=rnd.choice([7, 15, 30]),
                        note=MARK,
                    ))
                    n_quote += 1

                if rnd.random() < 0.82:
                    winner = (min(bids, key=lambda q: q.unit_price_rial)
                              if rnd.random() < 0.75 else rnd.choice(bids))
                    winner.is_selected = True
                    winner.reason = rnd.choice(wins) if wins else None
                    winner.decision_note = MARK
                    winner.save(update_fields=["is_selected", "reason", "decision_note"])
                    for q in bids:
                        if q.pk != winner.pk and loses:
                            q.reason = rnd.choice(loses)
                            q.decision_note = MARK
                            q.save(update_fields=["reason", "decision_note"])

                    req.status = "ordered"
                    req.save(update_fields=["status"])

                    ordered_on = winner.quoted_on + timedelta(days=rnd.randrange(1, 6))
                    status = rnd.choices(
                        ["delivered", "shipped", "buying", "pending", "cancelled"],
                        weights=[55, 15, 12, 15, 3],
                    )[0]
                    PurchaseOrder.objects.create(
                        request=req,
                        quote=winner,
                        supplier=winner.supplier,
                        material=mat,
                        quantity=req.quantity,
                        unit_price_rial=winner.unit_price_rial,
                        ordered_on=ordered_on,
                        delivered_on=(ordered_on + timedelta(days=winner.delivery_days)
                                      if status == "delivered" else None),
                        period=month,
                        status=status,
                        note=MARK,
                    )
                    n_order += 1
                else:
                    req.status = rnd.choice(["open", "quoting"])
                    req.save(update_fields=["status"])

        return n_req, n_quote, n_order

    # -- undo ------------------------------------------------------------
    def clear(self):
        counts = {}
        with transaction.atomic():
            # Orders before quotes before requests: the later ones point back.
            counts["سفارش خرید"] = PurchaseOrder.objects.filter(note=MARK).delete()[0]
            counts["استعلام"] = Quote.objects.filter(note=MARK).delete()[0]
            counts["درخواست خرید"] = PurchaseRequest.objects.filter(note=MARK).delete()[0]
            counts["کالا"] = Material.objects.filter(code__startswith="demo-mat-").delete()[0]
            counts["تأمین‌کننده"] = Supplier.objects.filter(code__startswith="demo-sup-").delete()[0]
            counts["تراکنش نقدی"] = CashMovement.objects.filter(note=MARK).delete()[0]
            counts["تسهیلات/جاری"] = CreditLine.objects.filter(note=MARK).delete()[0]
            counts["حساب بانکی"] = BankAccount.objects.filter(note=MARK).delete()[0]
        self.stdout.write(self.style.SUCCESS(
            "داده‌ی نمایشی حذف شد — " + "، ".join(f"{k}: {v}" for k, v in counts.items())
        ))
