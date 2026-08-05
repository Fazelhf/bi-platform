"""
Two-step login endpoints (ورود دو مرحله‌ای).

Shape of the login flow, from the client's side:

    POST /api/auth/token/            {username, password}
      → without 2FA:  {access, refresh}          ← unchanged from before
      → with 2FA:     {otp_required: true, challenge, phone_masked, …}
    POST /api/auth/2fa/verify/       {challenge, code}   → {access, refresh}
    POST /api/auth/2fa/resend/       {challenge}         → {…, resend_in}

The password step deliberately still returns *nothing* an unauthenticated
caller can use: the challenge token is worthless without the code, and it is
only handed out after the password has already checked out — so the second
factor is an addition to the first, never a replacement for it.

Enrolling is self-service and proves possession: a user types their number,
receives a code on it, and 2FA turns on only once that code comes back. An
administrator can *switch it off* for someone who lost their phone (that is a
support action, and it only ever reduces access), but cannot switch it on for
someone else — there would be no proof the number is theirs, and the result
would be an account nobody can log into.
"""
from __future__ import annotations

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import otp
from apps.accounts.models import OtpChallenge, User
from apps.accounts.sms import can_send, mask_phone, normalize_phone
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def issue_tokens(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def otp_response(exc: otp.OtpError) -> Response:
    return Response({"detail": exc.detail}, status=exc.status)


class PublicAuthView(APIView):
    """Base for the endpoints reached without a token.

    `authentication_classes = []` keeps them from trying to parse an Authorization
    header they have no use for — but DRF answers an authentication failure with
    403 when a view has no authenticator to name in WWW-Authenticate, and the
    login endpoint answered 401 before this feature existed. Naming the scheme
    keeps that contract.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'


def two_factor_status(user) -> dict:
    return {
        "enabled": user.two_factor_active,
        "phone_masked": mask_phone(user.phone) if user.phone else "",
        "phone": user.phone,
        "sms_configured": can_send(),
        "enabled_at": user.two_factor_enabled_at,
    }


# ---------------------------------------------------------------------------
# Step 1 — password
# ---------------------------------------------------------------------------
def complete_login(user, request) -> dict:
    """Everything that happens the moment a login actually succeeds.

    Both steps can be the last one — an account without 2FA finishes at the
    password, one with it finishes at the code — and the panel's audit trail
    and lockout counter must see exactly one success either way. So this is
    the only place that mints tokens for a login, and the only place that
    calls `register_success`.
    """
    from apps.adminpanel.models import UserSecurity
    from apps.adminpanel.services import security as sec_service

    sec_service.register_success(user, request)
    state = UserSecurity.get(user)
    return {
        **issue_tokens(user),
        "must_change_password": bool(
            state.must_change_password or sec_service.password_expired(user)
        ),
        "is_admin_panel_user": user.is_admin_panel_user,
    }


class LoginView(PublicAuthView):
    """
    Replaces SimpleJWT's TokenObtainPairView at the same URL.

    Credentials are checked here rather than by TokenObtainPairSerializer so
    that no token is ever minted for an account that still owes a second
    factor — a serializer that returns tokens and a view that throws them away
    is one refactor from leaking them.

    The panel's login policy — IP rules, lockout, and a LoginEvent for every
    outcome — used to live in PanelTokenObtainPairSerializer at this same URL.
    It is applied here instead: two views cannot own one endpoint, and running
    the checks in a serializer that returns tokens is the arrangement the
    paragraph above exists to avoid. The order matters — an IP that is not
    allowed to reach the platform should not get to find out whether a
    password was right.
    """

    throttle_scope = "login"

    def post(self, request):
        from apps.adminpanel.services import security as sec_service

        username = str(request.data.get("username") or "").strip()
        password = request.data.get("password") or ""

        # 400, not 401, for these two — and that is a UI decision as much as a
        # protocol one. The sign-in screen renders 401 as «نام کاربری یا رمز
        # عبور نادرست است», so a locked account answering 401 would send the
        # user hunting for a typo instead of reading «حساب موقتاً قفل است».
        # It is also the contract the panel's serializer already had.
        allowed, reason = sec_service.ip_allowed(sec_service.client_ip(request))
        if not allowed:
            sec_service.register_failure(username, request, reason)
            raise ValidationError({"detail": "ورود از این آدرس شبکه مجاز نیست."})

        locked_user = User.objects.filter(username=username).first()
        if locked_user:
            locked, message = sec_service.lock_state(locked_user)
            if locked:
                sec_service.register_failure(username, request, "locked")
                raise ValidationError({"detail": message})

        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            sec_service.register_failure(username, request, "bad_password")
            raise AuthenticationFailed("نام کاربری یا رمز عبور نادرست است.")

        if not user.two_factor_active:
            return Response(complete_login(user, request))

        try:
            challenge = otp.start(
                user, OtpChallenge.Purpose.LOGIN, user.phone, client_ip(request)
            )
        except otp.OtpError as exc:
            return otp_response(exc)
        # Deliberately no `register_success` yet: the password alone is not a
        # login for this account, and recording one here would clear the
        # failure counter for someone who never produces the code.
        return Response(otp.payload(challenge))


# ---------------------------------------------------------------------------
# Step 2 — the code
# ---------------------------------------------------------------------------
class OtpVerifyView(PublicAuthView):
    throttle_scope = "otp"

    def post(self, request):
        try:
            challenge = otp.load(
                request.data.get("challenge"), OtpChallenge.Purpose.LOGIN
            )
            otp.verify(challenge, request.data.get("code"))
        except otp.OtpError as exc:
            return otp_response(exc)

        user = challenge.user
        # Deactivated between the two steps — rare, but the password step's
        # check would otherwise be the only one.
        if not user.is_active:
            raise AuthenticationFailed("حساب کاربری غیرفعال است.")
        return Response(complete_login(user, request))


class OtpResendView(PublicAuthView):
    throttle_scope = "otp"

    def post(self, request):
        # One resend endpoint for every flow that shows a code box. The purpose
        # is still matched against the token, so naming the wrong one here just
        # fails to find the challenge — it cannot promote a code to another use.
        purpose = request.data.get("purpose") or OtpChallenge.Purpose.LOGIN
        if purpose not in OtpChallenge.Purpose.values:
            purpose = OtpChallenge.Purpose.LOGIN
        try:
            challenge = otp.load(request.data.get("challenge"), purpose)
            otp.resend(challenge)
        except otp.OtpError as exc:
            return otp_response(exc)
        return Response(otp.payload(challenge))


# ---------------------------------------------------------------------------
# Enrolment (self-service)
# ---------------------------------------------------------------------------
class TwoFactorView(APIView):
    """GET the current user's 2FA state."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(two_factor_status(request.user))


class TwoFactorStartView(APIView):
    """Send a code to the number the user wants to enrol."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "otp"

    def post(self, request):
        user = request.user
        # The password again: otherwise a laptop left unlocked for a minute is
        # enough to move someone's second factor to a stranger's phone.
        if not user.check_password(request.data.get("password") or ""):
            raise ValidationError({"password": "رمز عبور نادرست است."})

        phone = normalize_phone(request.data.get("phone") or user.phone)
        if not phone:
            raise ValidationError(
                {"phone": "شماره موبایل را به شکل ۰۹xxxxxxxxx وارد کنید."}
            )

        try:
            challenge = otp.start(
                user, OtpChallenge.Purpose.ENABLE, phone, client_ip(request)
            )
        except otp.OtpError as exc:
            return otp_response(exc)
        return Response(otp.payload(challenge))


class TwoFactorConfirmView(APIView):
    """Turn 2FA on once the code sent to the new number comes back."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "otp"

    def post(self, request):
        user = request.user
        try:
            challenge = otp.load(
                request.data.get("challenge"), OtpChallenge.Purpose.ENABLE
            )
            if challenge.user_id != user.pk:
                raise otp.OtpError("درخواست نامعتبر است.", 400)
            otp.verify(challenge, request.data.get("code"))
        except otp.OtpError as exc:
            return otp_response(exc)

        user.phone = challenge.phone
        user.two_factor_enabled = True
        user.two_factor_enabled_at = timezone.now()
        user.save(update_fields=["phone", "two_factor_enabled", "two_factor_enabled_at"])
        audit_log(
            user, user, AuditLog.Action.UPDATE,
            {"two_factor_enabled": {"before": "False", "after": "True"}},
        )
        return Response(two_factor_status(user))


class TwoFactorDisableView(APIView):
    """Turn 2FA off. Costs the account password, like enabling does."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.check_password(request.data.get("password") or ""):
            raise ValidationError({"password": "رمز عبور نادرست است."})

        was = user.two_factor_enabled
        user.two_factor_enabled = False
        user.two_factor_enabled_at = None
        user.save(update_fields=["two_factor_enabled", "two_factor_enabled_at"])
        OtpChallenge.objects.filter(user=user, consumed_at__isnull=True).update(
            consumed_at=timezone.now()
        )
        if was:
            audit_log(
                user, user, AuditLog.Action.UPDATE,
                {"two_factor_enabled": {"before": "True", "after": "False"}},
            )
        return Response(two_factor_status(user))
