from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.hr.models import OrgUnit, Position
from apps.hr.services.names import clean
from apps.sales.models import DimEmployee


class OrgUnitSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    sales_channel_label = serializers.CharField(
        source="get_sales_channel_display", read_only=True
    )

    class Meta:
        model = OrgUnit
        fields = [
            "id", "name_fa", "kind", "kind_label", "parent", "color", "sort_order",
            "sales_channel", "sales_channel_label", "is_active",
        ]

    def validate_parent(self, parent):
        # A unit cannot be moved under itself or anything below it.
        node = parent
        while node is not None and self.instance is not None:
            if node.pk == self.instance.pk:
                raise serializers.ValidationError("واحد نمی‌تواند زیرمجموعه خودش باشد.")
            node = node.parent
        return parent


class PositionSerializer(serializers.ModelSerializer):
    holder_name = serializers.CharField(source="holder.full_name_fa", read_only=True, default="")
    unit_name = serializers.CharField(source="unit.name_fa", read_only=True)

    class Meta:
        model = Position
        fields = [
            "id", "unit", "unit_name", "title_fa", "holder", "holder_name",
            "is_head", "on_sales_sheet", "sort_order", "note",
        ]

    def validate_holder(self, holder):
        if holder is not None and not holder.is_active:
            raise serializers.ValidationError(
                "این فرد بایگانی شده است؛ اول او را از بایگانی خارج کنید."
            )
        return holder


class PersonSerializer(serializers.ModelSerializer):
    """One person, with where they sit and what the rest of the site has on them."""

    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), allow_null=True, required=False
    )
    username = serializers.CharField(source="user.username", read_only=True, default="")
    account_name = serializers.SerializerMethodField()
    account_active = serializers.BooleanField(source="user.is_active", read_only=True, default=False)
    account_role = serializers.SerializerMethodField()
    account_last_login = serializers.DateTimeField(source="user.last_login", read_only=True, default=None)
    positions = serializers.SerializerMethodField()
    channels = serializers.SerializerMethodField()
    sales_records = serializers.SerializerMethodField()

    class Meta:
        model = DimEmployee
        fields = [
            "id", "code", "full_name_fa", "mobile", "hired_on", "note",
            "is_active", "archived_at", "archive_note",
            "user", "username", "account_name", "account_active", "account_role",
            "account_last_login", "positions", "channels", "sales_records",
        ]
        read_only_fields = ["code", "is_active", "archived_at", "archive_note"]

    def validate_full_name_fa(self, value):
        value = clean(value)
        if not value:
            raise serializers.ValidationError("نام الزامی است.")
        return value

    def validate_user(self, user):
        if user is None:
            return user
        taken = DimEmployee.objects.filter(user=user)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError(
                f"این حساب به «{taken.first().full_name_fa}» وصل است."
            )
        return user

    #: The model's role labels are English; this page speaks Persian.
    ROLE_FA = {
        "admin": "ادمین", "executive": "مدیریت", "manager": "مدیر بخش",
        "operator": "کارشناس", "viewer": "فقط مشاهده",
    }

    def get_account_role(self, obj) -> str:
        if not obj.user_id:
            return ""
        return "ادمین ارشد" if obj.user.is_superuser else self.ROLE_FA.get(obj.user.role, obj.user.role)

    def get_account_name(self, obj) -> str:
        return str(obj.user) if obj.user_id else ""

    def get_positions(self, obj) -> list[dict]:
        return [
            {"id": p.id, "title": p.title_fa, "unit": p.unit.name_fa, "unit_id": p.unit_id}
            for p in obj.positions.all()
        ]

    def get_channels(self, obj) -> list[str]:
        return [m.get_channel_display() for m in obj.memberships.all() if m.is_active]

    def get_sales_records(self, obj) -> int:
        return getattr(obj, "sales_n", 0)
