<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  commercialApi,
  type ConsumptionReport,
  type Forecast,
  type Material,
  type PriceHistory,
} from "@/api/commercial";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import StatTile from "@/components/commercial/StatTile.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * پرونده یک کالا: قیمتی که دادیم، قیمتی که بقیه خواستند، مصرف ماهانه و
 * پیش‌بینی ماه‌های آینده.
 */
const route = useRoute();
const router = useRouter();
const { exact, toUnit, unitLabel } = useMoney();

const material = ref<Material | null>(null);
const history = ref<PriceHistory | null>(null);
const usage = ref<ConsumptionReport | null>(null);
const forecast = ref<Forecast | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");

const CONFIDENCE: Record<string, { label: string; cls: string }> = {
  high: { label: "اطمینان بالا", cls: "bg-emerald-100 text-emerald-700" },
  medium: { label: "اطمینان متوسط", cls: "bg-amber-100 text-amber-700" },
  low: { label: "اطمینان پایین", cls: "bg-red-50 text-red-500" },
  none: { label: "بدون داده", cls: "bg-slate-100 text-slate-500" },
};

onMounted(async () => {
  await loadMoneySettings();
  const id = Number(route.params.id);
  try {
    [material.value, history.value, usage.value, forecast.value] = await Promise.all([
      commercialApi.material(id),
      commercialApi.materialHistory(id),
      commercialApi.materialConsumption(id),
      commercialApi.materialForecast(id, 3),
    ]);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
});

/** Price trend: what we paid, against the cheapest and dearest quotes seen. */
const priceChart = computed(() => {
  const rows = history.value?.rows ?? [];
  return {
    categories: rows.map((r) => r.label),
    series: [
      {
        name: "قیمت پرداختی",
        values: rows.map((r) => (r.paid_rial === null ? null : toUnit(r.paid_rial))),
      },
      {
        name: "کمترین استعلام",
        values: rows.map((r) =>
          r.quote_low_rial === null ? null : toUnit(r.quote_low_rial),
        ),
      },
      {
        name: "بیشترین استعلام",
        values: rows.map((r) =>
          r.quote_high_rial === null ? null : toUnit(r.quote_high_rial),
        ),
      },
    ],
  };
});

/**
 * Consumption chart with the forecast tacked on as a second series, so the
 * projection reads as a continuation of the history rather than a separate
 * picture the eye has to join up.
 */
const usageChart = computed(() => {
  const past = usage.value?.rows ?? [];
  const ahead = forecast.value?.rows ?? [];
  return {
    categories: [...past.map((r) => r.label), ...ahead.map((r) => r.label)],
    series: [
      {
        name: "مصرف واقعی",
        values: [
          ...past.map((r) => (r.has_data ? Number(r.quantity) : null)),
          ...ahead.map(() => null),
        ],
      },
      {
        name: "پیش‌بینی",
        values: [
          ...past.map(() => null),
          ...ahead.map((r) => Number(r.quantity)),
        ],
      },
    ],
  };
});
</script>

<template>
  <div class="space-y-4">
    <div v-if="loading" class="space-y-3">
      <Skeleton class="h-20 rounded-card" />
      <Skeleton class="h-64 rounded-card" />
    </div>

    <p
      v-else-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <template v-else-if="material">
      <div class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-lg font-bold text-ink">{{ material.name_fa }}</h2>
          <p class="text-xs text-slate-400 mt-0.5">
            <span class="ltr-nums">{{ material.code }}</span>
            · واحد {{ material.unit_label }}
            <span v-if="material.category_name"> · {{ material.category_name }}</span>
          </p>
        </div>
        <button
          class="text-sm text-slate-500 hover:text-ink px-2 py-2"
          @click="router.push({ name: 'commercial-materials' })"
        >← بازگشت</button>
      </div>

      <!-- Headline figures -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="آخرین قیمت خرید"
          :value="exact(history?.latest_rial ?? 0, true)"
          :hint="`ماه قبل: ${exact(history?.previous_rial ?? 0)}`"
          :change-pct="history?.change_pct ?? null"
          :rise-is-good="false"
        />
        <StatTile
          label="میانگین مصرف ماهانه"
          :value="`${num(usage?.average_qty ?? 0)} ${material.unit_label}`"
          :hint="`بیشترین ${num(usage?.max_qty ?? 0)} · کمترین ${num(usage?.min_qty ?? 0)}`"
        />
        <StatTile
          label="جمع خرید"
          :value="exact(usage?.total_amount ?? 0, true)"
          :hint="`${num(usage?.total_qty ?? 0)} ${material.unit_label} در مجموع`"
        />
        <StatTile
          label="پیش‌بینی ماه آینده"
          :value="forecast?.rows.length
            ? `${num(forecast.rows[0].quantity)} ${material.unit_label}`
            : '—'"
          :hint="forecast?.rows.length ? forecast.rows[0].label : forecast?.note ?? ''"
        />
      </div>

      <!-- Price trend -->
      <div v-if="priceChart.categories.length" class="bg-surface rounded-card shadow-soft p-4">
        <SeriesChart
          :title="`روند قیمت (${unitLabel})`"
          :categories="priceChart.categories"
          :series="priceChart.series"
          :height="260"
        />
      </div>

      <!-- Consumption + forecast -->
      <div v-if="usageChart.categories.length" class="bg-surface rounded-card shadow-soft p-4">
        <SeriesChart
          :title="`مصرف ماهانه و پیش‌بینی (${material.unit_label})`"
          :categories="usageChart.categories"
          :series="usageChart.series"
          :height="260"
        />
        <div
          v-if="forecast"
          class="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500"
        >
          <span
            class="rounded-full px-2 py-0.5"
            :class="CONFIDENCE[forecast.confidence_level].cls"
          >
            {{ CONFIDENCE[forecast.confidence_level].label }}
            <span v-if="forecast.confidence_level !== 'none'" class="ltr-nums">
              ({{ FA.format(Math.round(forecast.confidence * 100)) }}٪)
            </span>
          </span>
          <span>{{ forecast.method }}</span>
          <span>· {{ num(forecast.observed_months) }} ماه داده</span>
          <span>· {{ forecast.note }}</span>
        </div>
      </div>

      <!-- Forecast table -->
      <div
        v-if="forecast?.rows.length"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          پیش‌بینی خرید
        </h3>
        <table class="w-full text-sm">
          <tbody>
            <tr v-for="f in forecast.rows" :key="f.key" class="border-t border-slate-100">
              <td class="px-4 py-2.5 text-slate-500">{{ f.label }}</td>
              <td class="px-3 text-xs text-slate-400">
                {{ f.months_ahead === 1 ? "ماه آینده" : `${num(f.months_ahead)} ماه بعد` }}
              </td>
              <td class="px-4 text-left ltr-nums text-ink font-medium">
                {{ num(f.quantity) }} {{ material.unit_label }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Monthly consumption table -->
      <div
        v-if="usage?.rows.length"
        class="bg-surface rounded-card shadow-soft overflow-hidden"
      >
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          گزارش مصرف کارخانه
        </h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[600px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">ماه</th>
                <th class="text-right font-medium px-3">مقدار</th>
                <th class="text-right font-medium px-3">مبلغ</th>
                <th class="text-right font-medium px-3">میانگین قیمت</th>
                <th class="text-right font-medium px-4">تغییر مقدار</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in usage.rows" :key="r.key"
                class="border-t border-slate-100"
                :class="{ 'opacity-50': !r.has_data }"
              >
                <td class="px-4 py-2.5 text-slate-500">{{ r.label }}</td>
                <td class="px-3 ltr-nums text-ink">
                  <span v-if="r.has_data">{{ num(r.quantity) }} {{ material.unit_label }}</span>
                  <span v-else class="text-slate-300">ثبت نشده</span>
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ r.has_data ? exact(r.amount_rial) : "—" }}
                </td>
                <td class="px-3 ltr-nums text-slate-500">
                  {{ r.has_data ? exact(r.avg_price_rial) : "—" }}
                </td>
                <td class="px-4 ltr-nums text-xs">
                  <span v-if="r.qty_change_pct === null" class="text-slate-300">—</span>
                  <span v-else :class="r.qty_change_pct > 0 ? 'text-emerald-600' : 'text-red-500'">
                    {{ r.qty_change_pct > 0 ? "▲" : "▼" }}
                    {{ FA.format(Math.abs(Number(r.qty_change_pct.toFixed(1)))) }}٪
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Every quote this material has drawn -->
      <div class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h3 class="px-4 py-3 border-b border-slate-100 font-bold text-ink text-sm">
          تاریخچه استعلام‌ها
        </h3>
        <EmptyState
          v-if="!history?.entries.length"
          title="هنوز استعلامی ثبت نشده"
        />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[760px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-3">تاریخ</th>
                <th class="text-right font-medium px-3">تامین‌کننده</th>
                <th class="text-right font-medium px-3">قیمت</th>
                <th class="text-right font-medium px-3">تحویل</th>
                <th class="text-right font-medium px-4">نتیجه</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="e in history.entries" :key="e.id"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="router.push({ name: 'commercial-request', params: { id: e.request_id } })"
              >
                <td class="px-4 py-2.5 text-slate-500 ltr-nums text-xs">
                  {{ faDate(e.quoted_on) }}
                  <p class="text-slate-400">{{ e.request_no }}</p>
                </td>
                <td class="px-3 text-ink">{{ e.supplier }}</td>
                <td class="px-3 ltr-nums text-ink">{{ exact(e.unit_price_rial) }}</td>
                <td class="px-3 ltr-nums text-slate-500">{{ num(e.delivery_days) }} روز</td>
                <td class="px-4">
                  <span
                    v-if="e.is_selected"
                    class="text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700"
                  >✔ خرید شد{{ e.reason ? ` — ${e.reason}` : "" }}</span>
                  <span
                    v-else-if="e.reason"
                    class="text-xs rounded-full px-2 py-0.5 bg-red-50 text-red-500"
                  >{{ e.reason }}</span>
                  <span v-else class="text-xs text-slate-300">بدون نتیجه</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
