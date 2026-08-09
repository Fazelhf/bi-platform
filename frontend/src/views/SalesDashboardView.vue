<script setup lang="ts">
import { defaultPeriodId, type MonthProgress, type Period } from "@/types";
import { computed, onMounted, ref, watch } from "vue";
import api from "@/api/client";
import { salesApi } from "@/api/sales";
import SeriesChart, { type CompareSpec } from "@/components/charts/SeriesChart.vue";
import ChartCompareModal from "@/components/ChartCompareModal.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExportActions from "@/components/ExportActions.vue";
import WeekProgress from "@/components/WeekProgress.vue";
import PeriodCalendar from "@/components/PeriodCalendar.vue";
import ReconcilePanel from "@/components/ReconcilePanel.vue";
import PeriodReport from "@/components/PeriodReport.vue";
import { rial } from "@/utils/format";
import SectionBoard from "@/components/boards/SectionBoard.vue";

/** One component serves three channels, so its board follows the channel. */
const SECTION_BY_CHANNEL: Record<string, string> = {
  team: "sales_team",
  organizational: "sales_org",
  b2b: "sales_b2b",
};

/**
 * Mirrors the workbook's two chart sheets:
 *   داشبورد فروشنده — 11 charts (9 per-salesperson + 2 provincial)
 *   داشبورد تیم     — 9 charts across the 5 teams
 */
const props = withDefaults(defineProps<{ channel?: string; title?: string }>(), {
  channel: "team",
  title: "داشبورد فروش",
});

const boardSection = computed(() => SECTION_BY_CHANNEL[props.channel] ?? "sales_team");

interface Detail {
  period: { id: number; label: string };
  salespeople: Record<string, any>[];
  teams: Record<string, any>[];
  provinces: { name: string; sales: number; target: number }[];
}

const periods = ref<Period[]>([]);
const periodA = ref<number | null>(null);
const periodB = ref<number | null>(null);   // side-by-side comparison month
const compare = ref(false);
const data = ref<Detail | null>(null);
const dataB = ref<Detail | null>(null);
const tab = ref<"people" | "teams" | "period">("people");
const loading = ref(false);

// When a week is picked from the strip the charts show just that week;
// otherwise they show the whole month (its weeks rolled up).
const weekId = ref<number | null>(null);
const progress = ref<MonthProgress | null>(null);
const showBreakdown = ref(false);
const viewedPeriod = computed(() => weekId.value ?? periodA.value);

async function fetchDetail(pid: number): Promise<Detail> {
  const { data } = await api.get("/sales/dashboard/detail/", {
    params: { period: pid, channel: props.channel },
  });
  return data;
}

async function loadProgress() {
  if (!periodA.value) return;
  try {
    progress.value = await salesApi.monthProgress(periodA.value);
  } catch {
    progress.value = null; // months that were never split have no strip
  }
}

async function load() {
  if (!viewedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await fetchDetail(viewedPeriod.value);
    dataB.value = compare.value && periodB.value ? await fetchDetail(periodB.value) : null;
  } finally {
    loading.value = false;
  }
}

function pickWeek(id: number | null) {
  weekId.value = id;
}

/* ==========================================================================
 * Charts, declared as data.
 *
 * They used to be written out one by one with their series inline, and only
 * the six built through helper functions ever looked at the comparison month.
 * The other fourteen — سود/هزینه, فاکتور/مشتری, وصول/مطالبات, استان and the
 * whole team tab — silently ignored it, which is why "مقایسه با ماه دیگر"
 * looked broken: ticking it changed six charts out of twenty.
 *
 * Declaring each chart's metrics instead of its series means one builder
 * produces the bars, and comparison is simply "do it twice per metric". A
 * chart added later gets both comparison modes for free.
 * ======================================================================== */
type Scope = "people" | "teams" | "provinces";
interface Metric { key: string; label: string; percent?: boolean }
interface ChartDef {
  title: string;
  scope: Scope;
  metrics: Metric[];
  percent?: boolean;
  height?: number;
}

function rowsOf(d: Detail | null, scope: Scope): Record<string, any>[] {
  if (!d) return [];
  if (scope === "teams") return d.teams ?? [];
  if (scope === "provinces") return d.provinces ?? [];
  return d.salespeople ?? [];
}

/** Names present in either month, so nobody is dropped by comparing. */
function categoriesFor(scope: Scope): string[] {
  const out = rowsOf(data.value, scope).map((r) => r.name);
  if (!dataB.value) return out;
  const seen = new Set(out);
  for (const r of rowsOf(dataB.value, scope)) {
    if (!seen.has(r.name)) { seen.add(r.name); out.push(r.name); }
  }
  return out;
}

function seriesFor(def: ChartDef) {
  const cats = def.scope === "provinces" ? provinceCategories.value : categoriesFor(def.scope);
  const rowsA = rowsOf(data.value, def.scope);
  const rowsB = dataB.value ? rowsOf(dataB.value, def.scope) : null;
  const at = (rows: Record<string, any>[], name: string, key: string) =>
    Number(rows.find((r) => r.name === name)?.[key] ?? 0);

  const out: { name: string; values: number[] }[] = [];
  for (const m of def.metrics) {
    // With a comparison month the month has to be in the legend, or two
    // identically-named series sit side by side.
    out.push({
      name: rowsB ? `${m.label} (${data.value?.period.label})` : m.label,
      values: cats.map((n) => at(rowsA, n, m.key)),
    });
    if (rowsB) {
      out.push({
        name: `${m.label} (${dataB.value!.period.label})`,
        values: cats.map((n) => at(rowsB, n, m.key)),
      });
    }
  }
  return out;
}

function specOf(def: ChartDef): CompareSpec {
  return { scope: def.scope, metrics: def.metrics };
}

// B2B is wholesale on credit: tonnage and collection replace call activity,
// and the counterparty is a company rather than a retail customer.
const isB2B = computed(() => props.channel === "b2b");
const buyer = computed(() => (isB2B.value ? "شرکت" : "مشتری"));

const peopleCharts = computed<ChartDef[]>(() => {
  const base: ChartDef[] = [
    { title: "فروش ریالی", scope: "people", metrics: [{ key: "revenue", label: "فروش ریالی" }] },
    { title: `تعداد ${buyer.value} جدید`, scope: "people", metrics: [{ key: "new_customers", label: `${buyer.value} جدید` }] },
    { title: "سود فروش", scope: "people", metrics: [{ key: "profit", label: "سود فروش" }] },
    { title: "هزینه / سود فروش", scope: "people", metrics: [
      { key: "profit", label: "سود فروش" }, { key: "cost", label: "هزینه فروش" }] },
    { title: `تعداد فروش / تعداد ${buyer.value}`, scope: "people", metrics: [
      { key: "invoices", label: isB2B.value ? "تعداد قرارداد" : "تعداد فاکتور" },
      { key: "active_customers", label: `${buyer.value} فعال` }] },
    { title: "درصد رسیدن به تارگت", scope: "people", percent: true,
      metrics: [{ key: "target_achievement", label: "تحقق تارگت", percent: true }] },
  ];
  const tail: ChartDef[] = isB2B.value
    ? [
        { title: "مقدار فروش (تن)", scope: "people", metrics: [{ key: "quantity_ton", label: "تناژ فروش" }] },
        { title: "نرخ وصول مطالبات", scope: "people", percent: true,
          metrics: [{ key: "collection_rate", label: "نرخ وصول", percent: true }] },
        { title: "وصول‌شده / مانده مطالبات", scope: "people", metrics: [
          { key: "collected", label: "وصول‌شده" }, { key: "receivables", label: "مانده مطالبات" }] },
        { title: "میانگین قیمت هر تن", scope: "people", metrics: [{ key: "price_per_ton", label: "قیمت هر تن" }] },
      ]
    : [
        { title: "تعداد تماس", scope: "people", metrics: [{ key: "calls", label: "تعداد تماس" }] },
        { title: "نرخ تماس موفق", scope: "people", percent: true,
          metrics: [{ key: "call_conversion", label: "تماس به فروش", percent: true }] },
      ];
  return [...base, ...tail];
});

const teamCharts = computed<ChartDef[]>(() => [
  { title: "فروش ریالی تیم‌ها", scope: "teams", metrics: [{ key: "revenue", label: "فروش ریالی" }] },
  { title: "تعداد فاکتور فروش", scope: "teams", metrics: [{ key: "invoices", label: "تعداد فاکتور" }] },
  { title: "مشتری فعال / مشتری جدید", scope: "teams", metrics: [
    { key: "active_customers", label: "مشتری فعال" }, { key: "new_customers", label: "مشتری جدید" }] },
  { title: "فروش در برابر تارگت", scope: "teams", metrics: [
    { key: "revenue", label: "فروش ریالی" }, { key: "target", label: "تارگت فروش" }] },
  { title: "سود / هزینه فروش", scope: "teams", metrics: [
    { key: "profit", label: "سود فروش" }, { key: "cost", label: "هزینه فروش" }] },
  { title: "نسبت تماس موفق", scope: "teams", metrics: [{ key: "success_call_ratio", label: "نسبت تماس موفق" }] },
  { title: "درصد تحقق تارگت", scope: "teams", percent: true,
    metrics: [{ key: "target_achievement", label: "تحقق تارگت", percent: true }] },
  { title: "سهم تیم از فروش به تارگت", scope: "teams", percent: true,
    metrics: [{ key: "share_of_total_target", label: "سهم از تارگت کل", percent: true }] },
  { title: "هزینه به فروش", scope: "teams", percent: true,
    metrics: [{ key: "cost_to_sales", label: "هزینه به فروش", percent: true }] },
]);

// ---- the charts that are not plain per-entity bars ------------------------
const names = computed(() => categoriesFor("people"));
const teamNames = computed(() => categoriesFor("teams"));

/** Top provinces by this month's sales; the same list is used for the
 *  comparison month so the bars line up rather than shifting under each other. */
const provinceCategories = computed(() => {
  const rows = [...(data.value?.provinces ?? [])].filter((p) => p.sales > 0);
  rows.sort((a, b) => b.sales - a.sales);
  return rows.slice(0, 12).map((p) => p.name);
});
const provinceChart: ChartDef = {
  title: "فروش و تارگت به تفکیک استان", scope: "provinces", height: 300,
  metrics: [{ key: "sales", label: "فروش" }, { key: "target", label: "تارگت" }],
};

const tehran = computed(() => (data.value?.provinces ?? []).find((p) => p.name.trim() === "تهران"));
const tehranB = computed(() => (dataB.value?.provinces ?? []).find((p) => p.name.trim() === "تهران"));
const tehranSeries = computed(() => {
  const a = data.value?.period.label;
  const out = [
    { name: dataB.value ? `فروش (${a})` : "فروش", values: [tehran.value?.sales ?? 0] },
    { name: dataB.value ? `تارگت (${a})` : "تارگت", values: [tehran.value?.target ?? 0] },
  ];
  if (dataB.value) {
    const b = dataB.value.period.label;
    out.push(
      { name: `فروش (${b})`, values: [tehranB.value?.sales ?? 0] },
      { name: `تارگت (${b})`, values: [tehranB.value?.target ?? 0] },
    );
  }
  return out;
});

/**
 * Share of volume, per month.
 *
 * A pie shows one whole split into parts, so two months cannot share one —
 * the slices would no longer sum to anything. When comparing, the chart
 * becomes two donuts side by side, which is what you actually want to look
 * at: the same names in the same colours, two shapes to eyeball.
 */
function volumeShareOf(d: Detail | null) {
  return [{
    name: "سهم",
    values: names.value.map((n) =>
      Number(rowsOf(d, "people").find((p) => p.name === n)?.volume_share ?? 0)),
  }];
}
const volumeShare = computed(() => volumeShareOf(data.value));
const volumeShareB = computed(() => volumeShareOf(dataB.value));

const totalRevenue = computed(() =>
  (data.value?.salespeople ?? []).reduce((s, p) => s + Number(p.revenue || 0), 0),
);

/* ==========================================================================
 * Multi-month close-up.
 *
 * The checkbox above answers "this month against that one". When the manager
 * wants several at once, cramming them into twenty small cards makes all
 * twenty unreadable — so the months are chosen here and one chart is opened
 * big across them.
 * ======================================================================== */
const compareMonths = ref<number[]>([]);
const compareOpen = ref<{ spec: CompareSpec; title: string } | null>(null);

function toggleCompareMonth(id: number) {
  const i = compareMonths.value.indexOf(id);
  if (i >= 0) compareMonths.value.splice(i, 1);
  else compareMonths.value.push(id);
  compareMonths.value.sort(
    (a, b) => periods.value.findIndex((p) => p.id === a) - periods.value.findIndex((p) => p.id === b),
  );
}

function openCompare(spec: CompareSpec, title: string) {
  // Opening with nothing chosen would show an empty modal; fall back to the
  // month on screen plus the one before it.
  if (!compareMonths.value.length && periodA.value) {
    const i = periods.value.findIndex((p) => p.id === periodA.value);
    compareMonths.value = [periods.value[i - 1]?.id, periodA.value].filter(Boolean) as number[];
  }
  compareOpen.value = { spec, title };
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  // Main period = latest month that has data; comparison starts unset.
  periodA.value = defaultPeriodId(periods.value);
  periodB.value = null;
  await Promise.all([load(), loadProgress()]);
});
watch([periodA, periodB, compare, weekId, () => props.channel], load);
// Changing the month reloads the strip and drops any week drill-down.
watch([periodA, () => props.channel], () => {
  weekId.value = null;
  loadProgress();
});
</script>

<template>
  <div class="space-y-4">
    <!-- Header: month picker + comparison toggle -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">{{ title }}</h2>
        <p v-if="data" class="text-xs text-slate-400 mt-0.5">
          فروش کل این کانال: <span class="ltr-nums">{{ rial(totalRevenue) }}</span>
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <ExportActions :section="channel" :period="periodA" />
        <select v-model.number="periodA" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <label class="flex items-center gap-1.5 text-sm text-slate-500 bg-surface border border-slate-200 rounded-xl px-3 py-1.5 cursor-pointer hover:bg-slate-50 transition-colors">
          <input v-model="compare" type="checkbox" class="rounded accent-brand-600" /> مقایسه با ماه دیگر
        </label>
        <select
          v-if="compare"
          v-model.number="periodB"
          class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm"
        >
          <option :value="null">— ماه مقایسه —</option>
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <!-- Several months at once: choose here, then open any chart close-up -->
    <details class="bg-surface rounded-card shadow-soft no-print">
      <summary class="px-4 py-2.5 text-sm text-slate-500 cursor-pointer select-none flex items-center gap-2">
        <span>مقایسه چند ماه</span>
        <span v-if="compareMonths.length" class="text-[11px] bg-panel text-white rounded-full px-2 py-0.5">
          {{ compareMonths.length }} ماه
        </span>
        <span class="text-xs text-slate-300 mr-auto hidden sm:inline">
          ماه‌ها را انتخاب کنید، سپس روی «مقایسه ماه‌ها» در هر نمودار بزنید
        </span>
      </summary>
      <div class="px-4 pb-3 flex flex-wrap gap-1.5">
        <button
          v-for="p in periods" :key="p.id"
          class="text-xs rounded-xl px-3 py-1.5 border transition-colors"
          :class="compareMonths.includes(p.id)
            ? 'bg-panel text-white border-panel'
            : 'bg-surface text-slate-500 border-slate-200 hover:bg-slate-50'"
          @click="toggleCompareMonth(p.id)"
        >{{ p.label }}</button>
        <button
          v-if="compareMonths.length"
          class="text-xs text-red-500 hover:bg-red-50 rounded-xl px-3 py-1.5"
          @click="compareMonths = []"
        >پاک کردن</button>
      </div>
    </details>

    <ChartCompareModal
      v-if="compareOpen"
      :spec="compareOpen.spec"
      :title="compareOpen.title"
      :channel="channel"
      :periods="periods"
      :selected="compareMonths"
      @update:selected="compareMonths = $event"
      @close="compareOpen = null"
    />

    <!-- Week strip: progress through the month + drill-down -->
    <div class="flex items-center gap-3 flex-wrap">
      <WeekProgress :progress="progress" :selected="weekId" @pick="pickWeek" />
      <button
        v-if="(progress?.weeks.length ?? 0) > 1"
        class="text-xs text-brand-600 hover:underline no-print"
        @click="showBreakdown = !showBreakdown"
      >{{ showBreakdown ? "بستن تفکیک هفته‌ها" : "تفکیک هفته‌ها و تقویم" }}</button>
    </div>

    <!-- Calendar + the proof that the weeks add up to the month -->
    <div
      v-if="showBreakdown && progress"
      class="bg-surface rounded-card shadow-soft p-5 grid grid-cols-1 lg:grid-cols-2 gap-6"
    >
      <PeriodCalendar
        :calendar="progress.calendar"
        :selected-week="progress.weeks.find(w => w.id === weekId)?.seq ?? null"
        @pick="(seq) => pickWeek(progress!.weeks.find(w => w.seq === seq)?.id ?? null)"
      />
      <div>
        <h4 class="font-semibold text-ink text-sm mb-3">کنترل مغایرت</h4>
        <ReconcilePanel :recon="progress.reconciliation" />
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1">
      <button
        class="px-4 py-1.5 rounded-xl text-sm"
        :class="tab === 'people' ? 'bg-panel text-white' : 'bg-surface border border-slate-200 hover:bg-slate-50'"
        @click="tab = 'people'"
      >داشبورد فروشنده</button>
      <button
        class="px-4 py-1.5 rounded-xl text-sm"
        :class="tab === 'teams' ? 'bg-panel text-white' : 'bg-surface border border-slate-200 hover:bg-slate-50'"
        @click="tab = 'teams'"
      >داشبورد تیم</button>
      <button
        class="px-4 py-1.5 rounded-xl text-sm"
        :class="tab === 'period' ? 'bg-panel text-white' : 'bg-surface border border-slate-200 hover:bg-slate-50'"
        @click="tab = 'period'"
      >گزارش دوره‌ای</button>
    </div>

    <!-- ========== گزارش دوره‌ای ==========
         A range of months rather than one, so it owns its own period picker
         and ignores the month selector above. -->
    <PeriodReport v-if="tab === 'period'" :channel="channel" />

    <DashboardSkeleton v-else-if="loading || !data" :cards="0" :charts="6" :table="false" />

    <!-- ========== داشبورد فروشنده ========== -->
    <template v-else-if="tab === 'people'">
      <div v-if="!names.length" class="bg-surface rounded-card shadow-soft">
        <EmptyState
          icon="📊"
          title="داده‌ای برای این ماه نیست"
          hint="برای این دوره هنوز فروش تاییدشده‌ای ثبت نشده است. پس از ثبت و تأیید داده، نمودارها اینجا ظاهر می‌شوند."
        />
      </div>
      <template v-else>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <SeriesChart
            v-for="def in peopleCharts" :key="def.title"
            :title="def.title"
            :categories="names"
            :series="seriesFor(def)"
            :percent="def.percent"
            :compare="specOf(def)"
            @compare="openCompare"
          />

          <!-- Share of volume: one whole split into parts. Two months cannot
               share a pie, so comparing splits it into two donuts. -->
          <template v-if="dataB">
            <SeriesChart
              :title="`درصد از حجم فروش — ${data.period.label}`" kind="pie" percent
              :categories="names" :series="volumeShare"
            />
            <SeriesChart
              :title="`درصد از حجم فروش — ${dataB.period.label}`" kind="pie" percent
              :categories="names" :series="volumeShareB"
            />
          </template>
          <SeriesChart
            v-else
            title="درصد از حجم فروش" kind="pie" percent
            :categories="names" :series="volumeShare"
          />
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SeriesChart
            :title="provinceChart.title" :height="provinceChart.height"
            :categories="provinceCategories"
            :series="seriesFor(provinceChart)"
            :compare="specOf(provinceChart)"
            @compare="openCompare"
          />
          <SeriesChart
            v-if="tehran"
            title="تهران — فروش در برابر تارگت" :height="300"
            :categories="['تهران']" :series="tehranSeries"
          />
        </div>
      </template>
    </template>

    <!-- ========== داشبورد تیم ========== -->
    <template v-else>
      <div v-if="!teamNames.length" class="bg-surface rounded-card shadow-soft">
        <EmptyState
          icon="📊"
          title="داده‌ای برای این ماه نیست"
          hint="برای این دوره هنوز فروش تیمی تاییدشده‌ای ثبت نشده است. پس از ثبت و تأیید داده، نمودارها اینجا ظاهر می‌شوند."
        />
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <SeriesChart
          v-for="def in teamCharts" :key="def.title"
          :title="def.title"
          :categories="teamNames"
          :series="seriesFor(def)"
          :percent="def.percent"
          :compare="specOf(def)"
          @compare="openCompare"
        />
      </div>
    </template>
      <!-- گزارش این بخش، روی همین صفحه: داشبورد و گزارش یک صفحه‌اند. -->
    <SectionBoard :section="boardSection" :period="periodA" />
</div>
</template>
