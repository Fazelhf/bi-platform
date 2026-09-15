"""
Load the company's chart into an empty منابع انسانی.

Same as the button on the chart page, for a server where nobody has opened
it yet:

    python manage.py import_org_chart
"""
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.hr.services.people import import_chart


class Command(BaseCommand):
    help = "Build the org chart from apps/hr/services/chart_data.py (empty chart only)."

    def handle(self, *args, **options):
        try:
            stats = import_chart()
        except ValidationError as exc:
            raise CommandError(str(exc.detail))
        self.stdout.write(self.style.SUCCESS(str(stats)))
