<script setup lang="ts">
/**
 * تحلیل خزانه — the averages, kept off the CEO's page.
 *
 * A closing balance says where the month ended; an average says how much was
 * actually held through it. That second question is a treasury question — it
 * decides what can be committed to, and it is answered by whoever manages the
 * cash, not by the person reading the company's position once a month.
 *
 * On the نقدینگی page these three blocks were a table and two stacked charts
 * of the same quantity at three zoom levels, and they pushed the four figures
 * the CEO actually opens that page for below the fold. So they moved here,
 * where the person who uses them works.
 */
import { computed, onMounted, ref, watch } from "vue";
import { financeApi, type MonthTrend, type YearTrend } from "@/api/finance";
import { salesApi } from "@/api/sales";
import { currentPeriodId, type Period } from "@/types";
import { faYear, loadMoneySettings, useMoney } from "@/composables/useMoney";
import StackedAccountBar from "@/components/charts/StackedAccountBar.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";

const periods = ref<Period[]>([]);
const selected = ref<number | null>(null);
const monthTrend = ref<MonthTrend | null>(null);
const yearTrend = ref<YearTrend | null>(null);
const loading = ref(true);
const error = ref("");

const n = (v: string | null | undefined) => Number(v ?? 0);
const { money } = useMoney();
const rial = (v: number | string | null | undefined) => money(v, false);

async function load() {
  if (!selected.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [month, year] = await Promise.all([
      financeApi.monthTrend(selected.value),
      financeApi.yearTrend(),
    ]);
    monthTrend.value = month;
    yearTrend.value = year;
  } catch (e: any) {
    monthTrend.value = null;
    yearTrend.value = null;
    error.value = e?.response?.status === 403
      ? "این بخش برای شما قابل مشاهده نیست."
      : "محاسبه میانگین‌ها ناموفق بود.";
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    await loadMoneySettings();
    periods.value = await salesApi.periods();
    selected.value = currentPeriodId(periods.value);
    await load();
  } catch {
    error.value = "بارگذاری دوره‌ها ناموفق بود.";
    loading.value = false;
  }
});
watch(selected, load);

const weekly = computed(
  () => monthTrend.value?.grain === "week" && (monthTrend.value?.rows.length ?? 0) > 1,
);

const control =
  "bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";
</script>

<template>
  <div class="space-y-4">
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-lg font-bold text-ink">تحلیل خزانه</h1>
        <p class="text-xs text-slate-400 mt-1">
          میانگین مانده پایان هر روز — شامل روزهای بی‌حرکت. این عدد می‌گوید در طول
          دوره واقعاً چقدر پول در اختیار بوده، نه اینکه دوره با چه رقمی تمام شد.
        </p>
      </div>
      <select v-model.number="selected" :class="control">
        <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>
    <DashboardSkeleton v-else-if="loading && !monthTrend" :cards="2" :charts="2" />

    <template v-else-if="monthTrend">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">میانگین موجودی ماه</p>
          <p class="text-lg font-bold text-ink ltr-nums">
            {{ rial(n(monthTrend.month.average_rial)) }}
          </p>
        </div>
      </div>

      <section class="bg-surface rounded-card shadow-soft overflow-hidden">
        <div class="flex flex-wrap items-baseline justify-between gap-2 p-4 pb-2">
          <h2 class="font-semibold text-ink">
            میانگین موجودی — {{ monthTrend.grain === "week" ? "به تفکیک هفته" : "کل ماه" }}
          </h2>
          <span class="text-[11px] text-slate-400">{{ monthTrend.period.label }}</span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[520px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-4 py-2">بازه</th>
                <th class="text-left font-medium px-3 py-2">میانگین موجودی</th>
                <th class="text-left font-medium px-3 py-2">مانده پایان</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in monthTrend.rows" :key="row.label" class="border-t border-slate-100">
                <td class="px-4 py-2 text-ink whitespace-nowrap">{{ row.label }}</td>
                <td class="px-3 py-2 text-left ltr-nums text-ink whitespace-nowrap">
                  {{ rial(n(row.average_rial)) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500 whitespace-nowrap">
                  {{ rial(n(row.closing_rial)) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <StackedAccountBar
        v-if="yearTrend && yearTrend.rows.length"
        :title="`میانگین موجودی هر ماه — سال ${faYear(yearTrend.year)}`"
        :rows="yearTrend.rows"
      />

      <StackedAccountBar
        v-if="weekly"
        :title="`میانگین موجودی هر هفته — ${monthTrend.period.label}`"
        :rows="monthTrend.rows"
        :height="240"
        :show-closing="false"
      />
    </template>
  </div>
</template>
