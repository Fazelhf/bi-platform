<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { salesApi } from "@/api/sales";
import { executiveApi } from "@/api/executive";
import type { ExecutiveOverview, KpiResult, Period } from "@/types";
import { kpiValue, rial } from "@/utils/format";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ExecutiveOverview | null>(null);
const loading = ref(false);

function pick(kpis: KpiResult[] | undefined, codes: string[]) {
  return codes
    .map((c) => kpis?.find((k) => k.kpi_code === c))
    .filter((k): k is KpiResult => !!k);
}

const teamKpis = computed(() => pick(data.value?.sales_team.kpis, ["revenue", "target_achievement", "profit_margin"]));
const orgKpis = computed(() => pick(data.value?.sales_org.kpis, ["revenue", "profit_margin", "avg_invoice_value"]));
const prodKpis = computed(() => pick(data.value?.production.kpis, ["prod_productivity", "waste_rate", "financial_return"]));

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await executiveApi.overview(selectedPeriod.value);
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
      <h1 class="text-xl font-bold text-slate-800">نمای کلی سازمان</h1>
      <select v-model.number="selectedPeriod" class="border border-slate-300 rounded-lg px-3 py-1.5 bg-white text-sm">
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-slate-500">در حال بارگذاری…</div>

    <template v-else-if="data">
      <!-- Headline: total company sales -->
      <div class="bg-gradient-to-l from-brand-600 to-brand-500 text-white rounded-xl shadow p-5">
        <div class="text-sm opacity-90 mb-1">فروش کل شرکت (سازمانی + تیم)</div>
        <div class="text-3xl font-bold ltr-nums">{{ rial(data.combined.total_sales_revenue) }}</div>
        <div class="text-xs opacity-80 mt-1 ltr-nums">
          تیم: {{ rial(data.combined.sales_team_revenue) }} + سازمانی: {{ rial(data.combined.sales_org_revenue) }}
        </div>
      </div>

      <!-- Three domain cards -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <h2 class="font-bold text-brand-600 mb-3">تیم فروش (همکار)</h2>
          <div class="space-y-2">
            <div v-for="k in teamKpis" :key="k.id" class="flex justify-between text-sm">
              <span class="text-slate-500">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-medium">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: 'sales-dashboard' }" class="text-xs text-brand-600 hover:underline mt-3 inline-block">داشبورد فروش همکار ←</RouterLink>
        </div>

        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <h2 class="font-bold text-indigo-600 mb-3">فروش سازمانی (کلی)</h2>
          <div class="space-y-2">
            <div v-for="k in orgKpis" :key="k.id" class="flex justify-between text-sm">
              <span class="text-slate-500">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-medium">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: 'sales-org-dashboard' }" class="text-xs text-indigo-600 hover:underline mt-3 inline-block">داشبورد فروش کلی ←</RouterLink>
        </div>

        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <h2 class="font-bold text-sky-600 mb-3">تولید</h2>
          <div class="space-y-2">
            <div v-for="k in prodKpis" :key="k.id" class="flex justify-between text-sm">
              <span class="text-slate-500">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-medium">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: 'production-dashboard' }" class="text-xs text-sky-600 hover:underline mt-3 inline-block">داشبورد تولید ←</RouterLink>
        </div>
      </div>

      <!-- Combined financial picture -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
        <h2 class="font-bold text-slate-700 mb-4">تصویر مالی تلفیقی</h2>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <div class="text-xs text-slate-500 mb-1">فروش خارجی کل</div>
            <div class="text-xl font-bold ltr-nums text-brand-600">{{ rial(data.combined.total_sales_revenue) }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">درآمد اجرت تولید (داخلی)</div>
            <div class="text-xl font-bold ltr-nums text-sky-600">{{ rial(data.combined.internal_piece_rate_revenue) }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">هزینه تولید</div>
            <div class="text-xl font-bold ltr-nums text-slate-700">{{ rial(data.combined.production_cost) }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">حاشیه تولید</div>
            <div class="text-xl font-bold ltr-nums" :class="data.combined.production_margin >= 0 ? 'text-green-600' : 'text-red-600'">
              {{ rial(data.combined.production_margin) }}
            </div>
          </div>
        </div>
        <p class="text-xs text-amber-600 mt-4 bg-amber-50 rounded-lg p-2">⚠ {{ data.combined.note }}</p>
      </div>
    </template>
  </div>
</template>
