"""
Writing an آرپا party onto a CRM customer.

Two callers need this and they must not drift apart: the bulk importer, which
does it for two thousand parties at once, and the review screen, which does it
for one party after a person has ruled on it. When the logic lived only in the
management command, accepting a match from the UI meant re-implementing which
fields accounting owns — and the copy that fell behind would be the one users
touched.

The field policy is the substance here. آرپا is the authority on what a
company legally *is* — its ids, its address, its payment terms. دیدار is the
authority on what the relationship *is* — who owns it, where the lead came
from, what it is called on the sales team's screen. Nothing in this module
writes the second kind.
"""
from __future__ import annotations

import re

from django.utils.text import slugify

from apps.core import jalali
from apps.crm.matching import fold, id_key
from apps.crm.models import (
    Customer, CustomerExternalRef, CustomerGroup, ExternalSource,
)
from apps.sales.models import DimProvince

KIND = {"حقوقی": Customer.Kind.COMPANY, "حقیقی": Customer.Kind.PERSON}

#: Sister-company accounts. They buy from us and the invoices are real, so
#: they are kept — flagged, so no target or conversion rate counts them as the
#: sales team's work.
INTERCOMPANY_MARKERS = ("آرال", "فی ما بین", "فیمابین")

#: Columns آرپا is the authority on. Ownership, lead source, status and the
#: display name are deliberately absent.
TEXT_FIELDS = (
    ("national_id", "شناسه ملی", "کد ملی"),
    ("economic_code", "کد اقتصادی"),
    ("registration_no", "شماره ثبت"),
    ("postal_code", "کد پستی"),
    ("payment_terms", "شرایط تسویه پیش فرض"),
)

#: Fields filled only when the CRM has nothing. آرپا leaves آدرس empty on a
#: third of its parties and a phone on nearly half; a sync that blanks the
#: number a rep dialled last week is a loss, not an update.
FILL_IF_EMPTY = (
    ("phone", "شماره تلفن"), ("mobile", "موبایل"),
    ("address", "آدرس"), ("city", "شهر"),
)


def truthy(value) -> bool:
    return fold(value).lower() in {"true", "1", "بله", "دارد"}


def jdate(value):
    parts = fold(value).split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
    except ValueError:
        return None
    return jalali.to_gregorian(y, m, d) if y > 1000 else None


def _province_key(name) -> str:
    """
    Provinces matched on letters alone.

    Two of the thirty-one are spelled differently on each side —
    «چهارمحال و بختیاری» against «چهارمحال بختیاری», a space inside
    «بویر احمد» — and an exact lookup drops them silently, leaving two
    provinces with no customers at all on the geography report.
    """
    return re.sub(r"\s|و", "", fold(name))


class PartyWriter:
    """
    Applies one آرپا row to one Customer.

    `with_sales` is the set of party codes that appear on any invoice. It
    decides whether a *newly created* account arrives open or closed: the
    party list is a whole group's ledger and most of it has never traded
    here, so those accounts are kept but closed, and a rep's working list
    stays the customers who actually buy.
    """

    def __init__(self, with_sales=frozenset()):
        self.with_sales = with_sales
        self.provinces = {
            _province_key(p.name_fa): p for p in DimProvince.objects.all()
        }
        self.groups: dict[str, CustomerGroup] = {}

    # -- fields ----------------------------------------------------------
    def apply(self, customer: Customer, row: dict, save: bool = True) -> Customer:
        for field, *columns in TEXT_FIELDS:
            value = next(
                (fold(row.get(c)) for c in columns if fold(row.get(c))), ""
            )
            if field in {"national_id", "economic_code"}:
                value = id_key(value)
            if value:
                limit = customer._meta.get_field(field).max_length
                setattr(customer, field, value[:limit])

        for field, column in FILL_IF_EMPTY:
            value = fold(row.get(column))
            if value and not getattr(customer, field):
                limit = customer._meta.get_field(field).max_length
                setattr(customer, field, value[:limit])

        province = self.provinces.get(_province_key(row.get("استان")))
        if province and not customer.province_id:
            customer.province = province

        group = self.group(fold(row.get("نام گروه")))
        if group and not customer.group_id:
            customer.group = group

        customer.is_good_payer = truthy(row.get("خوش حساب"))
        customer.vat_cert_expires_at = (
            jdate(row.get("تاریخ اعتبار گواهی ارزش افزوده"))
            or customer.vat_cert_expires_at
        )
        customer.is_intercompany = any(
            m in fold(row.get("نام")) for m in INTERCOMPANY_MARKERS
        )

        # Both reasons an account is closed, re-derived on every call. Reading
        # only the آرپا column made a second import re-open all 1,597 accounts
        # the first had closed for never having traded.
        #
        # The no-trade rule applies only to accounts this sync created. A
        # دیدار customer has deals and calls behind it, and the invoice
        # exports begin at 1404 — judging it by them would close customers
        # whose last order was simply earlier.
        never_traded = (
            customer.code.startswith("arpa-")
            and fold(row.get("کد")) not in self.with_sales
        )
        customer.is_active = not (truthy(row.get("غیر فعال")) or never_traded)

        if save:
            customer.save()
        return customer

    def group(self, name: str):
        if not name:
            return None
        if name not in self.groups:
            self.groups[name] = CustomerGroup.objects.update_or_create(
                code=f"cg-{slugify(name, allow_unicode=True)[:40]}",
                defaults={"name_fa": name[:100]},
            )[0]
        return self.groups[name]

    # -- rows ------------------------------------------------------------
    def create(self, row: dict) -> Customer:
        from django.utils import timezone

        customer = Customer(
            code=f"arpa-{fold(row.get('کد'))}",
            name_fa=fold(row.get("نام"))[:200],
            kind=KIND.get(fold(row.get("نوع")), Customer.Kind.COMPANY),
            status=Customer.Status.LEAD,
            first_contact_at=timezone.now(),
        )
        self.apply(customer, row, save=False)
        customer.save()
        return customer

    @staticmethod
    def link(customer: Customer, row: dict) -> CustomerExternalRef:
        """
        File the آرپا code against this customer.

        دیدار's name for the account is left alone — the sales team knows
        accounts by what is on their own screen, and a silent rename
        mid-quarter is its own kind of loss. آرپا's legal name is kept here
        instead, where the review screen can show both.
        """
        return CustomerExternalRef.objects.update_or_create(
            source=ExternalSource.ARPA,
            external_id=fold(row.get("کد"))[:64],
            defaults={
                "customer": customer,
                "external_name": fold(row.get("نام"))[:200],
            },
        )[0]
