"""
Attach آرپا invoices to the دیدار deals they billed.

    python manage.py link_invoices

Runs on its own after `import_arpa_invoices`, which already calls it — this
command exists for after the review queue has been worked through or two
customers have been merged, since either can give an invoice a customer with
deals it did not have before. See `apps.crm.invoice_link` for the rule.
"""
from django.core.management.base import BaseCommand

from apps.crm.invoice_link import WINDOW_DAYS, link_invoices


class Command(BaseCommand):
    help = "وصل کردن فاکتورهای آرپا به معامله‌های موفق دیدار"

    def handle(self, *args, **options):
        report(self, link_invoices())


def report(command, stats) -> None:
    out = command.stdout
    out.write(command.style.SUCCESS(
        f"فاکتور وصل‌شده به معامله: {stats.linked} تازه"
        + (f"، {stats.already} از قبل" if stats.already else "")
    ))
    if stats.unlinked:
        out.write(
            f"  بی‌معامله ماند: {stats.unlinked}"
            f" — {stats.no_won_deal} چون مشتری‌اش در دیدار معامله‌ی موفقی ندارد،"
            f" {stats.out_of_window} چون نزدیک‌ترین معامله بیش از"
            f" {WINDOW_DAYS} روز فاصله دارد."
        )
