<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { commercialApi, type Dashboard } from "@/api/commercial";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** داشبورد بازرگانی داخلی — این ماه در یک نگاه. */
const router = useRouter();
const { exact, toUnit, unitLabel } = useMoney();

const data = ref<Dashboard | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const CONFIDENCE: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-red-50 text-red-500",
  none: "bg-slate-100 text-slate-500",
};

onMounted(async () => {
  await loadMoneySettings();
  try {
    data.value = await commercialApi.dashboard();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

const spendChart = computed(() => {
  const rows = data.value?.monthly_spend ?? [];
  return {
    categories: rows.map((r) => r.label),
    series: [{
      name: `مبلغ خرید (${unitLabel.value})`,
      // A month nobody bought in is drawn hollow rather than as a real zero —
      // «چیزی نخریدیم» and «ثبت نشده» are different statements.
      values: rows.map((r) => (r.has_data ? toUnit(r.amount_rial) : null)),
    }],
  };
});

const hasAnything = computed(
  () => !!data.value && (data.value.order_count > 0 || data.value.monthly_spend.length > 0),
);
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Skeleton v-for="i in 4" :key="i" class="h-24 rounded-card" />
      </div>
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p
      v-else-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <template v-else-if="data">
      <div class="flex items-baseline justify-between px-1">
        <h2 class="text-sm text-slate-500">{{ data.month.label }}</h2>
        <span class="text-xs text-slate-400">مبالغ به {{ unitLabel }}</span>
      </div>

      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="مبلغ خرید این ماه"
          :value="exact(data.spend_rial, true)"
          :change-pct="data.spend_change_pct"
          :rise-is-good="false"
        />
        <StatTile
          label="سفارش‌های خرید"
          :value="num(data.order_count)"
          :hint="`${num(data.open_request_count)} درخواست باز`"
        />
        <StatTile
          label="استعلام قیمت"
          :value="num(data.quote_count)"
          hint="در این ماه"
        />
        <StatTile
          label="تامین‌کنندگان فعال"
          :value="num(data.active_supplier_count)"
          :hint="`${num(data.material_count)} کالای فعال`"
        />
      </div>

      <div class="grid md:grid-cols-2 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm text-slate-500 mb-1">بیشترین کالای خریداری‌شده</p>
          <template v-if="data.top_material">
            <p class="text-lg font-bold text-ink">{{ data.top_material.name }}</p>
            <p class="text-xs text-slate-400 ltr-nums mt-1">
              {{ num(data.top_material.quantity) }} {{ data.top_material.unit_label }}
              · {{ exact(data.top_material.amount_rial, true) }}
            </p>
          </template>
          <p v-else class="text-sm text-slate-400">این ماه خریدی ثبت نشده.</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-sm text-slate-500 mb-1">بیشترین تامین‌کننده</p>
          <template v-if="data.top_supplier">
            <p class="text-lg font-bold text-ink">{{ data.top_supplier.name }}</p>
            <p class="text-xs text-slate-400 ltr-nums mt-1">
              {{ exact(data.top_supplier.amount_rial, true) }}
            </p>
          </template>
          <p v-else class="text-sm text-slate-400">این ماه خریدی ثبت نشده.</p>
        </div>
      </div>

      <div v-if="spendChart.categories.length" class="bg-surface rounded-card shadow-soft p-4">
        <SeriesChart
          title="روند مبلغ خرید ماهانه"
          :categories="spendChart.categories"
          :series="spendChart.series"
          :height="260"
        />
      </div>

      <!-- What the factory will likely need next -->
      <div v-if="data.forecast.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <!-- Not «ماه آینده»: each material is projected from the month it was
             last bought in, so a material nobody has ordered for a while is
             forecast for a month that has already started. The «ماه» column
             says which, and the heading must not contradict it. -->
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          پیش‌بینی نیاز
          <span class="font-normal text-slate-400">
            — یک ماه پس از آخرین خرید هر کالا
          </span>
        </h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[560px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">کالا</th>
                <th class="text-right font-medium px-3">ماه</th>
                <th class="text-right font-medium px-3">مقدار پیش‌بینی‌شده</th>
                <th class="text-right font-medium px-4">اطمینان</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="f in data.forecast" :key="f.material_id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="router.push({ name: 'commercial-material', params: { id: f.material_id } })"
              >
                <td class="px-4 py-2.5 text-ink font-medium">{{ f.material }}</td>
                <td class="px-3 text-slate-500">{{ f.next_label }}</td>
                <td class="px-3 ltr-nums text-ink">
                  {{ num(f.next_quantity) }} {{ f.unit_label }}
                </td>
                <td class="px-4">
                  <span
                    class="text-xs rounded-full px-2 py-0.5"
                    :class="CONFIDENCE[f.confidence_level]"
                  >
                    <span class="ltr-nums">{{ FA.format(Math.round(f.confidence * 100)) }}٪</span>
                    · {{ num(f.observed_months) }} ماه داده
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <EmptyState
        v-if="!hasAnything"
        title="هنوز داده‌ای نیست"
        hint="با ثبت کالاها و تامین‌کنندگان شروع کنید، بعد اولین درخواست خرید را بزنید."
      />
    </template>
  </div>
</template>
