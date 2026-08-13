"""
مکاتبات — the four mailboxes, and the actions that move a letter along.

Everything here is scoped to the caller. There is no «all letters» endpoint
and no admin override: correspondence is addressed, and a system where a
department manager can read a letter they were not sent is not correspondence,
it is a shared folder with extra steps.
"""
from __future__ import annotations

from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Letter, LetterAction, LetterRecipient, LetterTag
from .serializers import (
    LetterActionSerializer,
    LetterAttachmentSerializer,
    LetterDetailSerializer,
    LetterListSerializer,
    LetterTagSerializer,
    LetterWriteSerializer,
    PersonSerializer,
)


class OfficeAccess(BasePermission):
    """
    Every signed-in employee has a کارتابل.

    Unlike the reporting sections, correspondence is not gated by department:
    a letter is addressed to a person, and the addressing *is* the permission.
    """

    message = "برای دیدن مکاتبات باید وارد شوید."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated)


class LetterViewSet(viewsets.ModelViewSet):
    permission_classes = [OfficeAccess]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["number", "subject", "body"]
    ordering_fields = ["sent_at", "created_at"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return LetterWriteSerializer
        if self.action == "retrieve":
            return LetterDetailSerializer
        return LetterListSerializer

    def get_queryset(self):
        """
        Everything the caller is entitled to see: what they sent, and what was
        sent to them. The mailbox actions narrow this further; on its own it
        is the union, which is what search and «باز کردن با شناسه» need.
        """
        user = self.request.user
        return (
            Letter.objects.filter(
                Q(sender=user) | Q(recipients__user=user)
            )
            .distinct()
            .select_related("sender")
            .prefetch_related(
                "tags", "attachments",
                Prefetch(
                    "recipients",
                    queryset=LetterRecipient.objects.select_related("user"),
                ),
            )
        )

    # -- writing ---------------------------------------------------------
    def perform_destroy(self, instance):
        # Only an unsent draft can be deleted, and only by its author. A sent
        # letter sitting in someone else's inbox cannot be withdrawn by the
        # sender changing their mind — that is what the copy is for.
        if instance.is_sent:
            raise PermissionError
        instance.delete()

    def destroy(self, request, *args, **kwargs):
        letter = self.get_object()
        if letter.is_sent:
            return Response(
                {"detail": "نامه‌ی ارسال‌شده حذف نمی‌شود."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if letter.sender_id != request.user.id:
            return Response(
                {"detail": "فقط نویسنده می‌تواند پیش‌نویس را حذف کند."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        letter = self.get_object()
        if letter.sender_id != request.user.id:
            return Response(
                {"detail": "فقط نویسنده می‌تواند پیش‌نویس را ویرایش کند."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """Opening a letter is what marks it read — for the reader only."""
        letter = self.get_object()
        LetterRecipient.objects.filter(
            letter=letter, user=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())

        data = self.get_serializer(letter).data
        # The caller's own copy, the same way MailboxView stamps the list.
        # Without it the page cannot tell «I archived this» from «somebody
        # archived this», and the archive button labels itself from the wrong
        # person's state.
        mine = letter.recipients.filter(user=request.user).first()
        data["my_read_at"] = mine.read_at if mine else None
        data["my_archived_at"] = mine.archived_at if mine else None
        return Response(data)

    # -- moving it along --------------------------------------------------
    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        letter = self.get_object()
        if letter.sender_id != request.user.id:
            return Response(
                {"detail": "فقط نویسنده می‌تواند نامه را ارسال کند."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not letter.recipients.exists():
            return Response(
                {"detail": "برای ارسال، دست‌کم یک گیرنده لازم است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        letter.send()
        return Response(LetterDetailSerializer(letter).data)

    @action(detail=True, methods=["post"])
    def refer(self, request, pk=None):
        """
        ارجاع — pass the letter on, with a note.

        The person referred to becomes a recipient, so it lands in their
        صندوق ورودی like anything else. Without that they would have to be
        told out-of-band that a referral exists, which is the gap the
        paper-and-telephone process this replaces had.
        """
        letter = self.get_object()
        to_id = request.data.get("to_user")
        if not to_id:
            return Response(
                {"detail": "گیرنده‌ی ارجاع مشخص نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        LetterRecipient.objects.get_or_create(
            letter=letter, user_id=to_id,
            defaults={"kind": LetterRecipient.Kind.TO},
        )
        act = LetterAction.objects.create(
            letter=letter, kind=LetterAction.Kind.REFER,
            actor=request.user, to_user_id=to_id,
            note=(request.data.get("note") or "").strip(),
        )
        return Response(
            LetterActionSerializer(act).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def paraph(self, request, pk=None):
        """پاراف — sign off on the letter, optionally with a note."""
        letter = self.get_object()
        act = LetterAction.objects.create(
            letter=letter, kind=LetterAction.Kind.PARAPH, actor=request.user,
            note=(request.data.get("note") or "").strip(),
        )
        return Response(
            LetterActionSerializer(act).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def note(self, request, pk=None):
        letter = self.get_object()
        text = (request.data.get("note") or "").strip()
        if not text:
            return Response(
                {"detail": "متن یادداشت خالی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        act = LetterAction.objects.create(
            letter=letter, kind=LetterAction.Kind.NOTE,
            actor=request.user, note=text,
        )
        return Response(
            LetterActionSerializer(act).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """
        File it away — or take it back out.

        Archiving is per-person, like reading: one recipient filing their copy
        must not clear it off everyone else's desk.
        """
        letter = self.get_object()
        row = letter.recipients.filter(user=request.user).first()
        if not row:
            return Response(
                {"detail": "این نامه در صندوق ورودی شما نیست."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        undo = bool(request.data.get("undo"))
        row.archived_at = None if undo else timezone.now()
        row.save(update_fields=["archived_at"])
        return Response({"archived_at": row.archived_at})

    @action(detail=True, methods=["get"], url_path="attachments/(?P<att_id>[^/.]+)")
    def attachment(self, request, pk=None, att_id=None):
        """
        One attachment's bytes, asked for by name.

        The list and detail serializers omit `content` on purpose: a کارتابل
        of twenty letters would otherwise ship every file on the page.
        """
        letter = self.get_object()
        att = letter.attachments.filter(pk=att_id).first()
        if not att:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({
            "id": att.id, "name": att.name, "mime": att.mime,
            "size_bytes": att.size_bytes, "content": att.content,
        })


class MailboxView(APIView):
    """
    The four tabs of کارتابل, as four readings of the same two tables.

        ?box=inbox    نامه‌هایی که به من رسیده و بایگانی نشده
        ?box=outbox   نامه‌هایی که فرستاده‌ام
        ?box=paraph   نامه‌هایی که پاراف کرده‌ام
        ?box=archive  ورودی بایگانی‌شده
        ?box=draft    پیش‌نویس‌های من
    """

    permission_classes = [OfficeAccess]

    BOXES = {"inbox", "outbox", "paraph", "archive", "draft"}

    def get(self, request):
        box = (request.query_params.get("box") or "inbox").strip()
        if box not in self.BOXES:
            return Response(
                {"detail": f"صندوق «{box}» تعریف نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = request.user
        base = (
            Letter.objects.select_related("sender")
            .prefetch_related(
                "tags", "attachments",
                Prefetch(
                    "recipients",
                    queryset=LetterRecipient.objects.select_related("user"),
                ),
            )
        )

        if box == "draft":
            qs = base.filter(sender=user, status=Letter.Status.DRAFT)
        elif box == "outbox":
            qs = base.filter(sender=user, status=Letter.Status.SENT)
        elif box == "paraph":
            qs = base.filter(
                actions__actor=user, actions__kind=LetterAction.Kind.PARAPH
            ).distinct()
        else:
            mine = LetterRecipient.objects.filter(user=user)
            if box == "inbox":
                mine = mine.filter(archived_at__isnull=True)
            else:
                mine = mine.filter(archived_at__isnull=False)
            qs = base.filter(
                id__in=mine.values("letter_id"), status=Letter.Status.SENT
            )

        qs = self._apply_filters(qs, request)
        rows = LetterListSerializer(qs[:200], many=True).data
        self._stamp_my_copy(rows, user)
        return Response({
            "box": box,
            "count": qs.count(),
            "unread": self._unread(user),
            "rows": rows,
        })

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _apply_filters(qs, request):
        q = request.query_params
        if text := (q.get("q") or "").strip():
            qs = qs.filter(
                Q(subject__icontains=text)
                | Q(body__icontains=text)
                | Q(number__icontains=text)
            )
        if sender := q.get("sender"):
            qs = qs.filter(sender_id=sender)
        if tag := q.get("tag"):
            qs = qs.filter(tags__id=tag)
        if recipient := q.get("recipient"):
            qs = qs.filter(recipients__user_id=recipient)
        if q.get("has_attachment") in {"1", "true"}:
            qs = qs.filter(attachments__isnull=False)
        read = q.get("read")
        if read in {"0", "1"}:
            mine = LetterRecipient.objects.filter(
                user=request.user, read_at__isnull=(read == "0")
            )
            qs = qs.filter(id__in=mine.values("letter_id"))
        if start := q.get("from"):
            qs = qs.filter(sent_at__date__gte=start)
        if end := q.get("to"):
            qs = qs.filter(sent_at__date__lte=end)
        return qs.distinct()

    @staticmethod
    def _stamp_my_copy(rows: list[dict], user) -> None:
        """
        Attach the caller's own read/archive state to each row.

        Done in one query after serialisation rather than as a
        SerializerMethodField, which would issue one query per row — the
        difference between a mailbox that opens and one that crawls.
        """
        ids = [r["id"] for r in rows]
        mine = {
            r.letter_id: r
            for r in LetterRecipient.objects.filter(user=user, letter_id__in=ids)
        }
        for row in rows:
            copy = mine.get(row["id"])
            row["my_read_at"] = copy.read_at if copy else None
            row["my_archived_at"] = copy.archived_at if copy else None

    @staticmethod
    def _unread(user) -> int:
        return LetterRecipient.objects.filter(
            user=user, read_at__isnull=True, archived_at__isnull=True,
            letter__status=Letter.Status.SENT,
        ).count()


class LetterTagViewSet(viewsets.ModelViewSet):
    queryset = LetterTag.objects.all()
    serializer_class = LetterTagSerializer
    permission_classes = [OfficeAccess]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class OfficePeopleView(APIView):
    """
    Who a letter can be addressed to: every active account.

    Served from here rather than reused from the admin panel's user list,
    which is gated to administrators — a clerk must be able to address the
    CEO without being able to read the user table.
    """

    permission_classes = [OfficeAccess]

    def get(self, request):
        from django.contrib.auth import get_user_model

        people = (
            get_user_model().objects
            .filter(is_active=True)
            .exclude(pk=request.user.pk)
            .order_by("display_name_fa", "username")
        )
        return Response({
            "people": PersonSerializer(people, many=True).data,
            "tags": LetterTagSerializer(LetterTag.objects.all(), many=True).data,
        })
