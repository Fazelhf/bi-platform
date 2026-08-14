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

from apps.accounts.models import ChatGroup, ChatGroupMember, Message

from .serializers import PersonSerializer
from .views import OfficeAccess

User = get_user_model()


def _message_rows(qs) -> list[dict]:
    return [
        {
            "id": m.id,
            "body": m.body,
            "created_at": m.created_at,
            "sender": m.sender_id,
            "sender_detail": PersonSerializer(m.sender).data,
        }
        for m in qs.select_related("sender")
    ]


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
        rows = _message_rows(group.messages.order_by("created_at"))
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
        if not body:
            return Response(
                {"detail": "متن پیام خالی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        msg = Message.objects.create(sender=request.user, group=group, body=body)
        return Response(
            _message_rows(Message.objects.filter(pk=msg.pk))[0],
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
