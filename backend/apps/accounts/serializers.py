from rest_framework import serializers

from apps.accounts.models import Message, Note, User


class DEPT_LABEL:
    MAP = {
        "": "—",
        "production": "تولید",
        "sales_org": "فروش بانکی",
        "sales_team": "فروش همکار",
        "sales_b2b": "فروش B2B",
    }


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


class NoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name_fa", read_only=True)

    class Meta:
        model = Note
        fields = ["id", "author", "author_name", "subject", "title", "body",
                  "created_at", "updated_at"]
        read_only_fields = ["author"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "sender", "recipient", "body", "is_read", "created_at"]
        read_only_fields = ["sender", "is_read"]


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
        ]
        read_only_fields = ["is_superuser", "last_login"]

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
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
