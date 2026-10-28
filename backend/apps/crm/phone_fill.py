"""
Phone numbers from آرپا's party list (لیست طرف حساب) onto CRM customers.

The invoice export carries a «تلفن» column, but آرپا leaves it empty on most
invoices; the numbers live in the party list. Re-running the whole party
import to get them would also re-file groups, provinces and new parties. This
does one thing only: for a party already linked to a customer by its آرپا
code, fill that customer's phone and mobile **where they are blank**. Nobody
is created, merged or renamed, and a number a rep typed is never replaced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db import transaction

from apps.crm.arpa_file import read_sheet
from apps.crm.matching import fold
from apps.crm.models import Customer, CustomerExternalRef

CODE_HEADERS = ("کد طرف حساب", "کد")


@dataclass
class PhoneReport:
    dry_run: bool = False
    rows: int = 0
    linked: int = 0
    phones: int = 0
    mobiles: int = 0
    had_already: int = 0
    no_number: int = 0
    unknown_codes: list = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            "آزمایشی — چیزی ذخیره نشد" if self.dry_run else "ذخیره شد",
            f"ردیف طرف حساب: {self.rows} — وصل به مشتری CRM: {self.linked}",
            f"تلفن پر شد: {self.phones} — موبایل پر شد: {self.mobiles}",
            f"مشتری که شماره داشت (دست نخورد): {self.had_already} — طرف حساب بدون شماره در آرپا: {self.no_number}",
            f"کد آرپا که در CRM مشتری ندارد: {len(self.unknown_codes)}",
        ]


def _is_mobile(number: str) -> bool:
    digits = re.sub(r"\D", "", fold(number))
    return digits.startswith(("09", "989")) or (len(digits) == 10 and digits.startswith("9"))


def _numbers(row: dict) -> list[str]:
    out = []
    for head, value in row.items():
        if any(w in head for w in ("تلفن", "موبایل", "همراه")) and fold(value):
            out.append(fold(value))
    return out


def parse(data: bytes, filename: str) -> list[dict]:
    rows = read_sheet(data, filename)
    for h, row in enumerate(rows[:20]):
        names = [fold(v) for v in row]
        code = next((c for c in CODE_HEADERS if c in names), None)
        if code and any(any(w in n for w in ("تلفن", "موبایل", "همراه")) for n in names):
            out = []
            for r in rows[h + 1:]:
                d = {names[i]: v for i, v in enumerate(r) if i < len(names) and names[i]}
                d["__code"] = fold(d.get(code))
                if d["__code"]:
                    out.append(d)
            return out
    raise ValueError("ستون «کد» و ستون تلفن/موبایل در فایل پیدا نشد؛ خروجی «لیست طرف حساب» آرپا را بدهید.")


def _survivor(customer: Customer) -> Customer:
    seen = set()
    while customer.merged_into_id and customer.pk not in seen:
        seen.add(customer.pk)
        customer = customer.merged_into
    return customer


def fill(rows: list[dict], *, dry_run: bool = False) -> PhoneReport:
    report = PhoneReport(dry_run=dry_run, rows=len(rows))
    refs = {
        r.external_id: r.customer
        for r in CustomerExternalRef.objects.filter(source="arpa").select_related("customer")
    }
    with transaction.atomic():
        for row in rows:
            customer = refs.get(row["__code"])
            if customer is None:
                report.unknown_codes.append(row["__code"])
                continue
            report.linked += 1
            numbers = _numbers(row)
            if not numbers:
                report.no_number += 1
                continue
            customer = _survivor(customer)
            changed = []
            mobile = next((n for n in numbers if _is_mobile(n)), "")
            phone = next((n for n in numbers if not _is_mobile(n)), "")
            if mobile and not customer.mobile:
                customer.mobile = mobile[: Customer._meta.get_field("mobile").max_length]
                changed.append("mobile")
                report.mobiles += 1
            if phone and not customer.phone:
                customer.phone = phone[: Customer._meta.get_field("phone").max_length]
                changed.append("phone")
                report.phones += 1
            if changed:
                customer.save()  # `save` refreshes the match keys too.
            else:
                report.had_already += 1
        if dry_run:
            transaction.set_rollback(True)
    return report
