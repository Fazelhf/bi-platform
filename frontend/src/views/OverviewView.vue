<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { salesApi } from "@/api/sales";
import { executiveApi, type TrendMonth } from "@/api/executive";
import { defaultPeriodId } from "@/types";
import type { ExecutiveOverview, KpiResult, Period } from "@/types";
import { kpiValue, num, pct, rial } from "@/utils/format";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import ExportActions from "@/components/ExportActions.vue";
import { financeApi, type FinanceSummary } from "@/api/finance";
import { useAuthStore } from "@/stores/auth";
import ComboTrendChart from "@/components/charts/ComboTrendChart.vue";
import GaugeChart from "@/components/charts/GaugeChart.vue";
import SeriesChart from "@/components/charts/SeriesChart.vue";

/**
 * The CEO's one screen.
 *
 * Every headline carries the two things that make a number readable — how it
 * moved since last month and how it stands against plan — and anything
 * off-plan is called out rather than left to be spotted.
 *
 * The layout is fixed on purpose. It used to end in a user-editable board;
 * that was dropped: this page is read, not arranged, and a curated order
 * (verdict → the month → channels → cash) answers «is this good?» faster than
 * any layout a user would build.
 */
const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ExecutiveOverview | null>(null);
const trend = ref<TrendMonth[]>([]);
const loading = ref(false);

/** The financial picture. Optional: if it cannot be read, the rest still shows. */
const finance = ref<FinanceSummary | null>(null);
const auth = useAuthStore();
const canSeeFinance = computed(
  () => auth.isExecutive || !!auth.me?.is_superuser || auth.department === "finance",
);

function pick(kpis: KpiResult[] | undefined, codes: string[]) {
  return codes.map((c) => kpis?.find((k) => k.kpi_code === c)).filter((k): k is KpiResult => !!k);
}

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    const [ov, tr, fin] = await Promise.all([
      executiveApi.overview(selectedPeriod.value),
      executiveApi.trend(),
      canSeeFinance.value
        ? financeApi.executiveSummary(selectedPeriod.value).catch(() => null)
        : Promise.resolve(null),
    ]);
    data.value = ov;
    trend.value = tr.months;
    finance.value = fin;
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

// ---- context: this month against the last, and against plan ---------------
const here = computed(() => trend.value.find((m) => m.period === selectedPeriod.value) ?? null);
const previous = computed(() => {
  const i = trend.value.findIndex((m) => m.period === selectedPeriod.value);
  return i > 0 ? trend.value[i - 1] : null;
});

/** Percent change, or null when there is nothing to compare against. */
function delta(now: number | undefined, before: number | undefined): number | null {
  if (now === undefined || before === undefined || !before) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

/**
 * How to say a change out loud.
 *
 * A percentage stops meaning anything once the base is tiny: growing from 55
 * million to 188 billion is "+۳۴۰٬۲۸۲٪", which reads as a glitch rather than
 * as good news. Past ten-fold, a multiple is the honest phrasing.
 */
function deltaText(d: number | null): string {
  if (d === null) return "";
  const abs = Math.abs(d);
  if (abs >= 900) return `${num(Math.round(abs / 100))} برابر`;
  return pct(abs);
}

/**
 * A month nobody has entered yet is not a month that sold nothing: comparing
 * its zeros with last month drew a «▼ ۱۰۰٪» that read as a collapse.
 */
const salesReported = computed(() => (here.value?.total ?? 0) > 0);
const lastReported = computed(() => [...trend.value].reverse().find((m) => m.total > 0) ?? null);

const revenueDelta = computed(() => (salesReported.value ? delta(here.value?.total, previous.value?.total) : null));
const profitDelta = computed(() => (salesReported.value ? delta(here.value?.profit, previous.value?.profit) : null));

const achievement = computed(() => here.value?.achievement ?? 0);
const margin = computed(() => {
  const t = here.value?.total ?? 0;
  return t ? ((here.value?.profit ?? 0) / t) * 100 : 0;
});

/** Only months that have been reported — a flat zero tail is noise, not data. */
const reported = computed(() => trend.value.filter((m) => m.total > 0 || m.target > 0));

type Tone = "good" | "warn" | "bad" | "none";
const achievementTone = computed<Tone>(() =>
  !here.value?.target ? "none" : achievement.value >= 100 ? "good" : achievement.value >= 70 ? "warn" : "bad",
);

/** The achievement ring in the hero: an SVG arc, capped at a full circle. */
const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;
const ringOffset = computed(() => RING_C * (1 - Math.min(achievement.value, 100) / 100));
const ringStroke: Record<Tone, string> = {
  good: "rgba(255,255,255,.92)", warn: "#fbbf24", bad: "#f87171", none: "rgba(255,255,255,.3)",
};

// ---- the four domains, each with its own movement -------------------------
function share(v: number): number {
  const total = data.value?.combined.total_sales_revenue ?? 0;
  return total ? (v / total) * 100 : 0;
}

const channels = computed(() => {
  const d = data.value;
  if (!d) return [];
  return [
    {
      key: "team", title: "فروش همکار", color: "#3b6fed", route: "sales-dashboard",
      value: d.combined.sales_team_revenue,
      change: !salesReported.value ? null : delta(here.value?.channel_team, previous.value?.channel_team),
      kpis: pick(d.sales_team.kpis, ["target_achievement", "profit_margin", "new_customer_ratio"]),
    },
    {
      key: "org", title: "فروش بانکی", color: "#f59e0b", route: "sales-org-dashboard",
      value: d.combined.sales_org_revenue,
      change: !salesReported.value ? null : delta(here.value?.channel_organizational, previous.value?.channel_organizational),
      kpis: pick(d.sales_org.kpis, ["profit_margin", "avg_invoice_value", "call_conversion"]),
    },
    {
      key: "b2b", title: "فروش B2B", color: "#ec4899", route: "sales-b2b-dashboard",
      value: d.combined.sales_b2b_revenue,
      change: !salesReported.value ? null : delta(here.value?.channel_b2b, previous.value?.channel_b2b),
      kpis: pick(d.sales_b2b.kpis, ["target_achievement", "collection_rate", "avg_invoice_value"]),
    },
  ].map((c) => ({ ...c, share: share(c.value) }));
});

const productionKpis = computed(() =>
  pick(data.value?.production.kpis, ["prod_productivity", "waste_rate", "financial_return"]),
);

// ---- what needs attention -------------------------------------------------
const alerts = computed(() => {
  const out: { text: string; tone: "bad" | "warn" }[] = [];
  const d = data.value;
  if (!d) return out;

  if (here.value?.target && achievement.value < 100) {
    out.push({
      text: `فروش ماه ${pct(achievement.value)} تارگت است — ${rial((here.value.target ?? 0) - (here.value.total ?? 0))} عقب‌تر از برنامه`,
      tone: achievement.value < 70 ? "bad" : "warn",
    });
  }
  if (revenueDelta.value !== null && revenueDelta.value < 0) {
    out.push({ text: `فروش نسبت به ماه قبل ${deltaText(revenueDelta.value)} کاهش داشته`, tone: "warn" });
  }
  if (!salesReported.value) {
    out.push({ text: `فروش ${d.period.label} هنوز ثبت نشده است`, tone: "warn" });
  } else if (!d.sales_completeness.complete) {
    out.push({
      text: `داده فروش کامل تایید نشده (${num(d.sales_completeness.approved)} از ${num(d.sales_completeness.total)})`,
      tone: "warn",
    });
  }
  if (!d.production.completeness.complete) {
    out.push({
      text: `داده تولید کامل تایید نشده (${num(d.production.completeness.approved)} از ${num(d.production.completeness.total)})`,
      tone: "warn",
    });
  }
  const f = finance.value;
  for (const w of f?.cash.warnings ?? []) {
    out.push({ text: w.text, tone: w.level === "danger" ? "bad" : "warn" });
  }
  if (f?.budget?.has_actuals && f.budget.material_bad) {
    out.push({
      text: `${num(f.budget.material_bad)} انحراف نامطلوب مهم در بودجهٔ ${f.month.label}`,
      tone: f.budget.totals.net.verdict === "bad" ? "bad" : "warn",
    });
  }
  if (d.combined.production_margin < 0) {
    out.push({ text: `حاشیه تولید منفی است (${rial(d.combined.production_margin)})`, tone: "bad" });
  }
  // Worst first: the reader should meet the red lines before the amber ones.
  return out.sort((a, b) => (a.tone === b.tone ? 0 : a.tone === "bad" ? -1 : 1));
});

const card = "bg-surface rounded-card shadow-soft";

// ---- وضعیت حال حاضر شرکت ---------------------------------------------------
/** Heroicons-style outline paths, one per light, so each tile is recognised before it is read. */
const ICON = {
  sales: "M3 17l6-6 4 4 8-8M14 7h7v7",
  profit: "M12 6v12m-3-2.8.9.7c1.2.9 3 .9 4.2 0 1.2-.9 1.2-2.3 0-3.2-.6-.4-1.4-.7-2.1-.7-.7 0-1.4-.2-2-.7-1.2-.9-1.2-2.3 0-3.1 1.2-.9 3-.9 4.2 0l.4.4M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  cash: "M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z",
  budget: "M9 7h6m0 10v-3m-3 3v-6m-3 6v-1M6 21h12a2 2 0 002-2V5a2 2 0 00-2-2H6a2 2 0 00-2 2v14a2 2 0 002 2z",
  production: "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5",
  data: "M9 12l2 2 4-4m5.6-4A12 12 0 0112 2.9 12 12 0 013.4 6 12 12 0 003 9c0 5.6 3.8 10.3 9 11.6 5.2-1.3 9-6 9-11.6 0-1-.1-2-.4-3z",
};

/**
 * The company in six lights. Each says what it measures and why it is the
 * colour it is, so the strip answers «کجا باید نگاه کنم؟» before the details.
 */
const status = computed(() => {
  const d = data.value;
  if (!d) return [];
  const f = finance.value;
  // `route` is required, not optional: every tile states a figure that lives
  // in some module, and a tile that opens nothing looks broken next to five
  // that do.
  const items: {
    title: string; value: string; note: string; tone: Tone; icon: string; route: string;
  }[] = [];

  // The money, not the ratio: the ratio is the second line. A tile leads with
  // the figure someone would repeat out loud.
  const profit = here.value?.profit ?? 0;
  items.push({
    title: "سود فروش", icon: ICON.profit,
    value: rial(profit),
    note: `حاشیهٔ سود ${pct(margin.value)}`
      + (profitDelta.value !== null
        ? ` · ${profitDelta.value >= 0 ? "▲" : "▼"} ${deltaText(profitDelta.value)} نسبت به ماه قبل`
        : ""),
    tone: profit > 0 ? "good" : profit < 0 ? "bad" : "none",
    route: "sales-dashboard",
  });

  if (f) {
    const closing = Number(f.cash.closing_rial);
    const low = Number(f.cash.low_threshold_rial);
    items.push({
      title: "نقدینگی", icon: ICON.cash,
      value: rial(closing),
      // Carries what the cash card used to say, so nothing was lost by
      // folding that card into this tile.
      note: `ابتدای ماه ${rial(Number(f.cash.opening_rial))}`
        + ` · بدهی تسهیلات ${rial(Number(f.credit.owed_by_company_rial))}`,
      tone: closing < 0 ? "bad" : low && closing < low ? "warn" : f.cash.has_movements || closing ? "good" : "none",
      route: "finance-cash-report",
    });
    const b = f.budget;
    items.push({
      title: "بودجه", icon: ICON.budget,
      value: !b ? "تعریف نشده" : !b.has_actuals ? "ثبت نشده" : b.material_bad ? `${num(b.material_bad)} انحراف مهم` : "طبق برنامه",
      note: b ? b.title : "بودجه‌ای برای این ماه نیست",
      tone: !b || !b.has_actuals ? "none" : !b.material_bad ? "good" : b.totals.net.verdict === "bad" ? "bad" : "warn",
      // Straight to the deviations when there are any — the figure on the
      // tile is «۳ انحراف مهم», and the next question is which three.
      route: b && b.material_bad ? "finance-budget-variance" : "finance-budget",
    });
  }

  items.push({
    title: "تولید", icon: ICON.production,
    value: rial(d.combined.production_margin),
    note: "حاشیهٔ تولید",
    tone: d.combined.production_margin > 0 ? "good" : d.combined.production_margin < 0 ? "bad" : "none",
    route: "production-dashboard",
  });

  return items;
});

const overallTone = computed<Tone>(() =>
  status.value.some((s) => s.tone === "bad") ? "bad"
    : status.value.some((s) => s.tone === "warn") ? "warn" : "good",
);
/** Shown in the header rather than as a tile: it is a state of the data, not
 *  a figure about the business, and it only matters when it is «ناقص». */
const dataGap = computed(() => {
  const d = data.value;
  if (!d || (d.sales_completeness.complete && d.production.completeness.complete)) return null;
  return `داده ناقص · فروش ${num(d.sales_completeness.approved)}/${num(d.sales_completeness.total)}`
    + ` · تولید ${num(d.production.completeness.approved)}/${num(d.production.completeness.total)}`;
});

const overallText: Record<Tone, string> = {
  good: "همه‌چیز رو به راه است", warn: "چند مورد نیازمند توجه", bad: "وضعیت هشدار", none: "",
};
const toneIcon: Record<Tone, string> = {
  good: "bg-slate-100 text-slate-400",
  warn: "bg-amber-500/10 text-amber-600",
  bad: "bg-red-500/10 text-red-600",
  none: "bg-slate-100 text-slate-400",
};
const toneBar: Record<Tone, string> = {
  good: "bg-slate-300", warn: "bg-amber-500", bad: "bg-red-500", none: "bg-slate-200",
};
const toneChip: Record<Tone, string> = {
  good: "bg-slate-100 text-slate-500", warn: "bg-amber-500/10 text-amber-700",
  bad: "bg-red-500/10 text-red-600", none: "bg-slate-100 text-slate-500",
};
/** The figure itself is coloured only when it is a warning. */
const toneText: Record<Tone, string> = {
  good: "text-ink", warn: "text-amber-700", bad: "text-red-600", none: "text-ink",
};

// ---- نمای مالی -----------------------------------------------------------------
const financeTrend = computed(() => finance.value?.trend ?? []);

const cashTiles = computed(() => {
  const c = finance.value?.cash;
  if (!c) return [];
  const net = Number(c.net_rial);
  return [
    { title: "واریز ماه", value: rial(Number(c.in_rial)), cls: "text-green-600", icon: "M12 4v16m0 0l-6-6m6 6l6-6" },
    { title: "برداشت ماه", value: rial(Number(c.out_rial)), cls: "text-red-500", icon: "M12 20V4m0 0l-6 6m6-6l6 6" },
    { title: "خالص جریان نقد", value: rial(net), cls: net < 0 ? "text-red-600" : "text-green-600", icon: "M4 12h16M4 6h16M4 18h10" },
  ];
});

/** How much of the cash that came in went back out — one bar, read at a glance. */
const outOfIn = computed(() => {
  const c = finance.value?.cash;
  const i = Number(c?.in_rial ?? 0);
  return i ? (Number(c?.out_rial ?? 0) / i) * 100 : 0;
});

const budgetGauges = computed(() => {
  const b = finance.value?.budget;
  if (!b || !b.has_actuals) return [];
  const p = (c: { budget_rial: string; actual_rial: string }) =>
    Number(c.budget_rial) ? (Number(c.actual_rial) / Number(c.budget_rial)) * 100 : null;
  return [
    { title: "تحقق ورودی نقد", value: p(b.totals.in), good: true },
    { title: "مصرف بودجهٔ خروجی", value: p(b.totals.out), good: false },
  ];
});
</script>

<template>
  <div class="space-y-6">
    <!-- ===== Header ===== -->
    <div class="flex items-end justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-xl font-extrabold text-ink">نمای کلی سازمان</h2>
        <p class="text-xs text-slate-400 mt-1">
          تصویر یک‌جای فروش، سود، تولید و نقدینگی
          <template v-if="data"> · {{ data.period.label }}</template>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="data && !loading" class="hidden sm:inline-flex items-center gap-1.5 text-xs rounded-full px-3 py-1.5 font-medium" :class="toneChip[overallTone]">
          <span class="w-1.5 h-1.5 rounded-full" :class="toneBar[overallTone]"></span>
          {{ overallText[overallTone] }}
        </span>
        <RouterLink v-if="dataGap" :to="{ name: 'sales-entry' }"
                    class="hidden sm:inline-flex items-center text-xs rounded-full px-3 py-1.5 font-medium bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 transition">
          {{ dataGap }}
        </RouterLink>
        <ExportActions :excel="false" />
        <select v-model.number="selectedPeriod" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <DashboardSkeleton v-if="loading" :cards="4" :charts="2" :rows="0" />

    <template v-else-if="data">
      <!-- ===== Hero: the month, judged ===== -->
      <section class="relative overflow-hidden bg-panel text-white rounded-card shadow-soft p-6">
          <div class="relative flex items-center justify-between gap-6 flex-wrap">
            <div class="min-w-0">
              <RouterLink :to="{ name: 'sales-dashboard' }" class="text-sm text-white/60 hover:text-white/90 transition">فروش کل شرکت</RouterLink>
              <p class="text-4xl sm:text-5xl font-extrabold ltr-nums mt-2 tracking-tight">{{ rial(data.combined.total_sales_revenue) }}</p>
              <div class="flex items-center gap-2 mt-3 text-sm flex-wrap">
                <span v-if="revenueDelta !== null" class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 ltr-nums"
                      :class="revenueDelta >= 0 ? 'bg-green-400/15 text-green-300' : 'bg-red-400/15 text-red-300'">
                  {{ revenueDelta >= 0 ? "▲" : "▼" }} {{ deltaText(revenueDelta) }}
                </span>
                <span v-if="revenueDelta !== null" class="text-white/40">نسبت به {{ previous?.label }}</span>
                <template v-else-if="!salesReported">
                  <span class="text-white/50">فروش این ماه هنوز ثبت نشده</span>
                  <button v-if="lastReported && lastReported.period !== selectedPeriod"
                          class="rounded-full px-2.5 py-0.5 bg-white/10 hover:bg-white/20 text-white/80 transition"
                          @click="selectedPeriod = lastReported.period">
                    نمایش {{ lastReported.label }} ←
                  </button>
                </template>
                <span v-else class="text-white/40">ماه قبلی برای مقایسه ثبت نشده</span>
              </div>
            </div>

            <!-- Achievement ring -->
            <div class="flex items-center gap-4">
              <div class="relative w-[128px] h-[128px] shrink-0">
                <svg viewBox="0 0 128 128" class="w-full h-full -rotate-90">
                  <circle cx="64" cy="64" :r="RING_R" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="10" />
                  <circle cx="64" cy="64" :r="RING_R" fill="none" :stroke="ringStroke[achievementTone]" stroke-width="10"
                          stroke-linecap="round" :stroke-dasharray="RING_C" :stroke-dashoffset="ringOffset"
                          style="transition: stroke-dashoffset .8s ease" />
                </svg>
                <div class="absolute inset-0 flex flex-col items-center justify-center">
                  <span class="text-2xl font-extrabold ltr-nums">{{ here?.target ? pct(achievement, 0) : "—" }}</span>
                  <span class="text-[11px] text-white/50">تحقق تارگت</span>
                </div>
              </div>
              <div class="text-xs space-y-2 ltr-nums">
                <div>
                  <p class="text-white/40">تارگت ماه</p>
                  <p class="font-semibold text-white/90">{{ here?.target ? rial(here.target) : "تعیین نشده" }}</p>
                </div>
                <div v-if="here?.target && here.target > here.total">
                  <p class="text-white/40">فاصله تا تارگت</p>
                  <p class="font-semibold text-white/90">{{ rial(here.target - here.total) }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Channel mix: the split seen, then named -->
          <div class="relative mt-7">
            <div class="flex h-3 rounded-full overflow-hidden bg-white/10 gap-0.5">
              <div v-for="c in channels" :key="c.key" class="h-full first:rounded-r-full last:rounded-l-full transition-all duration-700"
                   :style="{ width: c.share + '%', backgroundColor: c.color }" :title="c.title"></div>
            </div>
            <div class="flex flex-wrap gap-x-5 gap-y-2 mt-3">
              <RouterLink
                v-for="c in channels" :key="c.key" :to="{ name: c.route }"
                class="flex items-center gap-1.5 text-[11px] text-white/50 hover:text-white/80 transition"
              >
                <span class="w-2 h-2 rounded-full" :style="{ backgroundColor: c.color }"></span>
                {{ c.title }}
                <span class="ltr-nums text-white/70">{{ pct(c.share, 0) }}</span>
              </RouterLink>
            </div>
          </div>
        </section>

      <!-- ===== وضعیت حال حاضر شرکت ===== -->
      <section class="space-y-3">
        <h3 class="font-bold text-ink text-sm">سود، نقدینگی، بودجه و تولید</h3>
        <div class="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <RouterLink
          v-for="s in status" :key="s.title" :to="{ name: s.route }" :class="card"
          class="relative overflow-hidden p-4 transition hover:bg-slate-50"
        >
          <span v-if="s.tone === 'warn' || s.tone === 'bad'" class="absolute top-0 inset-x-0 h-0.5" :class="toneBar[s.tone]"></span>
          <div class="flex items-center gap-2">
            <span class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" :class="toneIcon[s.tone]">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" :d="s.icon" /></svg>
            </span>
            <p class="text-xs text-slate-500">{{ s.title }}</p>
          </div>
          <p class="text-lg font-bold ltr-nums mt-2.5 truncate" :class="toneText[s.tone]" :title="s.value">{{ s.value }}</p>
          <p class="text-[11px] text-slate-400 mt-0.5 leading-5" :title="s.note">{{ s.note }}</p>
        </RouterLink>
        </div>
      </section>

      <!-- ===== Year trend + attention ===== -->
      <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div class="xl:col-span-2">
          <ComboTrendChart
            v-if="reported.length"
            title="روند فروش سال — در برابر تارگت"
            :categories="reported.map((m) => m.label)"
            :bars="[
              { name: 'فروش', values: reported.map((m) => m.total), tone: 'actual' },
              { name: 'سود', values: reported.map((m) => m.profit), tone: 'in' },
            ]"
            :lines="[{ name: 'تارگت', values: reported.map((m) => m.target || null), tone: 'budget', dashed: true }]"
            :height="300"
          />
          <div v-else :class="card" class="h-full min-h-[200px] flex items-center justify-center text-sm text-slate-400">
            هنوز برای هیچ ماهی داده‌ای ثبت نشده است.
          </div>
        </div>

        <div :class="card" class="p-5 flex flex-col">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-ink text-sm">نیازمند توجه</h3>
            <span v-if="alerts.length" class="text-[11px] rounded-full px-2 py-0.5 ltr-nums" :class="toneChip[overallTone]">{{ num(alerts.length) }} مورد</span>
          </div>
          <ul v-if="alerts.length" class="space-y-2 overflow-y-auto max-h-[260px]">
            <li v-for="(a, i) in alerts" :key="i"
                class="text-xs leading-6 flex items-start gap-2.5 rounded-xl px-3 py-2 border-r-[3px]"
                :class="a.tone === 'bad' ? 'bg-red-500/5 border-red-500 text-red-700' : 'bg-amber-500/5 border-amber-500 text-amber-700'">
              <span>{{ a.text }}</span>
            </li>
          </ul>
          <div v-else class="flex-1 flex flex-col items-center justify-center text-center py-6">
            <span class="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
            </span>
            <p class="text-sm text-slate-500 mt-3">همه‌چیز مطابق برنامه است</p>
          </div>
        </div>
      </div>

      <!-- ===== Channels & production ===== -->
      <section class="space-y-3">
        <h3 class="font-bold text-ink text-sm">واحدها</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          <RouterLink v-for="c in channels" :key="c.key" :to="{ name: c.route }"
                      :class="card" class="group p-5 flex flex-col transition hover:bg-slate-50">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full" :style="{ backgroundColor: c.color }"></span>
                <h4 class="font-bold text-ink text-sm">{{ c.title }}</h4>
              </div>
              <span class="text-[11px] rounded-full px-2 py-0.5 ltr-nums bg-slate-100 text-slate-500">{{ pct(c.share, 0) }}</span>
            </div>
            <p class="text-2xl font-extrabold text-ink ltr-nums mt-3">{{ rial(c.value) }}</p>
            <p v-if="c.change !== null" class="text-xs mt-0.5 ltr-nums" :class="c.change >= 0 ? 'text-green-600' : 'text-red-500'">
              {{ c.change >= 0 ? "▲" : "▼" }} {{ deltaText(c.change) }} <span class="text-slate-400">نسبت به ماه قبل</span>
            </p>
            <p v-else class="text-xs mt-0.5 text-slate-300">{{ salesReported ? "بدون مقایسه" : "هنوز ثبت نشده" }}</p>
            <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden mt-3">
              <div class="h-full rounded-full transition-all duration-700" :style="{ width: c.share + '%', backgroundColor: c.color }"></div>
            </div>
            <div class="space-y-2 mt-4 pt-3 border-t border-slate-100 flex-1">
              <div v-for="k in c.kpis" :key="k.id" class="flex justify-between items-baseline text-xs">
                <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
                <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
              </div>
            </div>
            <span class="text-xs mt-4 text-slate-400 group-hover:text-slate-600 transition">مشاهده داشبورد ←</span>
          </RouterLink>

          <!-- Production is not a sales channel; same card, its own figures -->
          <RouterLink :to="{ name: 'production-dashboard' }"
                      :class="card" class="group p-5 flex flex-col transition hover:bg-slate-50">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full bg-slate-400"></span>
                <h4 class="font-bold text-ink text-sm">تولید</h4>
              </div>
              <span class="text-[11px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-500">داخلی</span>
            </div>
            <p class="text-2xl font-extrabold text-ink ltr-nums mt-3">{{ rial(data.combined.internal_piece_rate_revenue) }}</p>
            <p class="text-xs mt-0.5 text-slate-400">درآمد اجرت</p>
            <div class="grid grid-cols-2 gap-2 mt-3 text-[11px]">
              <div class="rounded-lg bg-slate-50 px-2.5 py-1.5">
                <p class="text-slate-400">هزینه</p>
                <p class="font-bold text-ink ltr-nums">{{ rial(data.combined.production_cost) }}</p>
              </div>
              <div class="rounded-lg px-2.5 py-1.5" :class="data.combined.production_margin >= 0 ? 'bg-slate-50' : 'bg-red-500/5'">
                <p class="text-slate-400">حاشیه</p>
                <p class="font-bold ltr-nums" :class="data.combined.production_margin >= 0 ? 'text-ink' : 'text-red-600'">{{ rial(data.combined.production_margin) }}</p>
              </div>
            </div>
            <div class="space-y-2 mt-4 pt-3 border-t border-slate-100 flex-1">
              <div v-for="k in productionKpis" :key="k.id" class="flex justify-between items-baseline text-xs">
                <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
                <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
              </div>
            </div>
            <span class="text-xs mt-4 text-slate-400 group-hover:text-slate-600 transition">مشاهده داشبورد ←</span>
          </RouterLink>
        </div>
      </section>

      <!-- ===== نمای مالی ===== -->
      <section v-if="finance" class="space-y-3">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <h3 class="font-bold text-ink text-sm">نمای مالی <span class="font-normal text-slate-400">· {{ finance.month.label }}</span></h3>
          <div class="flex gap-2 text-xs">
            <RouterLink :to="{ name: 'finance-cash-report' }" class="rounded-full px-3 py-1 bg-slate-100 text-slate-600 hover:bg-slate-200 transition">گزارش نقدینگی ←</RouterLink>
            <RouterLink
              v-if="finance.budget"
              :to="{ name: 'finance-budget', query: { budget: String(finance.budget.id), period: String(finance.month.id) } }"
              class="rounded-full px-3 py-1 bg-slate-100 text-slate-600 hover:bg-slate-200 transition"
            >داشبورد بودجه ←</RouterLink>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div v-for="t in cashTiles" :key="t.title" :class="card" class="p-4 flex items-center gap-3">
            <span class="w-10 h-10 rounded-xl bg-slate-50 flex items-center justify-center shrink-0" :class="t.cls">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" :d="t.icon" /></svg>
            </span>
            <div class="min-w-0">
              <p class="text-[11px] text-slate-400">{{ t.title }}</p>
              <p class="text-lg font-bold ltr-nums truncate" :class="t.cls">{{ t.value }}</p>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div class="xl:col-span-2">
            <ComboTrendChart
              v-if="financeTrend.length"
              title="جریان نقد شش ماه اخیر"
              :categories="financeTrend.map((m) => m.label)"
              :bars="[
                { name: 'واریز', values: financeTrend.map((m) => Number(m.in)), tone: 'in' },
                { name: 'برداشت', values: financeTrend.map((m) => Number(m.out)), tone: 'out' },
              ]"
              :lines="[{ name: 'خالص', values: financeTrend.map((m) => Number(m.net)), tone: 'net', area: true }]"
              :height="300"
            />
          </div>
          <div class="flex flex-col gap-4">
            <SeriesChart
              v-if="finance.composition.out.length"
              title="برداشت‌های ماه به تفکیک"
              kind="pie"
              :categories="finance.composition.out.map((c) => c.label)"
              :series="[{ name: 'برداشت', values: finance.composition.out.map((c) => Number(c.rial)) }]"
              :height="250"
            />
            <div v-else :class="card" class="p-4 flex items-center justify-center text-xs text-slate-400 min-h-[120px]">
              در این ماه برداشتی ثبت نشده است.
            </div>
            <div v-if="Number(finance.cash.in_rial)" :class="card" class="p-4">
              <div class="flex justify-between text-xs mb-2">
                <span class="text-slate-500">سهم برداشت از واریز</span>
                <span class="ltr-nums font-bold" :class="outOfIn > 100 ? 'text-red-600' : 'text-ink'">{{ pct(outOfIn, 0) }}</span>
              </div>
              <div class="h-2 rounded-full bg-slate-100 overflow-hidden">
                <div class="h-full rounded-full transition-all duration-700" :class="outOfIn > 100 ? 'bg-red-500' : 'bg-slate-400'"
                     :style="{ width: Math.min(outOfIn, 100) + '%' }"></div>
              </div>
              <p class="text-[11px] text-slate-400 mt-1.5">{{ outOfIn <= 100 ? "بخشی از واریز ماه در شرکت ماند" : "برداشت از واریز ماه بیشتر بود" }}</p>
            </div>
          </div>
        </div>

        <div v-if="finance.budget" :class="card" class="p-5">
          <div class="flex items-center justify-between flex-wrap gap-2">
            <p class="text-sm font-semibold text-ink">
              بودجه: {{ finance.budget.title }}
              <span class="text-[11px] font-normal text-slate-400">· {{ finance.budget.status_label }}</span>
            </p>
            <span v-if="!finance.budget.has_actuals" class="text-xs text-sky-700 bg-sky-500/10 rounded-full px-2.5 py-1">
              هنوز رقم واقعی برای این ماه ثبت نشده
            </span>
          </div>
          <div v-if="budgetGauges.length" class="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-2">
            <GaugeChart
              v-for="g in budgetGauges" :key="g.title" flat
              :title="g.title" :value="g.value" :good-when-high="g.good" :height="170"
            />
          </div>
          <ul v-if="finance.budget.top_bad.length" class="mt-3 space-y-1.5 border-t border-slate-100 pt-3">
            <li v-for="b in finance.budget.top_bad" :key="b.label" class="flex items-center justify-between text-xs">
              <span class="text-ink">
                {{ b.label }}
                <span class="text-slate-400">· {{ b.direction === "in" ? "ورودی" : "خروجی" }}</span>
              </span>
              <span class="text-red-600 ltr-nums">
                {{ Number(b.variance_rial) > 0 ? "+" : "" }}{{ rial(Number(b.variance_rial)) }}
                <template v-if="b.variance_pct !== null">({{ pct(Math.abs(b.variance_pct)) }})</template>
              </span>
            </li>
          </ul>
        </div>
      </section>

      <p class="text-[11px] text-slate-400 text-center">{{ data.combined.note }}</p>
    </template>
  </div>
</template>
