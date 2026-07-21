<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { productionApi } from "@/api/production";
import type { Period, ProductionDashboard } from "@/types";
import KpiComparisonCard from "@/components/KpiComparisonCard.vue";
import BarChart from "@/components/BarChart.vue";
import { num, rial } from "@/utils/format";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ProductionDashboard | null>(null);
const loading = ref(false);

// The 7 headline KPIs, in the workbook's order.
const ORDER = [
  "prod_productivity", "waste_rate", "line_stoppage_rate", "labor_productivity",
  "defect_free_rate", "cost_per_roll", "financial_return",
];
const kpis = computed(() =>
  ORDER.map((c) => data.value?.kpis.find((k) => k.kpi_code === c)).filter(
    (k): k is NonNullable<typeof k> => !!k,
  ),
);

// Output per machine (cutting lines only).
const machineOutput = computed(() => {
  const rows = (data.value?.machines ?? []).filter((m) => m.machine__kind === "cutting");
  return {
    categories: rows.map((m) => m.machine__name_fa),
    values: rows.map((m) => m.output_units),
  };
});

// Downtime by reason, stacked per machine.
const downtime = computed(() => {
  const rows = data.value?.machines ?? [];
  return {
    categories: rows.map((m) => m.machine__name_fa),
    breakdown: rows.map((m) => m.downtime_breakdown_shifts),
    sizechange: rows.map((m) => m.downtime_sizechange_shifts),
    nowork: rows.map((m) => m.downtime_nowork_shifts),
  };
});

const costs = computed(() => ({
  categories: (data.value?.costs ?? []).map((c) => c.category__name_fa),
  values: (data.value?.costs ?? []).map((c) => c.amount),
}));

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
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-slate-800">داشبورد مدیریتی تولید</h1>
      <select v-model.number="selectedPeriod" class="border border-slate-300 rounded-lg px-3 py-1.5 bg-white text-sm">
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-slate-500">در حال بارگذاری…</div>

    <template v-else-if="data">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiComparisonCard v-for="k in kpis" :key="k.id" :kpi="k" />
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <BarChart
          title="تولید بر اساس خط برش"
          :categories="machineOutput.categories"
          :values="machineOutput.values"
          color="#0ea5e9"
        />
        <BarChart
          title="ساختار هزینه تولید (ریال)"
          :categories="costs.categories"
          :values="costs.values"
          color="#8b5cf6"
          horizontal
        />
      </div>

      <!-- Downtime by reason -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
        <h3 class="text-sm font-semibold text-slate-700 mb-3">
          توقف خط تولید به تفکیک علت (شیفت)
        </h3>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">خط</th>
              <th class="text-left font-medium py-2">خرابی</th>
              <th class="text-left font-medium py-2">تغییر سایز</th>
              <th class="text-left font-medium py-2">عدم سفارش</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, i) in downtime.categories" :key="m" class="border-b border-slate-50">
              <td class="py-2">{{ m }}</td>
              <td class="py-2 text-left ltr-nums">{{ num(downtime.breakdown[i]) }}</td>
              <td class="py-2 text-left ltr-nums">{{ num(downtime.sizechange[i]) }}</td>
              <td class="py-2 text-left ltr-nums text-amber-600">{{ num(downtime.nowork[i]) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="text-xs text-slate-400 mt-2">
          «عدم سفارش» یک مشکل تجاری است نه فنی — این تفکیک عمداً حفظ شده.
        </p>
      </div>

      <p class="text-xs text-slate-400">
        درآمد اجرت: <span class="ltr-nums">{{ rial(data.revenue.reduce((s, r) => s + r.amount, 0)) }}</span>
        · دوره: {{ data.period.label }}
      </p>
    </template>
  </div>
</template>
