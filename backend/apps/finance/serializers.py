from rest_framework import serializers

from apps.finance.models import (
    BankAccount,
    CashCategory,
    CashMovement,
    CreditLine,
    FinanceSetting,
)


class BankAccountSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    label = serializers.CharField(read_only=True)
    movement_count = serializers.SerializerMethodField()

    class Meta:
        model = BankAccount
        fields = [
            "id", "title", "label", "bank_name", "account_no", "iban",
            "kind", "kind_label", "opening_balance_rial", "color",
            "sort_order", "is_active", "note", "movement_count", "created_at",
        ]

    def get_movement_count(self, obj) -> int:
        return obj.movements.count()


class CashCategorySerializer(serializers.ModelSerializer):
    direction_label = serializers.CharField(
        source="get_direction_display", read_only=True
    )

    class Meta:
        model = CashCategory
        fields = [
            "id", "code", "name_fa", "direction", "direction_label",
            "expects_credit_line", "sort_order", "is_active", "note",
        ]


class CreditLineSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    balance_rial = serializers.SerializerMethodField()
    received_rial = serializers.SerializerMethodField()
    paid_rial = serializers.SerializerMethodField()
    movement_count = serializers.SerializerMethodField()

    class Meta:
        model = CreditLine
        fields = [
            "id", "kind", "kind_label", "title", "counterparty",
            "principal_rial", "rate_pct", "opened_on", "due_on",
            "installments", "status", "status_label", "note",
            "balance_rial", "received_rial", "paid_rial", "movement_count",
            "created_at",
        ]

    def get_balance_rial(self, obj) -> str:
        return str(obj.balance_rial)

    def get_received_rial(self, obj) -> str:
        return str(obj.totals()["received"])

    def get_paid_rial(self, obj) -> str:
        return str(obj.totals()["paid"])

    def get_movement_count(self, obj) -> int:
        return obj.movements.count()

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        principal = attrs.get(
            "principal_rial", getattr(self.instance, "principal_rial", 0)
        )
        # A partner current account has no agreed ceiling; a facility or a
        # loan without one is almost certainly a mistake being saved.
        if kind in {CreditLine.Kind.FACILITY, CreditLine.Kind.LENDING} and not principal:
            raise serializers.ValidationError({
                "principal_rial": "برای تسهیلات و قرض، مبلغ اصل الزامی است."
            })
        return attrs


class CashMovementSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name_fa", read_only=True)
    period_label = serializers.CharField(source="period.label", read_only=True)
    credit_line_title = serializers.SerializerMethodField()
    account_label = serializers.SerializerMethodField()
    # Both FKs sit in the unique-together, and DRF makes every field in such a
    # constraint required — which would refuse a movement with no facility
    # attached, or (before accounts existed) any movement at all.
    account = serializers.PrimaryKeyRelatedField(
        queryset=BankAccount.objects.all(),
        required=False, allow_null=True, default=None,
    )
    # `credit_line` is part of the unique-together, and DRF makes every field
    # in such a constraint required — which would refuse an ordinary movement
    # that belongs to no facility or loan. An explicit default keeps the
    # constraint working while leaving the field optional, as the model has it.
    credit_line = serializers.PrimaryKeyRelatedField(
        queryset=CreditLine.objects.all(),
        required=False, allow_null=True, default=None,
    )

    class Meta:
        model = CashMovement
        fields = [
            "id", "period", "period_label", "direction", "category",
            "category_name", "account", "account_label", "amount_rial",
            "credit_line", "credit_line_title", "note", "status", "created_at",
        ]
        read_only_fields = ["status"]

    def get_credit_line_title(self, obj) -> str:
        return str(obj.credit_line) if obj.credit_line else ""

    def get_account_label(self, obj) -> str:
        return obj.account.label if obj.account else ""

    def validate(self, attrs):
        category = attrs.get("category", getattr(self.instance, "category", None))
        direction = attrs.get("direction", getattr(self.instance, "direction", None))
        if category and direction and not category.allows(direction):
            raise serializers.ValidationError({
                "direction": f"دسته «{category.name_fa}» برای این جهت مجاز نیست."
            })
        return attrs


class FinanceSettingSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)
    #: Storage is always Rial; the unit only scales what is displayed.
    unit_divisor = serializers.SerializerMethodField()

    class Meta:
        model = FinanceSetting
        fields = [
            "opening_balance_rial", "opening_on", "low_balance_rial",
            "unit", "unit_label", "unit_divisor",
        ]

    def get_unit_divisor(self, obj) -> int:
        return 10 if obj.unit == "toman" else 1
