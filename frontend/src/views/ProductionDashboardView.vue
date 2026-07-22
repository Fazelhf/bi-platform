<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { productionApi } from "@/api/production";
import type { KpiResult, Period, ProductionDashboard } from "@/types";
import ComparisonBar from "@/components/charts/ComparisonBar.vue";
import DonutChart from "@/components/charts/DonutChart.vue";
import StackedMachineBar from "@/components/charts/StackedMachineBar.vue";
import ProfitLossBar from "@/components/charts/ProfitLossBar.vue";
import BarChart from "@/components/BarChart.vue";
import { kpiValue, num, rial } from "@/utils/format";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ProductionDashboard | null>(null);
const loading = ref(false);

function kpi(code: string): KpiResult | undefined {
  return data.value?.kpis.find((k) => k.kpi_code === code);
}
const n = (v: string | number | null | undefined) => (v == null ? null : Number(v));

// Per-machine (cutting lines only) for the machine charts.
const cutting = computed(() => (data.value?.machines ?? []).filter((m) => m.machine__kind === "cutting"));
const machineNames = computed(() => cutting.value.map((m) => m.machine__name_fa));
const machineOutput = computed(() => cutting.value.map((m) => m.output_units));
const machineAvg = computed(() =>
  cutting.value.map((m) => (m.active_shifts ? Math.round(m.output_units / m.active_shifts) : 0)),
);
const days = computed(() => data.value?.days_in_month ?? 30);
const activeShifts = computed(() => cutting.value.map((m) => m.active_shifts));
const inactiveShifts = computed(() => cutting.value.map((m) => Math.max(0, days.value - m.active_shifts)));

// The 7-row KPI comparison table (واقعی/مطلوب/ایده‌آل/انحراف/بهره‌وری).
const KPI_ORDER = [
  "prod_productivity", "waste_rate", "line_stoppage_rate", "labor_productivity",
  "defect_free_rate", "cost_per_roll", "financial_return",
];
const kpiRows = computed(() =>
  KPI_ORDER.map((c) => kpi(c)).filter((k): k is KpiResult => !!k),
);

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await productionApi.dashboard(selectedPeriod.value);
  } finally {
    loading.value = false;
  }
}
onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = periods.value[0]?.id ?? null;
  await load();
});
watch(selectedPeriod, load);

function fmtCell(v: string | null, unit: string) {
  return v == null ? "—" : kpiValue(v, unit);
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold text-ink">داشبورد مدیریتی تولید</h2>
      <select v-model.number="selectedPeriod" class="bg-white border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </div>

    <div v-if="loading || !data" class="text-slate-400">در حال بارگذاری…</div>

    <template v-else>
      <!-- Financial summary cards (درآمد / هزینه / کارکرد) -->
      <div class="grid grid-cols-3 gap-4">
        <div class="bg-white rounded-card shadow-soft p-4 text-center">
          <p class="text-xs text-slate-400 mb-1">درآمد</p>
          <p class="text-xl font-bold ltr-nums text-accent-600">{{ rial(data.financials.revenue) }}</p>
        </div>
        <div class="bg-white rounded-card shadow-soft p-4 text-center">
          <p class="text-xs text-slate-400 mb-1">هزینه</p>
          <p class="text-xl font-bold ltr-nums text-pink-500">{{ rial(data.financials.cost) }}</p>
        </div>
        <div class="bg-white rounded-card shadow-soft p-4 text-center">
          <p class="text-xs text-slate-400 mb-1">کارکرد (سود)</p>
          <p class="text-xl font-bold ltr-nums" :class="data.financials.net >= 0 ? 'text-brand-600' : 'text-red-600'">
            {{ rial(data.financials.net) }}
          </p>
        </div>
      </div>

      <!-- Row 1: productivity, labour, efficiency donut, production per machine -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <ComparisonBar title="بهره‌وری تولید"
          :actual="n(kpi('prod_productivity')?.actual)" :target="n(kpi('prod_productivity')?.target)" :ideal="n(kpi('prod_productivity')?.ideal)" />
        <ComparisonBar title="بهره‌وری نیروی انسانی"
          :actual="n(kpi('labor_productivity')?.actual)" :target="n(kpi('labor_productivity')?.target)" :ideal="n(kpi('labor_productivity')?.ideal)" />
        <DonutChart title="درصد بهره‌وری" :value="n(kpi('prod_productivity')?.efficiency_pct)" />
        <BarChart title="بهره‌وری تولید (بر اساس خط)" :categories="machineNames" :values="machineOutput" color="#f472b6" />
      </div>

      <!-- Row 2: avg per shift, waste, machine utilization, cost per roll -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <BarChart title="میانگین تولید در شیفت" :categories="machineNames" :values="machineAvg" color="#f472b6" />
        <ComparisonBar title="نرخ ضایعات"
          :actual="n(kpi('waste_rate')?.actual)" :target="n(kpi('waste_rate')?.target)" :ideal="n(kpi('waste_rate')?.ideal)" />
        <StackedMachineBar title="عملکرد دستگاه‌ها" :categories="machineNames" :active="activeShifts" :inactive="inactiveShifts" />
        <ComparisonBar title="هزینه تولید به ازای هر رول"
          :actual="n(kpi('cost_per_roll')?.actual)" :target="n(kpi('cost_per_roll')?.target)" :ideal="n(kpi('cost_per_roll')?.ideal)" />
      </div>

      <!-- Profit / loss -->
      <ProfitLossBar :revenue="data.financials.revenue" :cost="data.financials.cost" />

      <!-- The KPI comparison table (exactly like the workbook) -->
      <div class="bg-white rounded-card shadow-soft p-5 overflow-x-auto">
        <h3 class="font-bold text-ink mb-3">جدول شاخص‌های تولید</h3>
        <table class="w-full text-sm min-w-[640px]">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">شاخص</th>
              <th class="text-center font-medium py-2">واقعی</th>
              <th class="text-center font-medium py-2">مطلوب</th>
              <th class="text-center font-medium py-2">ایده‌آل</th>
              <th class="text-center font-medium py-2">انحراف</th>
              <th class="text-center font-medium py-2">درصد بهره‌وری</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in kpiRows" :key="k.id" class="border-b border-slate-50">
              <td class="py-2.5 font-medium">{{ k.kpi_name_fa }}</td>
              <td class="py-2.5 text-center ltr-nums bg-blue-50/50">{{ fmtCell(k.actual, k.unit) }}</td>
              <td class="py-2.5 text-center ltr-nums">{{ fmtCell(k.target, k.unit) }}</td>
              <td class="py-2.5 text-center ltr-nums">{{ fmtCell(k.ideal, k.unit) }}</td>
              <td class="py-2.5 text-center ltr-nums text-slate-500">{{ k.deviation == null ? "—" : num(k.deviation) }}</td>
              <td class="py-2.5 text-center ltr-nums font-semibold"
                :class="k.efficiency_pct == null ? 'text-slate-300' : (Number(k.efficiency_pct) >= 90 ? 'text-green-600' : Number(k.efficiency_pct) >= 60 ? 'text-amber-600' : 'text-red-600')">
                {{ k.efficiency_pct == null ? "—" : Number(k.efficiency_pct).toFixed(1) + "٪" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
