"""
Seed the 12 Jalali months of a year so the dashboard's month picker covers
فروردین..اسفند. Only months that actually have approved facts show data; the
rest render as empty (no data entered yet) rather than being missing.
"""
from django.core.management.base import BaseCommand

from apps.core.models import DimPeriod


class Command(BaseCommand):
    help = "Create DimPeriod rows for all 12 months of a Jalali year."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=1405)

    def handle(self, *args, **options):
        year = options["year"]
        created = 0
        for month in range(1, 13):
            _, was_created = DimPeriod.objects.get_or_create(
                jalali_year=year, jalali_month=month
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(
            f"Year {year}: {created} period(s) created, "
            f"{12 - created} already existed."
        ))
