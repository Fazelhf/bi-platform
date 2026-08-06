"""
The login endpoint, with the panel's security policy applied.

The authentication *class* lives in `apps.adminpanel.authentication` — it must
not import simplejwt's views (see the note there).
"""
from __future__ import annotations

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.adminpanel.authentication import PanelJWTAuthentication  # noqa: F401
from apps.adminpanel.services import security as sec_service


class PanelTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login with IP rules, account lockout and login auditing applied. Every
    outcome — blocked IP, locked account, wrong password, success — leaves a
    LoginEvent behind, which is what the security page reports on.
    """

    def validate(self, attrs):
        request = self.context.get("request")
        username = attrs.get(self.username_field, "")

        allowed, reason = sec_service.ip_allowed(sec_service.client_ip(request))
        if not allowed:
            sec_service.register_failure(username, request, reason)
            raise serializers.ValidationError(
                {"detail": "ورود از این آدرس شبکه مجاز نیست."}
            )

        from apps.accounts.models import User

        user = User.objects.filter(username=username).first()
        if user:
            locked, message = sec_service.lock_state(user)
            if locked:
                sec_service.register_failure(username, request, "locked")
                raise serializers.ValidationError({"detail": message})

        try:
            data = super().validate(attrs)
        except Exception:
            sec_service.register_failure(username, request, "bad_password")
            raise

        sec_service.register_success(self.user, request)

        from apps.adminpanel.models import UserSecurity

        state = UserSecurity.get(self.user)
        data["must_change_password"] = bool(
            state.must_change_password or sec_service.password_expired(self.user)
        )
        data["is_admin_panel_user"] = self.user.is_admin_panel_user
        return data


class PanelTokenObtainPairView(TokenObtainPairView):
    """No longer routed — do not put this back on /api/auth/token/.

    Two-step login owns that URL now (apps.accounts.twofactor.LoginView), and
    it applies the policy in the serializer above. Routing this view again
    would restore IP rules and auditing while silently dropping the second
    factor, because this class mints tokens straight from the password.
    """

    serializer_class = PanelTokenObtainPairSerializer
