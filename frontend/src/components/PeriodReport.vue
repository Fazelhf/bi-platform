<script setup lang="ts">
/**
 * گزارش دوره‌ای — the one thing the B2B manager's workbook did that the
 * platform could not: report across a *range* of months and put it beside the
 * equal range before it.
 *
 * Lives as a tab inside the sales dashboard rather than a page of its own:
 * it answers the same question as the rest of the dashboard, only over a
 * longer window, so splitting it out would have meant two places to look for
 * one channel's performance. It brings its own range picker and ignores the
 * dashboard's single-month selector.
 *
 * Growth is only shown when the prior span is the same length and exists in
 * the calendar. A shorter tail is reported as "no comparable period" rather
 * than divided into a number that would read as real.
 */
import { computed, onMounted, ref, watch } from "vue";
import {
  periodReportApi,
  type PeriodPresets,
  type PeriodReport,
} from "@/api/periodReport";
import { num, pct, rial } from "@/utils/format";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";

const props = withDefaults(defineProps<{ channel?: string; title?: string }>(), {
  channel: "b2b",
  title: "گزارش دوره‌ای",
});

const presets = ref<PeriodPresets | null>(null);
const report = ref<PeriodReport | null>(null);
const loading = ref(true);
const error = ref("");

const year = ref<number | null>(null);
const fromId = ref<number | null>(null);
const toId = ref<number | null>(null);
const activePreset = ref<string>("");

async function loadPresets() {
  presets.value = await periodReportApi.presets(props.channel, year.value ?? undefined);
  year.value = presets.value.year;
  if (!fromId.value || !toId.value) {
    // Open on the most recent quarter that actually holds figures. Opening on
    // the newest quarter regardless meant that for most of the year the page
    // greeted you with an empty report, which reads as broken rather than as
    // "nothing sold in the future yet".
    const quarters = presets.value.presets.filter((p) => p.key.startsWith("q"));
    const withData = quarters.filter((p) => p.has_data);
    const pick = withData[withData.length - 1]
      ?? quarters[quarters.length - 1]
      ?? presets.value.presets[0];
    if (pick) {
      fromId.value = pick.from;
      toId.value = pick.to;
      activePreset.value = pick.key;
    }
  }
}

async function loadReport() {
  if (!fromId.value || !toId.value) return;
  loading.value = true;
  error.value = "";
  try {
    report.value = await periodReportApi.report(fromId.value, toId.value, props.channel);
  } catch (e: any) {
    report.value = null;
    error.value = e?.response?.status === 403
      ? "این بخش فروش متعلق به شما نیست."
      : e?.response?.data?.detail || "گزارش ساخته نشد.";
  } finally {
    loading.value = false;
  }
}

function applyPreset(key: string) {
  const found = presets.value?.presets.find((p) => p.key === key);
  if (!found) return;
  activePreset.value = key;
  fromId.value = found.from;
  toId.value = found.to;
  loadReport();
}

function onManualRange() {
  activePreset.value = "";
  loadReport();
}

async function onYearChange() {
  fromId.value = null;
  toId.value = null;
  activePreset.value = "";
  await loadPresets();
  await loadReport();
}

onMounted(async () => {
  try {
    await loadPresets();
    await loadReport();
  } catch {
    error.value = "بارگذاری بازه‌ها ناموفق بود.";
    loading.value = false;
  }
});

watch(() => props.channel, async () => {
  fromId.value = toId.value = null;
  await loadPresets();
  await loadReport();
});

// ---- derived ---------------------------------------------------------------
const n = (v: string | null | undefined) => Number(v ?? 0);

const growthTone = (g: number | null | undefined) =>
  g === null || g === undefined ? "text-slate-400"
    : g > 0 ? "text-green-600" : g < 0 ? "text-red-500" : "text-slate-500";

const growthLabel = (g: number | null | undefined) =>
  g === null || g === undefined ? "—" : `${g > 0 ? "+" : ""}${pct(g)}`;

const achievementTone = (a: number | null | undefined) =>
  a === null || a === undefined ? "text-slate-400"
    : a >= 100 ? "text-green-600" : a >= 70 ? "text-amber-600" : "text-red-500";

const trendCategories = computed(() =>
  (report.value?.monthly ?? []).map((m) => m.label),
);
const trendSeries = computed(() => [
  { name: "فروش", values: (report.value?.monthly ?? []).map((m) => n(m.sales_rial)) },
  { name: "تارگت", values: (report.value?.monthly ?? []).map((m) => n(m.target_rial)) },
]);

const groupCategories = computed(() =>
  (report.value?.customer_groups ?? []).map((g) => g.name),
);
const groupSeries = computed(() => [
  {
    name: "فروش",
    values: (report.value?.customer_groups ?? []).map((g) => n(g.sales_rial)),
  },
]);

const topGroup = computed(() => {
  const groups = report.value?.customer_groups ?? [];
  if (!groups.length) return null;
  return groups.reduce((best, g) =>
    n(g.sales_rial) > n(best.sales_rial) ? g : best);
});

const peopleCategories = computed(() => (report.value?.rows ?? []).map((r) => r.name));
const peopleSeries = computed(() => {
  const rows = report.value?.rows ?? [];
  const series = [{ name: "دوره جاری", values: rows.map((r) => n(r.sales_rial)) }];
  if (report.value?.previous_range.comparable) {
    series.push({ name: "دوره قبل", values: rows.map((r) => n(r.prev_sales_rial)) });
  }
  return series;
});
</script>

<template>
  <div class="space-y-4">
    <!-- ===== Range picker ===== -->
    <section class="bg-surface rounded-card shadow-soft p-4">
      <div class="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <h2 class="font-bold text-ink">{{ title }}</h2>
        <p v-if="report" class="text-xs text-slate-400">
          {{ report.range.from.label }} تا {{ report.range.to.label }}
          · {{ num(report.range.length) }} ماه
        </p>
      </div>

      <div class="flex flex-wrap items-end gap-3">
        <label v-if="presets && presets.years.length > 1" class="block">
          <span class="text-[11px] text-slate-400">سال</span>
          <select
            v-model.number="year"
            class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface ltr-nums"
            @change="onYearChange"
          >
            <option v-for="y in presets.years" :key="y" :value="y">{{ num(y) }}</option>
          </select>
        </label>

        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="p in presets?.presets ?? []" :key="p.key"
            class="px-3 py-1.5 text-xs rounded-xl border transition"
            :class="activePreset === p.key
              ? 'bg-panel text-white border-panel'
              : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
            @click="applyPreset(p.key)"
          >{{ p.label }}</button>
        </div>

        <div class="flex items-end gap-2">
          <label class="block">
            <span class="text-[11px] text-slate-400">از ماه</span>
            <select
              v-model.number="fromId"
              class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
              @change="onManualRange"
            >
              <option v-for="m in presets?.months ?? []" :key="m.id" :value="m.id">
                {{ m.label }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="text-[11px] text-slate-400">تا ماه</span>
            <select
              v-model.number="toId"
              class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
              @change="onManualRange"
            >
              <option v-for="m in presets?.months ?? []" :key="m.id" :value="m.id">
                {{ m.label }}
              </option>
            </select>
          </label>
        </div>
      </div>

      <p
        v-if="report && !report.previous_range.comparable"
        class="text-[11px] text-amber-600 bg-amber-50 rounded-lg px-3 py-1.5 mt-3"
      >{{ report.previous_range.note }}</p>
      <p
        v-else-if="report"
        class="text-[11px] text-slate-400 mt-3"
      >
        مقایسه با دوره قبل: {{ report.previous_range.from?.label }}
        تا {{ report.previous_range.to?.label }}
      </p>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>

    <DashboardSkeleton v-else-if="loading && !report" />

    <template v-else-if="report">
      <!-- ===== Headline ===== -->
      <div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">فروش دوره</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ rial(n(report.totals.sales_rial)) }}</p>
          <p class="text-[11px]" :class="growthTone(report.totals.growth_pct)">
            {{ growthLabel(report.totals.growth_pct) }} نسبت به دوره قبل
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">تارگت دوره</p>
          <p class="text-lg font-bold text-slate-500 ltr-nums">{{ rial(n(report.totals.target_rial)) }}</p>
          <p class="text-[11px]" :class="achievementTone(report.totals.achievement_pct)">
            تحقق {{ report.totals.achievement_pct === null ? "—" : pct(report.totals.achievement_pct) }}
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">سود ناخالص</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ rial(n(report.totals.profit_rial)) }}</p>
          <p class="text-[11px] text-slate-400">
            حاشیه {{ report.totals.margin_pct === null ? "—" : pct(report.totals.margin_pct) }}
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">وصول‌شده</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ rial(n(report.totals.collected_rial)) }}</p>
          <p class="text-[11px] text-slate-400">
            نرخ وصول {{ report.totals.collection_pct === null ? "—" : pct(report.totals.collection_pct) }}
          </p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">مانده مطالبات</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ rial(n(report.totals.receivables_rial)) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">تعداد فاکتور</p>
          <p class="text-lg font-bold text-ink ltr-nums">{{ num(report.totals.invoice_count) }}</p>
          <p class="text-[11px] text-slate-400">{{ num(report.totals.calls) }} تماس</p>
        </div>
      </div>

      <!-- ===== Specialists ===== -->
      <section class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h2 class="font-semibold text-ink p-4 pb-2">عملکرد کارشناسان در این بازه</h2>
        <div v-if="!report.rows.length" class="p-8 text-center text-sm text-slate-400">
          در این بازه فروشی ثبت نشده است.
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[820px]">
            <thead class="bg-slate-50/60 text-[11px] text-slate-400">
              <tr>
                <th class="text-right font-medium px-3 py-2">کارشناس</th>
                <th class="text-left font-medium px-3 py-2">فروش دوره</th>
                <th class="text-left font-medium px-3 py-2">تارگت دوره</th>
                <th class="text-left font-medium px-3 py-2">تحقق</th>
                <th class="text-left font-medium px-3 py-2">سود ناخالص</th>
                <th class="text-left font-medium px-3 py-2">حاشیه</th>
                <th class="text-left font-medium px-3 py-2">دوره قبل</th>
                <th class="text-left font-medium px-3 py-2">رشد</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in report.rows" :key="r.employee_id"
                class="border-t border-slate-50 hover:bg-slate-50/60"
              >
                <td class="px-3 py-2 text-ink">{{ r.name }}</td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(r.sales_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500">{{ rial(n(r.target_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums" :class="achievementTone(r.achievement_pct)">
                  {{ r.achievement_pct === null ? "—" : pct(r.achievement_pct) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(r.profit_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500">
                  {{ r.margin_pct === null ? "—" : pct(r.margin_pct) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-400">
                  {{ r.prev_sales_rial === null ? "—" : rial(n(r.prev_sales_rial)) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums" :class="growthTone(r.growth_pct)">
                  {{ growthLabel(r.growth_pct) }}
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t-2 border-slate-100 font-semibold bg-slate-50/40">
                <td class="px-3 py-2 text-ink">جمع دپارتمان</td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(report.totals.sales_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(report.totals.target_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums" :class="achievementTone(report.totals.achievement_pct)">
                  {{ report.totals.achievement_pct === null ? "—" : pct(report.totals.achievement_pct) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(report.totals.profit_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums">
                  {{ report.totals.margin_pct === null ? "—" : pct(report.totals.margin_pct) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-400">
                  {{ report.totals.prev_sales_rial === null ? "—" : rial(n(report.totals.prev_sales_rial)) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums" :class="growthTone(report.totals.growth_pct)">
                  {{ growthLabel(report.totals.growth_pct) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <!-- ===== Charts ===== -->
      <div class="grid lg:grid-cols-2 gap-4">
        <SeriesChart
          title="روند ماهانه — فروش در برابر تارگت"
          :categories="trendCategories"
          :series="trendSeries"
        />
        <SeriesChart
          v-if="report.rows.length"
          title="فروش دوره جاری در برابر دوره قبل، به تفکیک کارشناس"
          :categories="peopleCategories"
          :series="peopleSeries"
        />
      </div>

      <!-- ===== Customer segments ===== -->
      <section v-if="report.customer_groups.length" class="grid lg:grid-cols-2 gap-4">
        <div class="bg-surface rounded-card shadow-soft overflow-hidden">
          <div class="flex items-baseline justify-between gap-2 p-4 pb-2">
            <h2 class="font-semibold text-ink">فروش به تفکیک گروه مشتری</h2>
            <span v-if="topGroup" class="text-xs text-slate-400">
              گروه برتر: <span class="text-ink font-medium">{{ topGroup.name }}</span>
            </span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-slate-50/60 text-[11px] text-slate-400">
                <tr>
                  <th class="text-right font-medium px-3 py-2">گروه</th>
                  <th class="text-left font-medium px-3 py-2">فروش</th>
                  <th class="text-left font-medium px-3 py-2">سهم</th>
                  <th class="text-left font-medium px-3 py-2">حاشیه</th>
                  <th class="text-left font-medium px-3 py-2">رشد</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="g in report.customer_groups" :key="g.group_id"
                  class="border-t border-slate-50"
                >
                  <td class="px-3 py-2 text-ink">{{ g.name }}</td>
                  <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(g.sales_rial)) }}</td>
                  <td class="px-3 py-2 text-left ltr-nums text-slate-500">
                    {{ g.share_pct === null ? "—" : pct(g.share_pct) }}
                  </td>
                  <td class="px-3 py-2 text-left ltr-nums text-slate-500">
                    {{ g.margin_pct === null ? "—" : pct(g.margin_pct) }}
                  </td>
                  <td class="px-3 py-2 text-left ltr-nums" :class="growthTone(g.growth_pct)">
                    {{ growthLabel(g.growth_pct) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <SeriesChart
          title="سهم فروش هر گروه مشتری"
          kind="pie"
          :categories="groupCategories"
          :series="groupSeries"
        />
      </section>
      <p
        v-else
        class="bg-surface rounded-card shadow-soft p-4 text-sm text-slate-400"
      >
        برای این بازه فروش به تفکیک گروه مشتری وارد نشده است — در صفحه‌ی ورود اطلاعات
        قابل ثبت است.
      </p>

      <!-- ===== Provinces ===== -->
      <section v-if="report.provinces.length" class="bg-surface rounded-card shadow-soft overflow-hidden">
        <h2 class="font-semibold text-ink p-4 pb-2">فروش استانی در این بازه</h2>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-slate-50/60 text-[11px] text-slate-400">
              <tr>
                <th class="text-right font-medium px-3 py-2">استان</th>
                <th class="text-left font-medium px-3 py-2">فروش</th>
                <th class="text-left font-medium px-3 py-2">تارگت</th>
                <th class="text-left font-medium px-3 py-2">تحقق</th>
                <th class="text-left font-medium px-3 py-2">رشد</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="p in report.provinces" :key="p.province_id"
                class="border-t border-slate-50"
              >
                <td class="px-3 py-2 text-ink">{{ p.name }}</td>
                <td class="px-3 py-2 text-left ltr-nums">{{ rial(n(p.sales_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums text-slate-500">{{ rial(n(p.target_rial)) }}</td>
                <td class="px-3 py-2 text-left ltr-nums" :class="achievementTone(p.achievement_pct)">
                  {{ p.achievement_pct === null ? "—" : pct(p.achievement_pct) }}
                </td>
                <td class="px-3 py-2 text-left ltr-nums" :class="growthTone(p.growth_pct)">
                  {{ growthLabel(p.growth_pct) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
