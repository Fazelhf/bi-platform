"""
Acting on a reviewer's decision about a suspected duplicate.

The matcher deliberately refuses to merge anything it is not certain of, which
leaves a queue: 160 pairs a person has to rule on. This is what happens when
they do.

Both answers end the same way — the party ends up with an external ref — and
that is the point. An unresolved party is invisible to the invoice import, so
its invoices are skipped; 260 invoices worth 543bn Rial are waiting on this
queue. «Reject» is not «discard»: it means *this is a different customer*, and
a different customer still needs an account.

Nothing here deletes. Accepting writes accounting's fields onto the customer
the reviewer chose; rejecting creates a new customer. If a decision turns out
to be wrong, the ref moves — no history has been destroyed in the meantime.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.crm.models import (
    Customer, CustomerExternalRef, CustomerMatchCandidate, ExternalSource,
)
from apps.crm.party_sync import PartyWriter


class MergeError(Exception):
    """A decision that cannot be carried out as asked."""


def _settle(candidate, state, user, customer):
    candidate.state = state
    candidate.customer = customer
    candidate.decided_at = timezone.now()
    candidate.decided_by = user if user and user.is_authenticated else None
    candidate.save(update_fields=[
        "state", "customer", "decided_at", "decided_by", "updated_at",
    ])
    # The same party may have been suggested against several customers — an
    # «ambig» name matches every customer carrying it. One decision settles
    # the party, so the rival suggestions are not left for someone to rule on
    # a second time and contradict the first.
    CustomerMatchCandidate.objects.filter(
        source=candidate.source, external_id=candidate.external_id,
        state=CustomerMatchCandidate.State.PENDING,
    ).exclude(pk=candidate.pk).update(
        state=CustomerMatchCandidate.State.REJECTED,
        decided_at=candidate.decided_at,
        decided_by=candidate.decided_by,
    )


#: Everything that hangs off a customer and has to travel when two are fused.
#: Missing one would leave records pointing at a row nobody can see any more —
#: invisible, but still counted by any report that joins from the other end.
OWNED = (
    ("deals", "customer"),
    ("activities", "customer"),
    ("tasks", "customer"),
    ("feedback", "customer"),
    ("invoices", "customer"),
    ("external_refs", "customer"),
)

#: Filled on the survivor from the absorbed row when the survivor has nothing.
#: A merge that keeps only one side's phone number loses the other, and the
#: whole reason two rows existed is usually that each knew something.
CARRIED = (
    "phone", "mobile", "email", "address", "city", "national_id",
    "economic_code", "registration_no", "postal_code", "payment_terms",
    "contact_name",
)


@transaction.atomic
def absorb(primary: Customer, duplicate: Customer, user=None) -> Customer:
    """
    Fold one customer into another.

    The duplicate is kept, not deleted. Its deals and invoices move to the
    survivor, so nothing is orphaned, and the row itself stays behind carrying
    `merged_into` — which is what makes the decision reversible. Deleting it
    would take its `Deal` rows with it by cascade, and a merge that destroys
    history to tidy a list is a worse outcome than the duplicate was.
    """
    if primary.pk == duplicate.pk:
        raise MergeError("یک مشتری را نمی‌شود در خودش ادغام کرد.")
    if duplicate.merged_into_id:
        raise MergeError(f"«{duplicate.name_fa}» قبلاً ادغام شده است.")
    if primary.merged_into_id:
        raise MergeError(
            f"«{primary.name_fa}» خودش در مشتری دیگری ادغام شده است."
        )

    moved = {}
    for accessor, field in OWNED:
        n = getattr(duplicate, accessor).update(**{field: primary})
        if n:
            moved[accessor] = n

    for field in CARRIED:
        if not getattr(primary, field) and getattr(duplicate, field):
            setattr(primary, field, getattr(duplicate, field))
    for field in ("group_id", "province_id", "owner_id", "lead_source_id"):
        if not getattr(primary, field) and getattr(duplicate, field):
            setattr(primary, field, getattr(duplicate, field))
    # The relationship started whenever the earlier of the two started.
    if duplicate.first_contact_at and (
        not primary.first_contact_at
        or duplicate.first_contact_at < primary.first_contact_at
    ):
        primary.first_contact_at = duplicate.first_contact_at
    primary.save()

    duplicate.merged_into = primary
    duplicate.is_active = False
    duplicate.save(update_fields=["merged_into", "is_active", "updated_at"])
    return primary


@transaction.atomic
def accept(candidate: CustomerMatchCandidate, user=None, customer=None) -> Customer:
    """
    «They are the same customer.»

    `customer` overrides the suggestion. The screen offers it for the
    «ambig» tier, where the party's name matches several CRM rows and the
    matcher has no basis to prefer one — that choice is the reviewer's whole
    contribution and refusing it would send them to the admin to do it by hand.
    """
    if candidate.state != CustomerMatchCandidate.State.PENDING:
        raise MergeError("این مورد قبلاً تعیین تکلیف شده است.")

    # A pair raised from the customer list has no external party to file —
    # both sides are CRM rows, so «same customer» means fusing them.
    if candidate.source == ExternalSource.CRM:
        if not candidate.duplicate_id:
            raise MergeError("این مورد طرف دومی ندارد.")
        primary = customer or candidate.customer
        other = (
            candidate.duplicate
            if primary.pk != candidate.duplicate_id
            else candidate.customer
        )
        survivor = absorb(primary, other, user)
        _settle(candidate, CustomerMatchCandidate.State.ACCEPTED, user, survivor)
        return survivor

    target = customer or candidate.customer
    if target.merged_into_id:
        raise MergeError(
            f"«{target.name_fa}» خودش در مشتری دیگری ادغام شده است."
        )

    taken = CustomerExternalRef.objects.filter(
        source=candidate.source, external_id=candidate.external_id,
    ).exclude(customer=target).first()
    if taken:
        raise MergeError(
            f"این کد از قبل به «{taken.customer.name_fa}» وصل است."
        )

    writer = PartyWriter()
    writer.apply(target, candidate.payload)
    writer.link(target, candidate.payload)
    _settle(candidate, CustomerMatchCandidate.State.ACCEPTED, user, target)
    return target


@transaction.atomic
def reject(candidate: CustomerMatchCandidate, user=None) -> Customer:
    """
    «They are different customers.»

    Which makes the party a customer in its own right, so it is created here
    rather than dropped. Skipping that would leave its invoices unimportable
    for good, and the reviewer would have said «not a duplicate» and watched
    the account disappear.

    The new account arrives open. Whether it has ever traded is not knowable
    from this screen — the invoice files are not loaded here — and the next
    `import_arpa_parties` run re-derives `is_active` for every linked party,
    so an account that never buys is closed then.
    """
    if candidate.state != CustomerMatchCandidate.State.PENDING:
        raise MergeError("این مورد قبلاً تعیین تکلیف شده است.")

    # Both sides already exist as accounts, so «different customers» is simply
    # the answer — there is nothing to create and nothing to undo.
    if candidate.source == ExternalSource.CRM:
        _settle(candidate, CustomerMatchCandidate.State.REJECTED, user,
                candidate.customer)
        return candidate.customer

    existing = CustomerExternalRef.objects.filter(
        source=candidate.source, external_id=candidate.external_id,
    ).first()
    if existing:
        customer = existing.customer
    else:
        writer = PartyWriter()
        customer = writer.create(candidate.payload)
        writer.link(customer, candidate.payload)

    _settle(candidate, CustomerMatchCandidate.State.REJECTED, user, candidate.customer)
    return customer


def queue_pair(primary: Customer, duplicate: Customer, method="manual"):
    """
    File two CRM rows as a suspected duplicate.

    Returns None when the pair is already known — in the queue, or already
    ruled on. Re-queueing a rejected pair would let a list of «these two look
    alike» quietly reopen a decision someone already made.
    """
    if primary.pk == duplicate.pk:
        return None
    # Order the pair so «A then B» and «B then A» are one row rather than two
    # questions about the same thing. The survivor is chosen at accept time,
    # so which side is stored first carries no meaning and must not.
    if primary.pk > duplicate.pk:
        primary, duplicate = duplicate, primary
    external_id = f"cust-{duplicate.pk}"
    if CustomerMatchCandidate.objects.filter(
        source=ExternalSource.CRM, external_id=external_id, customer=primary,
    ).exists():
        return None
    return CustomerMatchCandidate.objects.create(
        source=ExternalSource.CRM,
        external_id=external_id,
        external_name=duplicate.name_fa[:200],
        external_phone=(duplicate.phone or duplicate.mobile)[:40],
        external_city=duplicate.city[:100],
        customer=primary,
        duplicate=duplicate,
        method=method,
        score=1 if method == "manual" else 0,
    )


def queue_scan(customers, dataset: str):
    """
    Hunt for each customer's twin and queue whatever turns up.

    For when someone suspects a row is a duplicate without knowing of what.
    The same ladder the importer uses is run against the rest of the file, and
    the same rule applies: nothing here merges. Even an exact-name hit — which
    the importer would write unattended — is only queued, because the importer
    is matching *across* systems where a repeated name means one company,
    while inside one file it more often means someone typed it twice, and the
    person who pressed the button is right there to say which.
    """
    from apps.crm.matching import CustomerIndex

    index = CustomerIndex()
    picked = {c.pk for c in customers}
    for pk, name, nid, eco, phone, mobile in Customer.objects.filter(
        dataset=dataset, merged_into__isnull=True,
    ).values_list(
        "pk", "name_fa", "national_id", "economic_code", "phone", "mobile"
    ):
        if pk in picked:
            continue
        index.add(pk, name=name, nids=(nid, eco), phones=(phone, mobile))

    queued, skipped = [], []
    for customer in customers:
        match = index.find(
            source=ExternalSource.CRM,
            external_id=f"cust-{customer.pk}",
            name=customer.name_fa,
            nids=(customer.national_id, customer.economic_code),
            phones=(customer.phone, customer.mobile),
        )
        if not match.found:
            skipped.append({
                "name_fa": customer.name_fa,
                "reason": "مشابهی پیدا نشد.",
            })
            continue
        twin = Customer.objects.filter(pk=match.customer_id).first()
        row = queue_pair(customer, twin, match.method) if twin else None
        if row:
            queued.append(row)
        else:
            skipped.append({
                "name_fa": customer.name_fa,
                "reason": "این جفت از قبل در صف است یا تعیین تکلیف شده.",
            })
    return queued, skipped


def alternatives(candidate: CustomerMatchCandidate, limit: int = 6):
    """
    Other customers the party might be, for the «ambig» tier.

    That tier means the name matched more than one CRM row — a duplicate the
    دیدار import left behind. The reviewer's job there is to pick which half
    is real, so the halves have to be on screen.
    """
    from apps.crm.matching import name_key

    key = name_key(candidate.external_name)
    if not key:
        return Customer.objects.none()
    ids = [
        c.pk for c in Customer.objects.filter(
            dataset=candidate.customer.dataset, merged_into__isnull=True,
        ).exclude(pk=candidate.customer_id).only("pk", "name_fa")
        if name_key(c.name_fa) == key
    ][:limit]
    return Customer.objects.filter(pk__in=ids)
