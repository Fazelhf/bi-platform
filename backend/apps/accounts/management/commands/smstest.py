"""
Check the SMS gateway from the command line, without touching the platform.

Getting a one-time code to arrive depends on things that live in the panel,
not in this repository — the account's credentials, whether the server's IP is
allowed, and (on a shared service line) the id of a message template that the
panel's administrators have approved. When a code does not arrive, the useful
question is which of those is wrong, and answering it through the login screen
means creating a user and reading Django's log to find a number the panel sent
back. This command asks the panel directly instead.

    python manage.py smstest                       # settings + credit, sends nothing
    python manage.py smstest --to 09121112233      # really sends a code

`--to` is the only way to send: a test that goes out to a real phone and costs
real credit should not be what happens when the command is run with no
arguments to see what it does.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts import sms


class Command(BaseCommand):
    help = "Check the SMS gateway settings, credit, and optionally send a real code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            help="Mobile number to send a real test code to. Costs credit.",
        )
        parser.add_argument(
            "--code",
            default="123456",
            help="Code to send (default: 123456).",
        )

    def handle(self, *args, **options):
        self._report_settings()
        self._report_credit()

        to = options["to"]
        if not to:
            self.stdout.write(
                "\nهیچ پیامکی ارسال نشد. برای ارسال واقعی: "
                "manage.py smstest --to 09121112233"
            )
            return

        number = sms.normalize_phone(to)
        if not number:
            raise CommandError(f"شمارهٔ «{to}» معتبر نیست.")

        self.stdout.write(f"\nدر حال ارسال کد {options['code']} به {number} …")
        try:
            rec_id = sms.send_otp(number, options["code"])
        except sms.SmsError as exc:
            raise CommandError(
                f"ارسال نشد: {exc.detail}" + (f" (کد {exc.code})" if exc.code else "")
            ) from exc
        self.stdout.write(self.style.SUCCESS(f"ارسال شد. recId = {rec_id}"))

    # -- helpers ---------------------------------------------------------
    def _report_settings(self):
        shared = sms.is_shared_line()
        # Which file the values came from, named before the values themselves.
        # «پیکربندی نشده» after a deploy is almost always .env: it is
        # gitignored, so a server that was never given one by hand keeps
        # answering that no matter how many times the code is pulled.
        env_file = settings.BASE_DIR / ".env"
        self.stdout.write(
            f"فایل تنظیمات: {env_file} "
            f"({'موجود' if env_file.exists() else 'وجود ندارد'})"
        )
        self.stdout.write(f"حالت ارسال (SMS_MODE): {settings.SMS_MODE}")
        self.stdout.write(f"نام کاربری: {settings.SMS_USERNAME or '—'}")
        self.stdout.write(f"کلید/رمز: {'تنظیم شده' if settings.SMS_PASSWORD else '—'}")
        if shared:
            self.stdout.write(f"کد الگو (SMS_BODY_ID): {settings.SMS_BODY_ID or '—'}")
        else:
            self.stdout.write(f"شمارهٔ فرستنده (SMS_FROM): {settings.SMS_FROM or '—'}")

        if sms.is_configured():
            self.stdout.write(self.style.SUCCESS("تنظیمات کامل است."))
            return
        missing = "SMS_BODY_ID" if shared else "SMS_FROM"
        self.stdout.write(
            self.style.WARNING(
                f"تنظیمات کامل نیست — {missing} یا نام کاربری/کلید خالی است. "
                "کد یک‌بارمصرف ارسال نخواهد شد."
            )
        )

    def _report_credit(self):
        """GetCredit proves the credentials and the server's IP in one call.

        It is the only question worth asking that costs nothing: a wrong key
        and a blocked IP both fail here, before any send is attempted.
        """
        if not (settings.SMS_USERNAME and settings.SMS_PASSWORD):
            return
        body = urllib.parse.urlencode(
            {"username": settings.SMS_USERNAME, "password": settings.SMS_PASSWORD}
        ).encode()
        request = urllib.request.Request(
            f"{settings.SMS_BASE_URL.rstrip('/')}/GetCredit",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.SMS_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            self.stdout.write(self.style.ERROR(f"\nاتصال به پنل برقرار نشد: {exc}"))
            return

        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}

        value = str(payload.get("Value") or "")
        if str(payload.get("RetStatus")) == "1":
            self.stdout.write(self.style.SUCCESS(f"\nاعتبار پنل: {value}"))
            return

        # Fall back to RetStatus when Value is blank — the same rule
        # _read_result follows, and the reason it matters here: bad
        # credentials come back as {"Value":"","RetStatus":0}, so reading
        # Value alone printed an empty complaint.
        #
        # Failing that, show the raw body. The replies worth diagnosing are
        # the undocumented ones, and an empty «پنل پاسخ داد:» is the least
        # useful line this command could print at the moment someone is stuck.
        explained = sms.COMMON_ERRORS.get(value) or sms.COMMON_ERRORS.get(
            str(payload.get("RetStatus"))
        )
        self.stdout.write(self.style.ERROR(
            f"\nپنل پاسخ داد: {explained or value or raw.strip()[:200] or '(پاسخ خالی)'}"
        ))
        if not explained:
            self.stdout.write(
                "اگر مقدار بالا شبیه پاسخ معتبر نیست، معمولاً یعنی SMS_PASSWORD "
                "هنوز ApiKey واقعی نیست (مثلاً جای‌نگهدار <ApiKey> مانده)."
            )
