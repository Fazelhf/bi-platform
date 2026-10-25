<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmDashboard, type DashCard, type ReportRow } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { num, pct, rial } from "@/utils/format";
import CrmChart from "@/components/crm/CrmChart.vue";
import CrmExportButton from "@/components/crm/CrmExportButton.vue";
import FunnelChart from "@/components/crm/FunnelChart.vue";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import CustomerForm from "@/components/crm/CustomerForm.vue";
import DealForm from "@/components/crm/DealForm.vue";
import ActivityForm from "@/components/crm/ActivityForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * داشبورد CRM — the home screen.
 *
 * Every tile and every bar is clickable: the click opens the records behind
 * the figure. That is the whole difference from the tool this replaces, where
 * the same widgets existed but dead-ended.
 */
const crm = useCrmStore();
const router = useRouter();
const data = ref<CrmDashboard | null>(null);
const loading = ref(true);

/**
 * `crm.query` is a getter that builds a fresh object on every read, so a deep
 * watch on it fired for any store change at all — and opening the page ran
 * this query three times: once on mount, once when loadOptions filled in the
 * months the query is derived from, once more when the shell's own lookup call
 * landed. Three identical passes over sixteen months of CRM data, on a phone.
 * Comparing the serialised query instead means a fetch happens when the
 * question changes and not when the object identity does.
 */
let lastKey = "";

async function load(force = false) {
  const key = JSON.stringify(crm.query);
  if (!force && key === lastKey) return;
  lastKey = key;
  loading.value = true;
  try {
    data.value = await crmApi.dashboard(crm.query);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await crm.loadOptions(); await load(); });
// Something was saved from the global «ثبت جدید» button over the top of this
// page; the list under it is now stale.
watch(() => crm.revision, () => load());

watch(() => JSON.stringify(crm.query), () => load());

function cardValue(c: DashCard): string {
  if (c.unit === "rial") return rial(c.value);
  if (c.unit === "percent") return pct(c.value);
  if (c.unit === "days") return `${num(c.value)} روز`;
  return num(c.value);
}

function cardSub(c: DashCard): string {
  const s = c.sub ?? {};
  // Keyed by card, not guessed from which fields `sub` happens to carry: two
  // cards now both send `count`, and the shape-sniffing below gave the sales
  // card the pipeline's «معامله · وزنی» caption.
  if (c.key === "sales") {
    // The reconciliation, in one line: add the intercompany figure back and
    // this card equals آرپا's own total for the window.
    const parts = [`${num(s.count)} فاکتور`];
    if (s.intercompany) parts.push(`فی‌مابین جدا ${rial(s.intercompany)}`);
    if (s.unmatched) parts.push(`${rial(s.unmatched)} در انتظار تطبیق`);
    return parts.join(" · ");
  }
  if (c.key === "unbilled") return `${num(s.count)} معامله موفق بدون فاکتور`;
  if (s.amount !== undefined) return rial(s.amount);
  if (s.margin_pct !== undefined) return `حاشیه ${pct(s.margin_pct)}`;
  if (s.won !== undefined) return `${num(s.won)} از ${num(s.closed)} معامله بسته‌شده`;
  if (s.calls !== undefined) return `${num(s.success)} موفق از ${num(s.calls)} تماس`;
  if (s.count !== undefined) return `${num(s.count)} معامله · وزنی ${rial(s.weighted ?? 0)}`;
  return "";
}

const CARD_STYLE: Record<string, { accent: string; icon: string }> = {
  incoming: { accent: "text-sky-600", icon: "M12 5v14M5 12h14" },
  sales: { accent: "text-emerald-600", icon: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h6M9 17h6" },
  unbilled: { accent: "text-amber-600", icon: "M12 8v4M12 16h.01M4 4h16v16H4z" },
  lost: { accent: "text-red-500", icon: "M18 6L6 18M6 6l12 12" },
  profit: { accent: "text-emerald-600", icon: "M3 17l6-6 4 4 7-7" },
  pipeline: { accent: "text-violet-600", icon: "M4 6h16M7 12h10M10 18h4" },
  conversion: { accent: "text-amber-600", icon: "M4 4v16h16" },
  velocity: { accent: "text-sky-600", icon: "M12 8v4l3 2" },
  new_customers: { accent: "text-teal-600", icon: "M16 21v-2a4 4 0 00-8 0v2M12 3a4 4 0 100 8 4 4 0 000-8z" },
  calls: { accent: "text-indigo-600", icon: "M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7l.6 2.5a2 2 0 01-.5 1.9L8 9.3a16 16 0 006 6l1.2-1.2a2 2 0 011.9-.5l2.5.6a2 2 0 011.7 2z" },
  overdue: { accent: "text-orange-600", icon: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" },
};

/**
 * Where a card goes when it has no records of its own to list.
 *
 * A rate or an average is not a set of rows — «نرخ تبدیل» is a ratio of two
 * counts — so there is nothing to drill into. It still opens: onto the report
 * that breaks it down, which is where the next question about it gets
 * answered. A tile that looks like a button and does nothing reads as broken.
 */
const CARD_TARGET: Record<string, { name: string; query?: Record<string, string> }> = {
  conversion: { name: "crm-reports", query: { report: "conversion", axis: "time" } },
  velocity: { name: "crm-reports", query: { report: "conversion", axis: "user" } },
  overdue: { name: "crm-activities", query: { tab: "tasks" } },
};

/**
 * Which way is good. A fall in «معاملات شکست خورده» or «چرخه فروش» is the
 * news a manager wants, so the chip turns green going down for those.
 */
const LOWER_IS_BETTER = new Set(["lost", "velocity", "overdue", "unbilled"]);

/** The four that answer «how are we doing»; the rest are the detail. */
const HERO = ["sales", "profit", "pipeline", "conversion"];
const heroCards = computed(() =>
  HERO.map((k) => data.value?.cards.find((c) => c.key === k)).filter(Boolean) as DashCard[],
);
const minorCards = computed(() => data.value?.cards.filter((c) => !HERO.includes(c.key)) ?? []);

interface Delta { text: string; good: boolean; flat: boolean }
function delta(c: DashCard): Delta | null {
  if (c.prev === null || c.prev === undefined) return null;
  const now = Number(c.value), before = Number(c.prev);
  // A rate is compared in points; «۱۲٪ ← ۲۰٪» is +8 points, not +67%.
  if (c.unit === "percent") {
    const d = now - before;
    return {
      text: `${d >= 0 ? "+" : "−"}${num(Math.abs(Math.round(d * 10) / 10))} واحد`,
      good: (d >= 0) !== LOWER_IS_BETTER.has(c.key),
      flat: Math.abs(d) < 0.05,
    };
  }
  if (!before) return now ? { text: "جدید", good: !LOWER_IS_BETTER.has(c.key), flat: false } : null;
  const d = ((now - before) / Math.abs(before)) * 100;
  return {
    text: `${d >= 0 ? "▲" : "▼"} ${pct(Math.abs(d), Math.abs(d) >= 10 ? 0 : 1)}`,
    good: (d >= 0) !== LOWER_IS_BETTER.has(c.key),
    flat: Math.abs(d) < 0.5,
  };
}

function prevText(c: DashCard): string {
  if (c.prev === null || c.prev === undefined) return "";
  return `دوره قبل: ${cardValue({ ...c, value: c.prev })}`;
}

/** A tiny trend under a headline figure — the shape, not the numbers. */
const SPARK: Record<string, () => number[]> = {
  sales: () => data.value?.trend.map((r) => Number(r.amount) || 0) ?? [],
  profit: () => data.value?.trend.map((r) => Number(r.profit) || 0) ?? [],
};
function spark(key: string): string {
  const v = SPARK[key]?.() ?? [];
  if (v.length < 2 || v.every((x) => !x)) return "";
  const max = Math.max(...v), min = Math.min(...v, 0), span = max - min || 1;
  return v.map((x, i) => `${(i / (v.length - 1)) * 100},${28 - ((x - min) / span) * 26}`).join(" ");
}

const target = computed(() => {
  const s = data.value?.cards.find((c) => c.key === "sales")?.sub;
  if (!s?.target) return null;
  return { target: s.target, achieved: s.achievement_pct ?? 0, elapsed: s.elapsed_pct ?? 100 };
});

const comparisonLabel = computed(() => {
  const c = data.value?.comparison;
  if (!c?.start || !c?.end) return "";
  const f = (iso: string) => new Date(iso).toLocaleDateString("fa-IR", { year: "numeric", month: "long", day: "numeric" });
  return `مقایسه با ${f(c.start)} تا ${f(c.end)}`;
});

function openCard(c: DashCard) {
  if (c.drill?.kind) crm.openDrill(c.drill, c.label);
  else if (CARD_TARGET[c.key]) router.push(CARD_TARGET[c.key]);
}

/** A widget's title opens its full module — the drill on a bar answers «which
 *  records», the title answers «show me all of this». */
function goReport(report: string, axis = "") {
  router.push({ name: "crm-reports", query: { report, ...(axis ? { axis } : {}) } });
}

function openRow(rows: ReportRow[], i: number, title: string) {
  const row = rows[i];
  if (row?.drill?.kind) crm.openDrill(row.drill, `${title} — ${row.label}`);
}

// ---- chart data -----------------------------------------------------------
const trendCats = computed(() => data.value?.trend.map((r) => r.label) ?? []);
// One series: sales are the invoices. Won deals are pipeline, not a second
// «sales» bar beside them.
const trendSeries = computed(() => [
  { name: "فروش", values: data.value?.trend.map((r) => r.amount) ?? [], color: "#22c55e" },
  { name: "سود", values: data.value?.trend.map((r) => r.profit) ?? [], type: "line" as const, color: "#0ea5e9" },
]);

const incomingCats = computed(() => data.value?.incoming_trend.map((r) => r.label) ?? []);
const incomingSeries = computed(() => [
  { name: "موفق", values: data.value?.incoming_trend.map((r) => r.won_count) ?? [], stack: "s", color: "#22c55e" },
  { name: "جاری", values: data.value?.incoming_trend.map((r) => r.open_count) ?? [], stack: "s", color: "#f59e0b" },
  { name: "ناموفق", values: data.value?.incoming_trend.map((r) => r.lost_count) ?? [], stack: "s", color: "#ef4444" },
]);

const sellerCats = computed(() => data.value?.top_sellers.map((r) => r.label) ?? []);
const sellerSeries = computed(() => [
  { name: "فروش", values: data.value?.top_sellers.map((r) => r.amount) ?? [], color: "#22c55e" },
]);

const funnelRows = computed(() => data.value?.funnel.filter((r) => r.kind === "open") ?? []);

const lostCats = computed(() => data.value?.lost_reasons.map((r) => r.label) ?? []);
const lostSeries = computed(() => [
  { name: "تعداد", values: data.value?.lost_reasons.map((r) => r.count) ?? [], color: "#ef4444" },
]);

const actCats = computed(() => data.value?.activities_by_kind.map((r) => r.label) ?? []);
const actSeries = computed(() => [
  { name: "تعداد", values: data.value?.activities_by_kind.map((r) => r.count) ?? [], color: "#6366f1" },
]);

const activeCats = computed(() => data.value?.top_active.map((r) => r.label) ?? []);
const activeSeries = computed(() => [
  { name: "فعالیت", values: data.value?.top_active.map((r) => r.count) ?? [], color: "#14b8a6" },
]);

const newCustCats = computed(() => data.value?.new_customers_by_user.map((r) => r.label) ?? []);
const newCustSeries = computed(() => [
  { name: "مشتری جدید", values: data.value?.new_customers_by_user.map((r) => r.count) ?? [], color: "#0d9488" },
]);

const groupCats = computed(() => data.value?.by_group.map((r) => r.label) ?? []);
const groupSeries = computed(() => [
  { name: "فروش", values: data.value?.by_group.map((r) => r.amount) ?? [] },
]);

/**
 * `min-w-0` is load-bearing, not decoration.
 *
 * These cards are grid items, and a grid item's automatic minimum size is its
 * content — so the card holding «فروش و تارگت استان‌ها», whose table is
 * `min-w-[420px]` to stay readable, demanded 452px of column. On a desktop
 * there is 452px to give. On a phone there are 351, and since every item in a
 * one-column grid shares that one column, the table's demand widened the chart
 * card sitting next to it: the whole CRM page hung 89px off the side of the
 * screen and scrolled sideways into nothing. The table still scrolls inside
 * its own `overflow-x-auto`; it just no longer sets the width of the page.
 */
const card = "bg-surface rounded-card shadow-soft p-4 flex flex-col min-w-0";

/**
 * One chart height per row rather than per chart.
 *
 * The page had five heights (270/240/230/220/260) scattered across five rows,
 * so every row ended on a different line and the whole grid looked like it
 * had been assembled from spare parts. Cards in a row are the same height by
 * construction now; `flex flex-col` on the card lets the chart take whatever
 * the tallest sibling leaves.
 */
const H_MAIN = 280;
const H_WIDE = 250;

// Quick entry straight from the home screen.
const modal = ref<"customer" | "deal" | "activity" | null>(null);
async function onSaved(id?: number) {
  const kind = modal.value;
  modal.value = null;
  if (kind === "deal" && id) {
    router.push({ name: "crm-deal", params: { id } });
    return;
  }
  if (kind === "customer" && id) {
    router.push({ name: "crm-customer", params: { id } });
    return;
  }
  // A new record does not change the question, so this one must be forced.
  await load(true);
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="crm.canEdit" class="flex flex-wrap items-center gap-2 no-print">
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="modal = 'activity'">ثبت فعالیت</button>
      <button class="bg-surface shadow-soft text-slate-600 hover:text-ink rounded-xl px-4 py-2 text-sm" @click="modal = 'deal'">+ معامله</button>
      <button class="bg-surface shadow-soft text-slate-600 hover:text-ink rounded-xl px-4 py-2 text-sm" @click="modal = 'customer'">+ مشتری</button>
      <span class="text-xs text-slate-400">
        {{ crm.me?.employee_name ? `ثبت به نام ${crm.me.employee_name}` : "" }}
      </span>
    </div>

    <CustomerForm v-if="modal === 'customer'" @close="modal = null" @saved="onSaved" />
    <DealForm v-if="modal === 'deal'" @close="modal = null" @saved="onSaved" />
    <ActivityForm v-if="modal === 'activity'" @close="modal = null" @saved="onSaved" />

    <div class="flex justify-end no-print -mb-2">
      <CrmExportButton url="/crm/dashboard/export/" :params="crm.query" title="داشبورد CRM" :total="data?.cards.length ?? 0" subtle />
    </div>
    <CrmFilterBar />

    <!-- ============ Headline KPIs ============ -->
    <div class="flex items-baseline justify-between gap-2 px-1">
      <h2 class="section-title">نمای کلی</h2>
      <p v-if="comparisonLabel" class="text-[11px] text-slate-400">{{ comparisonLabel }}</p>
    </div>
    <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
      <Skeleton v-for="i in 4" :key="i" class="h-36 rounded-card" />
    </div>
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
      <button
        v-for="c in heroCards" :key="c.key"
        class="kpi bg-surface rounded-card shadow-soft p-4 text-right flex flex-col"
        :class="c.drill?.kind || CARD_TARGET[c.key] ? 'cursor-pointer' : 'cursor-default'"
        @click="openCard(c)"
      >
        <div class="flex items-center justify-between gap-2 w-full">
          <span class="flex items-center gap-2 text-xs text-slate-500">
            <span class="w-7 h-7 rounded-xl grid place-items-center kpi-icon" :class="CARD_STYLE[c.key]?.accent">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path :d="CARD_STYLE[c.key]?.icon" /></svg>
            </span>
            {{ c.label }}
          </span>
          <span
            v-if="delta(c)"
            class="text-[11px] font-medium rounded-full px-2 py-0.5 whitespace-nowrap"
            :class="delta(c)!.flat ? 'bg-slate-100 text-slate-500' : delta(c)!.good ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-500'"
            :title="prevText(c)"
          >{{ delta(c)!.text }}</span>
        </div>
        <p class="text-2xl font-bold text-ink mt-3 tracking-tight">{{ cardValue(c) }}</p>
        <p class="text-[11px] text-slate-400 mt-1 truncate w-full">{{ cardSub(c) }}</p>

        <!-- Sales carries its plan: how far along, and where it should be by now. -->
        <div v-if="c.key === 'sales' && target" class="mt-auto pt-3 w-full">
          <div class="flex justify-between text-[11px] text-slate-400 mb-1">
            <span>تحقق تارگت {{ pct(target.achieved) }}</span>
            <span>{{ rial(target.target) }}</span>
          </div>
          <div class="relative h-1.5 rounded-full bg-slate-100">
            <div
              class="absolute inset-y-0 right-0 rounded-full transition-all duration-700"
              :class="target.achieved >= target.elapsed ? 'bg-emerald-500' : 'bg-amber-500'"
              :style="{ width: `${Math.min(100, target.achieved)}%` }"
            ></div>
            <span
              v-if="target.elapsed < 100"
              class="absolute -top-1 w-0.5 h-3.5 bg-slate-400 rounded"
              :style="{ right: `${target.elapsed}%` }"
              :title="`${pct(target.elapsed, 0)} از بازه گذشته است`"
            ></span>
          </div>
        </div>
        <svg v-else-if="spark(c.key)" class="mt-auto pt-3 w-full h-9" viewBox="0 0 100 30" preserveAspectRatio="none">
          <polyline :points="spark(c.key)" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" :class="CARD_STYLE[c.key]?.accent" />
        </svg>
        <p v-else class="mt-auto pt-3 text-[11px] text-slate-400 truncate w-full">{{ prevText(c) }}</p>
      </button>
    </div>

    <!-- ============ Secondary KPIs ============ -->
    <div v-if="!loading" class="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-3">
      <button
        v-for="c in minorCards" :key="c.key"
        class="kpi bg-surface rounded-card shadow-soft px-3.5 py-3 text-right"
        :class="c.drill?.kind || CARD_TARGET[c.key] ? 'cursor-pointer' : 'cursor-default'"
        :title="prevText(c)"
        @click="openCard(c)"
      >
        <p class="text-[11px] text-slate-400 truncate">{{ c.label }}</p>
        <div class="flex items-baseline justify-between gap-1 mt-1">
          <p class="text-base font-bold" :class="CARD_STYLE[c.key]?.accent ?? 'text-ink'">{{ cardValue(c) }}</p>
          <span
            v-if="delta(c) && !delta(c)!.flat"
            class="text-[10px] font-medium whitespace-nowrap"
            :class="delta(c)!.good ? 'text-emerald-600' : 'text-red-500'"
          >{{ delta(c)!.text }}</span>
        </div>
        <p class="text-[10px] text-slate-400 mt-0.5 truncate">{{ cardSub(c) }}</p>
      </button>
    </div>

    <h2 class="section-title px-1 pt-2">روند و کاریز</h2>
    <!-- ============ Trend + incoming ============ -->
    <div class="grid lg:grid-cols-2 gap-4">
      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('sales', 'time')">روند فروش</button>
        <CrmChart
          :categories="trendCats" :series="trendSeries" format="rial" :height="H_MAIN"
          @pick="(i) => openRow(data!.trend, i, 'فروش ماه')"
        />
      </div>

      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('incoming', 'time')">معامله‌های جدید به تفکیک وضعیت</button>
        <CrmChart
          :categories="incomingCats" :series="incomingSeries" format="count" :height="H_MAIN"
          @pick="(i) => openRow(data!.incoming_trend, i, 'معامله‌های جدید')"
        />
      </div>
    </div>

    <!-- ============ Funnel + sellers ============ -->
    <div class="grid lg:grid-cols-2 gap-4">
      <div :class="card">
        <div class="flex flex-wrap items-baseline justify-between gap-2 mb-3">
          <button type="button" class="widget-title text-sm font-semibold text-ink" @click="router.push({ name: 'crm-pipeline' })">قیف فروش</button>
          <p class="text-[11px] text-slate-400">رسیده · همین‌جا</p>
        </div>
        <FunnelChart
          :stages="funnelRows"
          @pick="(s) => crm.openDrill(s.drill!, `مرحله فروش — ${s.label}`)"
        />
      </div>

      <!-- A ranking of one is not a ranking. A کارشناس only ever appears in
           their own rows, so these three charts would each draw a single bar
           labelled with the reader's own name. -->
      <div v-if="crm.seesAll" :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('sales', 'user')">بهترین فروشنده‌ها</button>
        <CrmChart
          :categories="sellerCats" :series="sellerSeries" format="rial" :height="H_WIDE" horizontal
          @pick="(i) => openRow(data!.top_sellers, i, 'فروش کارشناس')"
        />
      </div>
    </div>

    <h2 class="section-title px-1 pt-2">کیفیت فروش و منابع</h2>
    <!-- ============ Lost reasons / activities / sources ============ -->
    <div class="grid lg:grid-cols-3 gap-4">
      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('lost', 'reason')">اصلی‌ترین دلایل از دست رفتن</button>
        <CrmChart
          v-if="lostCats.length" :categories="lostCats" :series="lostSeries"
          format="count" :height="H_WIDE" horizontal
          @pick="(i) => openRow(data!.lost_reasons, i, 'دلیل از دست رفتن')"
        />
        <EmptyState v-else title="معامله شکست‌خورده‌ای نیست" />
      </div>

      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="router.push({ name: 'crm-activities' })">فعالیت‌های انجام شده</button>
        <CrmChart
          :categories="actCats" :series="actSeries" format="count" :height="H_WIDE" horizontal
          @pick="(i) => openRow(data!.activities_by_kind, i, 'فعالیت')"
        />
      </div>

      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('sources')">بهترین منابع سرنخ</button>
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-400">
              <th class="text-right font-medium pb-2">شیوه</th>
              <th class="text-left font-medium pb-2">فروش</th>
              <th class="text-left font-medium pb-2">تبدیل</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in data?.sources" :key="String(s.id)"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="crm.openDrill(s.drill!, `منبع سرنخ — ${s.label}`)"
            >
              <td class="py-2 text-slate-600">{{ s.label }}</td>
              <td class="py-2 text-left text-ink whitespace-nowrap">{{ rial(s.amount) }}</td>
              <td class="py-2 text-left" :class="s.conversion_pct >= 40 ? 'text-emerald-600' : 'text-slate-500'">
                {{ pct(s.conversion_pct) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ People ============ -->
    <h2 v-if="crm.seesAll" class="section-title px-1 pt-2">تیم فروش</h2>
    <div v-if="crm.seesAll" class="grid lg:grid-cols-3 gap-4">
      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('activities', 'user')">فعال‌ترین کارشناسان</button>
        <CrmChart
          :categories="activeCats" :series="activeSeries" format="count" :height="H_WIDE" horizontal
          @pick="(i) => openRow(data!.top_active, i, 'فعالیت‌های')"
        />
      </div>

      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('new_customers', 'user')">مشتریان جدید بر اساس کارشناس</button>
        <CrmChart
          :categories="newCustCats" :series="newCustSeries" format="count" :height="H_WIDE" horizontal
          @pick="(i) => openRow(data!.new_customers_by_user, i, 'مشتریان جدید')"
        />
      </div>

      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('satisfaction')">رضایت مشتری از کارشناسان</button>
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-400">
              <th class="text-right font-medium pb-2">کارشناس</th>
              <th class="text-left font-medium pb-2">میانگین</th>
              <th class="text-left font-medium pb-2">ناراضی</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in data?.satisfaction" :key="String(s.id)"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="crm.openDrill(s.drill!, `بازخورد — ${s.label}`)"
            >
              <td class="py-2 text-slate-600">{{ s.label }}</td>
              <td class="py-2 text-left text-ink">{{ num(s.avg_score) }}</td>
              <td class="py-2 text-left" :class="s.unhappy ? 'text-red-500 font-medium' : 'text-slate-400'">
                {{ num(s.unhappy) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <h2 class="section-title px-1 pt-2">بازار و مشتری</h2>
    <!-- ============ Geography + segments ============ -->
    <div class="grid lg:grid-cols-2 gap-4">
      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="router.push({ name: 'crm-geo' })">فروش و تارگت استان‌ها · نقشه</button>
        <div class="overflow-x-auto">
          <table class="w-full text-xs min-w-[420px]">
            <thead>
              <tr class="text-slate-400">
                <th class="text-right font-medium pb-2">استان</th>
                <th class="text-right font-medium pb-2">کارشناس</th>
                <th class="text-left font-medium pb-2">فروش</th>
                <th class="text-left font-medium pb-2">تارگت</th>
                <th class="text-left font-medium pb-2">تحقق</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="p in data?.provinces" :key="String(p.id)"
                class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="crm.openDrill(p.drill!, `فروش استان ${p.label}`)"
              >
                <td class="py-2 text-ink">{{ p.label }}</td>
                <td class="py-2 text-slate-500 truncate max-w-[130px]">{{ p.owner_label }}</td>
                <td class="py-2 text-left text-ink whitespace-nowrap">{{ rial(p.amount) }}</td>
                <td class="py-2 text-left text-slate-400 whitespace-nowrap">{{ rial(p.target) }}</td>
                <td class="py-2 text-left font-medium" :class="p.achievement_pct >= 100 ? 'text-emerald-600' : p.achievement_pct >= 70 ? 'text-amber-600' : 'text-red-500'">
                  {{ pct(p.achievement_pct) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div :class="card">
        <button type="button" class="widget-title text-sm font-semibold text-ink mb-3" @click="goReport('sales', 'group')">فروش بر اساس گروه مشتری</button>
        <CrmChart
          :categories="groupCats" :series="groupSeries" kind="pie" format="rial" :height="H_MAIN"
          @pick="(i) => openRow(data!.by_group, i, 'گروه مشتری')"
        />
      </div>
    </div>
</div>
</template>

<style scoped>
/* A widget title that opens its module. It stays a heading — no arrow, no
   underline — because eleven decorated links on one page is not a dashboard,
   it is a menu. The pointer is the affordance. */
.widget-title {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  text-align: right;
  align-self: flex-start;
  border-radius: 0.375rem;
}
.widget-title { transition: color 0.15s; }
.section-title { font-size: 0.8rem; font-weight: 700; color: rgb(100 116 139); letter-spacing: 0.01em; }
.kpi { transition: box-shadow 0.2s, transform 0.2s; }
.kpi:hover { transform: translateY(-2px); }
.kpi-icon { background: color-mix(in srgb, currentColor 12%, transparent); }
.widget-title:hover { color: rgb(100 116 139); }
.widget-title:focus-visible { outline: 2px solid rgb(148 163 184); outline-offset: 3px; }
</style>
