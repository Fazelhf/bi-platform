"""
Which department — فروش همکار, بانکی, B2B, PSP — a customer or invoice belongs to.

Every one of the 3,760 imported customers carried the model default, «همکار»,
so the department books the CRM is built around were fiction for real data:
«نمابر مهر بانکها» alone billed 478bn Rial in 1404–1405 and all of it showed
under فروش همکار, while the bank department's manager saw nothing.

The evidence, strongest first:

1. **«مسوول فروش» on the invoice.** آرپا's own label, though filled on only
   one invoice in seven. Its «سازمانی» is this app's `b2b`, not
   `organizational`: the one rep آرپا tags «سازمانی», سارا مسگرچیان, sits on
   the B2B roster. (The invoice import used to map it to `organizational`.)
2. **The salesperson's roster** (`EmployeeChannel`), where it names exactly
   one active channel. It agrees with (1) wherever both exist — the «بانکی»
   reps are on the bank roster, the «همکار» reps on the team one. A rep
   active in two channels (هانیه منزه: بانکی and PSP) decides nothing.
3. **The آرپا group**, for everything else — including حامد بهشتی's 123
   invoices, since he is on no roster at all.
4. Otherwise «همکار», which is what the business calls everyone not
   specifically assigned.
"""
from __future__ import annotations

from collections import defaultdict

from apps.crm.matching import fold
from apps.sales.models import EmployeeChannel, SalesChannel

RESPONSIBLE = {
    "گروه فروش همکار": SalesChannel.TEAM,
    "گروه فروش بانکی": SalesChannel.ORGANIZATIONAL,
    "گروه فروش سازمانی": SalesChannel.B2B,
}

GROUP = {
    "نمابر مهر بانکها": SalesChannel.ORGANIZATIONAL,
    "نمابر مهر سازمانها": SalesChannel.B2B,
    "سامان رول سازمانها": SalesChannel.B2B,
    "نمابر مهر همکار": SalesChannel.TEAM,
}

DEFAULT = SalesChannel.TEAM


class ChannelResolver:
    """Loads the roster once; answers per customer or invoice."""

    def __init__(self):
        active: dict[int, set[str]] = defaultdict(set)
        for employee_id, channel in EmployeeChannel.objects.filter(
            is_active=True
        ).values_list("employee_id", "channel"):
            active[employee_id].add(channel)
        self.single = {e: next(iter(c)) for e, c in active.items() if len(c) == 1}

    def for_employee(self, employee_id):
        return self.single.get(employee_id) if employee_id else None

    @staticmethod
    def for_group(name):
        return GROUP.get(fold(name)) if name else None

    def invoice(self, responsible, rep_id, group_name) -> str:
        return (
            RESPONSIBLE.get(fold(responsible))
            or self.for_employee(rep_id)
            or self.for_group(group_name)
            or DEFAULT
        )

    def customer(self, owner_id, group_name) -> str:
        return (
            self.for_employee(owner_id)
            or self.for_group(group_name)
            or DEFAULT
        )


def rederive_customer_channels(dataset: str = "real") -> dict[str, int]:
    """
    Set the department of every customer that came from دیدار or آرپا, and
    move their deals with them.

    Only imported customers: one a department created in the app was filed
    into that department on purpose, and there is no evidence here strong
    enough to overrule a person. Deals follow their customer because that is
    the rule when a deal is created (`DealViewSet`), and a deal left in the
    old book would appear in one department's pipeline and the other's
    customer list.
    """
    from apps.crm.models import Customer, Deal

    resolver = ChannelResolver()
    moved: dict[str, int] = defaultdict(int)
    for pk, owner_id, group_name, current in Customer.objects.filter(
        dataset=dataset, external_refs__isnull=False,
    ).distinct().values_list("pk", "owner_id", "group__name_fa", "channel"):
        channel = resolver.customer(owner_id, group_name)
        if channel != current:
            Customer.objects.filter(pk=pk).update(channel=channel)
            moved[channel] += 1
        Deal.objects.filter(customer_id=pk).exclude(channel=channel).update(
            channel=channel
        )
    return dict(moved)
