"""
تقویم — the meeting workflow, the way an organisation's calendar runs it.

`MeetingViewSet` is the event endpoint (`views_calendar.EventViewSet`) plus
what happens to a meeting after it is sent:

  • respond        — accept / tentative / decline, «I need until … to say»,
                     or «another time would suit me»;
  • proposals      — the organiser takes or turns down a proposed time; only
                     then does the meeting move, and everyone hears;
  • cancel         — formal: with a reason, the event stays (struck through),
                     a single occurrence of a series can go on its own;
  • occurrence     — change one occurrence of a series, not the whole of it;
  • comments       — the meeting's own thread: replies, @mentions, edits that
                     keep what was said before, files;
  • attachments    — files on the meeting;
  • minutes        — صورت‌جلسه, and its action items as tasks in «وظایف»;
  • history        — every one of the above, who and when.

Who may do what, on top of who may see the event at all (the viewset's
queryset is the IDOR guard — an id outside it is a 404):
  • the organiser — or whoever may edit the event — decides, cancels, edits;
  • an invitee answers for themselves;
  • the discussion, the files, the minutes and the history are for the
    people in the meeting (`views_calendar.in_meeting`) — not for everyone
    who can see a shared calendar it sits on.

Plus three views of one's own: the invitation inbox, the ICS feed, and the
personal preferences (free/busy consent).
"""
from __future__ import annotations

import re
from datetime import timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .calendar_rules import occurrences
from .models_calendar import (
    Calendar, Event, EventAttachment, EventComment, EventResponse, EventTask,
)
from .models_work import Task
from .views import OfficeAccess
from .views_calendar import (
    EVENT_PREFETCH, EventSerializer, EventViewSet, _name, _notify, _response, _sync_responses, _when_label,
    in_meeting, level_for, log, personal_calendar,
)
from .workdays import _off

MAX_FILE_BYTES = 5 * 1024 * 1024
S = EventResponse.Status

_dt = serializers.DateTimeField()


def _parse_dt(value, field: str):
    try:
        return _dt.to_internal_value(value)
    except serializers.ValidationError:
        raise ValidationError({field: "تاریخ و ساعت نامعتبر است."})


def _people(ev: Event) -> set:
    """Everyone in the meeting: its organiser and its invitees."""
    out = set(ev.attendees.all())
    if ev.created_by:
        out.add(ev.created_by)
    return out


def own_busy(user, lo, hi, exclude: int | None = None) -> list[dict]:
    """The caller's own commitments in [lo, hi): what is on their own
    calendar, what they organise with people on it, and what they are invited
    to and have not declined. Read from the caller's data only."""
    evs = (Event.objects.filter(cancelled_at__isnull=True)
           .filter(Q(calendar__kind=Calendar.Kind.PERSONAL, calendar__owner=user)
                   | Q(created_by=user, attendees__isnull=False)
                   | (Q(responses__user=user) & ~Q(responses__status=S.DECLINED)))
           .filter(start__lt=hi).filter(Q(repeat="", end__gt=lo) | ~Q(repeat="")).distinct())
    if exclude:
        evs = evs.exclude(pk=exclude).exclude(series_id=exclude)
    off = _off()
    return [{"id": ev.pk, "title": ev.title, "start": s.isoformat(), "end": e.isoformat()}
            for ev in evs for s, e in occurrences(ev, lo, hi, off) if e > lo and not ev.all_day]


def _fresh(ev: Event, request) -> dict:
    """The event as it is now — not as it was prefetched before the change."""
    ev = Event.objects.select_related("calendar", "created_by").prefetch_related(*EVENT_PREFETCH).get(pk=ev.pk)
    return EventSerializer(ev, context={"request": request}).data


def _file(data: dict) -> dict:
    content = str(data.get("content") or "")
    name = str(data.get("name") or "").strip()[:200]
    if not name or not content.startswith("data:"):
        raise ValidationError({"attachments": "فایل نامعتبر است."})
    size = len(content.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        raise ValidationError({"attachments": f"حجم «{name}» بیش از ۵ مگابایت است."})
    return {"name": name, "content": content, "mime": str(data.get("mime") or "")[:120], "size_bytes": size}


def _comment(c: EventComment, user, can_moderate: bool) -> dict:
    return {
        "id": c.pk, "parent": c.parent_id, "author": c.author_id, "author_name": _name(c.author),
        "author_color": getattr(c.author, "avatar_color", "") if c.author else "",
        "body": c.body, "created_at": c.created_at, "edited_at": c.edited_at, "versions": len(c.history),
        "mentions": [{"id": u.pk, "name": _name(u)} for u in c.mentions.all()],
        "attachments": [{"id": a.pk, "name": a.name, "mime": a.mime, "size_bytes": a.size_bytes}
                        for a in c.attachments.all()],
        "can_edit": c.author_id == user.pk,
        "can_delete": c.author_id == user.pk or can_moderate,
    }


class MeetingViewSet(EventViewSet):
    # ---- helpers -------------------------------------------------------------------
    def _event(self) -> Event:
        return self.get_object()  # Only what the caller may see: anything else is a 404.

    def _member(self, ev: Event) -> None:
        if not in_meeting(self.request.user, ev):
            raise PermissionDenied("این بخش فقط برای برگزارکننده و دعوت‌شدگان این جلسه است.")

    def _organiser(self, ev: Event) -> None:
        lv = level_for(self.request.user, ev.calendar)
        if not (ev.created_by_id == self.request.user.pk or lv == "manage"
                or (lv == "write" and ev.created_by_id == self.request.user.pk)):
            raise PermissionDenied("این کار با برگزارکننده‌ی جلسه است.")

    # ---- answering an invitation -------------------------------------------------------------
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def respond(self, request, pk=None):
        """accepted / tentative / declined; more_time (+ wait_until); proposed
        (+ proposed_start, proposed_end). Returns the answer and, for an
        acceptance, what it clashes with on the caller's own calendar."""
        ev = self._event()
        if ev.cancelled_at:
            raise ValidationError({"status": "این جلسه لغو شده است."})
        r = ev.responses.filter(user=request.user).first()
        if not r:
            raise PermissionDenied("شما به این جلسه دعوت نشده‌اید.")
        st = request.data.get("status")
        if st not in (S.ACCEPTED, S.TENTATIVE, S.DECLINED, S.MORE_TIME, S.PROPOSED):
            raise ValidationError({"status": "پاسخ نامعتبر است."})
        r.status, r.note = st, str(request.data.get("note") or "").strip()[:300]
        r.proposed_start = r.proposed_end = r.wait_until = None
        r.proposal_decision = ""
        if st == S.MORE_TIME:
            if not request.data.get("wait_until"):
                raise ValidationError({"wait_until": "بگویید تا کی پاسخ می‌دهید."})
            r.wait_until = _parse_dt(request.data["wait_until"], "wait_until")
            if r.wait_until <= timezone.now():
                raise ValidationError({"wait_until": "مهلت درخواستی باید در آینده باشد."})
        if st == S.PROPOSED:
            if not request.data.get("proposed_start"):
                raise ValidationError({"proposed_start": "زمان پیشنهادی را تعیین کنید."})
            r.proposed_start = _parse_dt(request.data["proposed_start"], "proposed_start")
            r.proposed_end = (_parse_dt(request.data["proposed_end"], "proposed_end")
                              if request.data.get("proposed_end") else r.proposed_start + (ev.end - ev.start))
            if r.proposed_end <= r.proposed_start:
                raise ValidationError({"proposed_end": "پایان پیش از شروع است."})
        r.responded_at = timezone.now()
        r.save()

        who = _name(request.user)
        msg = {
            S.ACCEPTED: f"{who} دعوت «{ev.title}» را پذیرفت",
            S.TENTATIVE: f"{who} برای «{ev.title}» پاسخ «شاید» داد",
            S.DECLINED: f"{who} دعوت «{ev.title}» را رد کرد",
            S.MORE_TIME: f"{who} برای پاسخ به «{ev.title}» تا {_when_label(ev, r.wait_until) if r.wait_until else ''} مهلت خواست",
            S.PROPOSED: f"{who} برای «{ev.title}» زمان دیگری پیشنهاد داد: {_when_label(ev, r.proposed_start) if r.proposed_start else ''}",
        }[st]
        if r.note:
            msg += f" — «{r.note}»"
        if ev.created_by:
            _notify(request.user, [ev.created_by], ev, msg)
        log(ev, request.user, {"accepted": "accepted", "tentative": "tentative", "declined": "declined",
                               "more_time": "more_time", "proposed": "proposed"}[st], msg)
        out = _response(r)
        if st == S.ACCEPTED:
            out["conflicts"] = own_busy(request.user, ev.start, ev.end, exclude=ev.pk)
        return Response(out)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def proposals(self, request, pk=None):
        """{user, decision: accept|reject}. Accepting moves the meeting to the
        proposed time — the proposer counts as coming, everyone else is asked
        again and told why."""
        ev = self._event()
        self._organiser(ev)
        r = ev.responses.filter(user_id=request.data.get("user"), status=S.PROPOSED).first()
        if not r or not r.proposed_start:
            raise ValidationError({"user": "پیشنهاد زمانی از این شخص نیست."})
        if r.user_id == request.user.pk:
            # Whoever proposed it does not also approve it: that is the organiser's call.
            raise PermissionDenied("پیشنهاد خودتان را برگزارکننده باید بپذیرد یا رد کند.")
        decision = request.data.get("decision")
        if decision not in ("accept", "reject"):
            raise ValidationError({"decision": "پذیرش یا رد را انتخاب کنید."})
        who = _name(r.user)
        if decision == "reject":
            r.proposal_decision = EventResponse.Decision.REJECTED
            r.status = S.PENDING
            r.save()
            _notify(request.user, [r.user], ev, f"پیشنهاد زمان شما برای «{ev.title}» پذیرفته نشد؛ زمان همان {_when_label(ev)} است.")
            log(ev, request.user, "proposal_rejected", who)
            return Response(_fresh(ev, request))

        shift = r.proposed_start - ev.start
        length = (r.proposed_end or r.proposed_start + (ev.end - ev.start)) - r.proposed_start
        ev.start = ev.start + shift
        ev.end = ev.start + length
        ev.save(update_fields=["start", "end", "updated_at"])
        ev.responses.exclude(pk=r.pk).update(status=S.PENDING, note="", proposed_start=None, proposed_end=None,
                                             wait_until=None, proposal_decision="", responded_at=None)
        r.status, r.proposal_decision, r.responded_at = S.ACCEPTED, EventResponse.Decision.ACCEPTED, timezone.now()
        r.save()
        log(ev, request.user, "proposal_accepted", f"{who} — {_when_label(ev)}")
        _notify(request.user, ev.attendees.exclude(pk=r.user_id), ev,
                f"«{ev.title}» به پیشنهاد {who} به {_when_label(ev)} منتقل شد؛ لطفاً دوباره پاسخ دهید.")
        _notify(request.user, [r.user], ev, f"پیشنهاد شما پذیرفته شد: «{ev.title}» — {_when_label(ev)}")
        return Response(_fresh(ev, request))

    # ---- cancelling ---------------------------------------------------------------
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, pk=None):
        """{reason, occurrence?}. The whole event, or — with `occurrence` (that
        occurrence's ISO start) — one occurrence of a series."""
        ev = self._event()
        self._own(ev)
        if ev.cancelled_at:
            raise ValidationError({"detail": "این برنامه پیش‌تر لغو شده است."})
        reason = str(request.data.get("reason") or "").strip()[:300]
        occ = request.data.get("occurrence")
        tail = f" — علت: {reason}" if reason else ""
        if occ and ev.repeat:
            at = timezone.localtime(_parse_dt(occ, "occurrence"))
            ev.exdates = sorted(set((ev.exdates or []) + [at.isoformat()]))
            ev.save(update_fields=["exdates", "updated_at"])
            log(ev, request.user, "occurrence_cancelled", f"{_when_label(ev, at)}{tail}")
            _notify(request.user, ev.attendees.all(), ev, f"«{ev.title}» ({_when_label(ev, at)}) لغو شد{tail}")
        else:
            ev.cancelled_at, ev.cancel_reason = timezone.now(), reason
            ev.save(update_fields=["cancelled_at", "cancel_reason", "updated_at"])
            log(ev, request.user, "cancelled", reason)
            _notify(request.user, ev.attendees.all(), ev, f"«{ev.title}» ({_when_label(ev)}) لغو شد{tail}")
        return Response(_fresh(ev, request))

    # ---- one occurrence of a series -------------------------------------------------------
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def occurrence(self, request, pk=None):
        """{original_start, …fields}: this occurrence only. It leaves the series
        (an exdate there) and becomes an event of its own (`series` → it), with
        the same people, asked again if its time changed."""
        master = self._event()
        self._own(master)
        if not master.repeat:
            raise ValidationError({"detail": "این برنامه تکراری نیست."})
        original = timezone.localtime(_parse_dt(request.data.get("original_start"), "original_start"))
        ser = EventSerializer(data={k: v for k, v in request.data.items() if k != "original_start"},
                              partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        length = master.end - master.start
        ev = Event.objects.create(
            calendar=d.get("calendar", master.calendar), title=d.get("title", master.title),
            kind=d.get("kind", master.kind), priority=d.get("priority", master.priority),
            start=d.get("start", original), end=d.get("end", original + length),
            all_day=d.get("all_day", master.all_day), reminders=d.get("reminders", master.reminders),
            location=d.get("location", master.location), online_link=d.get("online_link", master.online_link),
            description=d.get("description", master.description), guests=d.get("guests", master.guests),
            respond_by=d.get("respond_by", master.respond_by), created_by=master.created_by,
            series=master, original_start=original,
        )
        ev.attendees.set(d["attendees"] if "attendees" in d else master.attendees.all())
        _sync_responses(ev)
        moved = (ev.start, ev.end) != (original, original + length)
        if not moved:  # Same time: carry each answer over.
            for r in master.responses.all():
                ev.responses.filter(user_id=r.user_id).update(status=r.status, note=r.note, responded_at=r.responded_at)
        master.exdates = sorted(set((master.exdates or []) + [original.isoformat()]))
        master.save(update_fields=["exdates", "updated_at"])
        log(master, request.user, "occurrence_moved", f"{_when_label(master, original)} → {_when_label(ev)}")
        log(ev, request.user, "created", f"از تکرارهای «{master.title}» ({_when_label(master, original)})")
        if moved:
            _notify(request.user, ev.attendees.all(), ev,
                    f"«{ev.title}» ({_when_label(master, original)}) به {_when_label(ev)} تغییر کرد؛ لطفاً پاسخ دهید.")
        return Response(_fresh(ev, request), status=status.HTTP_201_CREATED)

    # ---- discussion ----------------------------------------------------------------
    def _can_moderate(self, ev: Event) -> bool:
        return ev.created_by_id == self.request.user.pk or level_for(self.request.user, ev.calendar) == "manage"

    def _thread(self, ev: Event):
        mod = self._can_moderate(ev)
        rows = ev.comments.select_related("author").prefetch_related("mentions", "attachments")
        return [_comment(c, self.request.user, mod) for c in rows]

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        """GET the thread. POST {body, parent?, mentions?: [user ids], attachments?: [{name, mime, content}]}."""
        ev = self._event()
        self._member(ev)
        if request.method == "GET":
            return Response(self._thread(ev))
        body = str(request.data.get("body") or "").strip()
        files = request.data.get("attachments") or []
        if not body and not files:
            raise ValidationError({"body": "متن نظر را بنویسید."})
        parent = None
        if request.data.get("parent"):
            parent = ev.comments.filter(pk=request.data["parent"]).first()
            if not parent:
                raise ValidationError({"parent": "نظری که به آن پاسخ می‌دهید پیدا نشد."})
        people = _people(ev)
        # Only people in the meeting can be named: anyone else could not read it.
        ids = {int(i) for i in (request.data.get("mentions") or []) if str(i).isdigit()}
        mentioned = [u for u in people if u.pk in ids and u.pk != request.user.pk]
        with transaction.atomic():
            c = EventComment.objects.create(event=ev, author=request.user, parent=parent, body=body[:2000])
            c.mentions.set(mentioned)
            for f in files[:10]:
                EventAttachment.objects.create(event=ev, comment=c, uploaded_by=request.user, **_file(f))
        who, short = _name(request.user), body[:100]
        told = set()
        if mentioned:
            _notify(request.user, mentioned, ev, f"{who} در گفتگوی «{ev.title}» شما را نام برد: {short}")
            told |= {u.pk for u in mentioned}
        if parent and parent.author and parent.author_id not in told:
            _notify(request.user, [parent.author], ev, f"{who} به نظر شما در «{ev.title}» پاسخ داد: {short}")
            told.add(parent.author_id)
        rest = [u for u in people if u.pk not in told]
        _notify(request.user, rest, ev, f"{who} درباره‌ی «{ev.title}» نوشت: {short}" + (" (با پیوست)" if files else ""))
        log(ev, request.user, "commented", short)
        return Response(self._thread(ev))

    @action(detail=True, methods=["patch", "delete"], url_path=r"comments/(?P<cid>\d+)")
    def comment(self, request, pk=None, cid=None):
        ev = self._event()
        self._member(ev)
        c = ev.comments.filter(pk=cid).first()
        if not c:
            raise ValidationError({"comment": "نظر پیدا نشد."})
        if request.method == "DELETE":
            if not (c.author_id == request.user.pk or self._can_moderate(ev)):
                raise PermissionDenied("فقط نویسنده‌ی نظر یا برگزارکننده آن را حذف می‌کند.")
            log(ev, request.user, "comment_deleted", c.body[:100])
            c.delete()
            return Response(self._thread(ev))
        if c.author_id != request.user.pk:
            raise PermissionDenied("فقط نویسنده‌ی نظر آن را ویرایش می‌کند.")
        body = str(request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "متن نظر را بنویسید."})
        if body != c.body:
            c.history = [*c.history, {"body": c.body, "at": (c.edited_at or c.created_at).isoformat()}]
            c.body, c.edited_at = body[:2000], timezone.now()
            c.save(update_fields=["body", "edited_at", "history", "updated_at"])
            log(ev, request.user, "comment_edited", body[:100])
        return Response(self._thread(ev))

    @action(detail=True, methods=["get"], url_path=r"comments/(?P<cid>\d+)/versions")
    def comment_versions(self, request, pk=None, cid=None):
        ev = self._event()
        self._member(ev)
        c = ev.comments.filter(pk=cid).first()
        if not c:
            raise ValidationError({"comment": "نظر پیدا نشد."})
        return Response(c.history)

    # ---- files ----------------------------------------------------------------------
    @action(detail=True, methods=["post"])
    def attachments(self, request, pk=None):
        """{name, mime, content (a data: URL)} — a file on the meeting itself."""
        ev = self._event()
        self._member(ev)
        a = EventAttachment.objects.create(event=ev, uploaded_by=request.user, **_file(request.data))
        _notify(request.user, _people(ev), ev, f"{_name(request.user)} فایل «{a.name}» را به «{ev.title}» افزود.")
        log(ev, request.user, "attachment", a.name)
        return Response(_fresh(ev, request))

    @action(detail=True, methods=["get", "delete"], url_path=r"attachments/(?P<aid>\d+)")
    def attachment(self, request, pk=None, aid=None):
        ev = self._event()
        self._member(ev)
        a = ev.attachments.filter(pk=aid).first()
        if not a:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if request.method == "DELETE":
            if not (a.uploaded_by_id == request.user.pk or self._can_moderate(ev)):
                raise PermissionDenied("فقط فرستنده‌ی فایل یا برگزارکننده آن را حذف می‌کند.")
            log(ev, request.user, "attachment_deleted", a.name)
            a.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"id": a.pk, "name": a.name, "mime": a.mime, "size_bytes": a.size_bytes, "content": a.content})

    # ---- minutes and action items -----------------------------------------------------------
    @action(detail=True, methods=["put"])
    @transaction.atomic
    def minutes(self, request, pk=None):
        """{minutes, action_items?: [{title, assignee, due_on?}]} — the organiser
        records the meeting; each new action item becomes a task in «وظایف»."""
        ev = self._event()
        self._organiser(ev)
        text = str(request.data.get("minutes") or "").strip()
        first = not ev.minutes
        ev.minutes, ev.minutes_at = text, timezone.now()
        ev.save(update_fields=["minutes", "minutes_at", "updated_at"])
        User = get_user_model()
        made = []
        for item in request.data.get("action_items") or []:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            who = User.objects.filter(pk=item.get("assignee"), is_active=True).first() if item.get("assignee") else None
            due = item.get("due_on") or None
            task = Task.objects.create(title=title[:250], description=f"از جلسه‌ی «{ev.title}» ({_when_label(ev)})",
                                       assignee=who, creator=request.user, due_on=due)
            EventTask.objects.create(event=ev, task=task)
            made.append(task)
            if who:
                _notify(request.user, [who], ev, f"اقدام از جلسه‌ی «{ev.title}» به شما سپرده شد: {title[:120]}")
        log(ev, request.user, "minutes", ("ثبت صورت‌جلسه" if first else "ویرایش صورت‌جلسه")
            + (f" و {len(made)} اقدام" if made else ""))
        if first and text:
            _notify(request.user, _people(ev), ev, f"صورت‌جلسه‌ی «{ev.title}» ثبت شد.")
        return Response(_fresh(ev, request))

    # ---- history, ICS -------------------------------------------------------------------
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        ev = self._event()
        self._member(ev)
        return Response([{"action": l.action, "detail": l.detail, "actor": _name(l.actor), "at": l.at}
                         for l in ev.log.select_related("actor")])

    @action(detail=True, methods=["get"])
    def ics(self, request, pk=None):
        ev = self._event()
        lo = ev.start - timedelta(days=1)
        return _ics_response([(ev, s, e) for s, e in occurrences(ev, lo, lo + timedelta(days=400))][:400],
                             f"event-{ev.pk}.ics")


# ---------------------------------------------------------------- the caller's own
class InvitationsView(APIView):
    """?box=received|sent — the invitation inbox. Received: what the caller
    is invited to, with their answer. Sent: the meetings they organise, with
    how everyone answered."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        box = request.query_params.get("box", "received")
        since = timezone.now() - timedelta(days=30)
        if box == "sent":
            evs = (Event.objects.filter(created_by=request.user, attendees__isnull=False)
                   .filter(Q(end__gte=since) | ~Q(repeat="")).distinct())
        else:
            evs = Event.objects.filter(responses__user=request.user).filter(Q(end__gte=since) | ~Q(repeat="")).distinct()
        evs = evs.select_related("calendar", "created_by").prefetch_related(*EVENT_PREFETCH).order_by("start")[:200]
        return Response(EventSerializer(evs, many=True, context={"request": request}).data)


class ConflictsView(APIView):
    """?from=ISO&to=ISO&exclude=id — what the caller already has then, on their own calendar."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        q = request.query_params
        lo, hi = _parse_dt(q.get("from"), "from"), _parse_dt(q.get("to"), "to")
        if not timedelta(0) < hi - lo <= timedelta(days=31):
            raise ValidationError({"from": "بازه‌ی زمانی نامعتبر است."})
        ex = q.get("exclude")
        return Response(own_busy(request.user, lo, hi, int(ex) if ex and ex.isdigit() else None))


class PreferencesView(APIView):
    """The caller's own calendar preferences: whether colleagues who invite
    them may see when they are busy (never what with)."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        return Response({"share_free_busy": personal_calendar(request.user).share_free_busy})

    def put(self, request):
        cal = personal_calendar(request.user)
        if "share_free_busy" in request.data:
            cal.share_free_busy = bool(request.data["share_free_busy"])
            cal.save(update_fields=["share_free_busy", "updated_at"])
        return Response({"share_free_busy": cal.share_free_busy})


class IcsFeedView(APIView):
    """?from&to — the caller's own commitments as an .ics file, for Outlook or Google Calendar."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        now = timezone.now()
        lo = _parse_dt(request.query_params["from"], "from") if request.query_params.get("from") else now - timedelta(days=30)
        hi = _parse_dt(request.query_params["to"], "to") if request.query_params.get("to") else now + timedelta(days=365)
        if not timedelta(0) < hi - lo <= timedelta(days=400):
            raise ValidationError({"from": "بازه‌ی زمانی نامعتبر است."})
        user = request.user
        evs = (Event.objects.filter(Q(calendar__kind=Calendar.Kind.PERSONAL, calendar__owner=user)
                                    | Q(created_by=user, attendees__isnull=False)
                                    | (Q(responses__user=user) & ~Q(responses__status=S.DECLINED)))
               .filter(start__lt=hi).filter(Q(repeat="", end__gt=lo) | ~Q(repeat="")).distinct())
        off = _off()
        rows = [(ev, s, e) for ev in evs for s, e in occurrences(ev, lo, hi, off)][:3000]
        return _ics_response(rows, "calendar.ics")


def _ics_escape(text: str) -> str:
    return re.sub(r"([,;\\])", r"\\\1", str(text or "")).replace("\r\n", "\\n").replace("\n", "\\n")


def _ics_response(rows, filename: str) -> HttpResponse:
    fmt = "%Y%m%dT%H%M%SZ"
    stamp = timezone.now().strftime(fmt)
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NTP BI//Calendar//FA", "CALSCALE:GREGORIAN"]
    for ev, s, e in rows:
        out += ["BEGIN:VEVENT", f"UID:event-{ev.pk}-{int(s.timestamp())}@ntpbi", f"DTSTAMP:{stamp}"]
        if ev.all_day:
            day = timezone.localtime(s).date()
            out += [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
        else:
            out += [f"DTSTART:{s.astimezone(dt_timezone.utc).strftime(fmt)}", f"DTEND:{e.astimezone(dt_timezone.utc).strftime(fmt)}"]
        out.append(f"SUMMARY:{_ics_escape(ev.title)}")
        if ev.location or ev.online_link:
            out.append(f"LOCATION:{_ics_escape(ev.location or ev.online_link)}")
        if ev.description:
            out.append(f"DESCRIPTION:{_ics_escape(ev.description)}")
        if ev.cancelled_at:
            out.append("STATUS:CANCELLED")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    resp = HttpResponse("\r\n".join(out) + "\r\n", content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
