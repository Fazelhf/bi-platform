"""
The project's JWT authentication class.

Kept in its own module, importing *only* simplejwt's authentication layer:
`DEFAULT_AUTHENTICATION_CLASSES` is resolved by DRF while `rest_framework.views`
is still initialising, so anything this module pulls in must not reach back
into `rest_framework.views` (as `rest_framework_simplejwt.views` does) —
otherwise the import cycles and Django reports the class as missing.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class PanelJWTAuthentication(JWTAuthentication):
    """
    JWT auth that honours the Admin Panel's controls:

    * an account locked by an administrator is refused immediately;
    * "force logout" bumps `UserSecurity.tokens_valid_from`, and any token
      issued before that instant stops working — without it, a revoked user
      would keep their access until the token expired on its own.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        # Reverse one-to-one: raises RelatedObjectDoesNotExist (an
        # AttributeError subclass) when the row was never created.
        state = getattr(user, "security", None)
        if state is None:
            return user

        if state.is_locked:
            raise AuthenticationFailed(
                state.lock_reason or "حساب کاربری قفل شده است.",
                code="account_locked",
            )

        if state.tokens_valid_from:
            issued_at = validated_token.get("iat")
            if issued_at is not None:
                issued = datetime.fromtimestamp(int(issued_at), tz=dt_timezone.utc)
                if issued < state.tokens_valid_from:
                    raise AuthenticationFailed(
                        "نشست شما توسط مدیر سیستم پایان یافته است. دوباره وارد شوید.",
                        code="session_revoked",
                    )
        return user
