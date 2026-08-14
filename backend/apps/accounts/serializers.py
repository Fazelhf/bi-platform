from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import (
    Department,
    Message,
    MessageAttachment,
    Note,
    User,
)


class DEPT_LABEL:
    """
    Department labels, derived from the model's own choices.

    This used to be a hand-written copy, and adding مالی to the model left it
    behind: the label rendered as raw "finance" and the Admin Panel's dropdown
    — another hand-written copy — had no option for it at all, so no one could
    be made a finance manager through the interface. Deriving it means a new
    department appears everywhere the moment it exists.
    """

    MAP = {value: label for value, label in Department.choices} | {"": "—"}


class UserCardSerializer(serializers.ModelSerializer):
    """Compact user card for team lists, avatars, chat headers, popovers."""

    name = serializers.SerializerMethodField()
    is_online = serializers.BooleanField(read_only=True)
    department_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "name", "initials", "job_title_fa",
            "role", "department", "department_label", "avatar_color", "avatar_image",
            "is_online", "last_seen", "phone",
        ]

    def get_name(self, obj) -> str:
        return obj.display_name_fa or obj.username

    def get_department_label(self, obj) -> str:
        return DEPT_LABEL.MAP.get(obj.department, obj.department)


class NotePersonSerializer(serializers.ModelSerializer):
    """Just enough of a person to draw a chip on a note."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "avatar_color", "avatar_image"]

    def get_name(self, obj) -> str:
        return obj.display_name_fa or obj.get_username()


class NoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name_fa", read_only=True)
    people_detail = NotePersonSerializer(source="people", many=True, read_only=True)
    is_pinned = serializers.BooleanField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)
    #: The palette the client offers. Served rather than hard-coded twice.
    palette = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = ["id", "author", "author_name", "subject", "title", "body",
                  "color", "pinned_at", "archived_at", "remind_on",
                  "people", "people_detail", "is_pinned", "is_archived",
                  "palette", "created_at", "updated_at"]
        read_only_fields = ["author", "pinned_at", "archived_at"]

    def get_palette(self, _obj) -> list:
        return Note.COLORS


class MessageAttachmentSerializer(serializers.ModelSerializer):
    is_image = serializers.BooleanField(read_only=True)

    class Meta:
        model = MessageAttachment
        fields = ["id", "name", "mime", "size_bytes", "is_image", "content"]
        # The bytes are fetched one at a time; a thread of forty messages
        # must not carry forty files.
        extra_kwargs = {"content": {"write_only": True}}


class MessageSerializer(serializers.ModelSerializer):
    """
    A direct message, in the same shape a group message has.

    The two halves of chat were drifting: groups grew replies, files and
    reactions while direct threads stayed plain text, so the same UI had to
    behave differently depending on who you were talking to. One shape means
    one set of components.
    """

    attachments = MessageAttachmentSerializer(many=True, required=False)
    reply_to_detail = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    sender_detail = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "sender", "sender_detail", "recipient", "body",
            "reply_to", "reply_to_detail", "attachments", "reactions",
            "is_read", "edited_at", "created_at",
        ]
        read_only_fields = ["sender", "is_read"]

    def get_sender_detail(self, obj) -> dict:
        return {
            "id": obj.sender_id,
            "name": obj.sender.display_name_fa or obj.sender.get_username(),
            "avatar_color": obj.sender.avatar_color,
            "avatar_image": obj.sender.avatar_image,
        }

    def get_reply_to_detail(self, obj):
        parent = obj.reply_to
        if not parent:
            return None
        return {
            "id": parent.id,
            "body": parent.body[:120],
            "sender_name": (
                parent.sender.display_name_fa or parent.sender.get_username()
            ),
        }

    def get_reactions(self, obj) -> list:
        me = getattr(self.context.get("request"), "user", None)
        out: dict = {}
        for r in obj.reactions.all():
            row = out.setdefault(
                r.emoji, {"emoji": r.emoji, "count": 0, "mine": False, "who": []}
            )
            row["count"] += 1
            row["who"].append(r.user_id)
            if me and r.user_id == me.pk:
                row["mine"] = True
        return list(out.values())


class UserSerializer(serializers.ModelSerializer):
    """Admin-panel user management. Password is write-only and optional on
    update (leave blank to keep). Superuser flag is read-only via API."""

    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id", "username", "display_name_fa", "role", "department",
            "is_active", "is_superuser", "last_login", "password",
            "phone", "two_factor_enabled",
        ]
        read_only_fields = ["is_superuser", "last_login"]

    def validate_two_factor_enabled(self, value):
        """An admin may switch two-step login **off** — that is the "lost the
        phone" support call — but never on. Turning it on for someone else
        would assert that a number is theirs without them ever proving it, and
        a wrong number here locks the account out for good. Users enrol
        themselves at /api/auth/2fa/start/, which sends a code to the number
        and only enables once that code comes back."""
        if value and not (self.instance and self.instance.two_factor_enabled):
            raise serializers.ValidationError(
                "ورود دو مرحله‌ای را باید خودِ کاربر از «امنیت حساب» فعال کند."
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", "")
        if not password:
            raise serializers.ValidationError({"password": "رمز عبور الزامی است."})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        # Switching 2FA off must also drop the enrolment timestamp and kill any
        # code still in flight, or the user's own security page keeps showing
        # an enrolment that no longer guards anything.
        if validated_data.get("two_factor_enabled") is False:
            validated_data["two_factor_enabled_at"] = None
            instance.otp_challenges.filter(consumed_at__isnull=True).update(
                consumed_at=timezone.now()
            )
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
