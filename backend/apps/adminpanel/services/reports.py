"""
Report datasets. Each builder returns (columns, rows, title) and is rendered
by services.exporters into xlsx / csv / print-ready PDF.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import User
from apps.adminpanel.models import LoginEvent, Team
from apps.core.models import AuditLog, FactKPI

DEPT_LABEL = {
    "": "—", "production": "تولید", "sales_org": "فروش بانکی",
    "sales_team": "فروش همکار", "sales_b2b": "فروش B2B",
}
ROLE_LABEL = {
    "admin": "ادمین سیستم", "executive": "مدیرعامل", "manager": "مدیر بخش",
    "operator": "اپراتور", "viewer": "بیننده",
}


def _days(params: dict, default: int = 30) -> int:
    try:
        return max(1, min(int(params.get("days", default)), 365))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
def users_report(params: dict):
    columns = [
        ("username", "نام کاربری"), ("name", "نام"), ("role", "نقش"),
        ("department", "بخش"), ("is_active", "فعال"), ("admin_access", "دسترسی ادمین"),
        ("teams", "تیم‌ها"), ("roles", "نقش‌های ادمین"),
        ("last_login", "آخرین ورود"), ("date_joined", "تاریخ ایجاد"),
    ]
    rows = []
    qs = User.objects.prefetch_related(
        "team_memberships__team", "admin_roles__role"
    ).order_by("username")
    for u in qs:
        rows.append({
            "username": u.username,
            "name": u.display_name_fa or "—",
            "role": ROLE_LABEL.get(u.role, u.role),
            "department": DEPT_LABEL.get(u.department, u.department),
            "is_active": u.is_active,
            "admin_access": u.is_admin_panel_user,
            "teams": "، ".join(m.team.name_fa for m in u.team_memberships.all()) or "—",
            "roles": "، ".join(a.role.name_fa for a in u.admin_roles.all()) or "—",
            "last_login": u.last_login,
            "date_joined": u.date_joined,
        })
    return columns, rows, "گزارش کاربران"


def activity_report(params: dict):
    days = _days(params)
    since = timezone.now() - timedelta(days=days)
    columns = [
        ("name", "کاربر"), ("username", "نام کاربری"), ("actions", "تعداد عملیات"),
        ("logins", "ورود موفق"), ("failed", "ورود ناموفق"), ("last_seen", "آخرین حضور"),
    ]
    audit = dict(
        AuditLog.objects.filter(created_at__gte=since)
        .values_list("user_id")
        .annotate(n=Count("id"))
    )
    logins = dict(
        LoginEvent.objects.filter(created_at__gte=since, success=True)
        .values_list("user_id").annotate(n=Count("id"))
    )
    rows = []
    for u in User.objects.order_by("username"):
        failed = LoginEvent.objects.filter(
            username_attempted=u.username, success=False, created_at__gte=since
        ).count()
        rows.append({
            "name": u.display_name_fa or u.username,
            "username": u.username,
            "actions": audit.get(u.id, 0),
            "logins": logins.get(u.id, 0),
            "failed": failed,
            "last_seen": u.last_seen,
        })
    rows.sort(key=lambda r: r["actions"], reverse=True)
    return columns, rows, f"گزارش فعالیت کاربران ({days} روز)"


def audit_report(params: dict):
    days = _days(params)
    since = timezone.now() - timedelta(days=days)
    columns = [
        ("at", "زمان"), ("user", "کاربر"), ("action", "عملیات"),
        ("model", "موجودیت"), ("object", "رکورد"), ("changes", "تغییرات"),
    ]
    rows = [
        {
            "at": e.created_at,
            "user": (e.user.display_name_fa or e.user.username) if e.user else "سیستم",
            "action": e.get_action_display(),
            "model": e.model_label,
            "object": e.object_repr,
            "changes": "، ".join(
                f"{k}: {v.get('before')} ← {v.get('after')}"
                for k, v in (e.changes or {}).items()
            ),
        }
        for e in AuditLog.objects.select_related("user").filter(created_at__gte=since)[:5000]
    ]
    return columns, rows, f"گزارش رخدادها ({days} روز)"


def logins_report(params: dict):
    days = _days(params)
    since = timezone.now() - timedelta(days=days)
    columns = [
        ("at", "زمان"), ("username", "نام کاربری"), ("success", "موفق"),
        ("reason", "علت"), ("ip", "IP"), ("agent", "مرورگر"),
    ]
    rows = [
        {
            "at": e.created_at, "username": e.username_attempted,
            "success": e.success, "reason": e.reason or "—",
            "ip": e.ip_address or "—", "agent": e.user_agent[:80],
        }
        for e in LoginEvent.objects.filter(created_at__gte=since)[:5000]
    ]
    return columns, rows, f"گزارش ورودها ({days} روز)"


def kpi_report(params: dict, domain: str):
    columns = [
        ("period", "دوره"), ("kpi", "شاخص"), ("scope", "سطح"),
        ("label", "عنوان"), ("channel", "کانال"),
        ("actual", "واقعی"), ("target", "مطلوب"), ("efficiency", "کارایی %"),
    ]
    qs = FactKPI.objects.select_related("kpi", "period").filter(kpi__domain=domain)
    if params.get("period"):
        qs = qs.filter(period_id=params["period"])
    rows = [
        {
            "period": k.period.label, "kpi": k.kpi.name_fa, "scope": k.scope,
            "label": k.scope_label, "channel": k.channel or "—",
            "actual": k.actual, "target": k.target, "efficiency": k.efficiency_pct,
        }
        for k in qs[:5000]
    ]
    title = "گزارش شاخص‌های فروش" if domain == "sales" else "گزارش شاخص‌های تولید"
    return columns, rows, title


def system_report(params: dict):
    from apps.adminpanel.services import stats

    d = stats.dashboard()
    columns = [("metric", "شاخص"), ("value", "مقدار")]
    rows = [
        {"metric": "کل کاربران", "value": d["users"]["total"]},
        {"metric": "کاربران فعال", "value": d["users"]["active"]},
        {"metric": "کاربران آنلاین", "value": d["users"]["online"]},
        {"metric": "ادمین‌ها", "value": d["users"]["admins"]},
        {"metric": "رخدادهای ۲۴ ساعت", "value": d["activity"]["audit_24h"]},
        {"metric": "ورود موفق ۲۴ ساعت", "value": d["activity"]["logins_24h"]},
        {"metric": "ورود ناموفق ۲۴ ساعت", "value": d["activity"]["failed_logins_24h"]},
        {"metric": "تعداد جدول‌ها", "value": d["database"]["table_count"]},
        {"metric": "کل ردیف‌ها", "value": d["database"]["row_total"]},
        {"metric": "حجم پایگاه داده (بایت)", "value": d["database"]["size_bytes"] or "—"},
        {"metric": "تیم‌ها", "value": d["content"]["teams"]},
        {"metric": "سطل بازیافت", "value": d["content"]["recycle_bin"]},
        {"metric": "پشتیبان‌ها", "value": d["content"]["backups"]},
    ]
    return columns, rows, "گزارش وضعیت سیستم"


def teams_report(params: dict):
    columns = [
        ("name", "تیم"), ("code", "کد"), ("department", "بخش"),
        ("manager", "مدیر"), ("parent", "تیم بالادست"), ("members", "تعداد اعضا"),
    ]
    rows = [
        {
            "name": t.name_fa, "code": t.code,
            "department": DEPT_LABEL.get(t.department, t.department or "—"),
            "manager": str(t.manager) if t.manager else "—",
            "parent": t.parent.name_fa if t.parent else "—",
            "members": t.member_count,
        }
        for t in Team.objects.select_related("manager", "parent")
    ]
    return columns, rows, "گزارش تیم‌ها"


BUILDERS = {
    "users": users_report,
    "activity": activity_report,
    "audit": audit_report,
    "logins": logins_report,
    "teams": teams_report,
    "sales": lambda p: kpi_report(p, "sales"),
    "production": lambda p: kpi_report(p, "production"),
    "system": system_report,
}


def build(kind: str, params: dict | None = None):
    if kind not in BUILDERS:
        raise ValueError(f"نوع گزارش «{kind}» تعریف نشده است.")
    return BUILDERS[kind](params or {})
