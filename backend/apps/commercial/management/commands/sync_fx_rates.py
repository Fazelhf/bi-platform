"""
Pull today's currency rates from the configured source.

Meant for a daily cron on the server:

    python manage.py sync_fx_rates
    python manage.py sync_fx_rates --date 2026-08-05

Exits non-zero when nothing was fetched, so a cron that mails on failure
actually mails. A rate table that quietly stopped updating is worse than one
that is obviously empty: every import gets valued at a stale number and
nobody notices until the customs bill arrives.

Until `COMMERCIAL_FX_PROVIDER` names a source, this reports that no provider
is configured and changes nothing — manual entry keeps working throughout.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.commercial.services import fx


class Command(BaseCommand):
    help = "دریافت نرخ‌های ارز از منبع تنظیم‌شده"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date", help="تاریخ میلادی YYYY-MM-DD — پیش‌فرض امروز"
        )

    def handle(self, *args, **options):
        on = None
        if options.get("date"):
            try:
                on = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("تاریخ باید به شکل YYYY-MM-DD باشد.")

        report = fx.sync(on)

        if not report["ok"]:
            self.stderr.write(self.style.ERROR(report["detail"]))
            if report["missing"]:
                self.stderr.write("نرخ‌های دریافت‌نشده: " + "، ".join(report["missing"]))
            raise CommandError(report["reason"])

        self.stdout.write(self.style.SUCCESS(report["detail"]))
        if report["skipped"]:
            self.stdout.write(
                f"{report['skipped']} نرخ دستی دست‌نخورده ماند."
            )
        if report["missing"]:
            self.stdout.write(
                self.style.WARNING("نرخ‌های دریافت‌نشده: " + "، ".join(report["missing"]))
            )
