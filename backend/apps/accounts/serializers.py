from rest_framework import serializers

from apps.accounts.models import User


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
