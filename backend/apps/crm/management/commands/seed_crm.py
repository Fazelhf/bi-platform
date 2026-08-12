"""
Seed the CRM with a realistic demo dataset (فروش همکار channel).

"Realistic" matters more than "random" here: the whole point of the CRM is
that the manager can ask *why* a number moved, so the generated data has to
contain real structure to find —

  • each rep has their own win-rate, deal size and activity tempo, so the
    per-rep reports rank meaningfully instead of being noise;
  • lead sources differ in both volume and quality (exhibition leads are few
    but convert; Instagram leads are many and cheap);
  • provinces are weighted by real market size, so the geography report and
    the existing province targets line up;
  • losing reasons correlate with what happened (deals that sat too long die
    of "تاخیر در تحویل", heavily discounted ones die of "قیمت");
  • the current month is deliberately partial, exactly like live data.

Idempotent: `--fresh` wipes CRM tables first, otherwise it tops up.
"""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.crm.jalali import jalali_to_gregorian, month_bounds, period_for
from apps.crm.models import (
    Activity, Customer, CustomerFeedback, CustomerGroup, Deal, DealItem,
    DealStageEvent, DemoProvinceTarget, LeadSource, LostReason, PipelineStage,
    Product, ProductCategory, Tag, Task,
)
from apps.sales.models import DimEmployee, DimProvince

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
STAGES = [
    # (code, name, order, kind, probability)
    ("contact", "ارتباط مشتری", 1, "open", 10),
    ("quote", "ارسال نمونه - اعلام قیمت", 2, "open", 25),
    ("approval", "پیگیری تایید", 3, "open", 40),
    ("order", "ثبت سفارش در سیستم حسابداری", 4, "open", 60),
    ("production", "اعلام به واحد تولید", 5, "open", 75),
    ("shipping", "هماهنگی ارسال بار با مشتری", 6, "open", 85),
    ("delivery", "پیگیری دریافت بار", 7, "open", 92),
    ("invoice", "صدور فاکتور", 8, "open", 96),
    ("settled", "تسویه", 9, "won", 100),
    ("lost", "از دست رفته", 10, "lost", 0),
]

GROUPS = [
    ("printing", "چاپخانه"),
    ("stationery", "لوازم‌التحریر و نوشت‌افزار"),
    ("bank", "بانک و موسسه مالی"),
    ("retail", "فروشگاه زنجیره‌ای"),
    ("hospital", "بیمارستان و درمانگاه"),
    ("gov", "سازمان دولتی"),
    ("trading", "شرکت بازرگانی"),
    ("industry", "صنایع و تولیدی"),
]

SOURCES = [
    # (code, name, share of new deals, quality multiplier on win-rate)
    ("referral", "معرفی مشتری قبلی", 0.22, 1.35),
    ("website", "وب‌سایت", 0.18, 0.95),
    ("exhibition", "نمایشگاه", 0.10, 1.45),
    ("cold_call", "تماس سرد", 0.16, 0.60),
    ("instagram", "اینستاگرام", 0.14, 0.70),
    ("agent", "معرفی همکار", 0.12, 1.20),
    ("repeat", "مشتری قدیمی", 0.08, 1.60),
]

REASONS = [
    ("competitor", "خرید از رقبا", False),
    ("price", "قیمت", True),
    ("delay", "تاخیر در تحویل", True),
    ("quality", "کیفیت محصول", True),
    ("no_need", "عدم نیاز فعلی", False),
    ("no_budget", "نبود بودجه", False),
    ("no_answer", "عدم پاسخگویی مشتری", False),
    ("other", "دلیل دیگر", False),
]

CATEGORIES = [
    ("thermal", "کاغذ حرارتی"),
    ("carbonless", "کاغذ کاربن‌لس"),
    ("bank_roll", "رول بانکی"),
    ("fax", "کاغذ فکس"),
    ("label", "لیبل و برچسب"),
]

# (code, name, category, unit, price Rial, cost Rial)
PRODUCTS = [
    ("th-80-80", "رول حرارتی ۸۰×۸۰", "thermal", "roll", 385_000, 268_000),
    ("th-80-60", "رول حرارتی ۸۰×۶۰", "thermal", "roll", 310_000, 219_000),
    ("th-57-40", "رول حرارتی ۵۷×۴۰", "thermal", "roll", 165_000, 118_000),
    ("th-110-80", "رول حرارتی ۱۱۰×۸۰", "thermal", "roll", 520_000, 379_000),
    ("th-jumbo", "جامبو رول حرارتی", "thermal", "ton", 1_850_000_000, 1_410_000_000),
    ("cl-2ply", "کاربن‌لس دو نسخه‌ای", "carbonless", "pack", 2_450_000, 1_790_000),
    ("cl-3ply", "کاربن‌لس سه نسخه‌ای", "carbonless", "pack", 3_380_000, 2_520_000),
    ("cl-sheet", "ورق کاربن‌لس A4", "carbonless", "sheet", 42_000, 30_500),
    ("cl-jumbo", "جامبو رول کاربن‌لس", "carbonless", "ton", 1_620_000_000, 1_255_000_000),
    ("bk-atm", "رول خودپرداز ATM", "bank_roll", "roll", 640_000, 452_000),
    ("bk-pos", "رول کارتخوان POS", "bank_roll", "roll", 178_000, 124_000),
    ("bk-branch", "رول نوبت‌دهی شعبه", "bank_roll", "roll", 295_000, 208_000),
    ("fx-210", "کاغذ فکس ۲۱۰ میلی‌متر", "fax", "roll", 268_000, 196_000),
    ("fx-216", "کاغذ فکس ۲۱۶ میلی‌متر", "fax", "roll", 289_000, 213_000),
    ("lb-thermal", "لیبل حرارتی رولی", "label", "roll", 720_000, 498_000),
    ("lb-paper", "لیبل کاغذی چاپی", "label", "roll", 545_000, 402_000),
    ("lb-barcode", "لیبل بارکد صنعتی", "label", "roll", 830_000, 601_000),
]

TAGS = [
    ("مشتری کلیدی", "#16a34a"), ("پرداخت نقدی", "#0ea5e9"),
    ("نیازمند پیگیری", "#f59e0b"), ("قرارداد سالانه", "#8b5cf6"),
    ("تخفیف ویژه", "#ef4444"), ("صادراتی", "#14b8a6"),
]

# Company-name building blocks — combined into plausible Iranian B2B names.
CO_PREFIX = ["شرکت", "بازرگانی", "گروه صنعتی", "تولیدی", "چاپ و نشر", "فروشگاه", "توزیع"]
CO_CORE = [
    "پارس", "آریا", "کیان", "مهر", "سپهر", "البرز", "زاگرس", "کاسپین", "دماوند",
    "نگین", "الماس", "ستاره", "پیشرو", "نوین", "آفتاب", "ماندگار", "رستاک",
    "هما", "سیمرغ", "خورشید", "آرمان", "بهار", "تندیس", "فرتاک", "ایده",
    "رادین", "ویرا", "پرشیا", "سامان", "توسکا", "آبان", "کارن", "دیبا",
    "شایان", "بارثاوا", "مانا", "هیرمند", "اطلس", "تکسان", "سرو",
]
CO_SUFFIX = ["", "", "", "تجارت", "صنعت", "کالا", "گستر", "پخش", "ایرانیان", "آسیا"]

PERSON_FIRST = ["علی", "محمد", "رضا", "حسین", "مهدی", "امیر", "سعید", "فرهاد",
                "زهرا", "فاطمه", "مریم", "نسرین", "الهام", "سمیرا", "بهنام", "کاوه"]
PERSON_LAST = ["احمدی", "محمدی", "رضایی", "کریمی", "موسوی", "حسینی", "جعفری",
               "صادقی", "نوری", "قاسمی", "شریفی", "امینی", "کاظمی", "زارع"]

# Province weights: Tehran dominates, then the industrial provinces.
PROVINCE_WEIGHTS = {
    "تهران": 26, "اصفهان": 11, "خراسان رضوی": 9, "فارس": 7, "البرز": 7,
    "آذربایجان شرقی": 6, "خوزستان": 5, "مازندران": 4, "گیلان": 4, "قم": 3,
    "کرمان": 3, "یزد": 3, "مرکزی": 2, "قزوین": 2, "همدان": 2, "کرمانشاه": 2,
    "گلستان": 2, "بوشهر": 1, "سمنان": 1, "زنجان": 1,
}

# Per-rep character: (share of deals, win-rate, avg deal size factor, calls/deal)
REP_PROFILE = {
    "هستی خانی":     (0.20, 0.46, 0.85, 7.5),
    "مهدیس مومنی":   (0.17, 0.52, 1.35, 5.0),
    "مهسا احمدی":    (0.16, 0.49, 1.10, 6.0),
    "صبا موسوی":     (0.13, 0.41, 0.95, 5.5),
    "هانیه منزه":    (0.11, 0.38, 0.80, 4.5),
    "مهسا قنبری":    (0.10, 0.44, 0.90, 5.0),
    "افسانه چوبینی": (0.08, 0.36, 0.75, 4.0),
    "پارسا مروتی":   (0.05, 0.33, 1.05, 3.5),
}

ACTIVITY_NOTES = {
    "call_out": ["پیگیری پیش‌فاکتور", "یادآوری تسویه", "پیگیری ارسال نمونه",
                 "هماهنگی زمان تحویل", "پیگیری تایید نهایی"],
    "call_in": ["درخواست قیمت", "پیگیری سفارش", "اعلام مشکل کیفیت", "درخواست نمونه"],
    "quote": ["ارسال پیش‌فاکتور", "اعلام قیمت جدید", "بازنگری قیمت با تخفیف"],
    "sample": ["ارسال نمونه رول حرارتی", "ارسال نمونه کاربن‌لس"],
    "meeting": ["جلسه در محل مشتری", "جلسه در دفتر شرکت", "بازدید از خط تولید"],
    "message": ["ارسال کاتالوگ", "پیگیری واتس‌اپ"],
    "order": ["ثبت سفارش در سیستم"],
    "invoice": ["صدور فاکتور رسمی"],
    "payment": ["دریافت وجه", "دریافت چک"],
}


class Command(BaseCommand):
    help = "Seed the CRM (فروش همکار) with a realistic demo dataset."

    #: Everything the showroom owns, children before parents.
    DEMO_MODELS = (
        Activity, Task, DealStageEvent, DealItem, Deal, CustomerFeedback,
        Customer, Product, ProductCategory, PipelineStage, LeadSource,
        LostReason, Tag, CustomerGroup,
    )

    def _wipe_demo(self) -> None:
        """Remove the showroom and nothing else — the real file stays put."""
        for model in self.DEMO_MODELS:
            model.objects.filter(dataset="demo").delete()
        DemoProvinceTarget.objects.all().delete()

    def _tag_demo(self, since) -> None:
        for model in self.DEMO_MODELS:
            model.objects.filter(created_at__gte=since).update(dataset="demo")

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh", action="store_true",
            help="حذف داده‌ی نمایشی قبلی (داده‌ی واقعی دست‌نخورده می‌ماند)",
        )
        parser.add_argument(
            "--if-empty", action="store_true",
            help="اگر داده‌ی نمایشی از قبل هست، هیچ کاری نکن (برای deploy).",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="فقط داده‌ی نمایشی را بردار و خارج شو.",
        )
        parser.add_argument("--customers", type=int, default=240)
        parser.add_argument("--months", type=int, default=17)
        parser.add_argument("--seed", type=int, default=1405)

    # ----------------------------------------------------------------------
    @transaction.atomic
    def handle(self, *args, **opts):
        rnd = random.Random(opts["seed"])
        self.rnd = rnd

        if opts["if_empty"] and Customer.objects.filter(dataset="demo").exists():
            self.stdout.write("داده‌ی نمایشی از قبل موجود است — ساخت رد شد.")
            return

        if opts["clear"]:
            self._wipe_demo()
            self.stdout.write(self.style.SUCCESS("داده‌ی نمایشی برداشته شد."))
            return

        if opts["fresh"]:
            self.stdout.write("پاک‌سازی داده‌ی نمایشی قبلی …")
            self._wipe_demo()

        # Everything written from here on belongs to the showroom. Tagging by
        # creation time at the end, rather than threading a dataset= through
        # forty create() calls, keeps the generator readable — and it is exact,
        # because the whole command is one transaction and nothing else is
        # writing CRM rows inside it.
        started_at = timezone.now()

        stages = self._seed_stages()
        groups = self._seed_simple(CustomerGroup, GROUPS)
        sources = self._seed_sources()
        reasons = self._seed_reasons()
        products = self._seed_products()
        tags = self._seed_tags()
        reps = self._reps()
        provinces = self._provinces()

        months = self._month_range(opts["months"])
        customers = self._seed_customers(
            opts["customers"], groups, sources, reps, provinces, months
        )
        self._seed_deals(months, customers, reps, stages, sources, reasons, products, tags)
        self._seed_standalone_activities(months, customers, reps)
        self._seed_feedback(customers, reps)
        self._seed_tasks(customers, reps)
        self._seed_province_targets(months)

        self._tag_demo(started_at)
        self.stdout.write(self.style.SUCCESS(
            f"✔ CRM seeded — {Customer.objects.count()} مشتری، "
            f"{Deal.objects.count()} معامله، {DealItem.objects.count()} ردیف، "
            f"{Activity.objects.count()} فعالیت، {Task.objects.count()} کار، "
            f"{CustomerFeedback.objects.count()} بازخورد"
        ))

    # ---- reference -------------------------------------------------------
    def _seed_stages(self):
        out = {}
        for code, name, order, kind, prob in STAGES:
            out[code], _ = PipelineStage.objects.update_or_create(
                code=code,
                defaults={"name_fa": name, "order": order, "kind": kind,
                          "probability_pct": prob, "is_active": True},
            )
        return out

    def _seed_simple(self, model, rows):
        out = {}
        for code, name in rows:
            out[code], _ = model.objects.update_or_create(
                code=code, defaults={"name_fa": name}
            )
        return out

    def _seed_sources(self):
        out = {}
        for code, name, _share, _q in SOURCES:
            out[code], _ = LeadSource.objects.update_or_create(
                code=code, defaults={"name_fa": name}
            )
        return out

    def _seed_reasons(self):
        out = {}
        for code, name, controllable in REASONS:
            out[code], _ = LostReason.objects.update_or_create(
                code=code,
                defaults={"name_fa": name, "is_controllable": controllable},
            )
        return out

    def _seed_products(self):
        cats = self._seed_simple(ProductCategory, CATEGORIES)
        out = []
        for code, name, cat, unit, price, cost in PRODUCTS:
            p, _ = Product.objects.update_or_create(
                code=code,
                defaults={"name_fa": name, "category": cats[cat], "unit": unit,
                          "list_price_rial": price, "unit_cost_rial": cost,
                          "is_active": True},
            )
            out.append(p)
        return out

    def _seed_tags(self):
        return [
            Tag.objects.get_or_create(name_fa=n, defaults={"color": c})[0]
            for n, c in TAGS
        ]

    def _reps(self):
        """
        The real salespeople, weighted by their profile.

        Ordered by REP_PROFILE, not by whatever order the database hands back.
        Every draw below is made against this list, so a different row order on
        another machine would silently produce a different dataset from the
        same seed — and "the same demo as my laptop" would stop being true.
        """
        by_name = {
            e.full_name_fa: e for e in DimEmployee.objects.filter(is_active=True)
        }
        out = [
            (by_name[name], *profile)
            for name, profile in REP_PROFILE.items()
            if name in by_name
        ]
        if not out:  # safety net if the employee dimension is empty
            emp = DimEmployee.objects.order_by("code").first()
            out = [(emp, 1.0, 0.45, 1.0, 5.0)]
        return out

    def _provinces(self):
        # Sorted by name for the same reason as _reps().
        return [
            (p, PROVINCE_WEIGHTS.get(p.name_fa, 1))
            for p in DimProvince.objects.order_by("name_fa")
        ]

    # ---- time ------------------------------------------------------------
    def _month_range(self, count: int) -> list[tuple[int, int, dt.date, dt.date]]:
        """The last `count` Jalali months, ending with the current one."""
        from apps.crm.jalali import jalali_month_of
        jy, jm = jalali_month_of(timezone.localdate())
        months = []
        for _ in range(count):
            s, e = month_bounds(jy, jm)
            months.append((jy, jm, s, e))
            jm -= 1
            if jm < 1:
                jm, jy = 12, jy - 1
        return list(reversed(months))

    def _aware(self, day: dt.date) -> dt.datetime:
        """Local midnight — filtering a DateTimeField by a bare date would be
        read as UTC and shift every Tehran month boundary by 3.5 hours."""
        return timezone.make_aware(dt.datetime.combine(day, dt.time.min))

    def _dt(self, day: dt.date, hour_from=8, hour_to=18) -> dt.datetime:
        naive = dt.datetime(
            day.year, day.month, day.day,
            self.rnd.randint(hour_from, hour_to), self.rnd.choice([0, 15, 30, 45]),
        )
        moment = timezone.make_aware(naive)
        # A working hour picked for *today* can still be in the future; demo
        # data with tomorrow's phone calls in it reads as broken.
        now = timezone.now()
        return min(moment, now) if moment > now else moment

    def _workday(self, start: dt.date, end: dt.date) -> dt.date:
        """A random date in [start, end) that is not a Friday (Iran's weekend)."""
        span = max((end - start).days, 1)
        for _ in range(6):
            d = start + dt.timedelta(days=self.rnd.randrange(span))
            if d.weekday() != 4:  # Friday
                return d
        return start + dt.timedelta(days=self.rnd.randrange(span))

    # ---- customers -------------------------------------------------------
    def _company_name(self) -> str:
        rnd = self.rnd
        return " ".join(x for x in (
            rnd.choice(CO_PREFIX), rnd.choice(CO_CORE), rnd.choice(CO_SUFFIX)
        ) if x)

    def _seed_customers(self, n, groups, sources, reps, provinces, months):
        rnd = self.rnd
        group_list = list(groups.values())
        source_codes = [c for c, *_ in SOURCES]
        source_shares = [s for _c, _n, s, _q in SOURCES]
        prov_objs = [p for p, _w in provinces]
        prov_weights = [w for _p, w in provinces]
        rep_objs = [r[0] for r in reps]
        rep_weights = [r[1] for r in reps]

        first_start = months[0][2]
        existing = Customer.objects.count()
        rows = []
        used_names = set(Customer.objects.values_list("name_fa", flat=True))

        for i in range(n):
            is_person = rnd.random() < 0.12
            for _ in range(30):
                name = (
                    f"{rnd.choice(PERSON_FIRST)} {rnd.choice(PERSON_LAST)}"
                    if is_person else self._company_name()
                )
                if name not in used_names:
                    break
            used_names.add(name)

            # Most accounts pre-date the reporting window; some arrive during it.
            if rnd.random() < 0.55:
                contact_day = first_start - dt.timedelta(days=rnd.randint(30, 900))
            else:
                jy, jm, s, e = rnd.choice(months)
                contact_day = self._workday(s, e)

            rows.append(Customer(
                code=f"cust-{existing + i + 1}",
                name_fa=name,
                kind=Customer.Kind.PERSON if is_person else Customer.Kind.COMPANY,
                status=Customer.Status.LEAD,
                group=rnd.choice(group_list),
                province=rnd.choices(prov_objs, weights=prov_weights, k=1)[0],
                city="",
                lead_source=sources[rnd.choices(source_codes, weights=source_shares, k=1)[0]],
                owner=rnd.choices(rep_objs, weights=rep_weights, k=1)[0],
                contact_name=f"{rnd.choice(PERSON_FIRST)} {rnd.choice(PERSON_LAST)}",
                phone=f"0{rnd.choice([21,26,31,51,71,41])}{rnd.randint(30000000, 89999999)}",
                mobile=f"09{rnd.choice([1,2,3,9])}{rnd.randint(10000000, 99999999)}",
                email="",
                national_id=str(rnd.randint(10_000_000_000, 14_999_999_999)),
                first_contact_at=self._dt(contact_day),
                channel="team",
            ))
        Customer.objects.bulk_create(rows, batch_size=500)
        self.stdout.write(f"  · {len(rows)} مشتری ساخته شد")
        return list(Customer.objects.select_related("owner", "group", "province",
                                                    "lead_source").all())

    # ---- deals -----------------------------------------------------------
    def _seed_deals(self, months, customers, reps, stages, sources, reasons,
                    products, tags):
        rnd = self.rnd
        open_stages = [stages[c] for c, _n, _o, k, _p in STAGES if k == "open"]
        won_stage, lost_stage = stages["settled"], stages["lost"]
        reason_codes = [c for c, *_ in REASONS]
        source_quality = {c: q for c, _n, _s, q in SOURCES}
        # Each rep's book, sorted by when the account was first contacted, so
        # a deal can only be opened against a customer that already existed.
        # Without this, ~5% of accounts had their first win dated before their
        # own first contact.
        import bisect
        by_owner: dict[int, list[Customer]] = {}
        for c in customers:
            by_owner.setdefault(c.owner_id, []).append(c)
        for lst in by_owner.values():
            lst.sort(key=lambda c: c.first_contact_at)
        owner_dates: dict[int, list] = {
            oid: [c.first_contact_at for c in lst] for oid, lst in by_owner.items()
        }

        rep_by_id = {r[0].id: r for r in reps}
        deal_rows, item_rows, event_rows, activity_rows = [], [], [], []
        seq = Deal.objects.count()
        today = timezone.localdate()

        for m_idx, (jy, jm, m_start, m_end) in enumerate(months):
            period = period_for(m_start)
            # Gentle growth plus seasonality: Nowruz (فروردین) is slow,
            # اسفند and تیر are peaks.
            season = {1: 0.55, 12: 1.35, 4: 1.20, 5: 1.05}.get(jm, 1.0)
            growth = 1 + 0.035 * m_idx
            month_deals = int(58 * season * growth)
            # The current month is only partially elapsed.
            partial = m_end > today
            if partial:
                elapsed = max((today - m_start).days, 1) / max((m_end - m_start).days, 1)
                month_deals = max(int(month_deals * elapsed), 3)

            for _ in range(month_deals):
                rep, _share, win_rate, size_factor, _cpd = rnd.choices(
                    reps, weights=[r[1] for r in reps], k=1
                )[0]
                open_day = self._workday(m_start, min(m_end, today + dt.timedelta(days=1)))
                opened_at = self._dt(open_day)

                pool = by_owner.get(rep.id) or []
                # Only accounts that already existed on the day the deal opened.
                eligible = bisect.bisect_right(owner_dates.get(rep.id, []), opened_at)
                if eligible:
                    customer = pool[rnd.randrange(eligible)]
                else:
                    continue  # this rep had no customers yet that early
                source = customer.lead_source
                quality = source_quality.get(source.code if source else "", 1.0)

                # ---- lines ------------------------------------------------
                n_items = rnd.choices([1, 2, 3, 4], weights=[45, 32, 16, 7], k=1)[0]
                chosen = rnd.sample(products, k=min(n_items, len(products)))
                gross = cost = Decimal(0)
                lines = []
                for prod in chosen:
                    if prod.unit == "ton":
                        qty = Decimal(rnd.choice(["0.50", "1.00", "1.50", "2.00", "3.00"]))
                    elif prod.unit == "sheet":
                        qty = Decimal(rnd.randrange(500, 6000, 500))
                    else:
                        qty = Decimal(rnd.randrange(20, 900, 10))
                    qty = (qty * Decimal(str(round(size_factor, 2)))).quantize(Decimal("0.01"))
                    if qty <= 0:
                        qty = Decimal("1.00")
                    # Price drifts a little around the list price; discounts are
                    # what later explain thin margins.
                    price = (prod.list_price_rial * Decimal(str(rnd.uniform(0.94, 1.08)))).quantize(Decimal(1))
                    discount = Decimal(str(rnd.choices([0, 2, 5, 8, 12], weights=[45, 20, 18, 11, 6], k=1)[0]))
                    line_total = (qty * price * (Decimal(100) - discount) / Decimal(100)).quantize(Decimal(1))
                    line_cost = (qty * prod.unit_cost_rial).quantize(Decimal(1))
                    gross += line_total
                    cost += line_cost
                    lines.append((prod, qty, price, discount))

                deal_discount = Decimal(0)
                if rnd.random() < 0.18:
                    deal_discount = (gross * Decimal(str(rnd.uniform(0.01, 0.04)))).quantize(Decimal(1))
                shipping = Decimal(rnd.randrange(2_000_000, 45_000_000, 500_000))
                other = Decimal(rnd.randrange(0, 12_000_000, 500_000))

                amount = gross - deal_discount
                total_cost = cost + shipping + other

                # ---- outcome ----------------------------------------------
                p_win = min(max(win_rate * quality, 0.05), 0.92)
                # Big deals are harder to close.
                if amount > Decimal(2_000_000_000):
                    p_win *= 0.75
                roll = rnd.random()
                age_limit = (today - open_day).days

                if age_limit < 6:
                    outcome = "open"           # too fresh to have closed
                elif roll < p_win:
                    outcome = "won"
                elif roll < p_win + (1 - p_win) * 0.62:
                    outcome = "lost"
                else:
                    outcome = "open"

                cycle = max(int(rnd.gauss(21, 11)), 2)
                seq += 1
                code = f"deal-{seq}"

                if outcome == "open":
                    stage = rnd.choices(
                        open_stages,
                        weights=[30, 22, 16, 11, 8, 6, 4, 3][:len(open_stages)],
                        k=1,
                    )[0]
                    closed_at, close_period, status = None, None, "open"
                    reason = None
                else:
                    cycle = min(cycle, max(age_limit, 2))
                    close_day = open_day + dt.timedelta(days=cycle)
                    if close_day > today:
                        close_day = today
                    closed_at = self._dt(close_day)
                    close_period = period_for(close_day)
                    if outcome == "won":
                        stage, status, reason = won_stage, "won", None
                    else:
                        stage, status = lost_stage, "lost"
                        # The loss reason follows what actually happened.
                        if deal_discount or any(l[3] >= 8 for l in lines):
                            weights = {"price": 34, "competitor": 26, "delay": 10,
                                       "quality": 6, "no_need": 10, "no_budget": 8,
                                       "no_answer": 4, "other": 2}
                        elif cycle > 30:
                            weights = {"delay": 30, "competitor": 22, "no_answer": 16,
                                       "price": 12, "no_need": 10, "no_budget": 6,
                                       "quality": 3, "other": 1}
                        else:
                            weights = {"competitor": 30, "price": 20, "no_need": 16,
                                       "no_budget": 12, "no_answer": 9, "delay": 7,
                                       "quality": 4, "other": 2}
                        reason = reasons[rnd.choices(
                            reason_codes, weights=[weights[c] for c in reason_codes], k=1
                        )[0]]

                deal = Deal(
                    code=code,
                    title=f"{rnd.choice(['فروش', 'سفارش', 'قرارداد'])} "
                          f"{chosen[0].name_fa} — {customer.name_fa}",
                    customer=customer, owner=rep, stage=stage, status=status,
                    channel="team", lead_source=source, lost_reason=reason,
                    amount_rial=amount, cost_rial=total_cost,
                    profit_rial=amount - total_cost,
                    discount_rial=deal_discount, shipping_cost_rial=shipping,
                    other_cost_rial=other,
                    opened_at=opened_at,
                    expected_close_date=open_day + dt.timedelta(days=rnd.randint(10, 45)),
                    closed_at=closed_at, period=period, close_period=close_period,
                )
                deal_rows.append((deal, lines, stage, outcome, open_day, cycle, rep, customer))

        # ---- persist ---------------------------------------------------
        Deal.objects.bulk_create([d for d, *_ in deal_rows], batch_size=400)
        saved = {d.code: d for d in Deal.objects.filter(
            code__in=[d.code for d, *_ in deal_rows]
        )}

        for deal, lines, stage, outcome, open_day, cycle, rep, customer in deal_rows:
            obj = saved[deal.code]
            for prod, qty, price, discount in lines:
                item_rows.append(DealItem(
                    deal=obj, product=prod, quantity=qty,
                    unit_price_rial=price, unit_cost_rial=prod.unit_cost_rial,
                    discount_pct=discount,
                ))
            event_rows.extend(self._stage_events(obj, stage, outcome, open_day, cycle))
            activity_rows.extend(
                self._deal_activities(obj, rep, customer, open_day, cycle, outcome)
            )

        DealItem.objects.bulk_create(item_rows, batch_size=800)
        DealStageEvent.objects.bulk_create(event_rows, batch_size=800)
        Activity.objects.bulk_create(activity_rows, batch_size=1000)

        self._mark_first_wins()
        self.stdout.write(
            f"  · {len(deal_rows)} معامله، {len(item_rows)} ردیف، "
            f"{len(activity_rows)} فعالیت مرتبط با معاملات"
        )

    def _stage_events(self, deal, final_stage, outcome, open_day, cycle):
        """Walk the deal through the pipeline so the funnel has real history."""
        rnd = self.rnd
        ordered = list(PipelineStage.objects.filter(kind="open").order_by("order"))
        target_index = (
            len(ordered) - 1 if outcome == "won"
            else ordered.index(final_stage) if final_stage in ordered
            else rnd.randint(0, len(ordered) - 1)
        )
        events, prev, at = [], None, deal.opened_at
        steps = ordered[: target_index + 1]
        # Spread the steps across the deal's REAL open interval, in seconds.
        # Stepping by whole days from opened_at overshot closed_at (whose hour
        # is independent), so a deal's history could list a mid-pipeline stage
        # after the win.
        # An open deal's transitions must all have already happened.
        end = deal.closed_at or min(
            deal.opened_at + dt.timedelta(days=max(cycle, 1)), timezone.now()
        )
        total = max((end - deal.opened_at).total_seconds(), 60)
        for i, st in enumerate(steps):
            moment = deal.opened_at + dt.timedelta(
                seconds=total * (i / max(len(steps), 1))
            )
            events.append(DealStageEvent(
                deal=deal, from_stage=prev, to_stage=st, at=moment,
                days_in_previous=max((moment - at).days, 0) if prev else 0,
            ))
            prev, at = st, moment
        if outcome in {"won", "lost"} and deal.closed_at:
            events.append(DealStageEvent(
                deal=deal, from_stage=prev, to_stage=final_stage,
                at=deal.closed_at,
                days_in_previous=max((deal.closed_at - at).days, 0),
            ))
        return events

    def _deal_activities(self, deal, rep, customer, open_day, cycle, outcome):
        """The touches that moved (or failed to move) this deal."""
        rnd = self.rnd
        acts = []
        span = max(cycle, 3)

        def add(kind, day_offset, result=None, minutes=None):
            day = open_day + dt.timedelta(days=min(day_offset, span))
            if day > timezone.localdate():
                return
            at = self._dt(day)
            # Same-day activities can draw an earlier working hour than the
            # deal's own opening hour; nudge them past it so no touch is dated
            # before the opportunity it belongs to.
            if at < deal.opened_at:
                at = deal.opened_at + dt.timedelta(minutes=rnd.randint(5, 90))
                if at > timezone.now():
                    return
            # ...and nothing may happen on a deal after it closed. The day
            # offsets are approximate, and the cycle gets clamped against
            # today, so the tail of the sequence can otherwise overshoot.
            if deal.closed_at and at > deal.closed_at:
                at = deal.closed_at - dt.timedelta(minutes=rnd.randint(1, 120))
                if at < deal.opened_at:
                    at = deal.opened_at + (deal.closed_at - deal.opened_at) / 2
            acts.append(Activity(
                kind=kind, customer=customer, deal=deal, owner=rep, at=at,
                duration_min=minutes if minutes is not None else rnd.randint(2, 25),
                result=result or rnd.choices(
                    ["success", "follow_up", "no_answer", "failed"],
                    weights=[58, 24, 13, 5], k=1,
                )[0],
                note=rnd.choice(ACTIVITY_NOTES.get(kind, [""])),
                period=period_for(day),
            ))

        add("call_in" if rnd.random() < 0.35 else "call_out", 0, "success")
        if rnd.random() < 0.72:
            add("quote", rnd.randint(1, 4), "success")
        if rnd.random() < 0.34:
            add("sample", rnd.randint(2, 6), "success")
        if rnd.random() < 0.22:
            add("meeting", rnd.randint(3, 10), "success", rnd.randint(30, 90))
        # Follow-up calls are the bulk of the workload — a rep chases a deal
        # several times before it resolves.
        for _ in range(rnd.randint(2, 9)):
            add("call_out", rnd.randint(1, span))
        if rnd.random() < 0.4:
            add("message", rnd.randint(1, span), "success", 1)
        if outcome == "won":
            add("order", span - 2, "success")
            add("invoice", span - 1, "success")
            if rnd.random() < 0.8:
                add("payment", span, "success")
        return acts

    def _mark_first_wins(self):
        """Set Customer.first_deal_won_at / status from the generated deals."""
        first: dict[int, dt.datetime] = {}
        for cid, closed in Deal.objects.filter(
            status="won", closed_at__isnull=False
        ).values_list("customer_id", "closed_at"):
            if cid not in first or closed < first[cid]:
                first[cid] = closed

        updates = []
        cutoff = timezone.now() - dt.timedelta(days=150)
        for c in Customer.objects.all().only(
            "id", "first_deal_won_at", "status", "last_activity_at"
        ):
            won_at = first.get(c.id)
            c.first_deal_won_at = won_at
            if won_at:
                c.status = (
                    Customer.Status.ACTIVE if won_at >= cutoff
                    else Customer.Status.DORMANT
                )
            else:
                c.status = (
                    Customer.Status.LOST
                    if Deal.objects.filter(customer_id=c.id, status="lost").exists()
                    else Customer.Status.LEAD
                )
            updates.append(c)
        Customer.objects.bulk_update(updates, ["first_deal_won_at", "status"], batch_size=500)

        # last_activity_at, straight from the activity log.
        last: dict[int, dt.datetime] = {}
        for cid, at in Activity.objects.values_list("customer_id", "at"):
            if cid not in last or at > last[cid]:
                last[cid] = at
        touched = []
        for c in Customer.objects.filter(id__in=last.keys()).only("id", "last_activity_at"):
            c.last_activity_at = last[c.id]
            touched.append(c)
        Customer.objects.bulk_update(touched, ["last_activity_at"], batch_size=500)

    # ---- everything else -------------------------------------------------
    def _seed_standalone_activities(self, months, customers, reps):
        """Calls and messages that are not attached to any deal — prospecting,
        support, courtesy calls. Without these the activity report would make
        the team look like it only ever touches live opportunities."""
        rnd = self.rnd
        rows = []
        today = timezone.localdate()
        for jy, jm, s, e in months:
            end = min(e, today + dt.timedelta(days=1))
            if end <= s:
                continue
            for _ in range(rnd.randint(90, 170)):
                customer = rnd.choice(customers)
                rep = customer.owner or rnd.choice([r[0] for r in reps])
                day = self._workday(s, end)
                kind = rnd.choices(
                    ["call_out", "call_in", "message", "quote", "meeting"],
                    weights=[62, 16, 12, 7, 3], k=1,
                )[0]
                rows.append(Activity(
                    kind=kind, customer=customer, deal=None, owner=rep,
                    at=self._dt(day), duration_min=rnd.randint(1, 18),
                    result=rnd.choices(
                        ["success", "no_answer", "follow_up", "failed"],
                        weights=[44, 30, 20, 6], k=1,
                    )[0],
                    note=rnd.choice(ACTIVITY_NOTES.get(kind, [""])),
                    period=period_for(day),
                ))
        Activity.objects.bulk_create(rows, batch_size=1000)
        self.stdout.write(f"  · {len(rows)} فعالیت مستقل")

    def _seed_feedback(self, customers, reps):
        rnd = self.rnd
        rows = []
        # Re-read from the DB: `customers` was captured before any deal existed,
        # so its first_deal_won_at values are all still None.
        pool = list(
            Customer.objects.filter(first_deal_won_at__isnull=False)
            .select_related("owner").order_by("code")
        )
        for customer in rnd.sample(pool, k=min(len(pool), 180)):
            # Score skews positive, but each rep has a different tail.
            base = {"هستی خانی": 4.4, "مهدیس مومنی": 4.1, "مهسا احمدی": 4.3,
                    "صبا موسوی": 3.8, "هانیه منزه": 3.6}.get(
                customer.owner.full_name_fa if customer.owner else "", 4.0)
            score = int(max(1, min(5, round(rnd.gauss(base, 1.0)))))
            at = customer.first_deal_won_at + dt.timedelta(days=rnd.randint(3, 40))
            if at > timezone.now():
                at = timezone.now() - dt.timedelta(days=rnd.randint(1, 20))
            rows.append(CustomerFeedback(
                customer=customer, employee=customer.owner, score=score,
                note="" if score >= 3 else rnd.choice([
                    "تاخیر در تحویل سفارش", "پاسخگویی کند", "کیفیت رول مطابق نمونه نبود",
                    "اختلاف در فاکتور",
                ]),
                at=at, period=period_for(at),
            ))
        CustomerFeedback.objects.bulk_create(rows, batch_size=500)
        self.stdout.write(f"  · {len(rows)} بازخورد مشتری")

    def _seed_tasks(self, customers, reps):
        rnd = self.rnd
        rows = []
        now = timezone.now()
        open_deals = list(Deal.objects.filter(status="open").select_related("customer").order_by("-opened_at", "code")[:400])
        for deal in open_deals:
            if rnd.random() > 0.55:
                continue
            due = now + dt.timedelta(days=rnd.randint(-14, 21),
                                     hours=rnd.randint(0, 8))
            rows.append(Task(
                title=rnd.choice([
                    "پیگیری پیش‌فاکتور", "تماس یادآوری تسویه", "ارسال نمونه",
                    "هماهنگی جلسه", "ارسال کاتالوگ جدید", "پیگیری تایید فنی",
                ]),
                customer=deal.customer, deal=deal, owner=deal.owner,
                kind=rnd.choice(["call_out", "meeting", "sample", "quote"]),
                due_at=due,
                done_at=now - dt.timedelta(days=rnd.randint(1, 10))
                if rnd.random() < 0.35 else None,
            ))
        Task.objects.bulk_create(rows, batch_size=500)
        self.stdout.write(f"  · {len(rows)} کار/یادآوری")

    def _seed_province_targets(self, months):
        """
        Give every province a monthly target for the team channel, derived
        from what it actually sold (±15%). The provinces report reads targets
        from sales.FactSalesProvince, so this is what makes the achievement
        column meaningful instead of empty.
        """
        rnd = self.rnd
        from django.db.models import Sum

        # Written to the CRM's OWN table, never to sales.FactSalesProvince or
        # sales.SalesTarget. Those hold the company's real plan; a demo that
        # overwrites them corrupts the live dashboards the moment it is
        # installed beside them. The provinces report prefers the real target
        # and only falls back to these.
        province_ids = list(DimProvince.objects.order_by("name_fa").values_list("id", flat=True))
        created = 0
        for jy, jm, s, e in months:
            period = period_for(s)
            actual = {
                r["customer__province_id"]: r["total"] or 0
                for r in Deal.objects.filter(
                    status="won", channel="team",
                    closed_at__gte=self._aware(s), closed_at__lt=self._aware(e),
                )
                .values("customer__province_id")
                .annotate(total=Sum("amount_rial"))
            }
            for pid in province_ids:
                sold = Decimal(actual.get(pid, 0))
                # Where nothing sold, still set a modest target — a province
                # with no sales and no target would silently look "on plan".
                target = (
                    sold * Decimal(str(rnd.uniform(0.85, 1.25)))
                    if sold
                    else Decimal(rnd.randrange(500_000_000, 3_000_000_000, 100_000_000))
                )
                DemoProvinceTarget.objects.update_or_create(
                    period=period, province_id=pid, channel="team",
                    defaults={"target_rial": target.quantize(Decimal(1))},
                )
                created += 1
        self.stdout.write(f"  · {created} ردیف تارگت استانی (جدول دمو)")
