"""
اتوماسیون اداری — مکاتبات داخلی.

The company runs its correspondence in Mizito today, and this replaces that
half of it. The shape follows what the team already uses: a letter has a
subject, a body, recipients, attachments and tags — not an indicator number,
an incoming/outgoing register and an external counterparty. Formal دبیرخانه
semantics were deliberately left out; they can be added beside these models
if the company ever registers correspondence with banks and customs here.

Three ideas shape it:

* **A letter is immutable once sent.** Everything that happens afterwards is
  an *action* recorded against it — پاراف, ارجاع, پاسخ. Editing a sent letter
  would make the copy in someone's inbox disagree with the copy in the
  sender's outbox, and the whole point of correspondence over chat is that
  what was sent is what was received.
* **The inbox is a view, not a table.** «صندوق ورودی», «صندوق خروجی»,
  «پاراف‌های من» and «آرشیو» are four questions asked of the same two tables.
  Four tables would need a letter to be copied between them to move, which is
  how the workbook this platform replaced ended up disagreeing with itself.
* **Read state belongs to the recipient, not the letter.** Ten people get one
  letter; nine of them have not opened it. A single `is_read` on the letter
  would answer «has anyone read this», which is not a question anybody asks.
"""
from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import models, transaction

from apps.core.models import TimeStampedModel


class LetterTag(TimeStampedModel):
    """
    A label the department applies to its own correspondence — «مرخصی»,
    «فاکتور», «گمرک». Data rather than choices: every company's filing
    vocabulary is its own, and it changes without a deploy.
    """

    name_fa = models.CharField(max_length=60, unique=True)
    #: Hex, drawn as the chip's background. Blank means the default grey.
    color = models.CharField(max_length=7, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "letter tag (برچسب نامه)"

    def __str__(self) -> str:
        return self.name_fa


class Letter(TimeStampedModel):
    """
    One piece of internal correspondence.

    `number` is handed out at send time, not at creation: a draft that is
    abandoned must not burn a number, or the sequence develops holes that look
    like deleted correspondence.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        SENT = "sent", "ارسال شده"

    number = models.CharField(max_length=24, unique=True, blank=True)
    subject = models.CharField("موضوع", max_length=250)
    body = models.TextField("متن", blank=True)

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="letters_sent"
    )
    status = models.CharField(
        max_length=6, choices=Status.choices, default=Status.DRAFT
    )
    sent_at = models.DateTimeField(null=True, blank=True)

    #: Set when this letter answers another. The thread is walked through this
    #: rather than stored as a thread id, so a reply to a reply keeps its own
    #: parent and «در پاسخ به» always names the right letter.
    in_reply_to = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="replies",
    )
    tags = models.ManyToManyField(LetterTag, blank=True, related_name="letters")

    class Meta:
        ordering = ("-sent_at", "-id")
        verbose_name = "letter (نامه)"
        indexes = [
            models.Index(fields=["status", "-sent_at"]),
            models.Index(fields=["sender", "status"]),
        ]

    # -- derived ---------------------------------------------------------
    @property
    def is_sent(self) -> bool:
        return self.status == self.Status.SENT

    @property
    def recipient_count(self) -> int:
        return self.recipients.count()

    @property
    def read_count(self) -> int:
        return self.recipients.filter(read_at__isnull=False).count()

    def send(self, at=None) -> "Letter":
        """
        Post the letter: give it its number and stop it being editable.

        Idempotent — sending twice must not renumber it, because the number is
        what people quote at each other in follow-ups.
        """
        from django.utils import timezone

        if self.is_sent:
            return self
        self.status = self.Status.SENT
        self.sent_at = at or timezone.now()
        if not self.number:
            self.number = next_letter_number(self.sent_at.date())
        self.save(update_fields=["status", "sent_at", "number", "updated_at"])
        return self

    def __str__(self) -> str:
        return f"{self.number or 'پیش‌نویس'} · {self.subject}"


class LetterRecipient(TimeStampedModel):
    """
    One person's copy of a letter, and the state that belongs to them alone:
    whether they have read it, and whether they have filed it away.
    """

    class Kind(models.TextChoices):
        TO = "to", "گیرنده"
        CC = "cc", "رونوشت"

    letter = models.ForeignKey(
        Letter, on_delete=models.CASCADE, related_name="recipients"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="letters_received"
    )
    kind = models.CharField(max_length=2, choices=Kind.choices, default=Kind.TO)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # One copy per person. Adding someone twice — as recipient and on cc —
        # would show the letter twice in their inbox and count them twice in
        # «چند نفر خوانده‌اند».
        unique_together = ("letter", "user")
        ordering = ("kind", "id")
        verbose_name = "letter recipient (گیرنده نامه)"
        indexes = [
            models.Index(fields=["user", "archived_at"]),
            models.Index(fields=["user", "read_at"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __str__(self) -> str:
        return f"{self.letter_id} → {self.user}"


class LetterAction(TimeStampedModel):
    """
    Something someone did to a letter after it was sent — the گردش کار.

    This is the table that makes correspondence auditable rather than merely
    delivered. «چه کسی این را به چه کسی ارجاع داد و چه نوشت» is the question a
    letter system exists to answer, and it cannot be reconstructed from the
    recipient list.
    """

    class Kind(models.TextChoices):
        PARAPH = "paraph", "پاراف"
        REFER = "refer", "ارجاع"
        NOTE = "note", "یادداشت"
        ARCHIVE = "archive", "بایگانی"

    letter = models.ForeignKey(
        Letter, on_delete=models.CASCADE, related_name="actions"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="letter_actions"
    )
    #: Who it was referred to. Null for a paraph or a note, which are about
    #: the letter rather than about passing it on.
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="letter_referrals",
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at", "id")
        verbose_name = "letter action (اقدام نامه)"
        indexes = [
            models.Index(fields=["letter", "created_at"]),
            models.Index(fields=["actor", "kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.actor}"


class LetterAttachment(TimeStampedModel):
    """
    A file on a letter.

    Stored as a base64 data-URL in the database, the same way
    `adminpanel.AdminFile` and `accounts.User.avatar_image` are: the platform
    deploys to cPanel/Passenger with no writable media directory, so a
    FileField would work locally and fail on the server. Size is capped in the
    serializer rather than here, where a validator could not report which file
    was too big.
    """

    letter = models.ForeignKey(
        Letter, on_delete=models.CASCADE, related_name="attachments"
    )
    name = models.CharField(max_length=200)
    content = models.TextField(blank=True)  # data:<mime>;base64,…
    mime = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("id",)
        verbose_name = "letter attachment (پیوست نامه)"

    def __str__(self) -> str:
        return self.name


class LetterCounter(models.Model):
    """
    The last letter number handed out in a Jalali year.

    A stored counter rather than «highest existing number + 1», for the reason
    `commercial.DocumentCounter` spells out: the shortcut reuses a number as
    soon as the newest letter is deleted, and two different letters end up
    sharing a number in whatever email quoted it. Kept local to this app
    rather than shared, so اتوماسیون اداری does not import from بازرگانی.
    """

    jalali_year = models.PositiveSmallIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "letter counter (شمارنده نامه)"

    def __str__(self) -> str:
        return f"{self.jalali_year}: {self.last_value}"


def next_letter_number(on: date | None = None) -> str:
    """«ن-۱۴۰۵-۰۰۴۲» — readable, and unique within its year."""
    from apps.core import jalali

    year = jalali.from_gregorian(on or date.today())[0]
    with transaction.atomic():
        counter, _ = LetterCounter.objects.select_for_update().get_or_create(
            jalali_year=year
        )
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
    return f"ن-{year}-{counter.last_value:04d}"
