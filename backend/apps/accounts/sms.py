"""
SMS delivery through ملی‌پیامک (Melipayamak).

Only one kind of message leaves the platform — the one-time login code — but
the panel offers two different ways to send it, and which one an account may
use depends on the line it bought. SMS_MODE picks between them:

* ``otp`` — **SendOtp**, for an account with its own sender line. The endpoint
  owns the message text («کد تایید شما / Code: 123456»), so there is no
  template to get approved and nothing we write can trip the filtered-word or
  contains-a-link rules. Needs SMS_FROM.

* ``shared`` — **BaseServiceNumber**, for a خط خدماتی اشتراکی (shared service
  line). There is no sender number to give; instead the message text is a
  template registered in the panel and approved by its administrators, and a
  send passes the template's id (SMS_BODY_ID) plus the values that fill its
  variables. So the code travels as `text` and the wording lives in the panel.

Credentials come from the environment. SMS_PASSWORD should hold the panel's
**ApiKey**, not the account password — the panel can be set to require exactly
that (it answers -110 otherwise), and an ApiKey is the credential you can
rotate without locking yourself out of the panel itself.

If the panel has an allowed-IP list, the server's outbound address must be on
it or *every* call — including ones that send nothing — comes back -111.

Talking to the endpoint uses stdlib urllib rather than `requests`: this is the
only outbound HTTP call the backend makes, and it is not worth a dependency
that then has to be installed on the cPanel host.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

#: Codes both endpoints return with the same meaning.
COMMON_ERRORS = {
    "-111": "آی‌پی سرور برای استفاده از وب‌سرویس پیامک مجاز نیست.",
    "-110": "باید به جای رمز عبور، ApiKey استفاده شود.",
    "-109": "تنظیم آی‌پی مجاز برای استفاده از وب‌سرویس الزامی است.",
    "-108": "آی‌پی سرور به دلیل تلاش‌های ناموفق مسدود شده است.",
    "0": "نام کاربری یا کلید وب‌سرویس پیامک نادرست است.",
    "2": "اعتبار پنل پیامک کافی نیست.",
    "6": "سامانه پیامک در حال به‌روزرسانی است.",
    "7": "متن پیامک حاوی کلمه فیلترشده است.",
    "10": "کاربر پنل پیامک فعال نیست.",
    "11": "پیامک ارسال نشد.",
    "12": "مدارک کاربر پنل پیامک کامل نیست.",
    "18": "شماره گیرنده نامعتبر است.",
    "19": "سقف ارسال روزانهٔ وب‌سرویس پر شده است.",
}

#: SendOtp only. The same numbers mean different things on the shared-line
#: endpoint, which is why the two maps are kept apart rather than merged.
OTP_ERRORS = {
    **COMMON_ERRORS,
    "3": "محدودیت ارسال روزانه پنل پیامک.",
    "4": "محدودیت حجم ارسال پنل پیامک.",
    "5": "شماره فرستنده معتبر نیست.",
    "9": "ارسال از خطوط عمومی از طریق وب‌سرویس ممکن نیست.",
    "14": "متن پیامک حاوی لینک است.",
    "15": "ارسال به بیش از یک شماره بدون «لغو۱۱» ممکن نیست.",
    "16": "شماره گیرنده یافت نشد.",
    "17": "متن پیامک خالی است.",
    "35": "شماره گیرنده در لیست سیاه مخابرات است.",
}

#: BaseServiceNumber (خط خدماتی اشتراکی) only.
SHARED_ERRORS = {
    **COMMON_ERRORS,
    "-10": "ارسال لینک در متغیرهای الگو مجاز نیست.",
    "-6": "خطای داخلی سامانهٔ پیامک؛ با پشتیبانی پنل تماس بگیرید.",
    "-5": "متن ارسالی با متغیرهای الگوی تأییدشده هم‌خوانی ندارد.",
    "-4": "کد الگو (bodyId) نادرست است یا هنوز تأیید نشده.",
    "-3": "خط خدماتی اشتراکی در سامانه تعریف نشده است.",
    "-2": "هر بار فقط به یک شماره می‌توان ارسال کرد.",
    "-1": "دسترسی این وب‌سرویس برای حساب شما غیرفعال است.",
}

#: Persian/Arabic-Indic digits, so a phone typed on a Persian keyboard works.
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class SmsError(Exception):
    """A send that did not happen. `detail` is safe to show to the user."""

    def __init__(self, detail: str, code: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.code = code


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------
def normalize_phone(raw: str) -> str:
    """
    An Iranian mobile number in the one shape the gateway accepts: 09xxxxxxxxx.

    Accepts what people actually type — +98/0098/98 prefixes, Persian digits,
    spaces and dashes — and returns "" for anything that is not a mobile
    number, so callers can treat "" as "invalid".
    """
    digits = re.sub(r"\D", "", str(raw or "").translate(_DIGIT_MAP))
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return digits if re.fullmatch(r"09\d{9}", digits) else ""


def mask_phone(phone: str) -> str:
    """0912***4567 — enough for a user to recognise their own number, not
    enough for someone else's screen to leak it."""
    p = normalize_phone(phone) or re.sub(r"\D", "", str(phone or ""))
    if len(p) < 8:
        return "—"
    return f"{p[:4]}***{p[-4:]}"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def is_shared_line() -> bool:
    return str(settings.SMS_MODE).lower() == "shared"


def is_configured() -> bool:
    """Enough settings present for a send to have a chance of working.

    The two modes need different things — a shared line has no sender number
    to give, and a dedicated line has no template id — so checking for all of
    them would leave one of the two permanently "unconfigured".
    """
    if not (settings.SMS_USERNAME and settings.SMS_PASSWORD):
        return False
    return bool(settings.SMS_BODY_ID) if is_shared_line() else bool(settings.SMS_FROM)


def can_send() -> bool:
    """Whether a code can reach a user at all — credentials, or the DEBUG echo
    below standing in for them. The enrolment screen asks this before offering
    to switch 2FA on, so it must agree with what send_otp() will actually do."""
    return is_configured() or (settings.DEBUG and settings.OTP_ECHO_IN_DEBUG)


def send_otp(phone: str, code: str) -> str:
    """
    Send one login code. Returns the gateway's recId; raises SmsError if the
    message did not go out.
    """
    to = normalize_phone(phone)
    if not to:
        raise SmsError("شماره موبایل معتبر نیست.")

    if not is_configured():
        # Local development with no panel credentials: print the code instead
        # of failing, so the two-step login can be exercised offline. Never in
        # production — there, an unsent code must surface as an error rather
        # than silently letting anyone in who can read the server log.
        if settings.DEBUG and settings.OTP_ECHO_IN_DEBUG:
            logger.warning("[DEV] OTP for %s is %s (SMS not configured)", to, code)
            return "dev-echo"
        raise SmsError("سرویس پیامک پیکربندی نشده است. با مدیر سیستم تماس بگیرید.")

    credentials = {
        "username": settings.SMS_USERNAME,
        "password": settings.SMS_PASSWORD,
        "to": to,
    }
    if is_shared_line():
        # The wording lives in the approved template; only the code travels.
        endpoint, errors = "BaseServiceNumber", SHARED_ERRORS
        params = {**credentials, "text": code, "bodyId": settings.SMS_BODY_ID}
    else:
        endpoint, errors = "SendOtp", OTP_ERRORS
        params = {**credentials, "from": settings.SMS_FROM, "code": code}

    request = urllib.request.Request(
        f"{settings.SMS_BASE_URL.rstrip('/')}/{endpoint}",
        data=urllib.parse.urlencode(params).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=settings.SMS_TIMEOUT) as response:
            payload = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        logger.error("%s HTTP %s: %s", endpoint, exc.code, exc.reason)
        raise SmsError("ارتباط با سرویس پیامک برقرار نشد.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("%s transport error: %s", endpoint, exc)
        raise SmsError("ارتباط با سرویس پیامک برقرار نشد.") from exc

    return _read_result(payload, errors)


def _read_result(payload: str, errors: dict) -> str:
    """
    Pull the return value out of a response.

    The REST endpoint answers with JSON ({"Value": …, "RetStatus": 1}), the
    SOAP one with a bare string in XML. Both are handled, because the two URLs
    are interchangeable in the panel's own docs and SMS_BASE_URL can point at
    either.
    """
    text = (payload or "").strip()
    value, ret_status = text, None

    try:
        parsed = json.loads(text)
    except ValueError:
        # <string xmlns="...">12345</string>
        stripped = re.sub(r"<[^>]+>", "", text).strip()
        value = stripped or text
    else:
        if isinstance(parsed, dict):
            value = str(parsed.get("Value", parsed.get("value", ""))).strip()
            ret_status = parsed.get("RetStatus", parsed.get("retStatus"))
        else:
            value = str(parsed).strip()

    # RetStatus is the authoritative verdict when the REST endpoint gives one:
    # 1 is success and Value is the recId, anything else puts the error code in
    # Value. Without it (the SOAP endpoint returns a bare string) fall back to
    # recognising the value as a documented error code.
    if ret_status is not None and str(ret_status) != "1":
        raise SmsError(_message_for(value or str(ret_status), errors), value)
    if value in errors:
        raise SmsError(errors[value], value)

    # A send that worked answers with a recId — a long number (the shared-line
    # docs say more than 15 digits). Requiring that, rather than treating
    # "anything not in the error table" as success, matters because the panel
    # has undocumented replies: SendOtp with a missing sender line answers a
    # bare "100", which would otherwise be recorded as a delivered code and
    # leave the user waiting for an SMS that was never sent.
    if not value.isdigit() or len(value) < 10:
        raise SmsError(_message_for(value, errors), value)
    return value


def _message_for(code: str, errors: dict) -> str:
    return errors.get(str(code), f"خطای سرویس پیامک (کد {code}).")
