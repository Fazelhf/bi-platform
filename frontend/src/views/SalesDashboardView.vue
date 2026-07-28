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
import { rial } from "@/utils/format";

/**
 * Mirrors the workbook's two chart sheets:
 *   داشبورد فروشنده — 11 charts (9 per-salesperson + 2 provincial)
 *   داشبورد تیم     — 9 charts across the 5 teams
 */
const props = withDefaults(defineProps<{ channel?: string; title?: string }>(), {
  channel: "team",
  title: "داشبورد فروش",
});

interface Detail {
  period: { id: number; label: string };
  salespeople: Record<string, any>[];
  teams: Record<string, any>[];
  provinces: { name: string; sales: number; target: number }[];
}

const periods = ref<Period[]>([]);
const periodA = ref<number | null>(null);
const data = ref<Detail | null>(null);
const tab = ref<"people" | "teams">("people");
const loading = ref(false);

/**
 * Multi-month comparison.
 *
 * The old design was a checkbox plus one other month, and it only reached the
 * six charts built through the series helpers — the rest (سود/هزینه,
 * فاکتور/مشتری, استان, پای) ignored it entirely, which is why comparison
 * looked broken. Two months was also never what was asked for.
 *
 * Now: choose any number of months here, then open a single chart close-up to
 * see it across them. Twenty small cards each carrying five months would be
 * unreadable; one big chart carrying five months is exactly the question.
 */
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
  } finally {
    loading.value = false;
  }
}

function pickWeek(id: number | null) {
  weekId.value = id;
}

// ---- helpers to build a chart series (with optional comparison month) ----
const names = computed(() => (data.value?.salespeople ?? []).map((s) => s.name));
const teamNames = computed(() => (data.value?.teams ?? []).map((t) => t.name));

function peopleSeries(label: string, key: string) {
  return [{ name: label, values: (data.value?.salespeople ?? []).map((p) => p[key]) }];
}
function teamSeries(label: string, key: string) {
  return [{ name: label, values: (data.value?.teams ?? []).map((t) => t[key]) }];
}

/** Shorthand for the compare spec each chart carries. */
function ppl(...metrics: { key: string; label: string; percent?: boolean }[]): CompareSpec {
  return { scope: "people", metrics };
}
function tm(...metrics: { key: string; label: string; percent?: boolean }[]): CompareSpec {
  return { scope: "teams", metrics };
}

// B2B is wholesale on credit: tonnage and collection replace call activity,
// and the counterparty is a company rather than a retail customer.
const isB2B = computed(() => props.channel === "b2b");
const buyer = computed(() => (isB2B.value ? "شرکت" : "مشتری"));

// Top provinces with any sales (chart 10) + Tehran highlight (chart 11)
const topProvinces = computed(() => (data.value?.provinces ?? []).filter((p) => p.sales > 0).slice(0, 12));
const tehran = computed(() => (data.value?.provinces ?? []).find((p) => p.name.trim() === "تهران"));

const totalRevenue = computed(() =>
  (data.value?.salespeople ?? []).reduce((s, p) => s + Number(p.revenue || 0), 0),
);

onMounted(async () => {
  periods.value = await salesApi.periods();
  // Main period = latest month that has data; comparison starts unset.
  periodA.value = defaultPeriodId(periods.value);
  await Promise.all([load(), loadProgress()]);
});
watch([periodA, weekId, () => props.channel], load);
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
      </div>
    </div>

    <!-- Multi-month comparison: pick the months here, then open any chart -->
    <details class="bg-surface rounded-card shadow-soft no-print">
      <summary class="px-4 py-2.5 text-sm text-slate-500 cursor-pointer select-none flex items-center gap-2">
        <span>مقایسه چند ماه</span>
        <span v-if="compareMonths.length" class="text-[11px] bg-panel text-white rounded-full px-2 py-0.5">
          {{ compareMonths.length }} ماه
        </span>
        <span class="text-xs text-slate-300 mr-auto">
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
    </div>

    <DashboardSkeleton v-if="loading || !data" :cards="0" :charts="6" :table="false" />

    <!-- ========== داشبورد فروشنده — 11 charts ========== -->
    <template v-else-if="tab === 'people'">
      <div v-if="!data.salespeople.length" class="bg-surface rounded-card shadow-soft">
        <EmptyState
          icon="📊"
          title="داده‌ای برای این ماه نیست"
          hint="برای این دوره هنوز فروش تاییدشده‌ای ثبت نشده است. پس از ثبت و تأیید داده، نمودارها اینجا ظاهر می‌شوند."
        />
      </div>
      <template v-else>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <SeriesChart title="فروش ریالی" :categories="names" :series="peopleSeries('فروش ریالی', 'revenue')"
            :compare="ppl({ key: 'revenue', label: 'فروش ریالی' })" @compare="openCompare" />
          <SeriesChart :title="`تعداد ${buyer} جدید`" :categories="names" :series="peopleSeries(`${buyer} جدید`, 'new_customers')"
            :compare="ppl({ key: 'new_customers', label: `${buyer} جدید` })" @compare="openCompare" />
          <SeriesChart title="سود فروش" :categories="names" :series="peopleSeries('سود فروش', 'profit')"
            :compare="ppl({ key: 'profit', label: 'سود فروش' })" @compare="openCompare" />
          <SeriesChart
            title="درصد از حجم فروش" kind="pie" percent
            :categories="names" :series="[{ name: 'سهم', values: data.salespeople.map(p => p.volume_share) }]"
          />
          <SeriesChart
            title="هزینه / سود فروش" :categories="names"
            :compare="ppl({ key: 'profit', label: 'سود فروش' }, { key: 'cost', label: 'هزینه فروش' })" @compare="openCompare"
            :series="[
              { name: 'سود فروش', values: data.salespeople.map(p => p.profit) },
              { name: 'هزینه فروش', values: data.salespeople.map(p => p.cost) },
            ]"
          />
          <SeriesChart
            :title="`تعداد فروش / تعداد ${buyer}`" :categories="names"
            :compare="ppl({ key: 'invoices', label: isB2B ? 'تعداد قرارداد' : 'تعداد فاکتور' }, { key: 'active_customers', label: `${buyer} فعال` })" @compare="openCompare"
            :series="[
              { name: isB2B ? 'تعداد قرارداد' : 'تعداد فاکتور', values: data.salespeople.map(p => p.invoices) },
              { name: `${buyer} فعال`, values: data.salespeople.map(p => p.active_customers) },
            ]"
          />
          <SeriesChart title="درصد رسیدن به تارگت" percent :categories="names" :series="peopleSeries('تحقق تارگت', 'target_achievement')"
            :compare="ppl({ key: 'target_achievement', label: 'تحقق تارگت', percent: true })" @compare="openCompare" />

          <!-- B2B tracks tonnage + collection; the other channels track calls -->
          <template v-if="isB2B">
            <SeriesChart title="مقدار فروش (تن)" :categories="names" :series="peopleSeries('تناژ فروش', 'quantity_ton')"
              :compare="ppl({ key: 'quantity_ton', label: 'تناژ فروش' })" @compare="openCompare" />
            <SeriesChart title="نرخ وصول مطالبات" percent :categories="names" :series="peopleSeries('نرخ وصول', 'collection_rate')"
              :compare="ppl({ key: 'collection_rate', label: 'نرخ وصول', percent: true })" @compare="openCompare" />
            <SeriesChart
              title="وصول‌شده / مانده مطالبات" :categories="names"
              :compare="ppl({ key: 'collected', label: 'وصول‌شده' }, { key: 'receivables', label: 'مانده مطالبات' })" @compare="openCompare"
              :series="[
                { name: 'وصول‌شده', values: data.salespeople.map(p => p.collected) },
                { name: 'مانده مطالبات', values: data.salespeople.map(p => p.receivables) },
              ]"
            />
            <SeriesChart title="میانگین قیمت هر تن" :categories="names" :series="peopleSeries('قیمت هر تن', 'price_per_ton')"
              :compare="ppl({ key: 'price_per_ton', label: 'قیمت هر تن' })" @compare="openCompare" />
          </template>
          <template v-else>
            <SeriesChart title="تعداد تماس" :categories="names" :series="peopleSeries('تعداد تماس', 'calls')"
              :compare="ppl({ key: 'calls', label: 'تعداد تماس' })" @compare="openCompare" />
            <SeriesChart title="نرخ تماس موفق" percent :categories="names" :series="peopleSeries('تماس به فروش', 'call_conversion')"
              :compare="ppl({ key: 'call_conversion', label: 'نرخ تماس موفق', percent: true })" @compare="openCompare" />
          </template>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SeriesChart
            title="فروش و تارگت به تفکیک استان" :height="300"
            :compare="{ scope: 'provinces', metrics: [{ key: 'sales', label: 'فروش' }, { key: 'target', label: 'تارگت' }] }" @compare="openCompare"
            :categories="topProvinces.map(p => p.name)"
            :series="[
              { name: 'فروش', values: topProvinces.map(p => p.sales) },
              { name: 'تارگت', values: topProvinces.map(p => p.target) },
            ]"
          />
          <SeriesChart
            v-if="tehran"
            title="تهران — فروش در برابر تارگت" :height="300"
            :categories="['تهران']"
            :series="[
              { name: 'فروش', values: [tehran.sales] },
              { name: 'تارگت', values: [tehran.target] },
            ]"
          />
        </div>
      </template>
    </template>

    <!-- ========== داشبورد تیم — 9 charts ========== -->
    <template v-else>
      <div v-if="!data.teams.length" class="bg-surface rounded-card shadow-soft">
        <EmptyState
          icon="📊"
          title="داده‌ای برای این ماه نیست"
          hint="برای این دوره هنوز فروش تیمی تاییدشده‌ای ثبت نشده است. پس از ثبت و تأیید داده، نمودارها اینجا ظاهر می‌شوند."
        />
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <SeriesChart title="فروش ریالی تیم‌ها" :categories="teamNames" :series="teamSeries('فروش ریالی', 'revenue')"
          :compare="tm({ key: 'revenue', label: 'فروش ریالی' })" @compare="openCompare" />
        <SeriesChart title="تعداد فاکتور فروش" :categories="teamNames" :series="teamSeries('تعداد فاکتور', 'invoices')"
          :compare="tm({ key: 'invoices', label: 'تعداد فاکتور' })" @compare="openCompare" />
        <SeriesChart
          title="مشتری فعال / مشتری جدید" :categories="teamNames"
          :compare="tm({ key: 'active_customers', label: 'مشتری فعال' }, { key: 'new_customers', label: 'مشتری جدید' })" @compare="openCompare"
          :series="[
            { name: 'مشتری فعال', values: data.teams.map(t => t.active_customers) },
            { name: 'مشتری جدید', values: data.teams.map(t => t.new_customers) },
          ]"
        />
        <SeriesChart
          title="فروش در برابر تارگت" :categories="teamNames"
          :compare="tm({ key: 'revenue', label: 'فروش ریالی' }, { key: 'target', label: 'تارگت فروش' })" @compare="openCompare"
          :series="[
            { name: 'فروش ریالی', values: data.teams.map(t => t.revenue) },
            { name: 'تارگت فروش', values: data.teams.map(t => t.target) },
          ]"
        />
        <SeriesChart
          title="سود / هزینه فروش" :categories="teamNames"
          :compare="tm({ key: 'profit', label: 'سود فروش' }, { key: 'cost', label: 'هزینه فروش' })" @compare="openCompare"
          :series="[
            { name: 'سود فروش', values: data.teams.map(t => t.profit) },
            { name: 'هزینه فروش', values: data.teams.map(t => t.cost) },
          ]"
        />
        <SeriesChart title="نسبت تماس موفق" :categories="teamNames" :series="teamSeries('نسبت تماس موفق', 'success_call_ratio')"
          :compare="tm({ key: 'success_call_ratio', label: 'نسبت تماس موفق' })" @compare="openCompare" />
        <SeriesChart title="درصد تحقق تارگت" percent :categories="teamNames" :series="teamSeries('تحقق تارگت', 'target_achievement')"
          :compare="tm({ key: 'target_achievement', label: 'تحقق تارگت', percent: true })" @compare="openCompare" />
        <SeriesChart title="سهم تیم از فروش به تارگت" percent :categories="teamNames" :series="teamSeries('سهم از تارگت کل', 'share_of_total_target')"
          :compare="tm({ key: 'share_of_total_target', label: 'سهم از تارگت کل', percent: true })" @compare="openCompare" />
        <SeriesChart title="هزینه به فروش" percent :categories="teamNames" :series="teamSeries('هزینه به فروش', 'cost_to_sales')"
          :compare="tm({ key: 'cost_to_sales', label: 'هزینه به فروش', percent: true })" @compare="openCompare" />
      </div>
    </template>
  </div>
</template>
