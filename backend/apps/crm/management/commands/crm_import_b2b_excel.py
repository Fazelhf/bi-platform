"""
Bring the B2B unit's Excel CRM into CRM — see `apps.crm.b2b_import`.

    python manage.py crm_import_b2b_excel pre.xlsx sales.xlsx --dry-run
    python manage.py crm_import_b2b_excel pre.xlsx sales.xlsx

Run with --dry-run first: it reads, matches and reports, and saves nothing.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.crm.b2b_import import import_files


class Command(BaseCommand):
    help = "ورود پیش‌فاکتورها، قیف و پلن فروش B2B از اکسل (بدون ادغام خودکار)."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+")
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش؛ چیزی ذخیره نمی‌شود.")
        parser.add_argument("--owner", help="کد کارشناس برای ردیف‌های «مدیر واحد» (پیش‌فرض: سرپرست B2B).")
        parser.add_argument("--report", help="مسیر فایل متنی گزارش.")

    def handle(self, *args, **opts):
        from apps.hr.models import Position
        from apps.sales.models import DimEmployee

        if opts["owner"]:
            owner = DimEmployee.objects.filter(code=opts["owner"]).first()
            if not owner:
                raise CommandError(f"کارشناسی با کد {opts['owner']} پیدا نشد.")
        else:
            # The head of the B2B unit: who «مدیر واحد» in his sheets is.
            seat = Position.objects.filter(
                is_head=True, holder__is_active=True, unit__sales_channel="b2b",
            ).select_related("holder").first()
            owner = seat.holder if seat else None
        self.stdout.write(f"مدیر واحد ← {owner.full_name_fa if owner else 'بی‌کارشناس'}")

        report = import_files(opts["paths"], dry_run=opts["dry_run"], default_owner=owner)
        text = "\n".join(report.lines())
        self.stdout.write(text)
        if opts["report"]:
            with open(opts["report"], "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
