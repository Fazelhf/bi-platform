"""
    manage.py sales2_cutover --from 1405/01/01 [--dry-run]
    manage.py sales2_cutover --undo

Brings آرپا invoices from that day on, opening balances before it, and open
CRM deals into فروش ۲. See `apps.sales2.cutover`. Safe to run again.
"""
import re

from django.core.management.base import BaseCommand, CommandError

from apps.core import jalali
from apps.sales2 import cutover


class Command(BaseCommand):
    help = "Move آرپا invoices, opening balances and open CRM deals into فروش ۲."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="start", help="Jalali cut-over day, e.g. 1405/01/01")
        parser.add_argument("--undo", action="store_true", help="Remove everything a cut-over brought.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would move, change nothing.")

    def handle(self, *args, start, dry_run, undo=False, **opts):
        if undo:
            self.stdout.write(self.style.SUCCESS(f"undone: {cutover.undo()}"))
            return
        if not start:
            raise CommandError("--from is required (or --undo).")
        m = re.match(r"^(1[34]\d\d)/(\d\d?)/(\d\d?)$", start)
        if not m:
            raise CommandError("--from must look like 1405/01/01")
        day = jalali.to_gregorian(*(int(x) for x in m.groups()))
        report = cutover.run(day, dry_run=dry_run)
        self.stdout.write(self.style.WARNING("[dry run — nothing saved]") if dry_run else self.style.SUCCESS("done"))
        for line in report.lines():
            self.stdout.write("  " + line)
        for number, party, total in report.unmatched[:25]:
            self.stdout.write(f"    · برگه {number} · {party} · {int(total):,}")
