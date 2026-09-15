"""
Loading the chart, archiving people, and folding a duplicate into its original.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Count
from rest_framework.exceptions import ValidationError

from apps.hr.models import OrgUnit, Position
from apps.hr.services.chart_data import CHART
from apps.hr.services.names import clean, normalize
from apps.hr.services.rosters import sync_rosters
from apps.sales.models import DimEmployee, EmployeeChannel


def new_code() -> str:
    return f"hr-{uuid.uuid4().hex[:10]}"


def find_by_name(name: str, *, include_archived: bool = False) -> DimEmployee | None:
    """
    The existing person a name refers to, spelling differences forgiven.

    When several rows match, the one with the most history wins — a duplicate
    created by a stray import is the empty one.
    """
    key = normalize(name)
    if not key:
        return None
    qs = DimEmployee.objects.all()
    if not include_archived:
        qs = qs.filter(is_active=True)
    matches = [e for e in qs.annotate(n=Count("sales")) if normalize(e.full_name_fa) == key]
    if not matches:
        return None
    return sorted(matches, key=lambda e: (-e.is_active, -e.n, e.id))[0]


def duplicate_groups() -> list[list[DimEmployee]]:
    """People whose names are the same once spelling is ignored."""
    buckets: dict[str, list[DimEmployee]] = defaultdict(list)
    for e in DimEmployee.objects.all():
        key = normalize(e.full_name_fa)
        if key:
            buckets[key].append(e)
    return [rows for rows in buckets.values() if len(rows) > 1]


@transaction.atomic
def import_chart(chart: dict = CHART) -> dict:
    """
    Build the chart from its starting data. Only into an empty chart: run
    twice, it would put every seat on the chart twice.
    """
    if OrgUnit.objects.exists():
        raise ValidationError({"detail": "چارت سازمانی قبلا ساخته شده است."})

    stats = {"units": 0, "positions": 0, "vacant": 0, "matched": 0, "created": 0}
    people: dict[str, DimEmployee] = {}

    def person(name: str) -> DimEmployee:
        key = normalize(name)
        if key in people:
            return people[key]
        found = find_by_name(name, include_archived=True)
        if found:
            if not found.is_active:
                found.is_active = True
                found.archived_at = None
                found.save(update_fields=["is_active", "archived_at", "updated_at"])
            stats["matched"] += 1
        else:
            found = DimEmployee.objects.create(code=new_code(), full_name_fa=clean(name))
            stats["created"] += 1
        people[key] = found
        return found

    def build(node: dict, parent: OrgUnit | None, order: int, color: str):
        colour = node.get("color") or color
        unit = OrgUnit.objects.create(
            name_fa=node["name"], kind=node.get("kind", OrgUnit.Kind.SECTION),
            parent=parent, color=colour, sort_order=order,
            sales_channel=node.get("channel", ""),
        )
        stats["units"] += 1
        for i, (title, holder, is_head) in enumerate(node.get("positions", [])):
            Position.objects.create(
                unit=unit, title_fa=title, is_head=is_head, sort_order=i,
                holder=person(holder) if holder else None,
                on_sales_sheet=not is_head,
            )
            stats["positions"] += 1
            if not holder:
                stats["vacant"] += 1
        for i, child in enumerate(node.get("children", [])):
            build(child, unit, i, colour)

    build(chart, None, 0, "")
    stats["rosters"] = sync_rosters()
    return stats


@transaction.atomic
def archive(person: DimEmployee, note: str = "", today: date | None = None) -> None:
    """
    بایگانی: out of every current list, still in every old report.

    Their seats are emptied rather than deleted — the سمت still exists and
    now reads as vacant, which is the truth the day someone leaves.
    """
    person.is_active = False
    person.archived_at = today or date.today()
    person.archive_note = note[:200]
    person.save(update_fields=["is_active", "archived_at", "archive_note", "updated_at"])
    Position.objects.filter(holder=person).update(holder=None)
    sync_rosters(today)


@transaction.atomic
def restore(person: DimEmployee) -> None:
    person.is_active = True
    person.archived_at = None
    person.save(update_fields=["is_active", "archived_at", "updated_at"])
    sync_rosters()


def delete_impact(person: DimEmployee) -> dict:
    """
    What a permanent delete would take with it, and what it would orphan.

    Read off the relations themselves rather than a hand-kept list, so a model
    added later that points at a person is counted instead of silently lost.
    Sales figures are PROTECTed in the schema; a permanent delete removes them
    explicitly, which is why they are listed under «حذف می‌شود».
    """
    deleted, unlinked = [], []
    for rel in DimEmployee._meta.related_objects:
        if rel.many_to_many:
            continue
        model = rel.related_model
        count = model._default_manager.filter(**{rel.field.name: person}).count()
        if not count:
            continue
        row = {"model": model._meta.label, "label": str(model._meta.verbose_name), "count": count}
        (unlinked if rel.on_delete.__name__ == "SET_NULL" else deleted).append(row)
    return {
        "person": person.full_name_fa,
        "deleted": deleted,
        "unlinked": unlinked,
        "account": person.user.username if person.user_id else "",
    }


@transaction.atomic
def hard_delete(person: DimEmployee) -> dict:
    """
    حذف دائمی — the person and everything that is only theirs, gone for good.

    Their sales figures and targets go with them. Records that belong to the
    company as much as to them (a CRM customer, a deal, an invoice) stay, with
    no owner. The login account is left alone: deleting who can sign in is an
    admin-panel act with its own guard rails.
    """
    impact = delete_impact(person)
    for rel in DimEmployee._meta.related_objects:
        if not rel.many_to_many and rel.on_delete.__name__ == "PROTECT":
            rel.related_model._default_manager.filter(**{rel.field.name: person}).delete()
    person.delete()
    sync_rosters()
    return impact


@transaction.atomic
def merge(source: DimEmployee, target: DimEmployee) -> dict:
    """
    Fold a duplicate into the real person, moving everything that points at it.

    Every reverse relation is moved generically, so a model added later that
    points at DimEmployee is carried too. When both rows hold a figure for the
    same slot (the same month and channel, say), the merge refuses instead of
    choosing whose number survives.
    """
    if source.pk == target.pk:
        raise ValidationError({"detail": "یک نفر را نمی‌توان با خودش ادغام کرد."})

    moved: dict[str, int] = {}

    # Channel memberships are unique per person: merge the flags, not the rows.
    for m in EmployeeChannel.objects.filter(employee=source):
        twin = EmployeeChannel.objects.filter(employee=target, channel=m.channel).first()
        if twin:
            if m.is_active and not twin.is_active:
                twin.is_active, twin.left_at = True, None
                twin.save(update_fields=["is_active", "left_at", "updated_at"])
            m.delete()
        else:
            m.employee = target
            m.save(update_fields=["employee", "updated_at"])

    for rel in DimEmployee._meta.related_objects:
        if rel.many_to_many or rel.related_model is EmployeeChannel:
            continue
        model, field = rel.related_model, rel.field.name
        rows = model._default_manager.filter(**{field: source})
        if not rows.exists():
            continue
        try:
            with transaction.atomic():
                count = rows.update(**{field: target})
        except IntegrityError:
            raise ValidationError({
                "detail": f"هر دو نفر در «{model._meta.verbose_name}» برای یک دوره رکورد "
                          "دارند؛ ادغام انجام نشد. اول رکورد تکراری را اصلاح کنید."
            })
        moved[model._meta.label] = count

    if source.user_id and not target.user_id:
        user_id = source.user_id
        source.user = None
        source.save(update_fields=["user"])
        target.user_id = user_id
        target.save(update_fields=["user"])

    for field in ("mobile", "hired_on", "note"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
    target.save()

    source.delete()
    sync_rosters()
    return moved
