"""
Cut a whole Jalali year into weeks.

    python manage.py split_year_into_weeks 1405

Months that already hold figures are skipped, not forced: splitting them
would leave numbers on both the month and its weeks and every total would be
counted twice. Those months simply stay monthly, which the roll-up handles
natively — they are leaves in their own right.
"""
from django.core.management.base import BaseCommand

from apps.core.jalali import MONTHS_FA
from apps.core.models import DimPeriod, PeriodKind, SiteSetting
from apps.core.periods import backfill_dates, ensure_weeks


class Command(BaseCommand):
    help = "Split every month of a Jalali year into weeks."

    def add_arguments(self, parser):
        parser.add_argument("year", type=int)
        parser.add_argument(
            "--create-missing", action="store_true",
            help="Create month rows that do not exist yet.",
        )
        parser.add_argument(
            "--min-days", type=int, default=None,
            help="Merge threshold for short edge weeks (default: site setting).",
        )

    def handle(self, *args, **opts):
        year = opts["year"]
        min_days = opts["min_days"] or SiteSetting.get().min_week_days

        split = skipped = created = 0
        for jm in range(1, 13):
            month = DimPeriod.objects.filter(
                jalali_year=year, jalali_month=jm, kind=PeriodKind.MONTH
            ).first()

            if month is None:
                if not opts["create_missing"]:
                    self.stdout.write(f"  — {MONTHS_FA[jm]}: وجود ندارد (رد شد)")
                    continue
                month = backfill_dates(
                    DimPeriod(jalali_year=year, jalali_month=jm)
                )
                month.save()
                created += 1

            try:
                weeks = ensure_weeks(month, min_days=min_days)
            except ValueError as exc:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(f"  ! {month.label}: {exc}")
                )
                continue

            split += 1
            spans = " · ".join(f"{w.days}روز" for w in weeks)
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ {month.label}: {len(weeks)} هفته ({spans})")
            )

        self.stdout.write("")
        self.stdout.write(
            f"سال {year}: {split} ماه تقسیم شد"
            + (f"، {created} ماه ساخته شد" if created else "")
            + (f"، {skipped} ماه به‌خاطر داشتن داده دست‌نخورده ماند" if skipped else "")
        )
