"""
Sales rosters, derived from the chart.

`sales.EmployeeChannel` is still what the entry sheets, targets and dashboards
read — nothing downstream had to change. What changed is who writes it: not a
department manager typing names, but this function, from the positions on the
chart. Run after every change to units, positions or people.

Two rules keep it safe:

* **Only channels the chart has claimed are touched.** Until some unit says
  «I am فروش همکار», that channel's roster is left exactly as it was, so
  installing the module does not empty every entry sheet.
* **Nobody is deleted.** Leaving a channel deactivates the membership, which
  takes the person off the sheet and leaves every past figure where it was.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.hr.models import OrgUnit, Position
from apps.sales.models import EmployeeChannel


def unit_channels() -> dict[int, str]:
    """Each unit's effective sales channel: its own, else its nearest parent's."""
    units = {u.id: u for u in OrgUnit.objects.all()}

    def effective(unit: OrgUnit | None) -> str:
        channel, seen = "", set()
        while unit is not None and unit.id not in seen:
            # A closed unit anywhere above closes everything under it.
            if not unit.is_active:
                return ""
            if not channel and unit.sales_channel:
                channel = unit.sales_channel
            seen.add(unit.id)
            unit = units.get(unit.parent_id)
        return channel

    return {uid: effective(u) for uid, u in units.items()}


@transaction.atomic
def sync_rosters(today: date | None = None) -> dict[str, dict[str, int]]:
    today = today or date.today()
    claimed = set(
        OrgUnit.objects.exclude(sales_channel="").values_list("sales_channel", flat=True)
    )
    channels = unit_channels()
    wanted: dict[str, set[int]] = {c: set() for c in claimed}

    seats = Position.objects.filter(
        holder__isnull=False, holder__is_active=True, on_sales_sheet=True,
    ).values_list("unit_id", "holder_id")
    for unit_id, holder_id in seats:
        channel = channels.get(unit_id, "")
        if channel in wanted:
            wanted[channel].add(holder_id)

    summary: dict[str, dict[str, int]] = {}
    for channel, people in wanted.items():
        added = 0
        for employee_id in people:
            member, created = EmployeeChannel.objects.get_or_create(
                employee_id=employee_id, channel=channel,
                defaults={"joined_at": today},
            )
            if created:
                added += 1
            elif not member.is_active:
                member.is_active = True
                member.left_at = None
                member.save(update_fields=["is_active", "left_at", "updated_at"])
                added += 1
        removed = (
            EmployeeChannel.objects.filter(channel=channel, is_active=True)
            .exclude(employee_id__in=people)
            .update(is_active=False, left_at=today)
        )
        summary[channel] = {"members": len(people), "added": added, "removed": removed}
    return summary
