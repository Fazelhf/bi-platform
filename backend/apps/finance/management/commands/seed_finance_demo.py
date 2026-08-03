"""
Load the finance colleague's sample week into a month, so the نقدینگی pages
have something real to show.

A command, never a data migration: these are demo figures, and `deploy.sh`
runs migrations automatically. Auto-inserting sample cash into production
would put invented money on the CEO's screen.

    python manage.py seed_finance_demo                # آبان 1405 by default
    python manage.py seed_finance_demo --month 5      # another Jalali month
    python manage.py seed_finance_demo --clear        # remove what it added
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import ensure_days, ensure_weeks
from apps.finance.models import (
    CashCategory,
    CashMovement,
    CreditLine,
    Direction,
    FinanceSetting,
)

# The seven days of گزارش نقدینگی ۱ تا ۷ مرداد ۱۴۰۵, as supplied.
CASH_IN = [
    ("sales", [7378450000, 0, 1727166000, 27560916797, 7058800000, 313624000, 5675360000]),
    ("unclassified", [0, 0, 0, 0, 0, 0, 900000000]),
    ("debt-returned", [0, 0, 5000000000, 0, 0, 0, 0]),
]
CASH_OUT = [
    ("supplier", [0, 0, 3733200000, 4000000000, 33940578000, 798000000, 8220921391]),
    ("payroll", [0, 0, 0, 0, 400000000, 380611860, 900000000]),
    ("petty-cash", [0, 0, 60990000, 289397290, 0, 261456000, 441850150]),
]
PARTNER_IN = [0, 0, 0, 1000000000, 0, 0, 0]
PARTNER_OUT = [0, 0, 0, 2000000000, 0, 0, 5000000000]

OPENING_BALANCE = Decimal(12_000_000_000)
LOW_BALANCE = Decimal(5_000_000_000)


class Command(BaseCommand):
    help = "Load the sample cash week into a month (demo data — opt-in)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=1405)
        parser.add_argument("--month", type=int, default=8)
        parser.add_argument(
            "--clear", action="store_true",
            help="Remove the movements this command created and stop.",
        )

    def handle(self, *args, **options):
        year, month_no = options["year"], options["month"]
        month = DimPeriod.objects.filter(
            kind=PeriodKind.MONTH, jalali_year=year, jalali_month=month_no
        ).first()
        if not month:
            self.stderr.write(
                f"ماه {year}/{month_no:02d} تعریف نشده — ابتدا seed_periods را اجرا کنید."
            )
            return

        days = self._days(month)
        if options["clear"]:
            self._clear(days)
            return

        if not days:
            self.stderr.write(
                "این ماه به روز تقسیم نشده و داده‌ی ثبت‌شده دارد، پس قابل تقسیم نیست. "
                "ماه دیگری را با --month انتخاب کنید."
            )
            return

        categories = {c.code: c for c in CashCategory.objects.all()}
        missing = [
            code for code, _ in CASH_IN + CASH_OUT if code not in categories
        ]
        if missing or "partner-account" not in categories:
            self.stderr.write(
                "دسته‌های نقدینگی یافت نشد — مایگریشن‌های finance اجرا نشده‌اند."
            )
            return

        partner = CreditLine.objects.get_or_create(
            kind=CreditLine.Kind.PARTNER, title="جاری شریک اول",
            counterparty="شریک اول",
        )[0]
        CreditLine.objects.get_or_create(
            kind=CreditLine.Kind.FACILITY, title="تسهیلات سرمایه در گردش",
            counterparty="بانک ملت",
            defaults={
                "principal_rial": Decimal(50_000_000_000),
                "rate_pct": Decimal("23.00"),
            },
        )

        written = 0
        written += self._write(days, CASH_IN, Direction.IN, categories)
        written += self._write(days, CASH_OUT, Direction.OUT, categories)
        written += self._write_partner(days, categories["partner-account"], partner)

        setting = FinanceSetting.get()
        setting.opening_balance_rial = OPENING_BALANCE
        setting.low_balance_rial = LOW_BALANCE
        setting.opening_on = days[0].start_date
        setting.save()

        self.stdout.write(self.style.SUCCESS(
            f"{written} حرکت در {month.label} ثبت شد "
            f"(موجودی اولیه {OPENING_BALANCE:,.0f} ریال)."
        ))

    # -- helpers --------------------------------------------------------
    def _clear(self, days: list[DimPeriod]) -> None:
        """
        Undo everything the seeder put in — movements, the two demo credit
        lines and the opening balance.

        Only the credit lines this command creates are removed, and only when
        nothing else references them, so clearing demo data can never delete a
        real facility someone entered by hand.
        """
        removed, _ = CashMovement.objects.filter(
            period_id__in=[d.id for d in days]
        ).delete()

        lines_removed = 0
        for kind, title in (
            (CreditLine.Kind.PARTNER, "جاری شریک اول"),
            (CreditLine.Kind.FACILITY, "تسهیلات سرمایه در گردش"),
        ):
            line = CreditLine.objects.filter(kind=kind, title=title).first()
            if line and not line.movements.exists():
                line.delete()
                lines_removed += 1

        setting = FinanceSetting.get()
        if setting.opening_balance_rial == OPENING_BALANCE:
            setting.opening_balance_rial = Decimal(0)
            setting.low_balance_rial = Decimal(0)
            setting.opening_on = None
            setting.save()
            reset = "موجودی اولیه صفر شد"
        else:
            reset = "موجودی اولیه دست‌نخورده ماند (توسط شما تغییر کرده بود)"

        self.stdout.write(self.style.SUCCESS(
            f"{removed} حرکت و {lines_removed} مورد تسهیلات/جاری حذف شد؛ {reset}."
        ))

    @staticmethod
    def _days(month: DimPeriod) -> list[DimPeriod]:
        """The month's first seven days, splitting it up if it is still whole."""
        if not month.children.exists():
            try:
                for week in ensure_weeks(month):
                    ensure_days(week)
            except ValueError:
                return []
        days = [
            d for d in DimPeriod.objects.filter(kind=PeriodKind.DAY, parent__parent=month)
        ]
        return sorted(days, key=lambda d: d.start_date or date.min)[:7]

    @staticmethod
    def _write(days, table, direction, categories) -> int:
        count = 0
        for code, values in table:
            for day, amount in zip(days, values):
                if not amount:
                    continue
                CashMovement.objects.update_or_create(
                    period=day, direction=direction,
                    category=categories[code], credit_line=None,
                    defaults={"amount_rial": Decimal(amount)},
                )
                count += 1
        return count

    @staticmethod
    def _write_partner(days, category, line) -> int:
        count = 0
        for direction, values in (
            (Direction.IN, PARTNER_IN), (Direction.OUT, PARTNER_OUT)
        ):
            for day, amount in zip(days, values):
                if not amount:
                    continue
                CashMovement.objects.update_or_create(
                    period=day, direction=direction,
                    category=category, credit_line=line,
                    defaults={"amount_rial": Decimal(amount)},
                )
                count += 1
        return count
