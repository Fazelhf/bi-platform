from rest_framework import serializers

from apps.core.models import DimKPI, DimPeriod, FactKPI
from apps.sales.models import (
    DimBank,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactCollection,
    FactSalesMonthly,
    FactSalesProvince,
)


class PeriodSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)
    has_data = serializers.SerializerMethodField()

    class Meta:
        model = DimPeriod
        fields = ["id", "jalali_year", "jalali_month", "label", "has_data"]

    def get_has_data(self, obj) -> bool:
        # A period "has data" if any computed KPI exists for it — this drives
        # the dashboard's default selection (latest filled month).
        return FactKPI.objects.filter(period=obj).exists()


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimTeam
        fields = ["id", "code", "name_fa", "name_en"]


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
