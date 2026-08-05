from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts import recovery, twofactor, views

router = DefaultRouter()
router.register("users", views.UserViewSet)
router.register("team", views.TeamViewSet, basename="team")
router.register("notes", views.NoteViewSet, basename="note")
router.register("messages", views.MessageViewSet, basename="message")

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("heartbeat/", views.HeartbeatView.as_view(), name="heartbeat"),
    # --- Two-step login (ورود دو مرحله‌ای) ---
    # `verify` and `resend` are open by design: the caller has passed the
    # password step but has no token yet, which is the whole point of them.
    path("2fa/verify/", twofactor.OtpVerifyView.as_view(), name="otp-verify"),
    path("2fa/resend/", twofactor.OtpResendView.as_view(), name="otp-resend"),
    path("2fa/", twofactor.TwoFactorView.as_view(), name="two-factor"),
    path("2fa/start/", twofactor.TwoFactorStartView.as_view(), name="two-factor-start"),
    path("2fa/confirm/", twofactor.TwoFactorConfirmView.as_view(), name="two-factor-confirm"),
    path("2fa/disable/", twofactor.TwoFactorDisableView.as_view(), name="two-factor-disable"),
    # --- Getting in without the password (both open, both throttled) ---
    path("otp-login/start/", recovery.OtpLoginStartView.as_view(), name="otp-login-start"),
    path("otp-login/verify/", recovery.OtpLoginVerifyView.as_view(), name="otp-login-verify"),
    path("password-reset/start/", recovery.PasswordResetStartView.as_view(),
         name="password-reset-start"),
    path("password-reset/verify/", recovery.PasswordResetVerifyView.as_view(),
         name="password-reset-verify"),
    path("password-reset/confirm/", recovery.PasswordResetConfirmView.as_view(),
         name="password-reset-confirm"),
    path("", include(router.urls)),
]
