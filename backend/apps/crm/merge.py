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

Decisions never delete. Accepting writes accounting's fields onto the customer
the reviewer chose; rejecting creates a new customer. The one delete path,
`delete_customers`, lives here too so it can leave a tombstone behind. If a decision turns out
to be wrong, the ref moves — no history has been destroyed in the meantime.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q
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
    # A CRM pair's `external_id` names only the second row, so «rivals» under
    # it are other pairs about that row — in a group of three, B–C is a rival
    # of A–C. Rejecting them would record «B and C are different customers»
    # the moment someone said A and C are one, which is the opposite of what
    # follows. Those pairs are closed by `_close_fused` instead.
    if candidate.source == ExternalSource.CRM:
        return
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
    # The activities moved, but `last_activity_at` is a cache written when an
    # activity is logged — the survivor's still said «258 days ago» while its
    # timeline, now holding the duplicate's calls, showed one last week.
    primary.refresh_last_activity()

    duplicate.merged_into = primary
    duplicate.is_active = False
    duplicate.save(update_fields=["merged_into", "is_active", "updated_at"])
    return primary


def live(customer: Customer) -> Customer:
    """Follow `merged_into` to the row that absorbed this one, if any."""
    seen = set()
    while customer.merged_into_id and customer.pk not in seen:
        seen.add(customer.pk)
        customer = customer.merged_into
    return customer


def survivor_of(a: Customer, b: Customer) -> tuple[Customer, Customer]:
    """
    Which of two rows to keep when nobody picked: (keep, absorb).

    The row with the trading history first — invoices, then deals — because
    that is the one reports and the invoice import already point at. Then the
    accounting row, whose code the next آرپا import will look for. Then the
    older row.
    """
    def rank(c):
        return (
            -c.invoices.count(), -c.deals.count(),
            0 if c.code.startswith("arpa-") else 1, c.pk,
        )
    keep, other = sorted((a, b), key=rank)
    return keep, other


def _close_fused(user):
    """
    Settle open CRM pairs whose two sides are now one customer.

    A group of three is three pairs; approving two of them fuses all three
    rows, and the third pair is then a question that has already been answered.
    """
    for c in CustomerMatchCandidate.objects.filter(
        source=ExternalSource.CRM, state=CustomerMatchCandidate.State.PENDING,
    ).filter(
        Q(customer__merged_into__isnull=False)
        | Q(duplicate__merged_into__isnull=False)
    ).select_related("customer", "duplicate"):
        if c.duplicate_id and live(c.customer).pk == live(c.duplicate).pk:
            # `customer` is left as it was: rewriting it to the survivor can
            # collide with the pair that did the fusing, which already holds
            # (source, external_id, survivor). The survivor is `live()` of it.
            _settle(c, CustomerMatchCandidate.State.ACCEPTED, user, c.customer)


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
        # Inside a group, an earlier approval may already have folded one
        # side away. The pair still means «same customer», so it is applied
        # to whatever each side became rather than refused.
        sides = [live(candidate.customer), live(candidate.duplicate)]
        primary = live(customer) if customer else sides[0]
        # A reviewer may also pick a third row of the same name (the «ambig»
        # alternatives); the duplicate then folds into that one, as before.
        other = sides[0] if primary.pk == sides[1].pk else sides[1]
        survivor = primary if primary.pk == other.pk else absorb(primary, other, user)
        # The pair keeps its own `customer`: inside a group the survivor may
        # be a third row already holding a pair under this external_id, and
        # (source, external_id, customer) is unique. `live()` names the survivor.
        _settle(candidate, CustomerMatchCandidate.State.ACCEPTED, user, candidate.customer)
        _close_fused(user)
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
    from this screen — the invoice files are not loaded here — and a reviewer
    who has just said «this is a customer of its own» should not find it
    hidden from the list. A later import opens accounts that start buying but
    never closes one, so closing it stays a decision for the team.
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


def queue_pair(primary: Customer, duplicate: Customer, method="manual", score=None):
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
    if score is None:
        score = 1 if method == "manual" else 0
    return CustomerMatchCandidate.objects.create(
        source=ExternalSource.CRM,
        external_id=external_id,
        external_name=duplicate.name_fa[:200],
        external_phone=(duplicate.phone or duplicate.mobile)[:40],
        external_city=duplicate.city[:100],
        customer=primary,
        duplicate=duplicate,
        method=method,
        score=score,
    )


def _evidence(customer: Customer) -> dict:
    """The fields `matching.certain_pair` weighs, read off a row."""
    return {
        "name": customer.name_fa,
        "nids": (customer.national_id, customer.economic_code),
        "phones": (customer.phone, customer.mobile),
    }


def is_certain(candidate: CustomerMatchCandidate) -> bool:
    """
    Whether a queued CRM pair clears the bar for bulk approval.

    Judged on the two rows as they are *now*, never on the score stored when
    the pair was queued: someone may have corrected a phone number in between,
    and a bulk action that trusts a stale verdict merges on evidence that no
    longer exists.
    """
    from apps.crm.matching import certain_pair

    if candidate.source != ExternalSource.CRM or not candidate.duplicate_id:
        return False
    return certain_pair(_evidence(candidate.customer), _evidence(candidate.duplicate))


def queue_scan(customers, dataset: str):
    """
    Hunt for each customer's twins and queue whatever turns up.

    For when someone suspects a row is a duplicate without knowing of what —
    or, with every customer passed, for sweeping the whole file. The rest of
    the file is indexed once and every twin of every row is queued: a name
    typed four times yields all its pairs, not just the first one found.

    Two mistakes this used to make, and why the button «did nothing»: the
    selected rows were left *out* of the index, so selecting a page of
    customers meant no two of them could ever find each other; and each row
    stopped at its first match, so groups of three or more never emptied.

    The same rule as ever applies: nothing here merges. Even a certain pair
    is only queued — scored 1 so the screen can offer to approve those in one
    go, which is a person's decision, not this function's.
    """
    from apps.crm.matching import CustomerIndex, certain_pair

    index = CustomerIndex()
    rows = {
        c.pk: c for c in Customer.objects.filter(
            dataset=dataset, merged_into__isnull=True,
        ).only(
            "pk", "name_fa", "national_id", "economic_code", "phone",
            "mobile", "city", "code",
        )
    }
    for c in rows.values():
        index.add(c.pk, name=c.name_fa, nids=(c.national_id, c.economic_code),
                  phones=(c.phone, c.mobile))

    queued, skipped = [], []
    for customer in customers:
        twins = index.twins(
            customer.pk,
            name=customer.name_fa,
            nids=(customer.national_id, customer.economic_code),
            phones=(customer.phone, customer.mobile),
        )
        if not twins:
            skipped.append({
                "name_fa": customer.name_fa,
                "reason": "مشابهی پیدا نشد.",
            })
            continue
        added = 0
        for match in twins:
            twin = rows.get(match.customer_id)
            if not twin:
                continue
            sure = certain_pair(_evidence(customer), _evidence(twin))
            # 1 is reserved for certain pairs so the counts mean something;
            # an exact name alone also scores 1.0 on the ladder.
            row = queue_pair(customer, twin, match.method,
                             score=1 if sure else min(match.score, 0.99))
            if row:
                queued.append(row)
                added += 1
        if not added:
            skipped.append({
                "name_fa": customer.name_fa,
                "reason": "این جفت از قبل در صف است یا تعیین تکلیف شده.",
            })
    return queued, skipped


def accept_certain(dataset: str, user=None, dry_run=False) -> dict:
    """
    Approve every open CRM pair that `is_certain` — the bulk half of review.

    Each pair goes through `accept`, so each one is its own transaction and
    leaves the absorbed row behind with `merged_into` set: one pair failing
    does not undo the others, and none of them is a delete. The survivor is
    chosen by `survivor_of` since no one is picking per pair.
    """
    pending = CustomerMatchCandidate.objects.filter(
        source=ExternalSource.CRM,
        state=CustomerMatchCandidate.State.PENDING,
        customer__dataset=dataset,
    ).select_related("customer", "duplicate").order_by("pk")

    sure = [c for c in pending if is_certain(c)]
    if dry_run:
        return {"certain": len(sure), "merged": 0, "failed": []}

    merged, failed = 0, []
    for c in sure:
        c.refresh_from_db()
        if c.state != CustomerMatchCandidate.State.PENDING:
            continue  # closed by an earlier approval in this same group
        keep, _ = survivor_of(live(c.customer), live(c.duplicate))
        try:
            accept(c, user, keep)
            merged += 1
        except MergeError as exc:
            failed.append({"name_fa": c.customer.name_fa, "reason": str(exc)})
    return {"certain": len(sure), "merged": merged, "failed": failed}


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


@transaction.atomic
def delete_customers(queryset, user=None) -> int:
    """
    Delete customers, leaving a tombstone for every source id they carried.

    The only sanctioned way to remove a customer. A bare `.delete()` cascades
    the external refs away, and with them the fact that the party was ever
    imported — so the next accounting load recreates it. Both the list's bulk
    action and the single-row DELETE come through here for that reason.
    """
    from apps.crm.models import DismissedParty

    ids = list(queryset.values_list("pk", flat=True))
    if not ids:
        return 0
    refs = CustomerExternalRef.objects.filter(customer_id__in=ids).values_list(
        "source", "external_id", "external_name"
    )
    DismissedParty.objects.bulk_create(
        [
            DismissedParty(
                source=source, external_id=external_id,
                external_name=name,
                dismissed_by=user if user and user.is_authenticated else None,
            )
            for source, external_id, name in refs
        ],
        ignore_conflicts=True,
    )
    return Customer.objects.filter(pk__in=ids).delete()[0]
