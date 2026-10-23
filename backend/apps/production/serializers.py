from rest_framework import serializers

from apps.production.models import (
    DimCostCategory,
    DimMachine,
    DimProduct,
    FactMaterialBalance,
    FactPrintColor,
    FactProduction,
    FactProductionCost,
    FactProductionRevenue,
    ProductionBenchmark,
)


class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimMachine
        fields = ["id", "code", "name_fa", "kind", "is_active", "sort_order"]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimProduct
        fields = ["id", "code", "name_fa", "unit", "piece_rate_rial", "index_factor"]


class CostCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DimCostCategory
        fields = ["id", "code", "name_fa", "is_direct"]


class BenchmarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionBenchmark
        fields = [
            "id", "period", "ideal_output_per_shift", "monthly_shift_capacity",
            "hours_per_shift", "full_system_staff", "total_headcount",
            "headcount_day", "headcount_night",
            "ideal_shift_count", "days_in_month",
        ]


class ProductionSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source="machine.name_fa", read_only=True)
    machine_kind = serializers.CharField(source="machine.kind", read_only=True)
    period_label = serializers.CharField(source="period.label", read_only=True)
    total_downtime_shifts = serializers.DecimalField(
        max_digits=8, decimal_places=2, read_only=True
    )
    total_actual_output = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = FactProduction
        fields = [
            "id", "period", "period_label", "machine", "machine_name", "machine_kind",
            "shift",
            "active_shifts", "output_units",
            "actual_journal", "actual_pos", "actual_receipt", "total_actual_output",
            "waste_pct", "repair_count",
            "downtime_breakdown_shifts", "downtime_sizechange_shifts",
            "downtime_nowork_shifts", "total_downtime_shifts",
            "status", "updated_at",
        ]
        read_only_fields = ["status"]


class ProductionCostSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name_fa", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)

    class Meta:
        model = FactProductionCost
        fields = ["id", "period", "category", "category_code", "category_name", "amount_rial", "description", "shift"]


class ProductionRevenueSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name_fa", read_only=True)
    amount_rial = serializers.DecimalField(
        max_digits=24, decimal_places=0, read_only=True
    )

    class Meta:
        model = FactProductionRevenue
        fields = [
            "id", "period", "product", "product_name",
            "quantity", "piece_rate_rial", "amount_rial", "shift",
        ]


class PrintColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = FactPrintColor
        fields = ["id", "period", "color_count", "shift", "area_sqm"]


class MaterialBalanceSerializer(serializers.ModelSerializer):
    waste_weight = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = FactMaterialBalance
        fields = ["id", "period", "stream", "input_weight", "output_weight", "waste_weight"]
