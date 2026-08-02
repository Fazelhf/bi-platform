from rest_framework import serializers

from apps.core.models import DimKPI, DimPeriod, FactKPI
from apps.sales.models import EmployeeChannel  # noqa: F401  (roster)
from apps.sales.models import (
    DimBank,
    DimCustomerGroup,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactCollection,
    FactSalesMonthly,
    FactSalesProvince,
)


class PeriodSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)
    days = serializers.IntegerField(read_only=True)
    has_data = serializers.SerializerMethodField()

    class Meta:
        model = DimPeriod
        fields = [
            "id", "jalali_year", "jalali_month", "label", "has_data",
            "kind", "seq", "code", "start_date", "end_date", "days", "parent",
        ]

    def get_has_data(self, obj) -> bool:
        # A period "has data" if any computed KPI exists for it — this drives
        # the dashboard's default selection (latest filled month).
        return FactKPI.objects.filter(period=obj).exists()


class TeamSerializer(serializers.ModelSerializer):
    # So the UI can say "۳ عضو" and refuse to delete a team in use.
    member_count = serializers.IntegerField(source="members.count", read_only=True)

    class Meta:
        model = DimTeam
        fields = ["id", "code", "name_fa", "name_en", "member_count"]
        extra_kwargs = {"code": {"required": False}}


class EmployeeSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name_fa", read_only=True)

    class Meta:
        model = DimEmployee
        fields = ["id", "code", "full_name_fa", "team", "team_name", "is_active"]


class ProvinceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimProvince
        fields = ["id", "code", "name_fa"]


class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimBank
        fields = ["id", "code", "name_fa", "kind"]


class SalesMonthlySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name_fa", read_only=True)
    period_label = serializers.CharField(source="period.label", read_only=True)

    class Meta:
        model = FactSalesMonthly
        fields = [
            "id", "period", "period_label", "employee", "employee_name", "channel",
            "revenue_rial", "invoice_count", "active_customers", "new_customers",
            "profit_rial", "cost_rial", "target_rial", "calls",
            # Team-only measures (0 for the other channels)
            "proforma_issued_rial", "proforma_cancelled_rial",
            # B2B-only measures (0 for the other channels)
            "quantity_ton", "collected_rial", "receivables_rial", "won_invoices_rial",
            "status", "updated_at",
        ]
        read_only_fields = ["status"]


class SalesProvinceSerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(source="province.name_fa", read_only=True)

    class Meta:
        model = FactSalesProvince
        fields = ["id", "period", "province", "province_name", "sales_rial", "target_rial"]


class CollectionSerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(source="bank.name_fa", read_only=True)

    class Meta:
        model = FactCollection
        fields = ["id", "period", "bank", "bank_name", "amount_rial"]


class KPIResultSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source="kpi.code", read_only=True)
    kpi_name_fa = serializers.CharField(source="kpi.name_fa", read_only=True)
    kpi_name_en = serializers.CharField(source="kpi.name_en", read_only=True)
    unit = serializers.CharField(source="kpi.unit", read_only=True)
    direction = serializers.CharField(source="kpi.direction", read_only=True)

    class Meta:
        model = FactKPI
        fields = [
            "id", "period", "kpi_code", "kpi_name_fa", "kpi_name_en",
            "unit", "direction", "scope", "scope_id", "scope_label", "channel",
            "actual", "target", "ideal", "deviation", "efficiency_pct",
        ]


class KPIDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimKPI
        fields = ["id", "code", "name_fa", "name_en", "domain", "unit", "direction", "formula_note"]


class RosterMemberSerializer(serializers.ModelSerializer):
    """
    One کارشناس on a department's roster, with enough context for the manager
    to decide whether to keep them: how much they have ever sold in this
    channel, how many periods they have filled in, and whether they can even
    log in.
    """

    employee_name = serializers.CharField(source="employee.full_name_fa", read_only=True)
    team = serializers.IntegerField(source="employee.team_id", read_only=True)
    team_name = serializers.CharField(source="employee.team.name_fa", read_only=True)
    has_login = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)

    # Attached by the view in one aggregate rather than queried per row.
    periods_filled = serializers.IntegerField(read_only=True, default=0)
    total_revenue = serializers.DecimalField(
        max_digits=20, decimal_places=0, read_only=True, default=0
    )
    last_period = serializers.CharField(read_only=True, default="")

    class Meta:
        model = EmployeeChannel
        fields = [
            "id", "employee", "employee_name", "channel", "channel_display",
            "team", "team_name", "has_login", "username",
            "is_active", "joined_at", "left_at", "note",
            "periods_filled", "total_revenue", "last_period",
        ]
        read_only_fields = ["employee"]

    def get_has_login(self, obj) -> bool:
        return bool(obj.employee.user_id)

    def get_username(self, obj) -> str:
        return obj.employee.user.username if obj.employee.user_id else ""


class CustomerGroupSerializer(serializers.ModelSerializer):
    """A customer segment, plus whether it can still be deleted outright."""

    has_data = serializers.SerializerMethodField()
    # Managers name groups, they do not invent slugs — one is derived on
    # create so the field never blocks them.
    code = serializers.SlugField(required=False)

    class Meta:
        model = DimCustomerGroup
        fields = ["id", "code", "name_fa", "sort_order", "is_active", "has_data"]

    def create(self, validated_data):
        import uuid

        validated_data.setdefault("code", f"grp-{uuid.uuid4().hex[:8]}")
        return super().create(validated_data)

    def get_has_data(self, obj) -> bool:
        from apps.sales.models import FactSalesByCustomerGroup

        return FactSalesByCustomerGroup.objects.filter(customer_group=obj).exists()

    def validate_name_fa(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("نام گروه الزامی است.")
        return name
