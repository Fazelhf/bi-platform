"""
Recycle bin — delete through here and a delete is always undoable.

`soft_delete` snapshots the row (including its primary key and every FK id)
into RecycleBin, then deletes it. `restore` re-inserts the snapshot with the
original pk, so anything that referenced it by id lines up again.

Rows are stored via Django's own serializer format, which already handles
dates, decimals and natural field types — no bespoke JSON coercion.
"""
from __future__ import annotations

import json

from django.apps import apps
from django.core import serializers as dj_serializers
from django.db import transaction

from apps.adminpanel.models import RecycleBin

#: Models an admin may delete/restore through the panel. Facts and dimensions
#: only — never auth rows (users have their own guarded endpoint) and never
#: the audit log, which is append-only by design.
DELETABLE_MODELS: dict[str, str] = {
    "sales.DimEmployee": "کارکنان فروش",
    "sales.DimTeam": "تیم‌های فروش",
    "sales.DimProvince": "استان‌ها",
    "sales.DimBank": "بانک‌ها",
    "sales.FactSalesMonthly": "فروش ماهانه",
    "sales.FactSalesProvince": "فروش استانی",
    "sales.FactCollection": "وصول مطالبات",
    "production.DimMachine": "ماشین‌آلات",
    "production.DimProduct": "محصولات",
    "production.DimCostCategory": "سرفصل هزینه",
    "production.FactProduction": "تولید ماهانه",
    "production.FactProductionCost": "هزینه تولید",
    "production.FactProductionRevenue": "درآمد اجرت",
    "core.DimKPI": "تعریف KPIها",
    "core.DimPeriod": "دوره‌ها",
    "adminpanel.Team": "تیم‌های سازمانی",
    "adminpanel.AdminFile": "فایل‌ها",
    "adminpanel.Announcement": "اطلاعیه‌ها",
}


class RecycleError(Exception):
    """Raised for an unknown model label or a restore that cannot proceed."""


def get_model(label: str):
    if label not in DELETABLE_MODELS:
        raise RecycleError(f"مدل «{label}» قابل مدیریت از این بخش نیست.")
    app_label, model_name = label.split(".")
    return apps.get_model(app_label, model_name)


def snapshot(instance) -> dict:
    """Serialised form of one row, ready to store as JSON."""
    raw = dj_serializers.serialize("json", [instance])
    return json.loads(raw)[0]


@transaction.atomic
def soft_delete(instance, user, note: str = "") -> RecycleBin:
    """Snapshot into the bin, then delete the row."""
    label = f"{instance._meta.app_label}.{instance._meta.object_name}"
    entry = RecycleBin.objects.create(
        model_label=label,
        object_id=str(instance.pk),
        object_repr=str(instance)[:250],
        payload=snapshot(instance),
        deleted_by=user if getattr(user, "is_authenticated", False) else None,
        note=note,
    )
    instance.delete()
    return entry


@transaction.atomic
def restore(entry: RecycleBin, user) -> object:
    """Re-insert the snapshot. Raises RecycleError if the pk is taken again."""
    if entry.restored_at:
        raise RecycleError("این رکورد قبلاً بازیابی شده است.")
    model = get_model(entry.model_label)
    if model.objects.filter(pk=entry.object_id).exists():
        raise RecycleError(
            "رکوردی با همین شناسه دوباره ساخته شده؛ ابتدا آن را حذف یا تغییر دهید."
        )
    payload = json.dumps([entry.payload])
    obj = None
    for deserialized in dj_serializers.deserialize("json", payload):
        deserialized.save()  # keeps the original pk
        obj = deserialized.object
    from django.utils import timezone

    entry.restored_at = timezone.now()
    entry.restored_by = user if getattr(user, "is_authenticated", False) else None
    entry.save(update_fields=["restored_at", "restored_by"])
    return obj


def purge(entry: RecycleBin) -> None:
    """Permanently forget a binned row (the snapshot itself is dropped)."""
    entry.delete()
