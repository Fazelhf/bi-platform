"""
Request-level enforcement of two admin switches: maintenance mode and IP rules.

Both are checked before the view runs, so a locked-down platform never touches
business logic. Administrators are always let through — otherwise turning
maintenance mode on would lock the person who turned it on out of the switch.
"""
from __future__ import annotations

from django.core.cache import cache
from django.http import JsonResponse

#: Always reachable, even in maintenance mode: login, identity, the admin API
#: itself, the docs, and anything that is not the REST API (SPA assets).
_ALWAYS_OPEN = (
    "/api/auth/token/",
    "/api/auth/token/refresh/",
    "/api/auth/me/",
    "/api/admin/",
    "/api/docs/",
    "/api/schema/",
)


def _maintenance_state() -> tuple[bool, str]:
    """Cached for 10s so this costs ~nothing per request."""
    cached = cache.get("adminpanel:maintenance")
    if cached is not None:
        return cached
    try:
        from apps.adminpanel.models import SystemConfig

        on = bool(SystemConfig.get_value("maintenance_mode", False))
        message = SystemConfig.get_value(
            "maintenance_message",
            "سامانه موقتاً در حال به‌روزرسانی است. لطفاً بعداً تلاش کنید.",
        )
        state = (on, message)
    except Exception:
        # Before the first migrate the table does not exist yet.
        state = (False, "")
    cache.set("adminpanel:maintenance", state, 10)
    return state


def clear_maintenance_cache() -> None:
    cache.delete("adminpanel:maintenance")


class AdminGuardMiddleware:
    """Applies IP rules and maintenance mode to /api/ requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not path.startswith("/api/"):
            return self.get_response(request)

        from apps.adminpanel.services import security as sec

        # --- IP rules (opt-in via the security policy) ---
        try:
            allowed, reason = sec.ip_allowed(sec.client_ip(request))
        except Exception:
            allowed, reason = True, ""
        if not allowed:
            return JsonResponse(
                {"detail": "دسترسی از این آدرس شبکه مجاز نیست.", "code": reason},
                status=403,
            )

        # --- Maintenance mode ---
        on, message = _maintenance_state()
        if on and not path.startswith(_ALWAYS_OPEN):
            if not self._is_admin(request):
                return JsonResponse(
                    {"detail": message, "code": "maintenance"}, status=503
                )
        return self.get_response(request)

    @staticmethod
    def _is_admin(request) -> bool:
        """Authenticate the bearer token just enough to spot an administrator."""
        try:
            from apps.adminpanel.authentication import PanelJWTAuthentication

            result = PanelJWTAuthentication().authenticate(request)
            return bool(result and result[0].is_admin_panel_user)
        except Exception:
            return False
