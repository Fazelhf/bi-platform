"""
Set each imported customer's department (and their deals') from the evidence
in `apps.crm.channels`.

    python manage.py derive_channels

`import_arpa_parties` does this at the end of every run. This command is for
after the sales roster changes — moving a rep between departments should move
their customers without waiting for the next accounting export.
"""
from django.core.management.base import BaseCommand

from apps.crm.channels import rederive_customer_channels


class Command(BaseCommand):
    help = "تعیین دپارتمان مشتریان واردشده از روی کارشناس و گروه آرپا"

    def handle(self, *args, **options):
        moved = rederive_customer_channels()
        if not moved:
            self.stdout.write("همه‌ی مشتریان در دپارتمان درست بودند.")
            return
        self.stdout.write(self.style.SUCCESS(
            "دپارتمان عوض شد: " + "، ".join(f"{k}={v}" for k, v in sorted(moved.items()))
        ))
