<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { salesApi } from "@/api/sales";
import { executiveApi } from "@/api/executive";
import { defaultPeriodId } from "@/types";
import type { ExecutiveOverview, KpiResult, Period } from "@/types";
import { kpiValue, rial } from "@/utils/format";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ExecutiveOverview | null>(null);
const loading = ref(false);

function pick(kpis: KpiResult[] | undefined, codes: string[]) {
  return codes.map((c) => kpis?.find((k) => k.kpi_code === c)).filter((k): k is KpiResult => !!k);
}

const cards = computed(() => {
  if (!data.value) return [];
  return [
    { title: "فروش همکار", color: "#3b6fed", route: "sales-dashboard",
      kpis: pick(data.value.sales_team.kpis, ["revenue", "target_achievement", "profit_margin"]) },
    { title: "فروش بانکی", color: "#f59e0b", route: "sales-org-dashboard",
      kpis: pick(data.value.sales_org.kpis, ["revenue", "profit_margin", "avg_invoice_value"]) },
    { title: "فروش B2B", color: "#ec4899", route: "sales-b2b-dashboard",
      kpis: pick(data.value.sales_b2b.kpis, ["revenue", "target_achievement", "profit_margin"]) },
    { title: "تولید", color: "#10b981", route: "production-dashboard",
      kpis: pick(data.value.production.kpis, ["prod_productivity", "waste_rate", "financial_return"]) },
  ];
});

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
  selectedPeriod.value = defaultPeriodId(periods.value);
  await load();
});
watch(selectedPeriod, load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold text-ink">نمای کلی سازمان</h2>
      <select v-model.number="selectedPeriod" class="bg-white border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition">
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </div>

    <DashboardSkeleton v-if="loading" :cards="4" :charts="0" :rows="4" />

    <template v-else-if="data">
      <!-- Hero: total company sales -->
      <div class="bg-ink text-white rounded-card shadow-soft p-6">
        <p class="text-sm text-white/60 mb-1">فروش کل شرکت (همکار + بانکی + B2B)</p>
        <p class="text-4xl font-extrabold ltr-nums">{{ rial(data.combined.total_sales_revenue) }}</p>
        <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-white/50 mt-2 ltr-nums">
          <span>همکار: {{ rial(data.combined.sales_team_revenue) }}</span>
          <span>بانکی: {{ rial(data.combined.sales_org_revenue) }}</span>
          <span>B2B: {{ rial(data.combined.sales_b2b_revenue) }}</span>
        </div>
      </div>

      <!-- 4 domain cards -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div v-for="c in cards" :key="c.title" class="bg-white rounded-card shadow-soft p-5 hover:shadow-pop transition-shadow duration-200">
          <div class="flex items-center gap-2 mb-4">
            <span class="w-2.5 h-2.5 rounded-full" :style="{ backgroundColor: c.color }"></span>
            <h3 class="font-bold text-ink">{{ c.title }}</h3>
          </div>
          <div class="space-y-2.5">
            <div v-for="k in c.kpis" :key="k.id" class="flex justify-between items-baseline text-sm">
              <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: c.route }" class="text-xs mt-4 inline-block hover:underline" :style="{ color: c.color }">
            مشاهده داشبورد ←
          </RouterLink>
        </div>
      </div>

      <!-- Combined financials -->
      <div class="bg-white rounded-card shadow-soft p-5">
        <h3 class="font-bold text-ink mb-4">تصویر مالی تلفیقی</h3>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <p class="text-xs text-slate-400 mb-1">فروش خارجی کل</p>
            <p class="text-xl font-bold ltr-nums text-brand-600">{{ rial(data.combined.total_sales_revenue) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400 mb-1">درآمد اجرت تولید (داخلی)</p>
            <p class="text-xl font-bold ltr-nums text-accent-600">{{ rial(data.combined.internal_piece_rate_revenue) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400 mb-1">هزینه تولید</p>
            <p class="text-xl font-bold ltr-nums text-ink">{{ rial(data.combined.production_cost) }}</p>
          </div>
          <div>
            <p class="text-xs text-slate-400 mb-1">حاشیه تولید</p>
            <p class="text-xl font-bold ltr-nums" :class="data.combined.production_margin >= 0 ? 'text-green-600' : 'text-red-600'">
              {{ rial(data.combined.production_margin) }}
            </p>
          </div>
        </div>
        <p class="text-xs text-amber-600 mt-4 bg-amber-50 rounded-xl p-2.5">⚠ {{ data.combined.note }}</p>
      </div>
    </template>
  </div>
</template>
