"""
Send the calendar's due reminders and the day-before digest.

Run from cron every five minutes (cPanel → Cron Jobs):
    */5 * * * * cd ~/bi-platform/backend && python manage.py calendar_reminders
Each reminder goes out once however often this runs (see `ReminderLog`).
"""
from django.core.management.base import BaseCommand

from apps.office.calendar_rules import run


class Command(BaseCommand):
    help = "یادآوری جلسات و پیامک برنامه‌ی فردای مدیرعامل"

    def handle(self, *args, **opts):
        sent = run()
        self.stdout.write(f"reminders={sent['reminders']} sms={sent['sms']} digests={sent['digests']}")
