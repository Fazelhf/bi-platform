<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import type { DashboardSummary, Period } from "@/types";
import KpiCard from "@/components/KpiCard.vue";
import BarChart from "@/components/BarChart.vue";
import { pct, rial } from "@/utils/format";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<DashboardSummary | null>(null);
const loading = ref(false);

// Show the headline KPIs in a sensible order.
const HEADLINE = ["revenue", "target_achievement", "profit_margin", "call_conversion"];
const headlineKpis = computed(() =>
  HEADLINE.map((code) => data.value?.kpis.find((k) => k.kpi_code === code)).filter(
    (k): k is NonNullable<typeof k> => !!k,
  ),
);

const teamRevenue = computed(() => ({
  categories: data.value?.team_revenue.map((t) => t.scope_label) ?? [],
  values: data.value?.team_revenue.map((t) => t.actual) ?? [],
}));

// Top 10 provinces with any sales, sales vs target.
const provinces = computed(() => {
  const rows = (data.value?.province_sales ?? [])
    .filter((p) => p.sales > 0)
    .slice(0, 10);
  return {
    categories: rows.map((p) => p.province__name_fa),
    sales: rows.map((p) => p.sales),
    targets: rows.map((p) => p.target),
  };
});

const leaderboard = computed(() =>
  (data.value?.leaderboard ?? []).filter((l) => l.actual > 0).slice(0, 10),
);

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await salesApi.dashboard(selectedPeriod.value);
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
      <h1 class="text-xl font-bold text-slate-800">داشبورد مدیریتی فروش</h1>
      <select
        v-model.number="selectedPeriod"
        class="border border-slate-300 rounded-lg px-3 py-1.5 bg-white text-sm"
      >
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-slate-500">در حال بارگذاری…</div>

    <template v-else-if="data">
      <!-- Headline KPI cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard v-for="k in headlineKpis" :key="k.id" :kpi="k" />
      </div>

      <!-- Charts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <BarChart
          title="فروش بر اساس تیم (ریال)"
          :categories="teamRevenue.categories"
          :values="teamRevenue.values"
          color="#3b6fed"
        />
        <BarChart
          title="۱۰ استان برتر: فروش در برابر تارگت"
          :categories="provinces.categories"
          :values="provinces.sales"
          :second="{ name: 'تارگت', values: provinces.targets }"
        />
      </div>

      <!-- Leaderboard -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
        <h3 class="text-sm font-semibold text-slate-700 mb-3">
          رتبه‌بندی فروشندگان بر اساس تحقق تارگت
        </h3>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2 w-10">#</th>
              <th class="text-right font-medium py-2">فروشنده</th>
              <th class="text-left font-medium py-2">تحقق تارگت</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in leaderboard" :key="row.scope_label" class="border-b border-slate-50">
              <td class="py-2 text-slate-400">{{ i + 1 }}</td>
              <td class="py-2">{{ row.scope_label }}</td>
              <td class="py-2 text-left ltr-nums font-medium text-brand-600">
                {{ pct(row.actual) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="text-xs text-slate-400">
        فروش کل: <span class="ltr-nums">{{ rial(data.kpis.find(k => k.kpi_code === 'revenue')?.actual ?? 0) }}</span>
        · دوره: {{ data.period.label }}
      </p>
    </template>
  </div>
</template>
