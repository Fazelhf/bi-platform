"""
Take back the B2B Excel import — see `apps.crm.b2b_import.undo`.

    python manage.py crm_undo_b2b_excel --dry-run
    python manage.py crm_undo_b2b_excel
"""
from django.core.management.base import BaseCommand

from apps.crm.b2b_import import undo


class Command(BaseCommand):
    help = "پاک کردن هرچه از اکسل B2B وارد شده (معامله‌ها، مشتری‌های ساخته‌شده، یادداشت و کارها)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="فقط گزارش؛ چیزی پاک نمی‌شود.")

    def handle(self, *args, **opts):
        self.stdout.write("\n".join(undo(dry_run=opts["dry_run"])))
