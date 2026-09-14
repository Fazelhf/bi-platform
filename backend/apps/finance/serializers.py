from rest_framework import serializers

from apps.finance.models import (
    BankAccount,
    Budget,
    BudgetLine,
    BudgetStatus,
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
    # The tree, flattened for a client that only needs to indent and to know
    # what it may offer as a column.
    is_leaf = serializers.BooleanField(read_only=True)
    needs_credit_line = serializers.BooleanField(read_only=True)
    parent_code = serializers.CharField(
        source="parent.code", read_only=True, default=""
    )

    class Meta:
        model = CashCategory
        fields = [
            "id", "code", "name_fa", "parent", "parent_code", "direction",
            "direction_label", "expects_credit_line", "needs_credit_line",
            "is_leaf", "sort_order", "is_active", "note",
        ]
        # Someone defining a budget by hand types «هزینهٔ تبلیغات», not a slug.
        extra_kwargs = {
            "code": {"required": False, "allow_blank": True},
            "direction": {"required": False},
            "sort_order": {"required": False},
        }

    def validate(self, attrs):
        """
        Keep the tree honest when the finance team grows it by hand.

        The one mistake that matters: hanging a child under a category that
        already holds figures. Those figures would then sit on a parent — the
        one place the tree forbids them — and every report above it would
        count them alongside the children, silently.
        """
        instance = self.instance
        parent = attrs.get("parent", instance.parent if instance else None)

        if parent is not None:
            if instance is not None and parent.pk == instance.pk:
                raise serializers.ValidationError({"parent": "دسته نمی‌تواند والد خودش باشد."})
            if parent.movements.exists():
                raise serializers.ValidationError({"parent": (
                    f"«{parent.name_fa}» خودش حرکت نقدینگی ثبت‌شده دارد و نمی‌تواند زیرمجموعه بگیرد."
                )})
            if parent.budget_lines.exists():
                raise serializers.ValidationError({"parent": (
                    f"«{parent.name_fa}» خودش قلم بودجه است و نمی‌تواند زیرمجموعه بگیرد."
                )})
            # A child left without a direction takes its group's.
            if "direction" not in attrs and instance is None:
                attrs["direction"] = parent.direction
            direction = attrs.get("direction", instance.direction if instance else None)
            if parent.direction != CashCategory.Allowed.BOTH and direction != parent.direction:
                raise serializers.ValidationError(
                    {"direction": "جهت این قلم با جهت گروهش نمی‌خواند."}
                )

        if instance is None:
            if not attrs.get("code"):
                attrs["code"] = _free_code(f"{parent.code}-" if parent else "custom-")
            if "sort_order" not in attrs:
                siblings = CashCategory.objects.filter(parent=parent)
                last = siblings.order_by("-sort_order").values_list("sort_order", flat=True).first()
                attrs["sort_order"] = (last or (parent.sort_order * 10 if parent else 90)) + 1
        return attrs


def _free_code(prefix: str) -> str:
    """The first unused `prefix-N` — codes are ids, not something anyone reads."""
    n = 1
    while CashCategory.objects.filter(code=f"{prefix}{n}").exists():
        n += 1
    return f"{prefix}{n}"


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


# --------------------------------------------------------------------------
# بودجه
# --------------------------------------------------------------------------

class BudgetSerializer(serializers.ModelSerializer):
    start_label = serializers.CharField(source="start_period.label", read_only=True)
    end_label = serializers.CharField(source="end_period.label", read_only=True)
    line_count = serializers.SerializerMethodField()
    month_count = serializers.SerializerMethodField()
    approved_count = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = [
            "id", "title", "jalali_year", "start_period", "start_label",
            "end_period", "end_label", "is_active", "note",
            "line_count", "month_count", "approved_count", "created_at",
        ]

    def get_line_count(self, obj) -> int:
        return obj.lines.filter(is_active=True).count()

    def get_month_count(self, obj) -> int:
        return obj.periods.count()

    def get_approved_count(self, obj) -> int:
        return obj.periods.filter(status=BudgetStatus.APPROVED).count()


class BudgetLineSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="__str__", read_only=True)
    category_name = serializers.CharField(source="category.name_fa", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    parent_name = serializers.CharField(
        source="category.parent.name_fa", read_only=True, default=""
    )
    counterparty = serializers.CharField(
        source="credit_line.counterparty", read_only=True, default=""
    )
    direction_label = serializers.CharField(
        source="get_direction_display", read_only=True
    )

    class Meta:
        model = BudgetLine
        fields = [
            "id", "budget", "category", "category_name", "category_code",
            "parent_name", "credit_line", "counterparty", "direction",
            "direction_label", "label", "sort_order", "is_active", "note",
        ]
        # The model's unique_together includes the nullable credit_line. DRF
        # turns that into «every field in it is required», which rejected
        # every line without a counterparty before its real rules could run —
        # and the database cannot enforce it either, since NULLs never
        # collide. Uniqueness is checked by hand in validate() instead.
        validators = []
        extra_kwargs = {"credit_line": {"required": False, "allow_null": True}}

    def validate(self, attrs):
        """
        Run the model's own rules — leaf-only, direction, counterparty — then
        refuse a duplicate line.

        DRF does not call `clean()`, and these are the invariants the whole
        module rests on, so they are enforced here rather than trusted to
        every caller.
        """
        merged = {**_as_dict(self.instance), **attrs}
        BudgetLine(**merged).full_clean(exclude=["budget"], validate_unique=False)

        duplicate = BudgetLine.objects.filter(
            budget=merged.get("budget"),
            category=merged.get("category"),
            credit_line=merged.get("credit_line"),
            direction=merged.get("direction"),
        )
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError(
                {"category": "این قلم با همین طرف‌حساب و جهت در این بودجه وجود دارد."}
            )
        return attrs


def _as_dict(instance) -> dict:
    if instance is None:
        return {}
    return {
        "budget": instance.budget,
        "category": instance.category,
        "credit_line": instance.credit_line,
        "direction": instance.direction,
        "sort_order": instance.sort_order,
        "is_active": instance.is_active,
        "note": instance.note,
    }
