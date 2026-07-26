"""
The CRM demo gate.

CRM is shipped inside the main platform as a locked demo: the sidebar shows a
single «دمو CRM» entry, and nothing behind it opens until a separate password
— not the user's login password — is entered.

The lock is enforced **here, on the server**. Hiding the menu would be
theatre: `/api/crm/deals/` is one curl away, and the whole point is that this
data stays behind the extra password.

How it works: unlocking returns a signed, expiring grant that the client
sends back as an `X-CRM-Key` header. The grant is bound to the user who
earned it, so it cannot be handed to another account, and it carries its own
expiry so a demo left open on someone's laptop stops working by itself.
Signing (rather than a server-side session) keeps it stateless, matching the
JWT auth the rest of the platform already uses.
"""
from __future__ import annotations

import hmac

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from rest_framework.permissions import BasePermission

SALT = "crm.demo.gate"
HEADER = "HTTP_X_CRM_KEY"

#: How long one unlock lasts. A demo session, not a login — every user enters
#: the password themselves (the grant is bound to them, so it cannot be passed
#: around), and after an hour it lapses and they enter it again. Short on
#: purpose: a demo left open on an unattended screen closes itself.
TTL_SECONDS = 60 * 60

#: Brute-force budget per user per window.
MAX_ATTEMPTS = 8
ATTEMPT_WINDOW = 15 * 60


def demo_password() -> str:
    return getattr(settings, "CRM_DEMO_PASSWORD", "") or ""


def check_password(raw: str) -> bool:
    """Constant-time compare, so the password cannot be guessed by timing."""
    expected = demo_password()
    if not expected:
        return False
    return hmac.compare_digest(str(raw or ""), expected)


def issue(user) -> str:
    """A signed grant for this user."""
    return signing.dumps({"uid": user.id}, salt=SALT)


def verify(token: str, user) -> bool:
    if not token:
        return False
    try:
        data = signing.loads(token, salt=SALT, max_age=TTL_SECONDS)
    except signing.BadSignature:
        return False
    return data.get("uid") == user.id


# --------------------------------------------------------------------------
# Attempt throttling
# --------------------------------------------------------------------------
def _attempt_key(user) -> str:
    return f"crm-gate-attempts:{user.id}"


def attempts_left(user) -> int:
    return max(MAX_ATTEMPTS - cache.get(_attempt_key(user), 0), 0)


def record_failure(user) -> int:
    key = _attempt_key(user)
    count = cache.get(key, 0) + 1
    cache.set(key, count, ATTEMPT_WINDOW)
    return max(MAX_ATTEMPTS - count, 0)


def clear_failures(user) -> None:
    cache.delete(_attempt_key(user))


# --------------------------------------------------------------------------
# Permission
# --------------------------------------------------------------------------
class CrmUnlocked(BasePermission):
    """Every CRM endpoint requires a valid, unexpired demo grant."""

    message = "برای دسترسی به CRM ابتدا رمز دمو را وارد کنید."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        # An unset password means the demo is closed, not wide open — failing
        # shut is the only safe default for a feature whose entire purpose is
        # to be locked.
        if not demo_password():
            return False
        return verify(request.META.get(HEADER, ""), user)
