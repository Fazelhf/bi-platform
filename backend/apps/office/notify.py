"""
اعلان‌های اتوماسیون اداری.

Until these existed, a letter arrived, a task was handed over or a referral
was made and nothing told anyone: the only sign was a number beside the menu,
which is visible only to someone already looking at the workspace. Each event
below now puts one row in the bell, and the row opens the letter or the task
itself (apps.core.notification_links).

Never the actor themselves, never twice to the same person for one event.
"""
from __future__ import annotations

from typing import Iterable

from apps.core.models import Notification

#: Kept short: the bell shows the message, and `verb` is a 20-char column.
LETTER = "letter"
REFER = "refer"
PARAPH = "paraph"
NOTE = "letter_note"
TASK = "task"
TASK_DONE = "task_done"
TASK_COMMENT = "task_comment"


def _name(user) -> str:
    return (getattr(user, "display_name_fa", "") or user.get_full_name() or user.username)


def _clip(text: str, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _send(user_ids: Iterable[int | None], actor, verb: str, message: str, instance) -> int:
    ids = {uid for uid in user_ids if uid and uid != getattr(actor, "pk", None)}
    if not ids:
        return 0
    label = f"{instance._meta.app_label}.{instance._meta.object_name}"
    Notification.objects.bulk_create([
        Notification(
            recipient_id=uid, actor=actor, verb=verb, message=message[:300],
            target_label=label, target_id=str(instance.pk),
        )
        for uid in ids
    ])
    return len(ids)


# -- letters ----------------------------------------------------------------
def letter_sent(letter) -> int:
    """Every recipient — گیرنده and رونوشت alike — of a letter just sent."""
    kind = "پاسخ" if letter.in_reply_to_id else "نامه‌ی جدید"
    return _send(
        letter.recipients.values_list("user_id", flat=True),
        letter.sender, LETTER,
        f"{kind} از {_name(letter.sender)}: «{_clip(letter.subject)}» ({letter.number})",
        letter,
    )


def letter_referred(letter, actor, to_user_id, note: str = "") -> int:
    tail = f" — {_clip(note, 80)}" if note else ""
    return _send(
        [to_user_id], actor, REFER,
        f"{_name(actor)} نامه‌ی «{_clip(letter.subject)}» را به شما ارجاع داد{tail}",
        letter,
    )


def letter_paraphed(letter, actor, private_to=None, note: str = "") -> int:
    """
    A public پاراف tells the sender their letter was signed off. A private
    one tells only the person it is addressed to — exactly who can read it.
    """
    tail = f" — {_clip(note, 80)}" if note else ""
    who = [private_to] if private_to else [letter.sender_id]
    extra = " (خصوصی)" if private_to else ""
    return _send(
        who, actor, PARAPH,
        f"{_name(actor)} نامه‌ی «{_clip(letter.subject)}» را پاراف کرد{extra}{tail}",
        letter,
    )


def letter_private_note(letter, actor, to_user_id, note: str) -> int:
    """A public note is part of the گردش for everyone to read; a private one is addressed."""
    return _send(
        [to_user_id], actor, NOTE,
        f"یادداشت خصوصی {_name(actor)} روی «{_clip(letter.subject)}»: {_clip(note, 80)}",
        letter,
    )


# -- tasks --------------------------------------------------------------------
def task_assigned(task, actor) -> int:
    due = ""
    if task.due_on:
        from apps.core import jalali

        jy, jm, jd = jalali.from_gregorian(task.due_on)
        due = f" — مهلت {jy}/{jm:02d}/{jd:02d}"
    return _send(
        [task.assignee_id], actor, TASK,
        f"{_name(actor)} کار «{_clip(task.title)}» را به شما سپرد{due}",
        task,
    )


def task_done(task, actor) -> int:
    """The person who handed it over hears it is finished."""
    return _send(
        [task.creator_id], actor, TASK_DONE,
        f"{_name(actor)} کار «{_clip(task.title)}» را انجام داد",
        task,
    )


def task_commented(task, actor, body: str) -> int:
    """Both ends of a handed-over task — whoever of them did not write it."""
    return _send(
        [task.assignee_id, task.creator_id], actor, TASK_COMMENT,
        f"{_name(actor)} روی «{_clip(task.title)}» نوشت: {_clip(body, 80)}",
        task,
    )
