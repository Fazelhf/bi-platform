"""
Backup & restore built on Django's own dumpdata/loaddata.

Snapshots are plain JSON fixtures under BASE_DIR/backups/, so they are
portable across SQLite and PostgreSQL and can be restored on a different
machine. Session and token tables are excluded: restoring them would resurrect
dead sessions.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from apps.adminpanel.models import BackupRecord

#: Never dumped — transient or environment-specific.
EXCLUDES = [
    "contenttypes",
    "auth.Permission",
    "sessions.Session",
    "admin.LogEntry",
]

#: What the UI offers as a scope.
SCOPES: dict[str, list[str]] = {
    "full": [],  # everything except EXCLUDES
    "accounts": ["accounts"],
    "adminpanel": ["adminpanel"],
    "business": ["sales", "production", "core"],
}

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+\.json$")


def backups_dir():
    path = settings.BASE_DIR / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create(user, scope: str = "full", note: str = "") -> BackupRecord:
    """Write a dumpdata snapshot and record it."""
    if scope not in SCOPES:
        raise ValueError(f"دامنه پشتیبان «{scope}» معتبر نیست.")
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    filename = f"backup-{scope}-{stamp}.json"
    target = backups_dir() / filename

    buffer = io.StringIO()
    call_command(
        "dumpdata", *SCOPES[scope],
        exclude=EXCLUDES, indent=1, stdout=buffer,
        natural_foreign=True,
    )
    target.write_text(buffer.getvalue(), encoding="utf-8")

    return BackupRecord.objects.create(
        filename=filename,
        size_bytes=target.stat().st_size,
        scope=scope,
        note=note,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def path_for(record: BackupRecord):
    """Resolve a record to a file path, refusing anything outside backups/."""
    if not SAFE_NAME.match(record.filename):
        raise ValueError("نام فایل پشتیبان معتبر نیست.")
    path = (backups_dir() / record.filename).resolve()
    if path.parent != backups_dir().resolve():
        raise ValueError("مسیر فایل پشتیبان معتبر نیست.")
    if not path.exists():
        raise ValueError("فایل پشتیبان روی سرور یافت نشد.")
    return path


def restore(record: BackupRecord, user) -> BackupRecord:
    """
    Load a snapshot back in. loaddata upserts by primary key: rows in the
    fixture overwrite current ones, rows created since the backup are left
    alone (it is a merge, not a wipe).
    """
    path = path_for(record)
    call_command("loaddata", str(path), verbosity=0)
    record.restored_at = timezone.now()
    record.save(update_fields=["restored_at"])
    return record


def discover_orphans() -> list[dict]:
    """Files sitting in backups/ with no BackupRecord (e.g. copied in by hand)."""
    known = set(BackupRecord.objects.values_list("filename", flat=True))
    out = []
    for f in sorted(backups_dir().glob("*.json")):
        if f.name not in known:
            out.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.get_current_timezone()
                ).isoformat(),
            })
    return out


def delete_file(record: BackupRecord) -> None:
    try:
        path_for(record).unlink()
    except (ValueError, OSError):
        pass  # record removal proceeds even if the file is already gone
