"""
Login auditing, account lockout and IP rules.

The lockout counter lives on UserSecurity and is driven entirely from here so
that the JWT view, the admin "unlock" action and the tests all agree on one
implementation.
"""
from __future__ import annotations

import ipaddress
from datetime import timedelta

from django.utils import timezone

from apps.adminpanel.models import IPRule, LoginEvent, PasswordPolicy, UserSecurity

CACHE_TTL = 20  # seconds — policy/IP rules are read on every login attempt


def client_ip(request) -> str | None:
    """Best-effort client IP, honouring the proxy header the deploy uses."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate
    return request.META.get("REMOTE_ADDR") or None


def user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:300]


# --------------------------------------------------------------------------
# IP rules
# --------------------------------------------------------------------------
def ip_allowed(ip: str | None) -> tuple[bool, str]:
    """
    -> (allowed, reason). Deny rules always win. If any active allow-rule
    exists the list becomes a whitelist and everything else is rejected.
    """
    policy = PasswordPolicy.get()
    if not policy.enforce_ip_rules:
        return True, ""
    if not ip:
        return True, ""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True, ""

    rules = list(IPRule.objects.filter(is_active=True))
    if not rules:
        return True, ""

    def matches(rule: IPRule) -> bool:
        try:
            return addr in ipaddress.ip_network(rule.cidr, strict=False)
        except ValueError:
            return False

    if any(r.mode == IPRule.Mode.DENY and matches(r) for r in rules):
        return False, "ip_blocked"

    allow_rules = [r for r in rules if r.mode == IPRule.Mode.ALLOW]
    if allow_rules and not any(matches(r) for r in allow_rules):
        return False, "ip_not_whitelisted"
    return True, ""


# --------------------------------------------------------------------------
# Lockout
# --------------------------------------------------------------------------
def lock_state(user) -> tuple[bool, str]:
    """-> (locked, Persian reason)."""
    sec = UserSecurity.get(user)
    if sec.is_locked:
        return True, sec.lock_reason or "حساب کاربری توسط مدیر سیستم قفل شده است."
    if sec.locked_until and sec.locked_until > timezone.now():
        minutes = int((sec.locked_until - timezone.now()).total_seconds() // 60) + 1
        return True, f"حساب موقتاً قفل است. {minutes} دقیقه دیگر تلاش کنید."
    return False, ""


def register_failure(username: str, request, reason: str = "bad_password") -> None:
    """Record a failed attempt and trip the lockout when the threshold is hit."""
    from apps.accounts.models import User

    user = User.objects.filter(username=username).first()
    policy = PasswordPolicy.get()
    if user and policy.max_failed_attempts:
        sec = UserSecurity.get(user)
        sec.failed_attempts += 1
        if sec.failed_attempts >= policy.max_failed_attempts:
            sec.locked_until = timezone.now() + timedelta(
                minutes=policy.lockout_minutes or 15
            )
            sec.failed_attempts = 0
            reason = "locked_out"
        sec.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
    LoginEvent.objects.create(
        user=user, username_attempted=username, success=False, reason=reason,
        ip_address=client_ip(request), user_agent=user_agent(request),
    )


def register_success(user, request) -> None:
    sec = UserSecurity.get(user)
    if sec.failed_attempts or sec.locked_until:
        sec.failed_attempts = 0
        sec.locked_until = None
        sec.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
    LoginEvent.objects.create(
        user=user, username_attempted=user.username, success=True,
        ip_address=client_ip(request), user_agent=user_agent(request),
    )


def force_logout(user) -> None:
    """Invalidate every JWT issued to this user before now."""
    sec = UserSecurity.get(user)
    sec.tokens_valid_from = timezone.now()
    sec.save(update_fields=["tokens_valid_from", "updated_at"])


def password_expired(user) -> bool:
    policy = PasswordPolicy.get()
    if not policy.expiry_days:
        return False
    sec = UserSecurity.get(user)
    changed = sec.password_changed_at or user.date_joined
    return timezone.now() - changed > timedelta(days=policy.expiry_days)


def active_sessions() -> list[dict]:
    """
    "Sessions" for a JWT platform = accounts with a live presence heartbeat.
    The frontend pings /auth/heartbeat/ every 30s, so last_seen is the honest
    signal of who is actually using the app right now.
    """
    from apps.accounts.models import ONLINE_WINDOW, User

    cutoff = timezone.now() - ONLINE_WINDOW
    rows = []
    for u in User.objects.filter(last_seen__gte=cutoff).select_related("security"):
        last_login_event = (
            LoginEvent.objects.filter(user=u, success=True).first()
        )
        rows.append({
            "user_id": u.id,
            "username": u.username,
            "name": u.display_name_fa or u.username,
            "role": u.role,
            "last_seen": u.last_seen,
            "ip_address": last_login_event.ip_address if last_login_event else None,
            "user_agent": last_login_event.user_agent if last_login_event else "",
            "since": last_login_event.created_at if last_login_event else None,
        })
    return rows
