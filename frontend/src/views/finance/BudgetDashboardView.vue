<script setup lang="ts">
/**
 * داشبورد بودجه — the page the CEO opens.
 *
 * Built around the questions in the order they get asked, every one answered
 * by a variance rather than a dial:
 *
 * 1. **Are we on plan?** — a scorecard per measure (cash in, cash out, net
 *    cash, sales): actual, plan, signed variance with its verdict, a bullet
 *    with the plan marked on it, and the variance month by month.
 * 2. **Where did it differ?** — the bridge from planned to actual net cash,
 *    and every line on one diverging axis: right saved money, left cost it.
 * 3. **Is it a pattern?** — monthly variance with its running total, the
 *    cumulative cash position, and the group × month heatmap.
 * 4. **Sales** — the forecast per channel against what the sales section
 *    recorded. Read, not keyed: the same figures as the sales dashboards.
 *
 * Actuals are not only what finance keyed: a line with nothing keyed shows
 * the cash ledger's figure for its category. The page says which is which.
 */
import { computed, onMounted, ref, watch } from "vue";
import {
  apiError,
  budgetApi,
  type BudgetHeatmapData,
  type BudgetSeries,
  type Verdict,
  type VarianceReport,
  type Waterfall,
} from "@/api/budget";
import { useBudgetContext } from "@/composables/useBudgetContext";
import { loadMoneySettings, useMoney } from "@/composables/useMoney";
import BudgetWaterfall from "@/components/charts/BudgetWaterfall.vue";
import BudgetCumulativeChart from "@/components/charts/BudgetCumulativeChart.vue";
import BudgetHeatmap from "@/components/charts/BudgetHeatmap.vue";
import ComboTrendChart from "@/components/charts/ComboTrendChart.vue";
import MonthlyVarianceChart from "@/components/charts/MonthlyVarianceChart.vue";
import PlanActualBars from "@/components/charts/PlanActualBars.vue";
import VarianceBars from "@/components/charts/VarianceBars.vue";
import VarianceScoreCard from "@/components/charts/VarianceScoreCard.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import { useAuthStore } from "@/stores/auth";

const { budgets, budgetId, periodId, months, budget, linkQuery, init } = useBudgetContext();
const { money, unitLabel } = useMoney();
const auth = useAuthStore();
const isFinance = computed(() => auth.department === "finance" || !!auth.me?.is_superuser);
const isCeo = computed(() => auth.isExecutive || !!auth.me?.is_superuser);

const series = ref<BudgetSeries | null>(null);
const report = ref<VarianceReport | null>(null);
const fall = ref<Waterfall | null>(null);
const heat = ref<BudgetHeatmapData | null>(null);
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");
const n = (v: string | number | null | undefined) => Number(v ?? 0);

async function loadSeries() {
  if (!budgetId.value) return;
  try {
    const [s, h] = await Promise.all([
      budgetApi.series(budgetId.value),
      budgetApi.heatmap(budgetId.value).catch(() => null),
    ]);
    series.value = s;
    heat.value = h;
  } catch (e) {
    error.value = apiError(e, "روند بودجه بارگذاری نشد.");
  }
}

async function loadMonth() {
  if (!budgetId.value || !periodId.value) {
    report.value = null;
    fall.value = null;
    return;
  }
  try {
    const [r, w] = await Promise.all([
      budgetApi.variance(budgetId.value, periodId.value),
      budgetApi.waterfall(budgetId.value, periodId.value),
    ]);
    report.value = r;
    fall.value = w;
  } catch (e: any) {
    error.value = e?.response?.status === 403
      ? "بخش مالی برای شما قابل مشاهده نیست."
      : apiError(e, "گزارش ماه بارگذاری نشد.");
  }
}

watch(budgetId, loadSeries);
watch([budgetId, periodId], loadMonth);

onMounted(async () => {
  try {
    await loadMoneySettings();
    await init();
    await Promise.all([loadSeries(), loadMonth()]);
  } catch (e) {
    error.value = apiError(e, "بارگذاری ناموفق بود.");
  } finally {
    loading.value = false;
  }
});

// ---- 1. scorecards --------------------------------------------------------------

const points = computed(() => series.value?.points ?? []);
const labels = computed(() => points.value.map((p) => p.label));

function verdictOf(variance: number, goodWhenHigher: boolean): Verdict {
  if (!variance) return "on-track";
  return (goodWhenHigher ? variance > 0 : variance < 0) ? "good" : "bad";
}

/** Month-by-month variance of one measure, for a scorecard's strip. */
function trendOf(budgetOf: (p: any) => number, actualOf: (p: any) => number, goodWhenHigher: boolean, has: (p: any) => boolean) {
  return points.value.map((p) => {
    const v = actualOf(p) - budgetOf(p);
    return {
      label: p.label,
      variance: v,
      verdict: verdictOf(v, goodWhenHigher),
      current: p.period_id === report.value?.month.id,
      empty: !has(p),
    };
  });
}

const salesHas = (p: any) => n(p.actual_sales) > 0;

const cards = computed(() => {
  const r = report.value;
  if (!r) return [];
  const src = r.sources ?? { keyed: 0, ledger: 0, none: 0 };
  const sourceHint = src.ledger
    ? `${FA.format(src.keyed)} سرفصل دستی/اکسل · ${FA.format(src.ledger)} از دفتر نقدینگی`
    : "ارقام واردشدهٔ واحد مالی";
  return [
    {
      title: "ورودی نقد",
      hint: sourceHint,
      budget: n(r.totals.in.budget_rial),
      actual: n(r.totals.in.actual_rial),
      verdict: r.totals.in.verdict,
      trend: trendOf((p) => n(p.budget_in), (p) => n(p.actual_in), true, (p) => p.has_actuals),
      bullet: true,
    },
    {
      title: "خروجی نقد",
      hint: sourceHint,
      budget: n(r.totals.out.budget_rial),
      actual: n(r.totals.out.actual_rial),
      verdict: r.totals.out.verdict,
      trend: trendOf((p) => n(p.budget_out), (p) => n(p.actual_out), false, (p) => p.has_actuals),
      bullet: true,
    },
    {
      title: "خالص جریان نقد",
      hint: "ورودی منهای خروجی",
      budget: n(r.totals.net.budget_rial),
      actual: n(r.totals.net.actual_rial),
      verdict: r.totals.net.verdict,
      trend: trendOf((p) => n(p.budget_net), (p) => n(p.actual_net), true, (p) => p.has_actuals),
      bullet: false,
    },
    {
      title: "فروش",
      hint: "پیش‌بینی بودجه در برابر فروش واقعی (اکسل مالی، وگرنه بخش فروش)",
      budget: n(r.sales?.total.budget_rial),
      actual: n(r.sales?.total.actual_rial),
      verdict: r.sales?.total.verdict ?? "on-track",
      trend: trendOf((p) => n(p.budget_sales), (p) => n(p.actual_sales), true, salesHas),
      bullet: true,
    },
  ];
});

const leafRows = computed(() => (report.value?.rows ?? []).filter((r) => r.kind !== "category"));

const facts = computed(() => {
  const r = report.value;
  if (!r) return [];
  const material = leafRows.value.filter((x) => x.is_material);
  const bad = material.filter((x) => x.verdict === "bad");
  const unexplained = bad.filter((x) => x.kind === "line" && !x.note);
  return [
    {
      title: "انحراف‌های مهم",
      value: FA.format(material.length),
      sub: bad.length ? `${FA.format(bad.length)} مورد نامطلوب` : "همه مطلوب یا طبق برنامه",
      tone: bad.length ? "text-rose-700 dark:text-rose-400" : "text-emerald-700 dark:text-emerald-400",
    },
    {
      title: "نامطلوبِ بدون علت",
      value: FA.format(unexplained.length),
      sub: unexplained.length ? "هنوز توضیحی ثبت نشده" : "همه توضیح دارند",
      tone: unexplained.length ? "text-amber-600" : "text-emerald-700 dark:text-emerald-400",
    },
    {
      title: "ماه‌های مصوب",
      value: budget.value ? `${FA.format(budget.value.approved_count)} از ${FA.format(budget.value.month_count)}` : "—",
      sub: r.status === "approved" ? `${r.month.label} مصوب است` : `${r.month.label} پیش‌نویس است`,
      tone: "text-ink",
    },
    {
      title: "سرفصل‌های بی‌رقم واقعی",
      value: FA.format(r.sources?.none ?? 0),
      sub: "نه دستی، نه در دفتر نقدینگی",
      tone: (r.sources?.none ?? 0) ? "text-amber-600" : "text-ink",
    },
  ];
});

// ---- 2. where it differed ------------------------------------------------------------

const lineRows = computed(() =>
  leafRows.value.map((r) => {
    const variance = n(r.variance_rial);
    return {
      label: r.label,
      direction: r.direction,
      budget: n(r.budget_rial),
      actual: n(r.actual_rial),
      effect: r.direction === "in" ? variance : -variance,
      verdict: r.verdict,
      material: r.is_material,
      note: r.note,
      source: r.source,
    };
  }),
);

const steps = computed(() =>
  (fall.value?.steps ?? []).map((s) => ({ label: s.label, effect: n(s.effect_rial), verdict: s.verdict })),
);

// ---- 3. pattern ---------------------------------------------------------------------------

const netPoints = computed(() =>
  points.value.map((p) => ({
    label: p.label,
    budget: n(p.budget_net),
    actual: n(p.actual_net),
    has: p.has_actuals,
    current: p.period_id === report.value?.month.id,
  })),
);

/** Actuals stop at the last month anything was recorded — see the chart. */
const lastActual = computed(() => {
  let last = -1;
  points.value.forEach((p, i) => {
    if (p.has_actuals) last = i;
  });
  return last;
});
const cumulativeBudget = computed(() => points.value.map((p) => n(p.cumulative_budget)));
const cumulativeActual = computed(() =>
  points.value.map((p, i) => (i <= lastActual.value ? n(p.cumulative_actual) : null)),
);

/** The month's top-level groups, plan against actual. */
function groupsOf(dir: "in" | "out") {
  return (report.value?.rows ?? [])
    .filter((r) => r.depth === 0 && r.direction === dir && (n(r.budget_rial) || n(r.actual_rial)))
    .map((r) => ({ label: r.label, budget: n(r.budget_rial), actual: n(r.actual_rial), verdict: r.verdict }));
}
const inGroups = computed(() => groupsOf("in"));
const outGroups = computed(() => groupsOf("out"));

// ---- 4. sales -------------------------------------------------------------------------------

const salesChannels = computed(() =>
  (report.value?.sales?.rows ?? [])
    .filter((r) => n(r.budget_rial) || n(r.actual_rial))
    .map((r) => ({
      label: r.label,
      budget: n(r.budget_rial),
      actual: n(r.actual_rial),
      verdict: r.verdict,
      // Finance's sheet and the sales section disagree: say so, with both figures.
      note: r.source === "excel" && n(r.section_rial) !== n(r.actual_rial)
        ? `طبق اکسل مالی · بخش فروش: ${money(n(r.section_rial), false)} (اختلاف ${money(n(r.actual_rial) - n(r.section_rial), false)})`
        : undefined,
    })),
);
const hasSalesPlan = computed(() => points.value.some((p) => n(p.budget_sales) || n(p.actual_sales)));

const worst = computed(() =>
  leafRows.value
    .filter((r) => r.is_material && r.verdict === "bad")
    .sort((a, b) => Math.abs(n(b.variance_rial)) - Math.abs(n(a.variance_rial)))
    .slice(0, 8),
);
</script>

<template>
  <div class="space-y-4">
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-bold text-ink">داشبورد بودجه</h1>
        <p class="text-xs text-slate-400 mt-0.5">
          <template v-if="budget">{{ budget.title }} · {{ budget.start_label }} تا {{ budget.end_label }} · </template>
          ارقام به <span class="font-medium">{{ unitLabel }}</span>
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <label v-if="budgets.length" class="block">
          <span class="text-[11px] text-slate-400">بودجه</span>
          <select v-model.number="budgetId" class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
            <option v-for="b in budgets" :key="b.id" :value="b.id">{{ b.title }}</option>
          </select>
        </label>
        <label v-if="months.length" class="block">
          <span class="text-[11px] text-slate-400">ماه</span>
          <select v-model.number="periodId" class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
            <option v-for="p in months" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
        <router-link
          :to="{ name: 'finance-budget-variance', query: linkQuery }"
          class="px-3 py-1.5 text-sm rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200"
        >جزئیات انحراف</router-link>
        <router-link
          v-if="isCeo"
          :to="{ name: 'finance-budget-plan', query: linkQuery }"
          class="px-3 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700"
        >تعریف بودجه</router-link>
        <router-link
          v-if="isFinance"
          :to="{ name: 'finance-budget-actuals', query: linkQuery }"
          class="px-3 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700"
        >ورود ارقام واقعی</router-link>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>

    <DashboardSkeleton v-else-if="loading" />

    <section v-else-if="!budgets.length" class="bg-surface rounded-card shadow-soft p-10 text-center">
      <p class="font-semibold text-ink">هنوز بودجه‌ای تعریف نشده</p>
      <p class="text-sm text-slate-400 mt-1">
        {{ isCeo ? 'از «تعریف بودجه» اولین بودجه را بسازید یا فایل اکسل جریان نقدی را وارد کنید.' : 'مدیرعامل هنوز بودجه‌ای تعریف نکرده است.' }}
      </p>
      <router-link v-if="isCeo" :to="{ name: 'finance-budget-plan' }" class="inline-block mt-3 text-sm text-brand-700">رفتن به تعریف بودجه ←</router-link>
    </section>

    <template v-else>
      <!-- Nothing recorded yet: say so before the scorecards look like a crisis. -->
      <div v-if="report && !report.has_actuals" class="rounded-card p-3 text-sm bg-sky-50 text-sky-800 leading-6">
        <span class="font-semibold">برای {{ report.month.label }} هنوز هیچ رقم واقعی نیست</span>
        — نه در دفتر نقدینگی، نه دستی، نه در بخش فروش. انحراف‌ها یعنی «هنوز ثبت نشده»؛ ماهی را انتخاب کنید که ارقامش آمده.
      </div>

      <!-- 1. On plan? -->
      <div v-if="report" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <VarianceScoreCard
          v-for="c in cards" :key="c.title"
          :title="`${c.title} — ${report.month.label}`" :hint="c.hint"
          :budget="c.budget" :actual="c.actual" :verdict="c.verdict"
          :trend="c.trend" :bullet="c.bullet"
        />
      </div>
      <div v-if="report" class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div v-for="f in facts" :key="f.title" class="bg-surface rounded-card shadow-soft px-4 py-3">
          <p class="text-[11px] text-slate-400">{{ f.title }}</p>
          <p class="text-lg font-bold ltr-nums" :class="f.tone">{{ f.value }}</p>
          <p class="text-[11px] text-slate-400 truncate" :title="f.sub">{{ f.sub }}</p>
        </div>
      </div>

      <!-- 2. Where did it go differently? -->
      <div v-if="report" class="grid grid-cols-1 xl:grid-cols-5 gap-3">
        <div class="xl:col-span-3">
          <VarianceBars :title="`انحراف به تفکیک سرفصل — ${report.month.label}`" :rows="lineRows" />
        </div>
        <div v-if="fall" class="xl:col-span-2">
          <BudgetWaterfall
            :title="`پل خالص نقد: از بودجه تا واقعی — ${report.month.label}`"
            :start="n(fall.start_rial)"
            :end="n(fall.end_rial)"
            :steps="steps"
            :max-steps="7"
            :height="360"
          />
        </div>
      </div>

      <div v-if="report && (inGroups.length || outGroups.length)" class="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <PlanActualBars
          :title="`ورودی به تفکیک گروه — ${report.month.label}`"
          subtitle="بیشتر از بودجه = مطلوب"
          :items="inGroups"
          empty="ورودی بودجه‌ریزی‌شده‌ای نیست."
        />
        <PlanActualBars
          :title="`خروجی به تفکیک گروه — ${report.month.label}`"
          subtitle="کمتر از بودجه = مطلوب"
          :items="outGroups"
          empty="خروجی بودجه‌ریزی‌شده‌ای نیست."
        />
      </div>

      <!-- 3. A month, or a pattern? -->
      <div v-if="points.length" class="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <MonthlyVarianceChart
          title="انحراف خالص نقد ماه‌به‌ماه"
          subtitle="ستون: واقعی منهای بودجهٔ هر ماه · خط: جمع انحراف تا آن ماه"
          :points="netPoints"
        />
        <BudgetCumulativeChart
          :title="series?.has_opening ? 'مانده پایان ماه — بودجه در برابر واقعی (مثل ردیف «مانده» اکسل)' : 'مانده تجمعی نقد — بودجه در برابر واقعی'"
          :labels="labels"
          :budget="cumulativeBudget"
          :actual="cumulativeActual"
        />
      </div>

      <ComboTrendChart
        v-if="points.length"
        title="جریان نقد ماهانه — واقعی (ستون) در برابر بودجه (خط‌چین)"
        :categories="labels"
        :bars="[
          { name: 'ورودی واقعی', values: points.map((p) => (p.has_actuals ? n(p.actual_in) : null)), tone: 'in' },
          { name: 'خروجی واقعی', values: points.map((p) => (p.has_actuals ? n(p.actual_out) : null)), tone: 'out' },
        ]"
        :lines="[
          { name: 'ورودی بودجه', values: points.map((p) => n(p.budget_in)), tone: 'in', dashed: true },
          { name: 'خروجی بودجه', values: points.map((p) => n(p.budget_out)), tone: 'out', dashed: true },
        ]"
        :height="300"
      />

      <!-- 4. Sales, from the sales section -->
      <div v-if="report && (salesChannels.length || hasSalesPlan)" class="grid grid-cols-1 xl:grid-cols-5 gap-3">
        <div class="xl:col-span-2">
          <PlanActualBars
            :title="`فروش به تفکیک کانال — ${report.month.label}`"
            subtitle="واقعی: ستون «واقعی» اکسل مالی؛ اگر خالی باشد، فروش تأییدشدهٔ بخش فروش"
            :items="salesChannels"
            empty="برای این ماه پیش‌بینی یا فروشی ثبت نشده."
          />
        </div>
        <div class="xl:col-span-3">
          <ComboTrendChart
            title="فروش ماهانه — واقعی بخش فروش (ستون) در برابر پیش‌بینی بودجه (خط‌چین)"
            :categories="labels"
            :bars="[{ name: 'فروش واقعی', values: points.map((p) => (n(p.actual_sales) ? n(p.actual_sales) : null)), tone: 'actual' }]"
            :lines="[{ name: 'پیش‌بینی فروش', values: points.map((p) => n(p.budget_sales)), tone: 'budget', dashed: true }]"
            :height="280"
          />
        </div>
      </div>

      <!-- The whole budget on one screen -->
      <BudgetHeatmap
        v-if="heat && heat.groups.length"
        title="نقشهٔ انحراف — گروه‌ها در ماه‌های بودجه"
        :months="heat.months" :groups="heat.groups" :cells="heat.cells"
      />

      <!-- The meeting agenda -->
      <section v-if="report" class="bg-surface rounded-card shadow-soft">
        <div class="flex items-center justify-between p-4 border-b border-slate-100">
          <h2 class="text-sm font-semibold text-ink">انحراف‌های نامطلوبِ مهم — {{ report.month.label }}</h2>
          <router-link :to="{ name: 'finance-budget-variance', query: linkQuery }" class="text-xs text-brand-700">همه ←</router-link>
        </div>
        <p v-if="!worst.length" class="text-sm text-slate-400 text-center py-8">انحراف نامطلوب مهمی در این ماه نیست.</p>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-[11px] text-slate-500">
                <th class="text-right font-medium p-3">سرفصل</th>
                <th class="text-left font-medium p-3">بودجه</th>
                <th class="text-left font-medium p-3">واقعی</th>
                <th class="text-left font-medium p-3">انحراف</th>
                <th class="text-right font-medium p-3">علت</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in worst" :key="`${r.code}-${r.line_id}-${r.kind}`" class="border-t border-slate-50">
                <td class="p-3 text-ink">
                  {{ r.label }}
                  <span class="text-[10px] text-slate-400 ms-1">{{ r.direction === 'in' ? 'ورودی' : 'خروجی' }}</span>
                </td>
                <td class="p-3 text-left ltr-nums text-slate-600 whitespace-nowrap">{{ money(n(r.budget_rial), false) }}</td>
                <td class="p-3 text-left ltr-nums whitespace-nowrap">{{ money(n(r.actual_rial), false) }}</td>
                <td class="p-3 text-left ltr-nums text-rose-700 dark:text-rose-400 whitespace-nowrap">
                  {{ n(r.variance_rial) > 0 ? '+' : '' }}{{ money(n(r.variance_rial), false) }}
                  <span v-if="r.variance_pct !== null" class="text-[10px]">({{ FA.format(Math.round(r.variance_pct)) }}٪)</span>
                </td>
                <td class="p-3 text-xs" :class="r.note ? 'text-slate-600' : 'text-amber-600'">
                  {{ r.note || (r.kind === 'unbudgeted' ? 'خارج از بودجه' : 'علت ثبت نشده') }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
