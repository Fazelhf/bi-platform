"""Serializers for مکاتبات."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import (
    Letter,
    LetterAction,
    LetterAttachment,
    LetterRecipient,
    LetterTag,
)

User = get_user_model()

#: Attachments live in the database as base64, so an unbounded upload is a row
#: nobody can delete through the UI and a page that never finishes loading.
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


class PersonSerializer(serializers.ModelSerializer):
    """The shape every «فرستنده / گیرنده» field renders as."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "job_title_fa", "avatar_color", "avatar_image"]

    def get_name(self, obj) -> str:
        return obj.display_name_fa or obj.get_username()


class LetterTagSerializer(serializers.ModelSerializer):
    letter_count = serializers.SerializerMethodField()

    class Meta:
        model = LetterTag
        fields = ["id", "name_fa", "color", "letter_count"]

    def get_letter_count(self, obj) -> int:
        return obj.letters.count()


class LetterAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LetterAttachment
        fields = ["id", "name", "mime", "size_bytes", "content"]
        extra_kwargs = {
            # The bytes are only sent when one attachment is asked for by
            # name; a list of twelve letters must not carry twelve files.
            "content": {"write_only": True},
        }

    def validate(self, attrs):
        content = attrs.get("content") or ""
        # base64 inflates by 4/3; measure what will actually be stored.
        size = len(content.encode("utf-8"))
        if size > MAX_ATTACHMENT_BYTES:
            raise serializers.ValidationError({
                "content": (
                    f"حجم «{attrs.get('name', 'پیوست')}» بیش از حد مجاز است "
                    f"({MAX_ATTACHMENT_BYTES // (1024 * 1024)} مگابایت)."
                )
            })
        attrs["size_bytes"] = size
        return attrs


class LetterActionSerializer(serializers.ModelSerializer):
    actor_detail = PersonSerializer(source="actor", read_only=True)
    to_user_detail = PersonSerializer(source="to_user", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    is_private = serializers.SerializerMethodField()

    class Meta:
        model = LetterAction
        fields = [
            "id", "letter", "kind", "kind_label", "actor", "actor_detail",
            "to_user", "to_user_detail", "note", "visibility", "is_private",
            "created_at",
        ]
        read_only_fields = ["actor"]

    def get_is_private(self, obj) -> bool:
        return obj.visibility == LetterAction.Visibility.PRIVATE


class LetterRecipientSerializer(serializers.ModelSerializer):
    user_detail = PersonSerializer(source="user", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = LetterRecipient
        fields = [
            "id", "user", "user_detail", "kind", "kind_label",
            "read_at", "archived_at", "sees_history",
        ]


class LetterListSerializer(serializers.ModelSerializer):
    """
    A row in a mailbox. Deliberately without the body or the attachment
    bytes — the کارتابل shows a hundred of these and only ever renders the
    first line of each.
    """

    sender_detail = PersonSerializer(source="sender", read_only=True)
    tags_detail = LetterTagSerializer(source="tags", many=True, read_only=True)
    attachment_count = serializers.SerializerMethodField()
    recipient_names = serializers.SerializerMethodField()
    #: The caller's own copy — null when they are the sender looking at
    #: صندوق خروجی, where «خوانده‌شده» belongs to other people.
    my_read_at = serializers.DateTimeField(read_only=True, default=None)
    my_archived_at = serializers.DateTimeField(read_only=True, default=None)
    preview = serializers.SerializerMethodField()

    class Meta:
        model = Letter
        fields = [
            "id", "number", "subject", "preview", "status", "sent_at",
            "sender", "sender_detail", "tags_detail", "attachment_count",
            "recipient_names", "recipient_count", "read_count",
            "my_read_at", "my_archived_at", "in_reply_to",
        ]

    def get_attachment_count(self, obj) -> int:
        return obj.attachments.count()

    def get_preview(self, obj) -> str:
        return (obj.body or "")[:160]

    def get_recipient_names(self, obj) -> list[str]:
        return [
            r.user.display_name_fa or r.user.get_username()
            for r in obj.recipients.all()[:6]
        ]


class LetterDetailSerializer(LetterListSerializer):
    recipients = LetterRecipientSerializer(many=True, read_only=True)
    actions = LetterActionSerializer(many=True, read_only=True)
    attachments = LetterAttachmentSerializer(many=True, read_only=True)
    in_reply_to_detail = serializers.SerializerMethodField()

    class Meta(LetterListSerializer.Meta):
        fields = LetterListSerializer.Meta.fields + [
            "body", "recipients", "actions", "attachments", "in_reply_to_detail",
        ]

    def get_in_reply_to_detail(self, obj):
        if not obj.in_reply_to:
            return None
        parent = obj.in_reply_to
        return {"id": parent.id, "number": parent.number, "subject": parent.subject}


class LetterWriteSerializer(serializers.ModelSerializer):
    """
    Compose or edit a draft.

    Recipients arrive as two id lists rather than nested objects: the form is
    two pickers, and asking the client to build `[{user, kind}]` would put the
    شکل of the join table into the UI for no gain.
    """

    to = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    cc = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    attachments = LetterAttachmentSerializer(many=True, required=False)
    send = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Letter
        fields = [
            "id", "subject", "body", "tags", "in_reply_to",
            "to", "cc", "attachments", "send",
        ]

    def validate(self, attrs):
        sending = attrs.get("send")
        # Only checked on send. A draft with no recipient yet is a normal
        # half-written letter, and refusing to save it loses the text.
        if sending:
            to = attrs.get("to") or []
            cc = attrs.get("cc") or []
            if not to and not cc:
                raise serializers.ValidationError(
                    {"to": "برای ارسال، دست‌کم یک گیرنده لازم است."}
                )
        return attrs

    @transaction.atomic
    def create(self, validated):
        to = validated.pop("to", [])
        cc = validated.pop("cc", [])
        files = validated.pop("attachments", [])
        send = validated.pop("send", False)
        tags = validated.pop("tags", [])

        letter = Letter.objects.create(
            sender=self.context["request"].user, **validated
        )
        letter.tags.set(tags)
        self._sync_recipients(letter, to, cc)
        self._add_files(letter, files)
        if send:
            letter.send()
        return letter

    @transaction.atomic
    def update(self, instance, validated):
        # A sent letter is a record of what was received; only a draft can
        # still change. The viewset refuses the request before it gets here,
        # but the rule belongs with the model's meaning, not only with the
        # route that happens to enforce it.
        if instance.is_sent:
            raise serializers.ValidationError(
                "نامه‌ی ارسال‌شده قابل ویرایش نیست. برای ادامه، پاسخ یا ارجاع بزنید."
            )
        to = validated.pop("to", None)
        cc = validated.pop("cc", None)
        files = validated.pop("attachments", None)
        send = validated.pop("send", False)
        tags = validated.pop("tags", None)

        for field, value in validated.items():
            setattr(instance, field, value)
        instance.save()

        if tags is not None:
            instance.tags.set(tags)
        if to is not None or cc is not None:
            self._sync_recipients(instance, to or [], cc or [])
        if files:
            self._add_files(instance, files)
        if send:
            instance.send()
        return instance

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _sync_recipients(letter: Letter, to: list[int], cc: list[int]) -> None:
        wanted = {uid: LetterRecipient.Kind.TO for uid in to}
        # A person named as both گیرنده and رونوشت is a گیرنده: the stronger
        # of the two, so nobody is demoted to cc by an accidental double pick.
        for uid in cc:
            wanted.setdefault(uid, LetterRecipient.Kind.CC)

        letter.recipients.exclude(user_id__in=wanted).delete()
        existing = {r.user_id: r for r in letter.recipients.all()}
        for uid, kind in wanted.items():
            row = existing.get(uid)
            if row is None:
                LetterRecipient.objects.create(letter=letter, user_id=uid, kind=kind)
            elif row.kind != kind:
                row.kind = kind
                row.save(update_fields=["kind"])

    def _add_files(self, letter: Letter, files: list[dict]) -> None:
        user = self.context["request"].user
        for f in files:
            LetterAttachment.objects.create(letter=letter, uploaded_by=user, **f)
