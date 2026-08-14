"""
گفتگوی گروهی — groups on top of the 1:1 chat that already exists.

`accounts.MessageViewSet` keeps serving direct messages exactly as it did.
This adds the group half: a named conversation, its members, and a read
marker per member. Nothing here rewrites a direct message, so the existing
پیام‌ها page carries on working while this is built beside it.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import (
    ChatGroup,
    ChatGroupMember,
    Message,
    MessageAttachment,
    MessageReaction,
)

from .serializers import PersonSerializer
from .views import OfficeAccess

User = get_user_model()


#: base64 inflates by 4/3, so this is what actually lands in the row.
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _reaction_summary(message, me) -> list[dict]:
    """
    Reactions grouped by emoji, with whether *you* gave each one.

    Grouped rather than listed: a message with twelve 👍 should read as
    «👍 ۱۲», and `mine` is what lets the same tap take it back.
    """
    out: dict[str, dict] = {}
    for r in message.reactions.all():
        row = out.setdefault(r.emoji, {"emoji": r.emoji, "count": 0, "mine": False, "who": []})
        row["count"] += 1
        row["who"].append(r.user_id)
        if r.user_id == me.pk:
            row["mine"] = True
    return list(out.values())


def _message_rows(qs, me=None) -> list[dict]:
    rows = []
    for m in qs.select_related("sender", "reply_to", "reply_to__sender").prefetch_related(
        "attachments", "reactions"
    ):
        rows.append({
            "id": m.id,
            "body": m.body,
            "created_at": m.created_at,
            "edited_at": m.edited_at,
            "sender": m.sender_id,
            "sender_detail": PersonSerializer(m.sender).data,
            # Enough of the parent to draw the quoted strip — not the whole
            # message, which would nest without end in a long back-and-forth.
            "reply_to": (
                {
                    "id": m.reply_to.id,
                    "body": m.reply_to.body[:120],
                    "sender_name": (
                        m.reply_to.sender.display_name_fa
                        or m.reply_to.sender.get_username()
                    ),
                }
                if m.reply_to else None
            ),
            "attachments": [
                {
                    "id": a.id, "name": a.name, "mime": a.mime,
                    "size_bytes": a.size_bytes, "is_image": a.is_image,
                }
                for a in m.attachments.all()
            ],
            "reactions": _reaction_summary(m, me) if me else [],
        })
    return rows


def _attach(message, files) -> None:
    """Store the files sent with a message, refusing anything oversized."""
    for f in files or []:
        content = f.get("content") or ""
        size = len(content.encode("utf-8"))
        if size > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"حجم «{f.get('name', 'پیوست')}» بیش از حد مجاز است.")
        MessageAttachment.objects.create(
            message=message, name=(f.get("name") or "فایل")[:200],
            content=content, mime=(f.get("mime") or "")[:120], size_bytes=size,
        )


class ChatGroupViewSet(viewsets.ViewSet):
    """
    Groups the caller belongs to, and the messages in them.

    A ViewSet rather than a ModelViewSet: a group is three tables to the
    client (itself, its members, its unread count) and shaping that by hand
    is clearer than three nested serializers.
    """

    permission_classes = [OfficeAccess]

    def _mine(self):
        return ChatGroup.objects.filter(
            memberships__user=self.request.user
        ).distinct()

    def _row(self, group, membership=None) -> dict:
        me = self.request.user
        membership = membership or group.memberships.filter(user=me).first()
        unread = Message.objects.filter(group=group).exclude(sender=me)
        if membership and membership.last_read_at:
            unread = unread.filter(created_at__gt=membership.last_read_at)
        last = group.messages.order_by("-created_at").first()
        return {
            "id": group.id,
            "title": group.title,
            "member_count": group.member_count,
            "members": PersonSerializer(
                [m.user for m in group.memberships.all()], many=True
            ).data,
            "unread": unread.count(),
            "last_message": last.body[:80] if last else "",
            "last_at": last.created_at if last else None,
        }

    def list(self, request):
        groups = (
            self._mine()
            .prefetch_related("memberships__user", "messages")
            .annotate(_last=Max("messages__created_at"))
            .order_by("-_last", "-created_at")
        )
        return Response({"groups": [self._row(g) for g in groups]})

    def create(self, request):
        title = (request.data.get("title") or "").strip()
        members = request.data.get("members") or []
        if not title:
            return Response(
                {"detail": "نام گروه را بنویسید."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        group = ChatGroup.objects.create(title=title, created_by=request.user)
        # The creator is always a member; a group its own author cannot see
        # is a group that vanishes the moment it is made.
        for uid in {*members, request.user.pk}:
            ChatGroupMember.objects.get_or_create(group=group, user_id=uid)
        return Response(self._row(group), status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        """The thread, and the read marker moves to now."""
        group = self._mine().filter(pk=pk).first()
        if not group:
            return Response(status=status.HTTP_404_NOT_FOUND)
        rows = _message_rows(group.messages.order_by("created_at"), request.user)
        ChatGroupMember.objects.filter(group=group, user=request.user).update(
            last_read_at=timezone.now()
        )
        return Response({**self._row(group), "messages": rows})

    @action(detail=True, methods=["post"])
    def post_message(self, request, pk=None):
        group = self._mine().filter(pk=pk).first()
        if not group:
            return Response(status=status.HTTP_404_NOT_FOUND)
        body = (request.data.get("body") or "").strip()
        files = request.data.get("attachments") or []
        # A message may be a file with no words — sending a photo and typing
        # nothing is the normal case, not an error.
        if not body and not files:
            return Response(
                {"detail": "پیام خالی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        msg = Message.objects.create(
            sender=request.user, group=group, body=body,
            reply_to_id=request.data.get("reply_to") or None,
        )
        try:
            _attach(msg, files)
        except ValueError as exc:
            msg.delete()
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            _message_rows(Message.objects.filter(pk=msg.pk), request.user)[0],
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def members(self, request, pk=None):
        """Add or remove people. Only a member may change the roster."""
        group = self._mine().filter(pk=pk).first()
        if not group:
            return Response(status=status.HTTP_404_NOT_FOUND)
        add = request.data.get("add") or []
        remove = request.data.get("remove") or []
        for uid in add:
            ChatGroupMember.objects.get_or_create(group=group, user_id=uid)
        if remove:
            # The creator cannot be removed by someone else's tidy-up; leaving
            # is a separate, deliberate act.
            group.memberships.filter(user_id__in=remove).exclude(
                user_id=group.created_by_id
            ).delete()
        return Response(self._row(group))

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        group = self._mine().filter(pk=pk).first()
        if not group:
            return Response(status=status.HTTP_404_NOT_FOUND)
        group.memberships.filter(user=request.user).delete()
        return Response({"left": True})


class MessageExtrasView(APIView):
    """
    React to a message, and fetch an attachment's bytes.

    Both are per-message rather than per-conversation, and both check that
    the caller can actually see the message: a reaction endpoint that trusts
    the id would let anyone react to — and so confirm the existence of — a
    private thread they are not in.
    """

    permission_classes = [OfficeAccess]

    def _visible(self, request, pk):
        me = request.user
        return (
            Message.objects.filter(pk=pk)
            .filter(
                Q(sender=me) | Q(recipient=me)
                | Q(group__memberships__user=me)
            )
            .distinct()
            .first()
        )

    def post(self, request, pk=None):
        """Toggle one emoji. Tapping the one you gave takes it back."""
        msg = self._visible(request, pk)
        if not msg:
            return Response(status=status.HTTP_404_NOT_FOUND)
        emoji = (request.data.get("emoji") or "").strip()[:8]
        if not emoji:
            return Response(
                {"detail": "واکنش مشخص نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row = MessageReaction.objects.filter(
            message=msg, user=request.user, emoji=emoji
        ).first()
        if row:
            row.delete()
        else:
            MessageReaction.objects.create(
                message=msg, user=request.user, emoji=emoji
            )
        return Response({"reactions": _reaction_summary(msg, request.user)})

    def get(self, request, pk=None):
        """One attachment's bytes, by `?attachment=<id>`."""
        msg = self._visible(request, pk)
        if not msg:
            return Response(status=status.HTTP_404_NOT_FOUND)
        att = msg.attachments.filter(pk=request.query_params.get("attachment")).first()
        if not att:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({
            "id": att.id, "name": att.name, "mime": att.mime,
            "size_bytes": att.size_bytes, "content": att.content,
        })


class ChatOverviewView(APIView):
    """
    Both halves of گفتگو in one response: direct threads and groups.

    One request because the chat page shows them in a single list, and two
    endpoints would mean the list could render half-sorted while the second
    reply was still in flight.
    """

    permission_classes = [OfficeAccess]

    def get(self, request):
        me = request.user

        direct = (
            Message.objects.filter(Q(sender=me) | Q(recipient=me), group__isnull=True)
            .select_related("sender", "recipient")
            .order_by("-created_at")
        )
        threads: dict[int, dict] = {}
        for m in direct[:500]:
            other = m.recipient if m.sender_id == me.pk else m.sender
            if not other or other.pk in threads:
                continue
            threads[other.pk] = {
                "user": PersonSerializer(other).data,
                "last_message": m.body[:80],
                "last_at": m.created_at,
                "unread": Message.objects.filter(
                    sender=other, recipient=me, is_read=False
                ).count(),
            }

        groups = []
        for mem in (
            ChatGroupMember.objects.filter(user=me)
            .select_related("group")
            .prefetch_related("group__memberships__user")
        ):
            g = mem.group
            unread = Message.objects.filter(group=g).exclude(sender=me)
            if mem.last_read_at:
                unread = unread.filter(created_at__gt=mem.last_read_at)
            last = g.messages.order_by("-created_at").first()
            groups.append({
                "id": g.id,
                "title": g.title,
                "member_count": g.member_count,
                "unread": unread.count(),
                "last_message": last.body[:80] if last else "",
                "last_at": last.created_at if last else None,
            })

        return Response({
            "direct": sorted(
                threads.values(), key=lambda t: t["last_at"], reverse=True
            ),
            "groups": sorted(
                groups,
                key=lambda g: g["last_at"] or g["title"],
                reverse=True,
            ),
            "people": PersonSerializer(
                User.objects.filter(is_active=True).exclude(pk=me.pk)
                .order_by("display_name_fa", "username"),
                many=True,
            ).data,
        })
