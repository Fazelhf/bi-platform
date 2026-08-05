"""
Getting into an account with the phone instead of the password.

Two flows, both starting from the login screen and both built on the same
one-time code as ورود دو مرحله‌ای:

* **ورود با کد پیامکی** — sign in with a code only. Convenient, and honest
  about what it costs: whoever holds the SIM holds the account, so this makes
  the phone a full credential rather than a second one. It is a single env
  var (OTP_LOGIN_ENABLED=False) to switch off for the whole platform, and it
  is refused outright for accounts that turned two-step login on — that user
  asked for *two* factors, and a one-factor side door would quietly undo it.

* **فراموشی رمز** — send a code, then set a new password. Two calls, so the
  new password is typed on a screen the user has already proved they own the
  phone for. The permit handed out in between is signed, expires in minutes,
  and carries a fingerprint of the current password hash — so it stops working
  the moment the password changes and cannot be replayed.

Both flows start from an "identifier": the username or the mobile number,
because someone who has forgotten their password often does not remember
which username was set up for them either.

On enumeration: a wrong identifier is answered with a plain "no such account".
This platform has a few dozen named employees behind a company login, so
hiding whether `ali` exists buys nothing real, while a vague error would send
people to the administrator for what is usually a typo. The throttles and the
per-challenge caps are what actually stand between a stranger and an account.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts import otp
from apps.accounts.models import OtpChallenge, User
from apps.accounts.sms import normalize_phone
from apps.accounts.twofactor import (
    PublicAuthView,
    client_ip,
    issue_tokens,
    otp_response,
)
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog

RESET_SALT = "accounts.password.reset"
#: How long the permit between "code accepted" and "new password saved" lasts.
RESET_TTL = 10 * 60


def find_user(identifier: str) -> User:
    """The account behind a username or a mobile number."""
    raw = str(identifier or "").strip()
    phone = normalize_phone(raw)
    query = Q(username__iexact=raw)
    if phone:
        query |= Q(phone=phone)
    user = User.objects.filter(query, is_active=True).order_by("id").first()
    if not user:
        raise ValidationError(
            {"identifier": "حسابی با این نام کاربری یا شمارهٔ موبایل پیدا نشد."}
        )
    if not user.phone:
        raise ValidationError(
            {"identifier": "برای این حساب شمارهٔ موبایلی ثبت نشده است. "
                           "با مدیر سیستم تماس بگیرید."}
        )
    return user


# ---------------------------------------------------------------------------
# ورود با کد پیامکی — password-free sign-in
# ---------------------------------------------------------------------------
class OtpLoginStartView(PublicAuthView):
    throttle_scope = "otp"

    def post(self, request):
        if not settings.OTP_LOGIN_ENABLED:
            return Response(
                {"detail": "ورود با کد پیامکی روی این سامانه فعال نیست."}, status=403
            )
        user = find_user(request.data.get("identifier"))
        if user.two_factor_active:
            # Their own choice of two factors wins over this shortcut.
            return Response(
                {"detail": "برای این حساب ورود دو مرحله‌ای فعال است؛ "
                           "با نام کاربری و رمز عبور وارد شوید."},
                status=403,
            )
        try:
            challenge = otp.start(
                user, OtpChallenge.Purpose.OTP_LOGIN, user.phone, client_ip(request)
            )
        except otp.OtpError as exc:
            return otp_response(exc)
        return Response(otp.payload(challenge))


class OtpLoginVerifyView(PublicAuthView):
    throttle_scope = "otp"

    def post(self, request):
        try:
            challenge = otp.load(
                request.data.get("challenge"), OtpChallenge.Purpose.OTP_LOGIN
            )
            otp.verify(challenge, request.data.get("code"))
        except otp.OtpError as exc:
            return otp_response(exc)
        user = challenge.user
        if not user.is_active:
            return Response({"detail": "حساب کاربری غیرفعال است."}, status=403)
        return Response(issue_tokens(user))


# ---------------------------------------------------------------------------
# فراموشی رمز — reset by SMS
# ---------------------------------------------------------------------------
class PasswordResetStartView(PublicAuthView):
    throttle_scope = "otp"

    def post(self, request):
        user = find_user(request.data.get("identifier"))
        try:
            challenge = otp.start(
                user, OtpChallenge.Purpose.RESET, user.phone, client_ip(request)
            )
        except otp.OtpError as exc:
            return otp_response(exc)
        return Response(otp.payload(challenge))


class PasswordResetVerifyView(PublicAuthView):
    """Trade a correct code for a short-lived permit to set a new password."""

    throttle_scope = "otp"

    def post(self, request):
        try:
            challenge = otp.load(
                request.data.get("challenge"), OtpChallenge.Purpose.RESET
            )
            otp.verify(challenge, request.data.get("code"))
        except otp.OtpError as exc:
            return otp_response(exc)
        return Response({"reset_token": issue_permit(challenge.user)})


class PasswordResetConfirmView(PublicAuthView):
    """Set the new password, then sign the user straight in."""

    throttle_scope = "otp"

    def post(self, request):
        user = read_permit(request.data.get("reset_token"))
        password = request.data.get("password") or ""
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc

        user.set_password(password)
        user.save(update_fields=["password"])
        # Codes issued before the reset are void — including any second one
        # someone else may have triggered while this was in flight.
        OtpChallenge.objects.filter(user=user, consumed_at__isnull=True).delete()
        audit_log(user, user, AuditLog.Action.UPDATE,
                  {"password": {"before": "—", "after": "بازنشانی با پیامک"}})
        return Response(issue_tokens(user))


# ---------------------------------------------------------------------------
# The reset permit
# ---------------------------------------------------------------------------
def issue_permit(user) -> str:
    """
    Signed, expiring, and one-shot.

    `pw` is a fingerprint of the password hash in force when the permit was
    issued. Setting a new password changes that hash, so the permit stops
    validating by itself — no server-side "used" flag to keep, and a permit
    captured in flight is worthless once the reset it belongs to has happened.
    """
    return signing.dumps(
        {"uid": user.id, "pw": user.password[-12:]}, salt=RESET_SALT
    )


def read_permit(token: str) -> User:
    try:
        data = signing.loads(str(token or ""), salt=RESET_SALT, max_age=RESET_TTL)
    except signing.SignatureExpired as exc:
        raise ValidationError(
            {"reset_token": "مهلت تعیین رمز جدید تمام شد. دوباره تلاش کنید."}
        ) from exc
    except signing.BadSignature as exc:
        raise ValidationError({"reset_token": "درخواست نامعتبر است."}) from exc

    user = User.objects.filter(pk=data.get("uid"), is_active=True).first()
    if not user or user.password[-12:] != data.get("pw"):
        raise ValidationError({"reset_token": "درخواست نامعتبر است."})
    return user
