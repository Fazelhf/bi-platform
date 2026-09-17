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
import SectionBoard from "@/components/boards/SectionBoard.vue";
import { financeApi, type FinanceSummary } from "@/api/finance";
import { useAuthStore } from "@/stores/auth";
import ComboTrendChart from "@/components/charts/ComboTrendChart.vue";
import GaugeChart from "@/components/charts/GaugeChart.vue";
import SeriesChart from "@/components/charts/SeriesChart.vue";

/**
 * The CEO's one screen.
 *
 * It used to be a wall of bare figures: a big total, twelve KPI values and
 * four financial numbers, none of them next to anything to judge them by. A
 * number on its own cannot answer "is this good?", which is the only question
 * this page exists to answer — so every headline now carries the two things
 * that make it readable: how it moved since last month, and how it stands
 * against the plan. The year's shape is drawn once at the top, and anything
 * off-plan is called out rather than left to be spotted.
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

const revenueDelta = computed(() => delta(here.value?.total, previous.value?.total));
const profitDelta = computed(() => delta(here.value?.profit, previous.value?.profit));

const achievement = computed(() => here.value?.achievement ?? 0);
const margin = computed(() => {
  const t = here.value?.total ?? 0;
  return t ? ((here.value?.profit ?? 0) / t) * 100 : 0;
});

/** Only months that have been reported — a flat zero tail is noise, not data. */
const reported = computed(() => trend.value.filter((m) => m.total > 0 || m.target > 0));

// ---- the four domains, each with its own movement -------------------------
const channels = computed(() => {
  const d = data.value;
  if (!d) return [];
  return [
    {
      title: "فروش همکار", color: "#3b6fed", route: "sales-dashboard",
      value: d.combined.sales_team_revenue,
      change: delta(here.value?.channel_team, previous.value?.channel_team),
      kpis: pick(d.sales_team.kpis, ["target_achievement", "profit_margin"]),
    },
    {
      title: "فروش بانکی", color: "#f59e0b", route: "sales-org-dashboard",
      value: d.combined.sales_org_revenue,
      change: delta(here.value?.channel_organizational, previous.value?.channel_organizational),
      kpis: pick(d.sales_org.kpis, ["profit_margin", "avg_invoice_value"]),
    },
    {
      title: "فروش B2B", color: "#ec4899", route: "sales-b2b-dashboard",
      value: d.combined.sales_b2b_revenue,
      change: delta(here.value?.channel_b2b, previous.value?.channel_b2b),
      kpis: pick(d.sales_b2b.kpis, ["target_achievement", "collection_rate"]),
    },
  ];
});

const productionKpis = computed(() =>
  pick(data.value?.production.kpis, ["prod_productivity", "waste_rate", "financial_return"]),
);

/** Share of the month's sales, for the mix bar under the hero. */
function share(v: number): number {
  const total = data.value?.combined.total_sales_revenue ?? 0;
  return total ? (v / total) * 100 : 0;
}

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
  if (!d.sales_completeness.complete) {
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
  return out;
});

const card = "bg-surface rounded-card shadow-soft";

// ---- وضعیت حال حاضر شرکت ---------------------------------------------------
type Tone = "good" | "warn" | "bad" | "none";

/**
 * The company in six lights. Each says what it measures and why it is the
 * colour it is, so the strip answers «کجا باید نگاه کنم؟» before the details.
 */
const status = computed(() => {
  const d = data.value;
  if (!d) return [];
  const f = finance.value;
  const items: { title: string; value: string; note: string; tone: Tone }[] = [];

  const hasTarget = !!here.value?.target;
  items.push({
    title: "فروش",
    value: hasTarget ? pct(achievement.value) : rial(d.combined.total_sales_revenue),
    note: hasTarget ? "تحقق تارگت ماه" : "تارگت ماه تعیین نشده",
    tone: !hasTarget ? "none" : achievement.value >= 100 ? "good" : achievement.value >= 70 ? "warn" : "bad",
  });

  const profit = here.value?.profit ?? 0;
  items.push({
    title: "سودآوری",
    value: pct(margin.value),
    note: `حاشیهٔ سود فروش · ${rial(profit)}`,
    tone: profit > 0 ? "good" : profit < 0 ? "bad" : "none",
  });

  if (f) {
    const closing = Number(f.cash.closing_rial);
    const low = Number(f.cash.low_threshold_rial);
    items.push({
      title: "نقدینگی",
      value: rial(closing),
      note: `موجودی پایان ${f.month.label}`,
      tone: closing < 0 ? "bad" : low && closing < low ? "warn" : f.cash.has_movements || closing ? "good" : "none",
    });
    const b = f.budget;
    items.push({
      title: "بودجه",
      value: !b ? "تعریف نشده" : !b.has_actuals ? "ثبت نشده" : b.material_bad ? `${num(b.material_bad)} انحراف مهم` : "طبق برنامه",
      note: b ? b.title : "بودجه‌ای برای این ماه نیست",
      tone: !b || !b.has_actuals ? "none" : !b.material_bad ? "good" : b.totals.net.verdict === "bad" ? "bad" : "warn",
    });
  }

  items.push({
    title: "تولید",
    value: rial(d.combined.production_margin),
    note: "حاشیهٔ تولید",
    tone: d.combined.production_margin > 0 ? "good" : d.combined.production_margin < 0 ? "bad" : "none",
  });

  const complete = d.sales_completeness.complete && d.production.completeness.complete;
  items.push({
    title: "کامل بودن داده",
    value: complete ? "کامل" : "ناقص",
    note: `فروش ${num(d.sales_completeness.approved)}/${num(d.sales_completeness.total)} · تولید ${num(d.production.completeness.approved)}/${num(d.production.completeness.total)}`,
    tone: complete ? "good" : "warn",
  });
  return items;
});

const overallTone = computed<Tone>(() =>
  status.value.some((s) => s.tone === "bad") ? "bad"
    : status.value.some((s) => s.tone === "warn") ? "warn" : "good",
);
const toneBox: Record<Tone, string> = {
  good: "border-green-200 bg-green-50/40",
  warn: "border-amber-200 bg-amber-50/40",
  bad: "border-red-200 bg-red-50/40",
  none: "border-slate-100 bg-slate-50/40",
};
const toneDot: Record<Tone, string> = {
  good: "bg-green-500", warn: "bg-amber-500", bad: "bg-red-500", none: "bg-slate-300",
};
const toneChip: Record<Tone, string> = {
  good: "bg-green-50 text-green-700", warn: "bg-amber-50 text-amber-700",
  bad: "bg-red-50 text-red-600", none: "bg-slate-100 text-slate-500",
};

// ---- نمای مالی -----------------------------------------------------------------
const financeTrend = computed(() => finance.value?.trend ?? []);

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
  <div class="space-y-4">
    <div class="flex items-center justify-between flex-wrap gap-2">
      <h2 class="text-lg font-bold text-ink">نمای کلی سازمان</h2>
      <div class="flex items-center gap-2">
        <ExportActions :excel="false" />
        <select v-model.number="selectedPeriod" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <DashboardSkeleton v-if="loading" :cards="4" :charts="0" :rows="4" />

    <template v-else-if="data">
      <!-- ===== وضعیت حال حاضر شرکت ===== -->
      <section :class="card" class="p-4">
        <div class="flex items-center justify-between flex-wrap gap-2 mb-3">
          <h3 class="font-bold text-ink text-sm">وضعیت حال حاضر شرکت — {{ data.period.label }}</h3>
          <span class="text-xs rounded-full px-2.5 py-1" :class="toneChip[overallTone]">
            {{ overallTone === "good" ? "✓ همه‌چیز رو به راه است" : overallTone === "warn" ? "نیازمند توجه" : "وضعیت هشدار" }}
          </span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <div v-for="s in status" :key="s.title" class="rounded-xl p-3 border" :class="toneBox[s.tone]">
            <div class="flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full" :class="toneDot[s.tone]"></span>
              <p class="text-[11px] text-slate-500">{{ s.title }}</p>
            </div>
            <p class="text-base font-bold text-ink ltr-nums mt-1 truncate" :title="s.value">{{ s.value }}</p>
            <p class="text-[11px] text-slate-400 mt-0.5 truncate" :title="s.note">{{ s.note }}</p>
          </div>
        </div>
      </section>

      <!-- ===== Hero: the month, judged ===== -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <!-- Headline + mix -->
        <div class="bg-panel text-white rounded-card shadow-soft p-6 lg:col-span-2">
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p class="text-sm text-white/60 mb-1">فروش کل شرکت — {{ data.period.label }}</p>
              <p class="text-4xl font-extrabold ltr-nums">{{ rial(data.combined.total_sales_revenue) }}</p>
              <p v-if="revenueDelta !== null" class="text-sm mt-1.5 ltr-nums"
                 :class="revenueDelta >= 0 ? 'text-green-300' : 'text-red-300'">
                {{ revenueDelta >= 0 ? "▲" : "▼" }} {{ deltaText(revenueDelta) }}
                <span class="text-white/40">نسبت به {{ previous?.label }}</span>
              </p>
              <p v-else class="text-sm mt-1.5 text-white/40">ماه قبلی برای مقایسه ثبت نشده</p>
            </div>

            <div v-if="here?.target" class="text-left min-w-[190px]">
              <p class="text-xs text-white/60 mb-1">تحقق تارگت</p>
              <p class="text-2xl font-bold ltr-nums"
                 :class="achievement >= 100 ? 'text-green-300' : achievement >= 70 ? 'text-amber-300' : 'text-red-300'">
                {{ pct(achievement) }}
              </p>
              <div class="h-1.5 bg-white/15 rounded-full mt-2 overflow-hidden">
                <div class="h-full rounded-full transition-all"
                     :class="achievement >= 100 ? 'bg-green-400' : achievement >= 70 ? 'bg-amber-400' : 'bg-red-400'"
                     :style="{ width: Math.min(achievement, 100) + '%' }"></div>
              </div>
              <p class="text-[11px] text-white/40 mt-1 ltr-nums">تارگت {{ rial(here.target) }}</p>
            </div>
          </div>

          <!-- Channel mix as one bar, so the split is seen rather than read -->
          <div class="mt-5">
            <div class="flex h-2.5 rounded-full overflow-hidden bg-white/10">
              <div class="bg-[#3b6fed]" :style="{ width: share(data.combined.sales_team_revenue) + '%' }" title="فروش همکار"></div>
              <div class="bg-[#f59e0b]" :style="{ width: share(data.combined.sales_org_revenue) + '%' }" title="فروش بانکی"></div>
              <div class="bg-[#ec4899]" :style="{ width: share(data.combined.sales_b2b_revenue) + '%' }" title="فروش B2B"></div>
            </div>
            <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-white/50 mt-2 ltr-nums">
              <span><span class="inline-block w-2 h-2 rounded-full bg-[#3b6fed] ml-1"></span>همکار {{ pct(share(data.combined.sales_team_revenue)) }}</span>
              <span><span class="inline-block w-2 h-2 rounded-full bg-[#f59e0b] ml-1"></span>بانکی {{ pct(share(data.combined.sales_org_revenue)) }}</span>
              <span><span class="inline-block w-2 h-2 rounded-full bg-[#ec4899] ml-1"></span>B2B {{ pct(share(data.combined.sales_b2b_revenue)) }}</span>
            </div>
          </div>
        </div>

        <!-- Profit + attention -->
        <div class="space-y-4">
          <div :class="card" class="p-5">
            <p class="text-xs text-slate-400">سود فروش این ماه</p>
            <p class="text-2xl font-bold text-ink ltr-nums mt-1">{{ rial(here?.profit ?? 0) }}</p>
            <div class="flex items-center gap-3 mt-1.5 text-xs">
              <span class="text-slate-400">حاشیه {{ pct(margin) }}</span>
              <span v-if="profitDelta !== null" class="ltr-nums" :class="profitDelta >= 0 ? 'text-green-600' : 'text-red-500'">
                {{ profitDelta >= 0 ? "▲" : "▼" }} {{ deltaText(profitDelta) }}
              </span>
            </div>
          </div>

          <div :class="card" class="p-5">
            <p class="text-xs text-slate-400 mb-2">نیازمند توجه</p>
            <ul v-if="alerts.length" class="space-y-1.5">
              <li v-for="(a, i) in alerts" :key="i" class="text-xs flex items-start gap-2">
                <span class="mt-1 w-1.5 h-1.5 rounded-full shrink-0" :class="a.tone === 'bad' ? 'bg-red-500' : 'bg-amber-500'"></span>
                <span :class="a.tone === 'bad' ? 'text-red-600' : 'text-amber-600'">{{ a.text }}</span>
              </li>
            </ul>
            <p v-else class="text-xs text-green-600">✓ همه‌چیز مطابق برنامه است</p>
          </div>
        </div>
      </div>

      <!-- ===== The year so far, as figures ===== -->
      <!-- Deliberately a table, not a chart: this page is read at a glance and
           the charts belong on the dashboards each row links to. -->
      <div :class="card" class="overflow-hidden">
        <h3 class="font-bold text-ink px-5 pt-5 pb-3">روند سال — فروش در برابر تارگت</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm min-w-[640px]">
            <thead>
              <tr class="text-xs text-slate-400 bg-slate-50">
                <th class="text-right font-medium px-5 py-2.5">ماه</th>
                <th class="text-left font-medium px-3">فروش</th>
                <th class="text-left font-medium px-3">تارگت</th>
                <th class="text-left font-medium px-3">تحقق</th>
                <th class="text-left font-medium px-3">سود</th>
                <th class="text-left font-medium px-5">تغییر</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(m, i) in reported" :key="m.period"
                class="border-t border-slate-100 cursor-pointer transition-colors"
                :class="m.period === selectedPeriod ? 'bg-brand-500/5' : 'hover:bg-slate-50'"
                @click="selectedPeriod = m.period"
              >
                <td class="px-5 py-2.5 text-ink font-medium whitespace-nowrap">{{ m.label }}</td>
                <td class="px-3 text-left ltr-nums text-ink whitespace-nowrap">{{ rial(m.total) }}</td>
                <td class="px-3 text-left ltr-nums text-slate-400 whitespace-nowrap">{{ rial(m.target) }}</td>
                <td class="px-3 text-left ltr-nums font-medium"
                    :class="m.achievement >= 100 ? 'text-green-600' : m.achievement >= 70 ? 'text-amber-600' : 'text-red-500'">
                  {{ m.target ? pct(m.achievement) : "—" }}
                </td>
                <td class="px-3 text-left ltr-nums text-slate-600 whitespace-nowrap">{{ rial(m.profit) }}</td>
                <td class="px-5 text-left ltr-nums whitespace-nowrap">
                  <span v-if="i > 0 && delta(m.total, reported[i - 1].total) !== null"
                        :class="delta(m.total, reported[i - 1].total)! >= 0 ? 'text-green-600' : 'text-red-500'">
                    {{ delta(m.total, reported[i - 1].total)! >= 0 ? "▲" : "▼" }}
                    {{ deltaText(delta(m.total, reported[i - 1].total)) }}
                  </span>
                  <span v-else class="text-slate-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!reported.length" class="text-sm text-slate-400 px-5 py-4">هنوز برای هیچ ماهی داده‌ای ثبت نشده است.</p>
      </div>

      <!-- ===== Channels ===== -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div v-for="c in channels" :key="c.title" :class="card" class="p-5 hover:shadow-pop transition-shadow duration-200">
          <div class="flex items-center gap-2 mb-3">
            <span class="w-2.5 h-2.5 rounded-full" :style="{ backgroundColor: c.color }"></span>
            <h3 class="font-bold text-ink text-sm">{{ c.title }}</h3>
          </div>
          <p class="text-xl font-bold text-ink ltr-nums">{{ rial(c.value) }}</p>
          <p v-if="c.change !== null" class="text-xs mt-0.5 ltr-nums" :class="c.change >= 0 ? 'text-green-600' : 'text-red-500'">
            {{ c.change >= 0 ? "▲" : "▼" }} {{ deltaText(c.change) }} نسبت به ماه قبل
          </p>
          <div class="space-y-1.5 mt-3 pt-3 border-t border-slate-100">
            <div v-for="k in c.kpis" :key="k.id" class="flex justify-between items-baseline text-xs">
              <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: c.route }" class="text-xs mt-3 inline-block hover:underline" :style="{ color: c.color }">
            مشاهده داشبورد ←
          </RouterLink>
        </div>

        <!-- Production is not a sales channel; it gets the same card, its own metrics -->
        <div :class="card" class="p-5 hover:shadow-pop transition-shadow duration-200">
          <div class="flex items-center gap-2 mb-3">
            <span class="w-2.5 h-2.5 rounded-full bg-[#10b981]"></span>
            <h3 class="font-bold text-ink text-sm">تولید</h3>
          </div>
          <p class="text-xl font-bold text-ink ltr-nums">{{ rial(data.combined.internal_piece_rate_revenue) }}</p>
          <p class="text-xs text-slate-400 mt-0.5">درآمد اجرت (داخلی)</p>
          <div class="space-y-1.5 mt-3 pt-3 border-t border-slate-100">
            <div v-for="k in productionKpis" :key="k.id" class="flex justify-between items-baseline text-xs">
              <span class="text-slate-400">{{ k.kpi_name_fa }}</span>
              <span class="ltr-nums font-semibold text-ink">{{ kpiValue(k.actual, k.unit) }}</span>
            </div>
          </div>
          <RouterLink :to="{ name: 'production-dashboard' }" class="text-xs mt-3 inline-block text-[#10b981] hover:underline">
            مشاهده داشبورد ←
          </RouterLink>
        </div>
      </div>

      <!-- ===== نمای مالی ===== -->
      <section v-if="finance" class="space-y-3">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <h3 class="font-bold text-ink">نمای مالی — {{ finance.month.label }}</h3>
          <div class="flex gap-4 text-xs">
            <RouterLink :to="{ name: 'finance-cash-report' }" class="text-brand-700 hover:underline">نقدینگی ←</RouterLink>
            <RouterLink
              v-if="finance.budget"
              :to="{ name: 'finance-budget', query: { budget: String(finance.budget.id), period: String(finance.month.id) } }"
              class="text-brand-700 hover:underline"
            >داشبورد بودجه ←</RouterLink>
          </div>
        </div>

        <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <div :class="card" class="p-4">
            <p class="text-[11px] text-slate-400">موجودی پایان ماه</p>
            <p class="text-lg font-bold ltr-nums mt-1" :class="Number(finance.cash.closing_rial) < 0 ? 'text-red-600' : 'text-ink'">
              {{ rial(Number(finance.cash.closing_rial)) }}
            </p>
            <p class="text-[11px] text-slate-400 mt-0.5 ltr-nums">ابتدای ماه {{ rial(Number(finance.cash.opening_rial)) }}</p>
          </div>
          <div :class="card" class="p-4">
            <p class="text-[11px] text-slate-400">واریز ماه</p>
            <p class="text-lg font-bold text-green-600 ltr-nums mt-1">{{ rial(Number(finance.cash.in_rial)) }}</p>
          </div>
          <div :class="card" class="p-4">
            <p class="text-[11px] text-slate-400">برداشت ماه</p>
            <p class="text-lg font-bold text-red-500 ltr-nums mt-1">{{ rial(Number(finance.cash.out_rial)) }}</p>
          </div>
          <div :class="card" class="p-4">
            <p class="text-[11px] text-slate-400">خالص ماه</p>
            <p class="text-lg font-bold ltr-nums mt-1" :class="Number(finance.cash.net_rial) < 0 ? 'text-red-600' : 'text-green-600'">
              {{ rial(Number(finance.cash.net_rial)) }}
            </p>
          </div>
          <div :class="card" class="p-4">
            <p class="text-[11px] text-slate-400">مانده تسهیلات (بدهی)</p>
            <p class="text-lg font-bold text-red-500 ltr-nums mt-1">{{ rial(Number(finance.credit.owed_by_company_rial)) }}</p>
            <p class="text-[11px] text-slate-400 mt-0.5 ltr-nums">طلب از قرض‌ها {{ rial(Number(finance.credit.owed_to_company_rial)) }}</p>
          </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-3 gap-3">
          <div class="xl:col-span-2">
            <ComboTrendChart
              v-if="financeTrend.length"
              title="جریان نقد شش ماه اخیر"
              :categories="financeTrend.map((m) => m.label)"
              :bars="[
                { name: 'واریز', values: financeTrend.map((m) => Number(m.in)), tone: 'in' },
                { name: 'برداشت', values: financeTrend.map((m) => Number(m.out)), tone: 'out' },
              ]"
              :lines="[{ name: 'خالص', values: financeTrend.map((m) => Number(m.net)), tone: 'net' }]"
              :height="280"
            />
          </div>
          <SeriesChart
            v-if="finance.composition.out.length"
            title="برداشت‌های ماه به تفکیک"
            kind="pie"
            :categories="finance.composition.out.map((c) => c.label)"
            :series="[{ name: 'برداشت', values: finance.composition.out.map((c) => Number(c.rial)) }]"
            :height="280"
          />
          <div v-else :class="card" class="p-4 flex items-center justify-center text-xs text-slate-400">
            در این ماه برداشتی ثبت نشده است.
          </div>
        </div>

        <div v-if="finance.budget" :class="card" class="p-4">
          <div class="flex items-center justify-between flex-wrap gap-2">
            <p class="text-sm font-semibold text-ink">
              بودجه: {{ finance.budget.title }}
              <span class="text-[11px] font-normal text-slate-400">· {{ finance.budget.status_label }}</span>
            </p>
            <span v-if="!finance.budget.has_actuals" class="text-xs text-sky-700 bg-sky-50 rounded-full px-2.5 py-1">
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

      <!-- ===== Combined financials ===== -->
      <div :class="card" class="p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-ink">تصویر مالی تلفیقی</h3>
          <span class="text-[11px] text-slate-400">{{ data.combined.note }}</span>
        </div>
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
      </div>
    </template>
      <!-- گزارش این بخش، روی همین صفحه: داشبورد و گزارش یک صفحه‌اند. -->
    <SectionBoard section="overview" :period="selectedPeriod" />
</div>
</template>
