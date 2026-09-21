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

#: Of the above, the ones a person can also edit on the CRM screen
#: (`CustomerWriteSerializer`). On an existing account these are filled only
#: when blank — see `PartyWriter.apply`.
CRM_EDITABLE = frozenset({"national_id"})

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

    def __init__(self, with_sales=None):
        # None means «not known» — the review screen creates accounts without
        # the invoice workbooks at hand — and is not the same as «no sales».
        # Reading it as the empty set closed every account a reviewer created.
        self.with_sales = with_sales
        self.provinces = {
            _province_key(p.name_fa): p for p in DimProvince.objects.all()
        }
        self.groups: dict[str, CustomerGroup] = {}

    # -- fields ----------------------------------------------------------
    def apply(self, customer: Customer, row: dict, save: bool = True) -> Customer:
        """
        Write one آرپا row onto a customer.

        Two policies, split by who else can change the field:

        * **Fields the CRM screen edits** — phone, address, national id,
          province, group — are only *filled*, never overwritten, on an
          account that already exists. This used to overwrite, and because
          every deploy re-ran the import, a rep who corrected a phone number
          watched it revert on the next release.
        * **Fields only accounting holds** — economic code, payment terms,
          credit standing — stay in sync, since nobody in the CRM can be
          contradicted by them.

        An existing account is never *closed* by an import. Closing is a
        judgement the team makes; the import may only open an account that
        has started buying.
        """
        fresh = customer._state.adding

        for field, *columns in TEXT_FIELDS:
            value = next(
                (fold(row.get(c)) for c in columns if fold(row.get(c))), ""
            )
            if field in {"national_id", "economic_code"}:
                value = id_key(value)
            if not value:
                continue
            if field in CRM_EDITABLE and not fresh and getattr(customer, field):
                continue
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
        # Only ever raised. A name that says «فی ما بین» makes the account
        # intercompany; a name that stops saying it is not evidence enough to
        # put a sister company's billing back into the sales team's figures.
        if any(m in fold(row.get("نام")) for m in INTERCOMPANY_MARKERS):
            customer.is_intercompany = True

        has_sales = (
            None if self.with_sales is None
            else fold(row.get("کد")) in self.with_sales
        )
        if fresh:
            # The party list is a whole group's ledger and most of it has
            # never traded here, so a new account arrives closed unless it has
            # invoices — keeping a rep's working list to customers who buy.
            customer.is_active = (
                not truthy(row.get("غیر فعال")) and has_sales is not False
            )
        elif (
            not customer.is_active and has_sales is True
            and customer.code.startswith("arpa-")
        ):
            # The one change an import may make to an existing account's
            # state: one that was closed for never having traded has now
            # traded.
            customer.is_active = True

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

        It also hands the customer every invoice that was waiting for it.
        Invoices are imported whether or not their party is matched yet, so
        that no total depends on the review queue; this is the moment they
        get a customer. Every resolution path — the bulk import, «same
        customer» and «different customer» on the review screen — ends here,
        which is why it is done here and nowhere else.
        """
        from apps.crm.models import SalesInvoice

        code = fold(row.get("کد"))[:64]
        ref = CustomerExternalRef.objects.update_or_create(
            source=ExternalSource.ARPA,
            external_id=code,
            defaults={
                "customer": customer,
                "external_name": fold(row.get("نام"))[:200],
            },
        )[0]
        if code:
            waiting = SalesInvoice.objects.filter(
                party_code=code, customer__isnull=True
            )
            waiting.update(customer=customer)
            if customer.is_intercompany:
                SalesInvoice.objects.filter(party_code=code).update(
                    is_intercompany=True
                )
        return ref
