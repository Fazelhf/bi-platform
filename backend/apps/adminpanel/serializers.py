"""Serializers for the Admin Panel API."""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import DEPT_LABEL
from apps.adminpanel.models import (
    AdminFile,
    Announcement,
    ApiToken,
    AppRole,
    BackupRecord,
    Broadcast,
    ContentCategory,
    ContentTag,
    ContentTemplate,
    FeatureFlag,
    Folder,
    IPRule,
    LoginEvent,
    PasswordPolicy,
    RecycleBin,
    ScheduledReport,
    StaticPage,
    SystemConfig,
    Team,
    TeamMembership,
    UserRoleAssignment,
    UserSecurity,
)

ROLE_LABEL = {
    "admin": "ادمین سیستم", "executive": "مدیرعامل", "manager": "مدیر بخش",
    "operator": "اپراتور", "viewer": "بیننده",
}


# ==========================================================================
# Roles & permissions
# ==========================================================================
class AppRoleSerializer(serializers.ModelSerializer):
    # Reads AppRole.user_count (a property) — deliberately not an annotation,
    # which would collide with the property name on the model.
    user_count = serializers.IntegerField(read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = AppRole
        fields = [
            "id", "code", "name_fa", "description", "permissions", "color",
            "is_system", "is_active", "user_count", "created_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["is_system", "created_at", "updated_at"]

    def validate_permissions(self, value):
        from apps.adminpanel.permissions import ALL_PERMISSIONS

        if not isinstance(value, list):
            raise serializers.ValidationError("فهرست دسترسی‌ها باید آرایه باشد.")
        unknown = [c for c in value if c not in ALL_PERMISSIONS]
        if unknown:
            raise serializers.ValidationError(
                f"دسترسی ناشناخته: {'، '.join(unknown)}"
            )
        return value


class RoleAssignmentSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name_fa", read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = UserRoleAssignment
        fields = ["id", "user", "user_name", "role", "role_code", "role_name", "granted_at"]

    def get_user_name(self, obj) -> str:
        return obj.user.display_name_fa or obj.user.username


# ==========================================================================
# Users
# ==========================================================================
class AdminUserSerializer(serializers.ModelSerializer):
    """Full user record for the panel's user table and edit drawer."""

    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True,
        style={"input_type": "password"},
    )
    name = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()
    department_label = serializers.SerializerMethodField()
    is_online = serializers.BooleanField(read_only=True)
    is_admin_panel_user = serializers.BooleanField(read_only=True)
    admin_role_ids = serializers.SerializerMethodField()
    admin_role_names = serializers.SerializerMethodField()
    team_ids = serializers.SerializerMethodField()
    team_names = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    locked_until = serializers.SerializerMethodField()
    must_change_password = serializers.SerializerMethodField()
    twofa_enabled = serializers.SerializerMethodField()
    last_login_ip = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "name", "display_name_fa", "job_title_fa", "email",
            "phone", "role", "role_label", "department", "department_label",
            "is_active", "is_staff", "is_superuser", "admin_access",
            "is_admin_panel_user", "avatar_color", "avatar_image",
            "last_login", "last_seen", "is_online", "date_joined", "password",
            "admin_role_ids", "admin_role_names", "team_ids", "team_names",
            "is_locked", "locked_until", "must_change_password", "twofa_enabled",
            "last_login_ip",
        ]
        read_only_fields = [
            "is_superuser", "last_login", "last_seen", "date_joined", "is_staff",
        ]

    # -- derived --------------------------------------------------------
    def get_name(self, obj) -> str:
        return obj.display_name_fa or obj.username

    def get_role_label(self, obj) -> str:
        return ROLE_LABEL.get(obj.role, obj.role)

    def get_department_label(self, obj) -> str:
        return DEPT_LABEL.MAP.get(obj.department, obj.department or "—")

    def get_admin_role_ids(self, obj) -> list[int]:
        return [a.role_id for a in obj.admin_roles.all()]

    def get_admin_role_names(self, obj) -> list[str]:
        return [a.role.name_fa for a in obj.admin_roles.all()]

    def get_team_ids(self, obj) -> list[int]:
        return [m.team_id for m in obj.team_memberships.all()]

    def get_team_names(self, obj) -> list[str]:
        return [m.team.name_fa for m in obj.team_memberships.all()]

    def _security(self, obj):
        return getattr(obj, "security", None)

    def get_is_locked(self, obj) -> bool:
        s = self._security(obj)
        return bool(s and s.is_currently_locked)

    def get_locked_until(self, obj):
        s = self._security(obj)
        return s.locked_until if s else None

    def get_must_change_password(self, obj) -> bool:
        s = self._security(obj)
        return bool(s and s.must_change_password)

    def get_twofa_enabled(self, obj) -> bool:
        s = self._security(obj)
        return bool(s and s.twofa_enabled)

    def get_last_login_ip(self, obj) -> str | None:
        event = LoginEvent.objects.filter(user=obj, success=True).first()
        return event.ip_address if event else None

    # -- write ----------------------------------------------------------
    def validate_password(self, value):
        if not value:
            return value
        errors = PasswordPolicy.get().validate(value)
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            errors.extend(exc.messages)
        if errors:
            raise serializers.ValidationError(errors)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", "")
        if not password:
            raise serializers.ValidationError({"password": "رمز عبور الزامی است."})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        UserSecurity.objects.create(user=user)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        if password:
            from django.utils import timezone

            state = UserSecurity.get(instance)
            state.password_changed_at = timezone.now()
            state.must_change_password = False
            state.save(update_fields=[
                "password_changed_at", "must_change_password", "updated_at",
            ])
        return instance


class UserBriefSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "name", "role", "department", "is_active"]

    def get_name(self, obj) -> str:
        return obj.display_name_fa or obj.username


# ==========================================================================
# Teams
# ==========================================================================
class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True)
    manager_name = serializers.SerializerMethodField()
    parent_name = serializers.CharField(source="parent.name_fa", read_only=True)
    department_label = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id", "code", "name_fa", "description", "department",
            "department_label", "manager", "manager_name", "parent",
            "parent_name", "is_active", "member_count", "members", "created_at",
        ]

    def get_manager_name(self, obj) -> str:
        return str(obj.manager) if obj.manager else ""

    def get_department_label(self, obj) -> str:
        return DEPT_LABEL.MAP.get(obj.department, obj.department or "—")

    def get_members(self, obj) -> list[dict]:
        return [
            {
                "id": m.id, "user_id": m.user_id, "is_lead": m.is_lead,
                "name": m.user.display_name_fa or m.user.username,
                "username": m.user.username,
            }
            for m in obj.memberships.select_related("user")
        ]

    def validate(self, attrs):
        parent = attrs.get("parent")
        if parent and self.instance:
            node = parent
            while node:
                if node.pk == self.instance.pk:
                    raise serializers.ValidationError(
                        {"parent": "چرخه در سلسله‌مراتب تیم مجاز نیست."}
                    )
                node = node.parent
        return attrs


class TeamMembershipSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    team_name = serializers.CharField(source="team.name_fa", read_only=True)

    class Meta:
        model = TeamMembership
        fields = ["id", "user", "user_name", "team", "team_name", "is_lead", "joined_at"]

    def get_user_name(self, obj) -> str:
        return obj.user.display_name_fa or obj.user.username


# ==========================================================================
# Data management
# ==========================================================================
class RecycleBinSerializer(serializers.ModelSerializer):
    deleted_by_name = serializers.SerializerMethodField()
    restored_by_name = serializers.SerializerMethodField()
    model_label_fa = serializers.SerializerMethodField()
    is_restored = serializers.BooleanField(read_only=True)

    class Meta:
        model = RecycleBin
        fields = [
            "id", "model_label", "model_label_fa", "object_id", "object_repr",
            "payload", "deleted_by", "deleted_by_name", "deleted_at",
            "restored_at", "restored_by_name", "is_restored", "note",
        ]

    def get_deleted_by_name(self, obj) -> str:
        return str(obj.deleted_by) if obj.deleted_by else "—"

    def get_restored_by_name(self, obj) -> str:
        return str(obj.restored_by) if obj.restored_by else ""

    def get_model_label_fa(self, obj) -> str:
        from apps.adminpanel.services.softdelete import DELETABLE_MODELS

        return DELETABLE_MODELS.get(obj.model_label, obj.model_label)


# ==========================================================================
# System
# ==========================================================================
class SystemConfigSerializer(serializers.ModelSerializer):
    typed = serializers.SerializerMethodField()
    updated_by_name = serializers.CharField(source="updated_by.username", read_only=True)

    class Meta:
        model = SystemConfig
        fields = [
            "id", "key", "label_fa", "category", "value", "typed", "value_type",
            "description", "is_secret", "updated_by_name", "updated_at",
        ]
        read_only_fields = ["key", "value_type", "category", "label_fa"]

    def get_typed(self, obj):
        return "••••••••" if obj.is_secret and obj.value else obj.typed_value()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_secret and instance.value:
            data["value"] = "••••••••"
        return data


class FeatureFlagSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source="updated_by.username", read_only=True)

    class Meta:
        model = FeatureFlag
        fields = [
            "id", "key", "name_fa", "description", "is_enabled", "roles",
            "updated_by_name", "updated_at",
        ]


# ==========================================================================
# Security
# ==========================================================================
class LoginEventSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    reason_fa = serializers.SerializerMethodField()

    REASONS = {
        "": "—",
        "bad_password": "نام کاربری یا رمز اشتباه",
        "locked": "حساب قفل بود",
        "locked_out": "قفل شدن پس از تلاش‌های ناموفق",
        "ip_blocked": "IP مسدود",
        "ip_not_whitelisted": "IP خارج از فهرست مجاز",
    }

    class Meta:
        model = LoginEvent
        fields = [
            "id", "user", "name", "username_attempted", "success", "reason",
            "reason_fa", "ip_address", "user_agent", "created_at",
        ]

    def get_name(self, obj) -> str:
        return str(obj.user) if obj.user else obj.username_attempted

    def get_reason_fa(self, obj) -> str:
        return self.REASONS.get(obj.reason, obj.reason)


class PasswordPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PasswordPolicy
        exclude = ["singleton", "created_at"]


class IPRuleSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = IPRule
        fields = [
            "id", "mode", "cidr", "note", "is_active",
            "created_by_name", "created_at",
        ]

    def validate_cidr(self, value):
        import ipaddress

        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise serializers.ValidationError(
                "آدرس معتبر نیست. نمونه: 192.168.1.10 یا 10.0.0.0/8"
            )
        return value


class ApiTokenSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiToken
        fields = [
            "id", "name", "user", "user_name", "prefix", "scopes",
            "expires_at", "last_used_at", "is_active", "is_expired", "created_at",
        ]
        read_only_fields = ["prefix", "last_used_at"]

    def get_user_name(self, obj) -> str:
        return str(obj.user)


# ==========================================================================
# Notifications
# ==========================================================================
class BroadcastSerializer(serializers.ModelSerializer):
    sent_by_name = serializers.SerializerMethodField()
    audience_label = serializers.SerializerMethodField()

    class Meta:
        model = Broadcast
        fields = [
            "id", "title", "body", "level", "audience", "audience_label",
            "audience_value", "send_email", "recipient_count",
            "sent_by_name", "created_at",
        ]
        read_only_fields = ["recipient_count"]

    def get_sent_by_name(self, obj) -> str:
        return str(obj.sent_by) if obj.sent_by else "سیستم"

    def get_audience_label(self, obj) -> str:
        return obj.get_audience_display()


# ==========================================================================
# Files
# ==========================================================================
class FolderSerializer(serializers.ModelSerializer):
    path = serializers.CharField(read_only=True)
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = ["id", "name", "parent", "path", "file_count", "created_at"]

    def get_file_count(self, obj) -> int:
        return obj.files.filter(is_current=True).count()


class AdminFileSerializer(serializers.ModelSerializer):
    """`content` is write-only: listing thousands of data-URLs would be huge."""

    uploaded_by_name = serializers.SerializerMethodField()
    folder_path = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()

    MAX_BYTES = 4 * 1024 * 1024  # 4 MB of base64 payload

    class Meta:
        model = AdminFile
        fields = [
            "id", "name", "folder", "folder_path", "content", "mime",
            "size_bytes", "visibility", "version", "version_count", "is_current",
            "uploaded_by_name", "created_at",
        ]
        read_only_fields = ["size_bytes", "version", "is_current"]
        extra_kwargs = {"content": {"write_only": True}}

    def get_uploaded_by_name(self, obj) -> str:
        return str(obj.uploaded_by) if obj.uploaded_by else "—"

    def get_folder_path(self, obj) -> str:
        return obj.folder.path if obj.folder else "/"

    def get_version_count(self, obj) -> int:
        return obj.versions.count() + 1

    def validate_content(self, value):
        if value and not value.startswith("data:"):
            raise serializers.ValidationError("محتوای فایل باید data-URL باشد.")
        if len(value or "") > self.MAX_BYTES:
            raise serializers.ValidationError(
                f"حجم فایل بیش از حد مجاز است (حداکثر {self.MAX_BYTES // 1024 // 1024} مگابایت)."
            )
        return value


# ==========================================================================
# Reports
# ==========================================================================
class ScheduledReportSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    frequency_label = serializers.CharField(source="get_frequency_display", read_only=True)

    class Meta:
        model = ScheduledReport
        fields = [
            "id", "name", "kind", "kind_label", "fmt", "params", "frequency",
            "frequency_label", "recipients", "is_active", "last_run_at",
            "last_run_rows", "created_by_name", "created_at",
        ]
        read_only_fields = ["last_run_at", "last_run_rows"]


# ==========================================================================
# Database
# ==========================================================================
class BackupRecordSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BackupRecord
        fields = [
            "id", "filename", "size_bytes", "scope", "note",
            "created_by_name", "created_at", "restored_at",
        ]
        read_only_fields = ["filename", "size_bytes", "restored_at"]

    def get_created_by_name(self, obj) -> str:
        return str(obj.created_by) if obj.created_by else "—"


# ==========================================================================
# Content
# ==========================================================================
class ContentCategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.name", read_only=True)

    class Meta:
        model = ContentCategory
        fields = [
            "id", "name", "slug", "parent", "parent_name",
            "description", "is_active", "created_at",
        ]


class ContentTagSerializer(serializers.ModelSerializer):
    usage = serializers.SerializerMethodField()

    class Meta:
        model = ContentTag
        fields = ["id", "name", "color", "usage", "created_at"]

    def get_usage(self, obj) -> int:
        return obj.announcements.count()


class ContentTemplateSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = ContentTemplate
        fields = [
            "id", "name", "kind", "kind_label", "subject", "body",
            "variables", "is_active", "updated_at",
        ]


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    is_live = serializers.BooleanField(read_only=True)
    tag_names = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = [
            "id", "title", "body", "level", "is_published", "is_live",
            "starts_at", "ends_at", "category", "tags", "tag_names",
            "created_by_name", "created_at",
        ]

    def get_created_by_name(self, obj) -> str:
        return str(obj.created_by) if obj.created_by else "—"

    def get_tag_names(self, obj) -> list[str]:
        return [t.name for t in obj.tags.all()]


class StaticPageSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source="updated_by.username", read_only=True)

    class Meta:
        model = StaticPage
        fields = [
            "id", "slug", "title", "body", "is_published",
            "updated_by_name", "updated_at",
        ]
