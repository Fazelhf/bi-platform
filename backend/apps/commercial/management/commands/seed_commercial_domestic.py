"""
Fill بازرگانی داخلی with a year of plausible purchasing history.

A management command, never a data migration. `deploy.sh` runs `migrate` and
nothing else, so anything seeded from a migration lands on the CEO's screen in
production as if the company had really bought it. This has to be asked for.

    python manage.py seed_commercial_domestic              # ۱۲ ماه گذشته
    python manage.py seed_commercial_domestic --months 18
    python manage.py seed_commercial_domestic --clear      # هرچه ساخته را برمی‌دارد

What it makes is a *shape*, not noise. The reports this module exists for only
say something when the data has the structure real purchasing has:

* **Prices climb.** Each material has its own monthly rate, so «افزایش قیمت»
  has a real slope to report instead of a flat line with jitter on it.
* **Losers are recorded with reasons.** Every استعلام gets three suppliers and
  every one that lost carries a دلیل — that file is the whole point of the
  module, and a seed without it leaves تحلیل تامین‌کنندگان empty.
* **One supplier is consistently expensive.** «بازرگانی کیمیا مواد» quotes
  ~۱۴٪ over everyone else, so the win-rate column has something to separate.
  A seed where every supplier wins equally teaches the page nothing.
* **Age drives status.** Old orders are delivered, this week's are still
  pending, and the newest استعلام‌ها have no winner yet — otherwise درخواست‌ها
  opens with an empty work list on a database that is supposedly full.

Everything it writes is tagged in `note`, and `--clear` removes exactly that
and nothing else, so it can be run on a database that already has real rows.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import ProtectedError

from apps.accounts.models import Department, User
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
from apps.commercial.services.base import month_key, step
from apps.core import jalali
from apps.core.models import DimPeriod, PeriodKind

#: Stamped into `note` on everything this command writes. `--clear` deletes by
#: it, which is why it must be a string nobody would type by accident.
SEED_TAG = "[نمونه بازرگانی داخلی]"

#: Fixed, so two runs on the same day produce the same figures. A seed that
#: reshuffles itself makes «این عدد دیروز فرق داشت» a bug report.
RNG_SEED = 1405


# code, name, category, unit, base price (Rial), monthly rise, qty, min stock,
# every N months, requesting unit
#
# The quantities are chosen so no single line owns the chart. مواد اولیه leads,
# as it should in a paper mill, but by a factor the eye can read — a material
# worth ten times every other bar turns «پرخریدترین کالاها» into one bar and
# nine slivers, and the page stops answering the question it was built for.
MATERIALS = [
    ("shrink-film", "نوار شیرینگ ۵۰ میکرون", "packaging", MaterialUnit.ROLL,
     4_800_000, 0.030, 120, 40, 1, "واحد بسته‌بندی"),
    ("carton-5ply", "کارتن ۵ لایه چاپ‌دار", "packaging", MaterialUnit.PIECE,
     185_000, 0.028, 4_000, 1_000, 1, "واحد بسته‌بندی"),
    ("paper-core", "مغزی مقوایی رول ۷۶ میلی‌متر", "packaging", MaterialUnit.PIECE,
     320_000, 0.032, 2_500, 600, 1, "خط تولید"),
    ("wooden-pallet", "پالت چوبی ۱۰۰×۱۲۰", "packaging", MaterialUnit.PIECE,
     1_450_000, 0.025, 400, 120, 2, "انبار محصول"),
    ("hotmelt-glue", "چسب هات‌ملت گرانولی", "raw-material", MaterialUnit.KILO,
     2_750_000, 0.035, 300, 100, 1, "خط تولید"),
    ("cationic-starch", "نشاسته کاتیونی", "raw-material", MaterialUnit.KILO,
     890_000, 0.033, 1_500, 400, 1, "خط تولید"),
    ("antifoam", "آنتی‌فوم سیلیکونی", "raw-material", MaterialUnit.LITER,
     1_980_000, 0.030, 250, 80, 2, "خط تولید"),
    ("hydraulic-oil", "روغن هیدرولیک ISO 68", "consumables", MaterialUnit.LITER,
     640_000, 0.026, 600, 200, 2, "تعمیرات و نگهداری"),
    ("bearing-skf", "یاتاقان SKF 22320", "spare-parts", MaterialUnit.PIECE,
     42_000_000, 0.022, 8, 3, 3, "تعمیرات و نگهداری"),
    ("a4-paper", "کاغذ A4 ۸۰ گرمی", "office", MaterialUnit.PACK,
     1_150_000, 0.024, 120, 40, 3, "اداری"),
]

# code, name, contact, mobile, activity, price factor, delivery days
SUPPLIERS = [
    ("alborz-plastic", "پلاستیک‌سازی البرز", "رضا کریمی", "09121234501",
     "فیلم و نایلون بسته‌بندی", 1.00, 7),
    ("pars-carton", "کارتن‌سازی پارس مقوا", "مهدی رستمی", "09121234502",
     "کارتن و ورق مقوایی", 0.97, 10),
    ("esfahan-core", "مقوا و مغزی اصفهان", "حسین دادگر", "09121234503",
     "مغزی و لوله مقوایی", 0.98, 9),
    ("zagros-pallet", "صنایع چوب زاگرس", "علی نجفی", "09121234504",
     "پالت چوبی و جعبه صنعتی", 1.00, 12),
    ("shimi-peyvand", "شیمی پیوند تهران", "سمیرا فتحی", "09121234505",
     "چسب و مواد شیمیایی", 1.05, 6),
    ("glucosan", "نشاسته گلوکزان کرمانشاه", "فرشاد امینی", "09121234506",
     "نشاسته و مشتقات آن", 1.02, 14),
    ("aria-bearing", "بازرگانی فنی آریا", "بابک صادقی", "09121234507",
     "بلبرینگ و قطعات صنعتی", 1.08, 20),
    ("sepahan-lube", "روانکار سپاهان", "محسن یاوری", "09121234508",
     "روغن و گریس صنعتی", 0.99, 8),
    ("nikara-office", "تجهیزات اداری نیک‌آرا", "الهام رحیمی", "09121234509",
     "ملزومات اداری و اداری‌جات", 1.03, 4),
    # The expensive one. Quotes everything, wins almost nothing — which is what
    # gives «درصد برد» and «قیمت بالا» a number worth looking at.
    ("kimia-mavad", "بازرگانی کیمیا مواد", "جواد ملکی", "09121234510",
     "واسطه مواد شیمیایی و بسته‌بندی", 1.14, 16),
]

#: Who is asked for each material. Three names wherever the market really has
#: three — a two-row comparison table is not a comparison.
CANDIDATES = {
    "shrink-film": ["alborz-plastic", "kimia-mavad", "pars-carton"],
    "carton-5ply": ["pars-carton", "esfahan-core", "kimia-mavad"],
    "paper-core": ["esfahan-core", "pars-carton", "kimia-mavad"],
    "wooden-pallet": ["zagros-pallet", "kimia-mavad"],
    "hotmelt-glue": ["shimi-peyvand", "kimia-mavad", "alborz-plastic"],
    "cationic-starch": ["glucosan", "shimi-peyvand", "kimia-mavad"],
    "antifoam": ["shimi-peyvand", "glucosan", "kimia-mavad"],
    "hydraulic-oil": ["sepahan-lube", "aria-bearing", "kimia-mavad"],
    "bearing-skf": ["aria-bearing", "sepahan-lube"],
    "a4-paper": ["nikara-office", "kimia-mavad"],
}

#: Materials where the cheapest quote does not always win — a bearing or a
#: chemical is bought on brand as often as on price.
QUALITY_LED = {"bearing-skf", "hotmelt-glue", "antifoam", "cationic-starch"}


class Command(BaseCommand):
    help = "Load a year of sample بازرگانی داخلی purchasing (demo data — opt-in)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--months", type=int, default=12,
            help="چند ماه گذشته ساخته شود (پیش‌فرض ۱۲)",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="فقط داده‌های نمونه را حذف کن و خارج شو.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self._clear_all()
            return

        months = max(1, min(options["months"], 48))
        rng = random.Random(RNG_SEED)
        today = date.today()

        removed = self._clear_documents()
        if removed:
            self.stdout.write(f"  {removed} سند نمونه قبلی حذف شد.")

        reasons = {r.code: r for r in QuoteReason.objects.all()}
        if "good-price" not in reasons:
            self.stderr.write(
                "دلایل انتخاب/رد یافت نشد — مایگریشن‌های commercial اجرا نشده‌اند."
            )
            raise SystemExit(1)

        author = (
            User.objects.filter(
                department=Department.COMMERCIAL, is_active=True
            ).first()
            or User.objects.filter(is_superuser=True).first()
        )

        materials = self._materials()
        suppliers = self._suppliers()
        periods = self._periods()

        window = self._month_window(today, months)
        requests, quotes, orders = self._write_history(
            rng, today, window, materials, suppliers, reasons, periods, author
        )

        self.stdout.write(self.style.SUCCESS(
            f"{len(materials)} کالا، {len(suppliers)} تامین‌کننده، "
            f"{requests} درخواست، {quotes} استعلام و {orders} سفارش خرید "
            f"در {months} ماه گذشته ثبت شد."
        ))

    # -- reference rows --------------------------------------------------
    def _materials(self) -> dict[str, Material]:
        categories = {c.code: c for c in MaterialCategory.objects.all()}
        out = {}
        for code, name, cat, unit, _p, _r, _q, min_stock, _e, _u in MATERIALS:
            out[code] = Material.objects.update_or_create(
                code=code,
                defaults={
                    "name_fa": name,
                    "category": categories.get(cat),
                    "unit": unit,
                    "min_stock": Decimal(min_stock),
                    "is_active": True,
                    "note": SEED_TAG,
                },
            )[0]
        return out

    def _suppliers(self) -> dict[str, Supplier]:
        out = {}
        for code, name, contact, mobile, activity, _f, _d in SUPPLIERS:
            out[code] = Supplier.objects.update_or_create(
                code=code,
                defaults={
                    "name_fa": name,
                    "origin": Supplier.Origin.DOMESTIC,
                    "contact_name": contact,
                    "mobile": mobile,
                    "activity": activity,
                    "is_active": True,
                    "note": SEED_TAG,
                },
            )[0]
        return out

    @staticmethod
    def _periods() -> dict[tuple[int, int], DimPeriod]:
        """
        The month rows purchases hang off, where they exist.

        Missing months are fine and deliberately not created here: the reports
        bucket by `ordered_on`, and the period tree is seeded on purpose by
        someone who decided which years the platform reports on.
        """
        return {
            (p.jalali_year, p.jalali_month): p
            for p in DimPeriod.objects.filter(kind=PeriodKind.MONTH)
        }

    @staticmethod
    def _month_window(today: date, months: int) -> list[tuple[int, int]]:
        current = month_key(today)
        return [step(current, -(months - 1) + i) for i in range(months)]

    # -- the history itself ----------------------------------------------
    def _write_history(
        self, rng, today, window, materials, suppliers, reasons, periods, author
    ) -> tuple[int, int, int]:
        n_requests = n_quotes = n_orders = 0

        for i, key in enumerate(window):
            for m_index, spec in enumerate(MATERIALS):
                (code, _name, _cat, _unit, base, rise, qty,
                 _min_stock, every, unit_name) = spec
                # Stagger the materials so each month has a mix rather than
                # every quarterly item landing in the same month.
                if (i + m_index) % every:
                    continue

                on = self._day_in(key, rng, today)
                if on is None or on > today:
                    continue

                age = (today - on).days
                # Recent requests are allowed to be unfinished. A seed where
                # every استعلام already has a winner leaves درخواست‌ها opening
                # on an empty work list with a full database behind it.
                waiting_for_quotes = age < 12 and rng.random() < 0.25
                undecided = age < 28 and rng.random() < 0.30

                request = PurchaseRequest.objects.create(
                    material=materials[code],
                    quantity=self._quantity(rng, qty),
                    requester_unit=unit_name,
                    requested_on=on,
                    needed_by=on + timedelta(days=rng.randint(18, 35)),
                    period=periods.get(key),
                    status=(
                        PurchaseRequest.Status.OPEN if waiting_for_quotes
                        else PurchaseRequest.Status.QUOTING
                    ),
                    note=SEED_TAG,
                    created_by=author,
                )
                n_requests += 1

                if waiting_for_quotes:
                    continue

                quotes = self._write_quotes(
                    rng, request, code, base, rise, i, suppliers, on
                )
                n_quotes += len(quotes)

                if undecided or not quotes:
                    continue

                winner = self._award(rng, request, code, quotes, reasons)
                order = self._write_order(
                    rng, today, request, winner, periods, author
                )
                if order:
                    n_orders += 1

        return n_requests, n_quotes, n_orders

    def _write_quotes(
        self, rng, request, code, base, rise, month_index, suppliers, on
    ) -> list[Quote]:
        """One price per candidate supplier, all for the same month's market."""
        market = Decimal(base) * Decimal(str((1 + rise) ** month_index))
        out = []
        for supplier_code in CANDIDATES[code]:
            factor, delivery = self._supplier_terms(supplier_code)
            # ±4٪ of personal spread on top of the supplier's standing level,
            # so two استعلام from the same pair are not identical.
            spread = Decimal(str(rng.uniform(0.96, 1.04)))
            price = _round_price(market * Decimal(str(factor)) * spread)
            out.append(Quote.objects.create(
                request=request,
                supplier=suppliers[supplier_code],
                unit_price_rial=price,
                quoted_on=on + timedelta(days=rng.randint(1, 4)),
                delivery_days=max(1, delivery + rng.randint(-2, 4)),
                validity_days=rng.choice([15, 15, 30]),
            ))
        return out

    def _award(self, rng, request, code, quotes, reasons) -> Quote:
        """
        Pick the winner and write a reason on every row, winner and losers.

        Mostly the cheapest — but not always, because a seed where price alone
        decides makes «کیفیت بهتر» a reason that exists in the dropdown and
        never in the data.
        """
        ranked = sorted(quotes, key=lambda q: q.unit_price_rial)
        fastest = min(quotes, key=lambda q: q.delivery_days)
        slowest = max(quotes, key=lambda q: q.delivery_days)

        roll = rng.random()
        # Sometimes the cheapest simply cannot supply, and the buy goes to
        # whoever can. This is the only route by which an expensive supplier
        # ever wins — which is what stops «درصد برد» being a pure ranking of
        # price and makes «عدم موجودی» a reason with data behind it.
        stockout = roll > 0.94 and len(ranked) > 1

        if stockout:
            winner, win_reason = ranked[-1], "past-cooperation"
        elif code in QUALITY_LED and len(ranked) > 1 and roll < 0.35:
            winner, win_reason = ranked[1], "better-quality"
        elif fastest is not ranked[0] and roll > 0.86:
            winner, win_reason = fastest, "faster-delivery"
        else:
            winner, win_reason = ranked[0], "good-price"

        winner.is_selected = True
        winner.reason = reasons.get(win_reason)
        winner.decision_note = (
            "تنها تامین‌کننده‌ای که موجودی داشت." if stockout else ""
        )
        winner.save(update_fields=["is_selected", "reason", "decision_note"])

        for quote in quotes:
            if quote.pk == winner.pk:
                continue
            if stockout:
                lose = "out-of-stock"
            elif quote.pk == slowest.pk and slowest.delivery_days > winner.delivery_days + 6:
                lose = "late-delivery"
            elif quote.unit_price_rial > winner.unit_price_rial:
                lose = "high-price"
            else:
                lose = "low-quality"
            quote.reason = reasons.get(lose)
            quote.save(update_fields=["reason"])

        request.status = PurchaseRequest.Status.AWARDED
        request.save(update_fields=["status"])
        return winner

    def _write_order(self, rng, today, request, winner, periods, author):
        """
        Turn a won استعلام into a purchase, aged by how long ago it was placed.

        A cancelled order keeps its row: reports have to exclude it, and they
        can only be shown to do that if one exists.
        """
        ordered_on = request.requested_on + timedelta(days=rng.randint(2, 6))
        if ordered_on > today:
            return None

        age = (today - ordered_on).days
        if rng.random() < 0.05:
            status, delivered_on = PurchaseOrder.Status.CANCELLED, None
        elif age > 45:
            status = PurchaseOrder.Status.DELIVERED
            delivered_on = ordered_on + timedelta(
                days=max(1, winner.delivery_days + rng.randint(-2, 9))
            )
            delivered_on = min(delivered_on, today)
        elif age > 20:
            status, delivered_on = PurchaseOrder.Status.SHIPPED, None
        elif age > 7:
            status, delivered_on = PurchaseOrder.Status.BUYING, None
        else:
            status, delivered_on = PurchaseOrder.Status.PENDING, None

        order = PurchaseOrder.objects.create(
            request=request,
            quote=winner,
            supplier=winner.supplier,
            material=request.material,
            quantity=request.quantity,
            unit_price_rial=winner.unit_price_rial,
            ordered_on=ordered_on,
            delivered_on=delivered_on,
            period=periods.get(month_key(ordered_on)),
            status=status,
            note=SEED_TAG,
            created_by=author,
        )
        if status != PurchaseOrder.Status.CANCELLED:
            request.status = PurchaseRequest.Status.ORDERED
            request.save(update_fields=["status"])
        return order

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _supplier_terms(code: str) -> tuple[float, int]:
        for row in SUPPLIERS:
            if row[0] == code:
                return row[5], row[6]
        return 1.0, 10

    @staticmethod
    def _quantity(rng, typical: int) -> Decimal:
        # Deliberately a narrow band. A factory's monthly consumption of a
        # given consumable moves by a few percent, not by half, and wide
        # jitter here shows up at the far end as a forecast that reports «کم»
        # confidence on every material — the seed telling the page it is
        # broken when it is only being fed noise.
        value = typical * rng.uniform(0.9, 1.12)
        # Keep round numbers round: nobody orders ۱٬۸۳۷ کارتن.
        grain = 100 if typical >= 1000 else (10 if typical >= 100 else 1)
        return Decimal(max(grain, round(value / grain) * grain))

    @staticmethod
    def _day_in(key: tuple[int, int], rng, today: date) -> date | None:
        """
        A Gregorian date inside a Jalali month, never later than today.

        The running month is *clamped* rather than resampled: drawing a day at
        random and discarding the ones past today would silently drop roughly
        half of this month's purchases, and the current month would open the
        dashboard looking like a slow one every time.
        """
        year, month = key
        last = jalali.month_days(year, month)
        jy, jm, jd = jalali.from_gregorian(today)
        if (jy, jm) == key:
            last = min(last, jd)
        if last < 1:
            return None
        # Stay clear of the month's last few days. The order follows its
        # request by two to six days, and a request raised on the ۲۹th books
        # its purchase in the *next* month — which shows up in every monthly
        # series as an empty month beside a double one, and reads as a supply
        # problem rather than as the calendar it is.
        day = rng.randint(1, max(1, last - 6))
        return jalali.to_gregorian(year, month, day)

    # -- removal ---------------------------------------------------------
    @staticmethod
    def _clear_documents() -> int:
        """
        Drop the seeded paperwork. Quotes go with their requests (CASCADE);
        orders have to go first, since they only SET_NULL their request and
        would otherwise survive as orphans.
        """
        orders, _ = PurchaseOrder.objects.filter(note__contains=SEED_TAG).delete()
        requests, _ = PurchaseRequest.objects.filter(note__contains=SEED_TAG).delete()
        return orders + requests

    def _clear_all(self) -> None:
        removed = self._clear_documents()

        # Materials and suppliers only go if nothing else points at them — a
        # seeded name someone later used on a real purchase is now their row,
        # not ours, and deleting it would take the purchase with it.
        kept = 0
        for model in (Material, Supplier):
            for obj in model.objects.filter(note__contains=SEED_TAG):
                try:
                    with transaction.atomic():
                        obj.delete()
                except ProtectedError:
                    kept += 1

        note = f"؛ {kept} کالا/تامین‌کننده نگه داشته شد (داده واقعی به آن‌ها وصل است)"
        self.stdout.write(self.style.SUCCESS(
            f"{removed} سند نمونه حذف شد{note if kept else ''}."
        ))


def _round_price(value: Decimal) -> Decimal:
    """
    Round to a price a person would actually quote.

    Quotes are integers in Rial, and an unrounded product of three floats
    («۴٬۸۳۷٬۲۹۱ ریال») reads as a computed figure rather than an offer, which
    is exactly what the comparison table must not look like.
    """
    grain = Decimal(10_000) if value >= 1_000_000 else Decimal(1_000)
    return (value / grain).quantize(Decimal(1), rounding=ROUND_HALF_UP) * grain
