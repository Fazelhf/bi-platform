<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { defaultPeriodId } from "@/types";
import type { DashboardSummary, Period } from "@/types";
import KpiCard from "@/components/KpiCard.vue";
import BarChart from "@/components/BarChart.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { pct, rial } from "@/utils/format";

const props = withDefaults(
  defineProps<{ channel?: string; title?: string }>(),
  { channel: "team", title: "داشبورد مدیریتی فروش" },
);

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

const collections = computed(() => (data.value?.collections ?? []).filter((c) => c.amount > 0));

// The team-revenue chart is only meaningful for the multi-team channel.
const showTeamChart = computed(() => props.channel === "team");

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await salesApi.dashboard(selectedPeriod.value, props.channel);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = defaultPeriodId(periods.value);
  await load();
});

watch([selectedPeriod, () => props.channel], load);
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-ink">{{ title }}</h1>
      <select
        v-model.number="selectedPeriod"
        class="border border-slate-200 rounded-xl px-3 py-1.5 bg-surface text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition"
      >
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </div>

    <DashboardSkeleton v-if="loading" />

    <template v-else-if="data">
      <!-- Headline KPI cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard v-for="k in headlineKpis" :key="k.id" :kpi="k" />
      </div>

      <!-- Charts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <BarChart
          v-if="showTeamChart"
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

      <!-- Bank collections (organizational channel) -->
      <div
        v-if="collections.length"
        class="bg-surface rounded-card shadow-soft p-4"
      >
        <h3 class="text-sm font-semibold text-ink mb-3">وصول بانکی</h3>
        <table class="w-full text-sm">
          <tbody>
            <tr v-for="c in collections" :key="c.bank__name_fa" class="border-b border-slate-50">
              <td class="py-2">{{ c.bank__name_fa }}</td>
              <td class="py-2 text-left ltr-nums font-medium text-emerald-600">{{ rial(c.amount) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Leaderboard -->
      <div class="bg-surface rounded-card shadow-soft p-4">
        <h3 class="text-sm font-semibold text-ink mb-3">
          رتبه‌بندی فروشندگان بر اساس تحقق تارگت
        </h3>
        <table v-if="leaderboard.length" class="w-full text-sm">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2 w-10">#</th>
              <th class="text-right font-medium py-2">فروشنده</th>
              <th class="text-left font-medium py-2">تحقق تارگت</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in leaderboard"
              :key="row.scope_label"
              class="border-b border-slate-50 hover:bg-slate-50/60 transition-colors"
            >
              <td class="py-2 text-slate-400">{{ i + 1 }}</td>
              <td class="py-2">{{ row.scope_label }}</td>
              <td class="py-2 text-left ltr-nums font-medium text-brand-600">
                {{ pct(row.actual) }}
              </td>
            </tr>
          </tbody>
        </table>
        <EmptyState
          v-else
          icon="🏆"
          title="هنوز فروشی ثبت نشده"
          hint="با ثبت و تأیید فروش فروشندگان در این دوره، رتبه‌بندی اینجا نمایش داده می‌شود."
        />
      </div>

      <p class="text-xs text-slate-400">
        فروش کل: <span class="ltr-nums">{{ rial(data.kpis.find(k => k.kpi_code === 'revenue')?.actual ?? 0) }}</span>
        · دوره: {{ data.period.label }}
      </p>
    </template>
  </div>
</template>
