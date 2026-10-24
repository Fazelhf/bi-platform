"""
Sample CRM data for a showcase — never for the company's real figures.

    python manage.py seed_crm_sample            # add the sample
    python manage.py seed_crm_sample --clear    # remove it again

Shaped on آرپا's «فاکتور فروش» export of رول مارکت (1405/07–08): the same
customer groups, payment terms, shipping, roll counts and a price per roll
of roughly 0.7–1.2 million Rial, attributed to the salespeople already on
the roster. Spread over every province so فروش جغرافیایی has a country to
show, with deals, follow-ups and calls behind the invoices so the dashboard
has a pipeline too.

Every row it writes has a code starting with `seed-`, which is both how
`--clear` finds them and how the app knows to put «داده نمونه» on screen
(see `apps.crm.views.has_sample_data`). Nothing here may ever reach the
server: a sample that looks exactly like the customer file is the reason the
old showroom dataset was removed.
"""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.crm.jalali import period_for
from apps.crm.models import (
    Activity, Customer, CustomerGroup, Dataset, Deal, LeadSource, LostReason,
    PipelineStage, Product, SalesInvoice, SalesInvoiceItem, Task,
)
from apps.sales.models import DimEmployee, DimProvince, EmployeeChannel, SalesChannel

PREFIX = "seed-"

# Weight ≈ how much of the trade each province carries; city list for the
# address. Names match DimProvince.name_fa.
PROVINCES = {
    "تهران": (16, ["تهران", "شهریار", "اسلامشهر"]),
    "اصفهان": (7, ["اصفهان", "کاشان", "نجف‌آباد"]),
    "خراسان رضوی": (7, ["مشهد", "نیشابور", "سبزوار"]),
    "فارس": (6, ["شیراز", "مرودشت", "لار"]),
    "آذربایجان شرقی": (5, ["تبریز", "مراغه"]),
    "البرز": (5, ["کرج", "فردیس"]),
    "خوزستان": (4, ["اهواز", "دزفول", "آبادان"]),
    "مازندران": (4, ["ساری", "بابل", "آمل"]),
    "قم": (3, ["قم"]),
    "گیلان": (3, ["رشت", "لاهیجان"]),
    "کرمان": (3, ["کرمان", "رفسنجان"]),
    "یزد": (3, ["یزد", "میبد"]),
    "مرکزی": (2, ["اراک", "ساوه"]),
    "آذربایجان غربی": (2, ["ارومیه", "خوی"]),
    "زنجان": (2, ["زنجان"]),
    "قزوین": (2, ["قزوین"]),
    "همدان": (2, ["همدان", "ملایر"]),
    "کرمانشاه": (2, ["کرمانشاه"]),
    "گلستان": (2, ["گرگان", "گنبد"]),
    "هرمزگان": (2, ["بندرعباس", "کیش"]),
    "سمنان": (1, ["سمنان", "شاهرود"]),
    "اردبیل": (1, ["اردبیل"]),
    "کردستان": (1, ["سنندج"]),
    "لرستان": (1, ["خرم‌آباد"]),
    "بوشهر": (1, ["بوشهر"]),
    "سیستان و بلوچستان": (1, ["زاهدان"]),
    "چهارمحال بختیاری": (1, ["شهرکرد"]),
    "کهگیلویه و بویر احمد": (1, ["یاسوج"]),
    "خراسان شمالی": (1, ["بجنورد"]),
    "خراسان جنوبی": (1, ["بیرجند"]),
    "ایلام": (1, ["ایلام"]),
}

SURNAMES = [
    "احمدی", "رضایی", "کریمی", "حسینی", "موسوی", "جعفری", "نوری", "صادقی",
    "رحیمی", "قاسمی", "اکبری", "سلیمانی", "زارعی", "عباسی", "نظری", "یوسفی",
    "کاظمی", "طاهری", "فرهادی", "شریفی", "باقری", "مرادی", "حیدری", "نیک‌نام",
    "امینی", "سعیدی", "رستمی", "خلیلی", "صفری", "میرزایی",
]
TRADES = [
    "پخش رول {s}", "فروشگاه {s}", "بازرگانی {s}", "رول‌چی {s}", "نوشت‌افزار {s}",
    "شرکت پویا کاغذ {s}", "تجهیزات فروشگاهی {s}", "صنایع بسته‌بندی {s}",
]
GROUPS = [
    ("seed-grp-other", "سایر طرف حسابها", "#94a3b8"),
    ("seed-grp-partner", "نمابر مهر همکار", "#22c55e"),
    ("seed-grp-aral", "آرال رول آریا تهران", "#0ea5e9"),
]
SOURCES = [("seed-src-phone", "تماس ورودی"), ("seed-src-ref", "معرفی مشتری"),
           ("seed-src-site", "وب‌سایت"), ("seed-src-show", "نمایشگاه")]
REASONS = [("seed-lr-price", "قیمت بالاتر از رقبا", True),
           ("seed-lr-credit", "شرایط پرداخت", True),
           ("seed-lr-stock", "نبود موجودی", True),
           ("seed-lr-gone", "انصراف مشتری", False)]
STAGES = [("seed-st-1", "ارتباط اولیه", "open", 10), ("seed-st-2", "اعلام قیمت", "open", 30),
          ("seed-st-3", "ارسال نمونه", "open", 50), ("seed-st-4", "مذاکره", "open", 75),
          ("seed-st-won", "موفق", "won", 100), ("seed-st-lost", "ناموفق", "lost", 0)]
PRODUCTS = [
    ("seed-p-80", "رول حرارتی ۸۰ میلی‌متر", 880_000),
    ("seed-p-57", "رول حرارتی ۵۷ میلی‌متر", 690_000),
    ("seed-p-atm", "رول ATM", 1_150_000),
    ("seed-p-pos", "رول کارتخوان", 720_000),
    ("seed-p-lbl", "لیبل حرارتی", 1_050_000),
]
# The export's own terms, with roughly its mix.
TERMS = ["نقدی"] * 4 + ["نقدی 7 روزه"] * 2 + ["15 روزه", "20 روز", "20 روز", "30روزه", "45 روزه"]
TERM_DAYS = {"نقدی": 1, "نقدی 7 روزه": 7, "15 روزه": 15, "20 روز": 20, "30روزه": 30, "45 روزه": 45}


class Command(BaseCommand):
    help = "Add (or --clear) clearly-marked sample CRM data shaped like the رول مارکت export."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="remove the sample and stop")
        parser.add_argument("--customers", type=int, default=260)
        parser.add_argument("--months", type=int, default=13)

    def handle(self, *args, **opts):
        with transaction.atomic():
            removed = self.clear()
            if opts["clear"]:
                self.stdout.write(self.style.SUCCESS(f"sample removed ({removed} rows)"))
                return
            self.seed(opts["customers"], opts["months"])

    # ------------------------------------------------------------------
    def clear(self) -> int:
        n = 0
        p = {"code__startswith": PREFIX}
        for qs in (
            SalesInvoiceItem.objects.filter(invoice__code__startswith=PREFIX),
            SalesInvoice.objects.filter(**p),
            Task.objects.filter(customer__code__startswith=PREFIX),
            Activity.objects.filter(customer__code__startswith=PREFIX),
            Deal.objects.filter(**p),
            Customer.objects.filter(**p),
            PipelineStage.objects.filter(**p), LostReason.objects.filter(**p),
            LeadSource.objects.filter(**p), CustomerGroup.objects.filter(**p),
            Product.objects.filter(**p),
        ):
            n += qs.delete()[0]
        return n

    def seed(self, n_customers: int, n_months: int):
        rnd = random.Random(1405)
        now = timezone.now()
        today = timezone.localdate()
        real = Dataset.REAL

        reps = self.reps()
        if not reps:
            self.stderr.write("no salesperson on the roster — run the sales seed first")
            return
        provinces = {p.name_fa: p for p in DimProvince.objects.all()}

        groups = [CustomerGroup.objects.create(code=c, name_fa=n, color=col, dataset=real)
                  for c, n, col in GROUPS]
        sources = [LeadSource.objects.create(code=c, name_fa=n, dataset=real) for c, n in SOURCES]
        reasons = [LostReason.objects.create(code=c, name_fa=n, is_controllable=k, dataset=real)
                   for c, n, k in REASONS]
        stages = {k: PipelineStage.objects.create(code=c, name_fa=n, kind=kind, order=i,
                                                  probability_pct=pr, dataset=real)
                  for i, (c, n, kind, pr) in enumerate(STAGES)
                  for k in [c]}
        open_stages = [s for s in stages.values() if s.kind == "open"]
        products = [Product.objects.create(code=c, name_fa=n, list_price_rial=pr,
                                           unit_cost_rial=int(pr * 0.74), dataset=real)
                    for c, n, pr in PRODUCTS]

        names = list(PROVINCES)
        weights = [PROVINCES[n][0] for n in names]
        window_days = n_months * 30

        customers: list[Customer] = []
        used: set[str] = set()
        for i in range(n_customers):
            pname = rnd.choices(names, weights)[0]
            city = rnd.choice(PROVINCES[pname][1])
            while True:
                s = rnd.choice(SURNAMES)
                name = rnd.choice(TRADES).format(s=s) if rnd.random() < 0.6 else f"آقای {s} ({city})"
                if name not in used:
                    used.add(name)
                    break
            channel, owner = rnd.choices(reps, [r[2] for r in reps])[0][:2]
            customers.append(Customer(
                code=f"{PREFIX}c-{i + 1}", name_fa=name, dataset=real,
                kind=Customer.Kind.PERSON if name.startswith("آقای") else Customer.Kind.COMPANY,
                status=Customer.Status.ACTIVE, channel=channel, owner=owner,
                group=rnd.choices(groups, [6, 2, 2])[0], lead_source=rnd.choice(sources),
                province=provinces.get(pname), city=city,
                payment_terms=rnd.choice(TERMS),
                first_contact_at=now - dt.timedelta(days=rnd.randint(window_days, window_days + 400)),
            ))
        Customer.objects.bulk_create(customers)
        customers = list(Customer.objects.filter(code__startswith=PREFIX))

        # Some customers buy all the time, most now and then, a few never.
        appetite = {c.id: rnd.choices([0, 1, 3, 8], [2, 8, 6, 2])[0] for c in customers}

        deals, invoices, items, activities, tasks = [], [], [], [], []
        inv_no = 300
        for c in customers:
            base_rolls = rnd.choice([60, 120, 300, 600, 800, 1400, 2100, 3000])
            for k in range(appetite[c.id]):
                day = today - dt.timedelta(days=rnd.randint(0, window_days))
                rolls = max(30, int(base_rolls * rnd.uniform(0.5, 1.8)) // 10 * 10)
                product = rnd.choice(products)
                price = int(product.list_price_rial * rnd.uniform(0.85, 1.08)) // 100 * 100
                amount = rolls * price
                terms = c.payment_terms or "نقدی"
                due = day + dt.timedelta(days=TERM_DAYS.get(terms, 7))
                age = (today - due).days
                paid = 1.0 if age > 20 else (rnd.choice([0, 0.5, 1]) if age > 0 else 0)
                settled = int(amount * paid)
                inv_no += 1
                opened = _aware(day - dt.timedelta(days=rnd.randint(3, 25)))
                deal = Deal(
                    code=f"{PREFIX}d-{c.id}-{k}", title=f"{product.name_fa} — {c.name_fa}",
                    customer=c, owner=c.owner, channel=c.channel, dataset=real,
                    stage=stages["seed-st-won"], status=Deal.Status.WON,
                    lead_source=c.lead_source, amount_rial=amount,
                    cost_rial=int(amount * rnd.uniform(0.68, 0.8)),
                    opened_at=opened, closed_at=_aware(day),
                    period=period_for(opened), close_period=period_for(day),
                )
                deal.profit_rial = deal.amount_rial - deal.cost_rial
                deals.append(deal)
                invoices.append((deal, SalesInvoice(
                    code=f"{PREFIX}inv-{inv_no}", number=str(inv_no), dataset=real,
                    kind=SalesInvoice.Kind.SALE, customer=c,
                    party_code=f"{PREFIX}{400000 + c.id}", party_name=c.name_fa,
                    issued_at=day, period=period_for(day),
                    amount_rial=amount, total_rial=amount,
                    settled_rial=settled, unsettled_rial=amount - settled,
                    payment_terms=terms, due_date=due, grace_date=due,
                    shipping_method="به عهده کارخانه", owner=c.owner, channel=c.channel,
                    branch="کاغذ حساس نمابر مهر",
                ), product, rolls, price))

            # The pipeline still in play, and what was lost.
            for k in range(rnd.choices([0, 1, 2, 3], [4, 4, 2, 1])[0]):
                # Losses happen all year; what is still open is recent.
                lost = rnd.random() < 0.45
                opened = now - dt.timedelta(days=rnd.randint(1, window_days if lost else 80))
                amount = rnd.choice([300, 600, 1000, 2000, 4000]) * rnd.randint(650, 1100) * 1000
                closed = opened + dt.timedelta(days=rnd.randint(3, 30)) if lost else None
                if closed and closed > now:
                    closed = now
                deals.append(Deal(
                    code=f"{PREFIX}o-{c.id}-{k}", title=f"پیش‌فاکتور {c.name_fa}",
                    customer=c, owner=c.owner, channel=c.channel, dataset=real,
                    stage=stages["seed-st-lost"] if lost else rnd.choice(open_stages),
                    status=Deal.Status.LOST if lost else Deal.Status.OPEN,
                    lost_reason=rnd.choice(reasons) if lost else None,
                    lead_source=c.lead_source, amount_rial=amount,
                    cost_rial=int(amount * 0.75), profit_rial=int(amount * 0.25),
                    opened_at=opened, closed_at=closed,
                    expected_close_date=(opened + dt.timedelta(days=rnd.randint(10, 60))).date(),
                    period=period_for(opened), close_period=period_for(closed) if closed else None,
                ))

            # Follow-ups: a handful of calls and the odd meeting per customer.
            for _ in range(rnd.randint(1, 3 + appetite[c.id])):
                at = now - dt.timedelta(days=rnd.randint(0, window_days), hours=rnd.randint(0, 8))
                kind = rnd.choices(
                    ["call_out", "call_in", "quote", "message", "meeting", "sample"],
                    [10, 4, 3, 3, 1, 1],
                )[0]
                activities.append(Activity(
                    kind=kind, customer=c, owner=c.owner, at=at, dataset=real,
                    duration_min=rnd.choice([2, 5, 8, 15]) if kind.startswith("call") else 0,
                    result=rnd.choices(["success", "no_answer", "follow_up", "failed"], [6, 2, 2, 1])[0],
                    period=period_for(at), note="",
                ))
            if rnd.random() < 0.3:
                tasks.append(Task(
                    title=f"پیگیری سفارش بعدی {c.name_fa}", customer=c, owner=c.owner,
                    kind="call_out", dataset=real,
                    due_at=now + dt.timedelta(days=rnd.randint(-10, 10)),
                ))

        Deal.objects.bulk_create(deals)
        by_code = {d.code: d for d in Deal.objects.filter(code__startswith=PREFIX)}
        inv_rows = []
        for deal, inv, product, rolls, price in invoices:
            inv.deal = by_code[deal.code]
            inv_rows.append((inv, product, rolls, price))
        SalesInvoice.objects.bulk_create([r[0] for r in inv_rows])
        saved = {i.code: i for i in SalesInvoice.objects.filter(code__startswith=PREFIX)}
        for inv, product, rolls, price in inv_rows:
            items.append(SalesInvoiceItem(
                invoice=saved[inv.code], product=product, product_code=product.code,
                product_name=product.name_fa, quantity=rolls, unit_price_rial=price,
                amount_rial=rolls * price, dataset=real,
            ))
        SalesInvoiceItem.objects.bulk_create(items)
        Activity.objects.bulk_create(activities)
        Task.objects.bulk_create(tasks)

        # The denormalised dates the reports read.
        for c in customers:
            won = [d.closed_at for d in by_code.values() if d.customer_id == c.id and d.status == "won"]
            acts = [a.at for a in activities if a.customer_id == c.id]
            c.first_deal_won_at = min(won) if won else None
            c.last_activity_at = max(acts) if acts else None
            if not won:
                c.status = Customer.Status.LEAD
        Customer.objects.bulk_update(customers, ["first_deal_won_at", "last_activity_at", "status"])

        total = sum(i.amount_rial for i, *_ in inv_rows)
        self.stdout.write(self.style.SUCCESS(
            f"sample added: {len(customers)} customers, {len(inv_rows)} invoices "
            f"({Decimal(total) / 10**9:.1f} bn Rial), {len(deals)} deals, "
            f"{len(activities)} activities, {len(tasks)} tasks"
        ))

    def reps(self) -> list[tuple[str, DimEmployee, int]]:
        """(channel, employee, weight) for the people actually on the roster."""
        out = []
        for ec in EmployeeChannel.objects.select_related("employee"):
            e = ec.employee
            if getattr(e, "is_placeholder", False) or "بدون" in e.full_name_fa:
                continue
            out.append((ec.channel, e, 6 if ec.channel == SalesChannel.TEAM else 2))
        return out


def _aware(d: dt.date) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(d, dt.time(10, 0)))
