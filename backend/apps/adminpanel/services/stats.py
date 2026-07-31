"""
Numbers for the admin dashboard, the database page and the monitoring page.

Everything here is measured, never guessed: if a figure cannot be obtained on
the current stack (e.g. table sizes on SQLite, or Celery when no broker is
reachable) the payload says so with `available: False` rather than inventing
a value.
"""
from __future__ import annotations

import os
import platform
import sys
from datetime import timedelta

import django
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.accounts.models import ONLINE_WINDOW, User
from apps.adminpanel.models import (
    AdminFile,
    ApiToken,
    BackupRecord,
    LoginEvent,
    RecycleBin,
    Team,
)
from apps.core.models import AuditLog, DimPeriod, FactKPI, Notification


# --------------------------------------------------------------------------
# Dashboard (6)
# --------------------------------------------------------------------------
def dashboard() -> dict:
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    online_since = now - ONLINE_WINDOW

    users = User.objects.all()
    logins_24h = LoginEvent.objects.filter(created_at__gte=day_ago)

    return {
        "users": {
            "total": users.count(),
            "active": users.filter(is_active=True).count(),
            "inactive": users.filter(is_active=False).count(),
            "online": users.filter(last_seen__gte=online_since).count(),
            "admins": users.filter(is_superuser=True).count()
            + users.filter(role="admin").exclude(is_superuser=True).count(),
            "new_this_week": users.filter(date_joined__gte=week_ago).count(),
        },
        "activity": {
            "audit_24h": AuditLog.objects.filter(created_at__gte=day_ago).count(),
            "audit_total": AuditLog.objects.count(),
            "logins_24h": logins_24h.filter(success=True).count(),
            "failed_logins_24h": logins_24h.filter(success=False).count(),
            "notifications_unread": Notification.objects.filter(is_read=False).count(),
        },
        "storage": storage(),
        "database": database(),
        "content": {
            "periods": DimPeriod.objects.count(),
            "kpi_results": FactKPI.objects.count(),
            "teams": Team.objects.count(),
            "files": AdminFile.objects.filter(is_current=True).count(),
            "recycle_bin": RecycleBin.objects.filter(restored_at__isnull=True).count(),
            "backups": BackupRecord.objects.count(),
        },
        "errors": error_summary(),
        "generated_at": now.isoformat(),
    }


def recent_activity(limit: int = 15) -> list[dict]:
    """A merged timeline of audit entries and logins, newest first."""
    items: list[dict] = []
    for row in AuditLog.objects.select_related("user")[:limit]:
        items.append({
            "kind": "audit",
            "action": row.action,
            "actor": (row.user.display_name_fa or row.user.username) if row.user else "سیستم",
            "text": f"{row.get_action_display()} · {row.object_repr or row.model_label}",
            "at": row.created_at.isoformat(),
        })
    for row in LoginEvent.objects.select_related("user")[:limit]:
        items.append({
            "kind": "login" if row.success else "login_failed",
            "action": "login" if row.success else "login_failed",
            "actor": row.username_attempted or "—",
            "text": ("ورود موفق" if row.success else f"ورود ناموفق ({row.reason})")
                    + (f" از {row.ip_address}" if row.ip_address else ""),
            "at": row.created_at.isoformat(),
        })
    items.sort(key=lambda i: i["at"], reverse=True)
    return items[:limit]


# --------------------------------------------------------------------------
# Storage & database (6, 12)
# --------------------------------------------------------------------------
def storage() -> dict:
    """Disk usage of the deployment directory, plus in-DB blob usage."""
    base = settings.BASE_DIR
    try:
        import shutil

        total, used, free = shutil.disk_usage(base)
        disk = {"available": True, "total": total, "used": used, "free": free}
    except OSError:
        disk = {"available": False}

    # The platform stores avatars and admin files as data-URLs inside the DB,
    # so "storage" also means text volume in those columns.
    blob_bytes = sum(
        len(v or "") for v in AdminFile.objects.values_list("content", flat=True)
    )
    avatar_bytes = sum(
        len(v or "") for v in User.objects.values_list("avatar_image", flat=True)
    )
    backups_dir = base / "backups"
    backup_bytes = 0
    if backups_dir.exists():
        backup_bytes = sum(f.stat().st_size for f in backups_dir.glob("*") if f.is_file())

    return {
        "disk": disk,
        "db_files_bytes": blob_bytes,
        "db_avatars_bytes": avatar_bytes,
        "backups_bytes": backup_bytes,
        "db_file_bytes": _sqlite_file_size(),
    }


def _sqlite_file_size() -> int | None:
    name = settings.DATABASES["default"].get("NAME")
    if connection.vendor != "sqlite" or not name:
        return None
    try:
        return os.path.getsize(name)
    except OSError:
        return None


def database() -> dict:
    """Vendor, size and per-table row counts — measured, not estimated."""
    tables = table_stats()
    return {
        "vendor": connection.vendor,
        "name": str(settings.DATABASES["default"].get("NAME", "")),
        "size_bytes": _database_size(),
        "table_count": len(tables),
        "row_total": sum(t["rows"] for t in tables),
        "tables": tables,
    }


def _database_size() -> int | None:
    if connection.vendor == "sqlite":
        return _sqlite_file_size()
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            return cur.fetchone()[0]
    return None


def table_stats() -> list[dict]:
    """[{table, model, rows, bytes|None}] for every app table, biggest first."""
    from django.apps import apps as django_apps

    sizes: dict[str, int] = {}
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute(
                "SELECT relname, pg_total_relation_size(c.oid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
            sizes = dict(cur.fetchall())

    rows: list[dict] = []
    for model in django_apps.get_models():
        table = model._meta.db_table
        try:
            count = model.objects.count()
        except Exception:  # table missing (unmigrated) — report it as such
            continue
        rows.append({
            "table": table,
            "model": f"{model._meta.app_label}.{model._meta.object_name}",
            "label": model._meta.verbose_name,
            "rows": count,
            "bytes": sizes.get(table),
        })
    rows.sort(key=lambda r: (r["bytes"] or 0, r["rows"]), reverse=True)
    return rows


# --------------------------------------------------------------------------
# Monitoring (14)
# --------------------------------------------------------------------------
def server() -> dict:
    boot = getattr(settings, "PROCESS_STARTED_AT", None)
    return {
        "python": sys.version.split()[0],
        "django": django.get_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "hostname": platform.node(),
        "debug": settings.DEBUG,
        "timezone": settings.TIME_ZONE,
        "pid": os.getpid(),
        "started_at": boot.isoformat() if boot else None,
        "uptime_seconds": int((timezone.now() - boot).total_seconds()) if boot else None,
    }


def api_health() -> dict:
    """Round-trip the database and the cache to prove the API path works."""
    import time

    checks = []

    start = time.perf_counter()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks.append({"name": "database", "ok": True,
                       "ms": round((time.perf_counter() - start) * 1000, 2)})
    except Exception as exc:
        checks.append({"name": "database", "ok": False, "error": str(exc)[:200]})

    start = time.perf_counter()
    try:
        from django.core.cache import cache

        cache.set("adminpanel:health", "1", 10)
        ok = cache.get("adminpanel:health") == "1"
        checks.append({"name": "cache", "ok": ok,
                       "ms": round((time.perf_counter() - start) * 1000, 2),
                       "backend": settings.CACHES["default"]["BACKEND"].split(".")[-1]
                       if hasattr(settings, "CACHES") else "locmem"})
    except Exception as exc:
        checks.append({"name": "cache", "ok": False, "error": str(exc)[:200]})

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def queues() -> dict:
    """
    Celery/broker status. Returns available=False (with the reason) when no
    worker answers — the platform runs fine without one in eager mode.
    """
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return {"available": False, "reason": "eager",
                "detail": "کارها به‌صورت همزمان اجرا می‌شوند (بدون کارگر)."}
    try:
        from config.celery import app as celery_app

        inspector = celery_app.control.inspect(timeout=1.5)
        active = inspector.active() or {}
        scheduled = inspector.scheduled() or {}
        reserved = inspector.reserved() or {}
        if not active and not scheduled and not reserved:
            return {"available": False, "reason": "no_workers",
                    "detail": "هیچ کارگری پاسخ نداد."}
        return {
            "available": True,
            "broker": settings.CELERY_BROKER_URL.split("@")[-1],
            "workers": [
                {
                    "name": name,
                    "active": len(active.get(name, [])),
                    "scheduled": len(scheduled.get(name, [])),
                    "reserved": len(reserved.get(name, [])),
                }
                for name in set(active) | set(scheduled) | set(reserved)
            ],
        }
    except Exception as exc:
        return {"available": False, "reason": "error", "detail": str(exc)[:200]}


def error_summary(days: int = 7) -> dict:
    """What went wrong lately, from the signals the platform actually records."""
    since = timezone.now() - timedelta(days=days)
    failed = LoginEvent.objects.filter(success=False, created_at__gte=since)
    by_reason: dict[str, int] = {}
    for reason in failed.values_list("reason", flat=True):
        by_reason[reason or "unknown"] = by_reason.get(reason or "unknown", 0) + 1
    return {
        "window_days": days,
        "failed_logins": failed.count(),
        "failed_by_reason": by_reason,
        "locked_accounts": User.objects.filter(security__is_locked=True).count(),
        "expired_tokens": ApiToken.objects.filter(
            is_active=True, expires_at__lt=timezone.now()
        ).count(),
    }
