"""
Fill blank phone/mobile from آرپا's party list — see `apps.crm.phone_fill`.

    python manage.py crm_fill_phones parties.xlsx --dry-run
    python manage.py crm_fill_phones parties.xlsx
"""
from django.core.management.base import BaseCommand, CommandError

from apps.crm.arpa_file import ArpaFileError
from apps.crm.phone_fill import fill, parse


class Command(BaseCommand):
    help = "پر کردن تلفن/موبایلِ خالی مشتری‌ها از «لیست طرف حساب» آرپا؛ چیز دیگری عوض نمی‌شود."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش؛ چیزی ذخیره نمی‌شود.")

    def handle(self, *args, **opts):
        with open(opts["path"], "rb") as fh:
            data = fh.read()
        try:
            rows = parse(data, opts["path"])
        except (ValueError, ArpaFileError) as e:
            raise CommandError(str(e))
        self.stdout.write("\n".join(fill(rows, dry_run=opts["dry_run"]).lines()))
