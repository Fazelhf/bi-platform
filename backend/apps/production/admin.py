from django.contrib import admin

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


@admin.register(FactProduction)
class FactProductionAdmin(admin.ModelAdmin):
    list_display = ("machine", "period", "active_shifts", "output_units", "waste_pct", "status")
    list_filter = ("status", "period", "machine")


@admin.register(DimMachine)
class DimMachineAdmin(admin.ModelAdmin):
    list_display = ("name_fa", "code", "kind", "is_active")
    list_filter = ("kind", "is_active")


admin.site.register([
    DimProduct, DimCostCategory, ProductionBenchmark,
    FactProductionCost, FactProductionRevenue,
    FactPrintColor, FactMaterialBalance,
])
