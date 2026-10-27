"""
A salesperson's name in آرپا or دیدار onto a colleague on the roster.

Both uploads need this and must agree, or the same invoice and the same call
would land on two different people. The rule: the same words, or one name's
words all inside the other's («هانیه خواجه منزه» is «هانیه منزه»). It stops
there. A different surname or given name is either two people or a typo, and
fusing them halves a real person's numbers wherever they are reported — so
an unknown name leaves the owner blank and is reported, and no employee is
ever created from an import.
"""
from __future__ import annotations

from collections import Counter

from apps.crm.matching import fold, name_key
from apps.sales.models import DimEmployee

def sales_roster(channels=None):
    """
    کارشناسان فعال واحد فروش: active, real (not a placeholder) employees with
    an active membership in a sales channel — the roster HR keeps from the
    sales units of the org chart (`hr.services.rosters.sync_rosters`).

    Finance, production and warehouse staff have no such membership, which is
    what keeps them out of every CRM picker.

    The managers are added from the org chart's seats: a سرپرست is kept off
    the sales sheet (`Position.on_sales_sheet`), so HR never gives them a
    membership, and مدیر فروش sits in «فروش», which is no book of its own.
    """
    from django.db.models import Q

    from apps.sales.models import DimEmployee

    match = Q(memberships__is_active=True)
    if channels is not None:
        match &= Q(memberships__channel__in=list(channels))
    wanted = None if channels is None else set(channels)
    managers = [e for e, chs in sales_seats().items() if wanted is None or chs & wanted]
    return (
        DimEmployee.objects.filter(is_active=True, is_placeholder=False)
        .exclude(full_name_fa__in=["", "0"])
        .filter(match | Q(pk__in=managers)).distinct()
    )


def sales_seats() -> dict[int, set[str]]:
    """
    Holder of every seat in a sales unit → the books under that seat, on the
    sales sheet or not. A sales unit has a channel (its own or a parent's), or
    is a unit whose sub-units are all sales units — «فروش» above همکار, B2B
    and بانکی — so a head of the whole company is never counted.
    """
    from apps.hr.models import OrgUnit, Position
    from apps.hr.services.rosters import unit_channels

    own = unit_channels()
    kids: dict[int, list[int]] = {}
    for uid, parent, active in OrgUnit.objects.values_list("id", "parent_id", "is_active"):
        if parent and active:
            kids.setdefault(parent, []).append(uid)

    memo: dict[int, set[str]] = {}

    def books(uid: int, seen=frozenset()) -> set[str]:
        if uid not in memo:
            if own.get(uid):
                memo[uid] = {own[uid]}
            elif uid in seen or not kids.get(uid):
                return set()
            else:
                parts = [books(k, seen | {uid}) for k in kids[uid]]
                memo[uid] = set().union(*parts) if all(parts) else set()
        return memo[uid]

    seats: dict[int, set[str]] = {}
    for unit, holder in Position.objects.filter(
        holder__isnull=False, holder__is_active=True, unit__is_active=True,
    ).values_list("unit_id", "holder_id"):
        if chs := books(unit):
            seats.setdefault(holder, set()).update(chs)
    return seats


#: A placeholder in آرپا's بازاریاب column, not a colleague. 425 of 1,098
#: invoices carry it.
NO_REP = "بازاریاب بدون پورسانت"

#: Colleagues whose two spellings no rule can bridge, because it is the name
#: that differs and not its spelling. Both confirmed by the sales manager as
#: one person; written down precisely because a rule loose enough to catch
#: them would also fuse people who merely share a surname.
REP_ALIASES = {
    "محسن بوساک": "پیام بوساک",
    "سارا مسگرقمی": "سارا مسگرچیان",
}


class RepMatcher:
    """Loads the roster once; `match(name)` per row."""

    def __init__(self, employees=None):
        rows = DimEmployee.objects.all() if employees is None else employees
        self.employees = {
            name_key(e if isinstance(e, str) else e.full_name_fa): e for e in rows
        }
        self.unknown: Counter = Counter()

    def match(self, name):
        if not fold(name) or fold(name) == NO_REP:
            return None
        clean = name_key(REP_ALIASES.get(fold(name), name))
        if clean in self.employees:
            return self.employees[clean]
        words = set(clean.split())
        for other, employee in self.employees.items():
            theirs = set(other.split())
            if theirs and (theirs <= words or words <= theirs):
                return employee
        self.unknown[fold(name)] += 1
        return None
