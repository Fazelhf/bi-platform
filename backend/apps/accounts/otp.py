"""
One-time codes for the two-step login.

The rules that make a 6-digit code safe live here, in one place, because each
of them is load-bearing and none is obvious from the endpoints:

* a code is short-lived (OTP_TTL_SECONDS) — a code read off a lock screen an
  hour later is worthless;
* it may be guessed a handful of times (OTP_MAX_ATTEMPTS) and then the
  challenge dies — 6 digits are only 10⁶, which is nothing without a cap;
* it may be re-sent a handful of times (OTP_MAX_SENDS), no faster than
  OTP_RESEND_COOLDOWN — otherwise a login form is a button that spends the
  company's SMS credit;
* starting a new challenge kills the user's previous ones, so exactly one code
  is ever live per purpose;
* the code is stored hashed and compared in constant time.

Every failure raises OtpError with a Persian `detail` the API hands straight
to the user, since "why didn't it work" is the whole UX of an OTP screen.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import OtpChallenge
from apps.accounts.sms import SmsError, mask_phone, normalize_phone, send_otp

CODE_DIGITS = 6


class OtpError(Exception):
    """A challenge that cannot proceed. `detail` is user-facing Persian."""

    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _new_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def hash_code(token: str, code: str) -> str:
    """Bound to the challenge token, so one row's hash says nothing about
    another's even when the same code comes up twice."""
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{token}:{code}".encode(), sha256
    ).hexdigest()


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------
def start(user, purpose: str, phone: str, ip: str | None = None) -> OtpChallenge:
    """Create a challenge, send its code, and return it. Raises OtpError."""
    to = normalize_phone(phone)
    if not to:
        raise OtpError("شماره موبایل ثبت‌شده معتبر نیست. با مدیر سیستم تماس بگیرید.")

    # At most one live challenge per user per purpose: a code the user asked
    # to have re-sent must invalidate the one before it, or two codes work at
    # once and the attempt cap is silently doubled.
    OtpChallenge.objects.filter(
        user=user, purpose=purpose, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())

    token = secrets.token_hex(32)
    code = _new_code()
    challenge = OtpChallenge.objects.create(
        token=token,
        user=user,
        purpose=purpose,
        phone=to,
        code_hash=hash_code(token, code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
        ip=ip or None,
    )
    _deliver(challenge, code)
    return challenge


def resend(challenge: OtpChallenge) -> OtpChallenge:
    """A fresh code on the same challenge, subject to cooldown and send cap."""
    if not challenge.is_live:
        raise OtpError("کد منقضی شده است. دوباره وارد شوید.", 410)
    if challenge.sends >= settings.OTP_MAX_SENDS:
        raise OtpError("تعداد ارسال مجاز کد به پایان رسید. دوباره وارد شوید.", 429)

    wait = _cooldown_left(challenge)
    if wait:
        raise OtpError(f"تا ارسال دوباره {wait} ثانیه صبر کنید.", 429)

    code = _new_code()
    challenge.code_hash = hash_code(challenge.token, code)
    # The window restarts with the new code — the old one is already dead, so
    # leaving the original expiry would hand the user a code that expires in
    # five seconds.
    challenge.expires_at = timezone.now() + timedelta(
        seconds=settings.OTP_TTL_SECONDS
    )
    challenge.attempts = 0
    _deliver(challenge, code)
    return challenge


def _deliver(challenge: OtpChallenge, code: str) -> None:
    try:
        send_otp(challenge.phone, code)
    except SmsError as exc:
        # The challenge dies with the message: leaving a row whose code was
        # never delivered would present the user an OTP box they can never
        # satisfy.
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        raise OtpError(exc.detail, 503) from exc

    challenge.sends += 1
    challenge.last_sent_at = timezone.now()
    challenge.save(
        update_fields=["code_hash", "expires_at", "attempts", "sends", "last_sent_at"]
    )


def _cooldown_left(challenge: OtpChallenge) -> int:
    if not challenge.last_sent_at:
        return 0
    elapsed = (timezone.now() - challenge.last_sent_at).total_seconds()
    return max(int(settings.OTP_RESEND_COOLDOWN - elapsed), 0)


# ---------------------------------------------------------------------------
# Verifying
# ---------------------------------------------------------------------------
def load(token: str, purpose: str) -> OtpChallenge:
    """The live challenge for this token, or an OtpError explaining why not.

    `purpose` is matched too: a code issued to switch 2FA on must not be
    redeemable as a login step, and vice versa.
    """
    challenge = OtpChallenge.objects.filter(
        token=str(token or ""), purpose=purpose
    ).select_related("user").first()
    if not challenge:
        raise OtpError("درخواست نامعتبر است. دوباره وارد شوید.", 400)
    if challenge.consumed_at:
        raise OtpError("این کد قبلاً استفاده شده است. دوباره وارد شوید.", 410)
    if challenge.is_expired:
        raise OtpError("کد منقضی شده است. دوباره وارد شوید.", 410)
    return challenge


def verify(challenge: OtpChallenge, code: str) -> OtpChallenge:
    """Check a submitted code and consume the challenge on success."""
    if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        raise OtpError("تعداد تلاش‌های مجاز به پایان رسید. دوباره وارد شوید.", 429)

    submitted = str(code or "").strip().translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    if not hmac.compare_digest(
        challenge.code_hash, hash_code(challenge.token, submitted)
    ):
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        left = settings.OTP_MAX_ATTEMPTS - challenge.attempts
        if left <= 0:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
            raise OtpError("تعداد تلاش‌های مجاز به پایان رسید. دوباره وارد شوید.", 429)
        raise OtpError(f"کد واردشده درست نیست. {left} تلاش باقی مانده است.", 400)

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])
    return challenge


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------
def payload(challenge: OtpChallenge) -> dict:
    """What the client needs to render the code screen — never the code."""
    return {
        "otp_required": True,
        "challenge": challenge.token,
        "phone_masked": mask_phone(challenge.phone),
        "expires_in": challenge.seconds_left,
        "resend_in": _cooldown_left(challenge),
        "sends_left": max(settings.OTP_MAX_SENDS - challenge.sends, 0),
    }
