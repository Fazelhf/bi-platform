<script setup lang="ts">
/**
 * داشبورد بودجه — the page the CEO opens.
 *
 * Built around three questions, in the order they get asked:
 *
 * 1. **Are we on plan?** — the KPI row, judged by the server's verdict.
 * 2. **Where did the money go differently?** — the waterfall from planned to
 *    actual net cash, and the largest variances beside it.
 * 3. **Where will we end up?** — cumulative cash, planned against actual:
 *    the position, not just the monthly surplus.
 */
import { computed, onMounted, ref, watch } from "vue";
import {
  apiError,
  budgetApi,
  type BudgetSeries,
  type VarianceReport,
  type Waterfall,
} from "@/api/budget";
import { useBudgetContext } from "@/composables/useBudgetContext";
import { loadMoneySettings, useMoney } from "@/composables/useMoney";
import SeriesChart from "@/components/charts/SeriesChart.vue";
import BudgetWaterfall from "@/components/charts/BudgetWaterfall.vue";
import BudgetTornado from "@/components/charts/BudgetTornado.vue";
import BudgetCumulativeChart from "@/components/charts/BudgetCumulativeChart.vue";
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
const loading = ref(true);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");
const n = (v: string | number | null | undefined) => Number(v ?? 0);

async function loadSeries() {
  if (!budgetId.value) return;
  try {
    series.value = await budgetApi.series(budgetId.value);
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

// ---- KPIs -------------------------------------------------------------

const leafRows = computed(() => (report.value?.rows ?? []).filter((r) => r.kind !== "category"));

const achievement = (cellKey: "in" | "out") => {
  const c = report.value?.totals[cellKey];
  if (!c || !n(c.budget_rial)) return null;
  return Math.round((n(c.actual_rial) / n(c.budget_rial)) * 1000) / 10;
};

const kpis = computed(() => {
  const r = report.value;
  if (!r) return [];
  const material = leafRows.value.filter((x) => x.is_material);
  const bad = material.filter((x) => x.verdict === "bad");
  const unexplained = bad.filter((x) => x.kind === "line" && !x.note);
  const inPct = achievement("in");
  const outPct = achievement("out");
  const salesBudget = n(r.sales.total.budget_rial);
  const salesPct = salesBudget
    ? Math.round((n(r.sales.total.actual_rial) / salesBudget) * 1000) / 10
    : null;
  const tone = (v: string) =>
    v === "good" ? "text-green-600" : v === "bad" ? "text-red-600" : "text-slate-500";

  return [
    {
      title: "تحقق فروش",
      value: salesPct === null ? "—" : `${FA.format(salesPct)}٪`,
      sub: `${money(n(r.sales.total.actual_rial))} از ${money(n(r.sales.total.budget_rial), false)}`,
      tone: tone(r.sales.total.verdict),
    },
    {
      title: "تحقق ورودی",
      value: inPct === null ? "—" : `${FA.format(inPct)}٪`,
      sub: `${money(n(r.totals.in.actual_rial))} از ${money(n(r.totals.in.budget_rial), false)}`,
      tone: tone(r.totals.in.verdict),
    },
    {
      title: "مصرف بودجهٔ خروجی",
      value: outPct === null ? "—" : `${FA.format(outPct)}٪`,
      sub: `${money(n(r.totals.out.actual_rial))} از ${money(n(r.totals.out.budget_rial), false)}`,
      tone: tone(r.totals.out.verdict),
    },
    {
      title: "انحراف خالص نقدینگی",
      value: `${n(r.totals.net.variance_rial) > 0 ? "+" : ""}${money(n(r.totals.net.variance_rial), false)}`,
      sub: `واقعی ${money(n(r.totals.net.actual_rial))}`,
      tone: tone(r.totals.net.verdict),
    },
    {
      title: "انحراف‌های مهم",
      value: FA.format(material.length),
      sub: bad.length ? `${FA.format(bad.length)} مورد نامطلوب` : "همه مطلوب یا طبق برنامه",
      tone: bad.length ? "text-red-600" : "text-green-600",
    },
    {
      title: "نامطلوبِ بدون علت",
      value: FA.format(unexplained.length),
      sub: unexplained.length ? "هنوز توضیحی ثبت نشده" : "همه توضیح دارند",
      tone: unexplained.length ? "text-amber-600" : "text-green-600",
    },
    {
      title: "ماه‌های مصوب",
      value: budget.value ? `${FA.format(budget.value.approved_count)} از ${FA.format(budget.value.month_count)}` : "—",
      sub: r.status === "approved" ? `${r.month.label} مصوب است` : `${r.month.label} پیش‌نویس است`,
      tone: "text-ink",
    },
  ];
});

// ---- charts -----------------------------------------------------------

const points = computed(() => series.value?.points ?? []);
const labels = computed(() => points.value.map((p) => p.label));

const inSeries = computed(() => [
  { name: "مورد انتظار", values: points.value.map((p) => n(p.budget_in)) },
  { name: "واقعی", values: points.value.map((p) => n(p.actual_in)) },
]);
const salesSeries = computed(() => [
  { name: "پیش‌بینی", values: points.value.map((p) => n(p.budget_sales)) },
  { name: "فروش ثبت‌شده", values: points.value.map((p) => n(p.actual_sales)) },
]);
const outSeries = computed(() => [
  { name: "مورد انتظار", values: points.value.map((p) => n(p.budget_out)) },
  { name: "واقعی", values: points.value.map((p) => n(p.actual_out)) },
]);

/** Actuals stop at the last month anything was recorded — see the chart. */
const lastActual = computed(() => {
  let last = -1;
  points.value.forEach((p, i) => {
    if (n(p.actual_in) || n(p.actual_out)) last = i;
  });
  return last;
});
const cumulativeBudget = computed(() => points.value.map((p) => n(p.cumulative_budget)));
const cumulativeActual = computed(() =>
  points.value.map((p, i) => (i <= lastActual.value ? n(p.cumulative_actual) : null)),
);

const steps = computed(() =>
  (fall.value?.steps ?? []).map((s) => ({ label: s.label, effect: n(s.effect_rial), verdict: s.verdict })),
);

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
        {{ isCeo ? 'از «تعریف بودجه» اولین بودجه را بسازید.' : 'مدیرعامل هنوز بودجه‌ای تعریف نکرده است.' }}
      </p>
      <router-link v-if="isCeo" :to="{ name: 'finance-budget-plan' }" class="inline-block mt-3 text-sm text-brand-700">رفتن به تعریف بودجه ←</router-link>
    </section>

    <template v-else>
      <!-- Nothing recorded yet: say so before the KPIs look like a crisis. -->
      <div v-if="report && !report.has_actuals" class="rounded-card p-3 text-sm bg-sky-50 text-sky-800 leading-6">
        <span class="font-semibold">برای {{ report.month.label }} هنوز هیچ رقم واقعی ثبت نشده است.</span>
        ارقام «واقعی» صفرند و انحراف‌ها یعنی «هنوز ثبت نشده» — برای دیدن عملکرد، ماهی را انتخاب کنید که ارقام واقعی‌اش وارد شده.
      </div>

      <!-- 1. On plan? -->
      <div v-if="report" class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
        <div v-for="k in kpis" :key="k.title" class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">{{ k.title }}</p>
          <p class="text-xl font-bold ltr-nums mt-1" :class="k.tone">{{ k.value }}</p>
          <p class="text-[11px] text-slate-400 mt-1 truncate" :title="k.sub">{{ k.sub }}</p>
        </div>
      </div>

      <!-- 2. Where did it go differently? -->
      <div v-if="report && fall" class="grid grid-cols-1 xl:grid-cols-5 gap-3">
        <div class="xl:col-span-3">
          <BudgetWaterfall
            :title="`از بودجهٔ خالص تا واقعی — ${report.month.label}`"
            :start="n(fall.start_rial)"
            :end="n(fall.end_rial)"
            :steps="steps"
          />
        </div>
        <div class="xl:col-span-2">
          <BudgetTornado title="بزرگ‌ترین اثرها بر نقدینگی" :items="steps" />
        </div>
      </div>

      <!-- 3. Where will we end up? -->
      <BudgetCumulativeChart
        v-if="points.length"
        title="مانده تجمعی نقدینگی — مورد انتظار در برابر واقعی"
        :labels="labels"
        :budget="cumulativeBudget"
        :actual="cumulativeActual"
      />

      <div v-if="points.length" class="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <SeriesChart title="فروش ماهانه" :categories="labels" :series="salesSeries" :height="240" />
        <SeriesChart title="ورودی ماهانه" :categories="labels" :series="inSeries" :height="240" />
        <SeriesChart title="خروجی ماهانه" :categories="labels" :series="outSeries" :height="240" />
      </div>

      <!-- The meeting agenda -->
      <section v-if="report" class="bg-surface rounded-card shadow-soft">
        <div class="flex items-center justify-between p-4 border-b border-slate-100">
          <h2 class="text-sm font-semibold text-ink">انحراف‌های نامطلوبِ مهم — {{ report.month.label }}</h2>
          <router-link :to="{ name: 'finance-budget-variance', query: linkQuery }" class="text-xs text-brand-700">همه ←</router-link>
        </div>
        <p v-if="!worst.length" class="text-sm text-slate-400 text-center py-8">انحراف نامطلوب مهمی در این ماه نیست.</p>
        <table v-else class="min-w-full text-sm">
          <thead>
            <tr class="text-[11px] text-slate-500">
              <th class="text-right font-medium p-3">سرفصل</th>
              <th class="text-left font-medium p-3">مورد انتظار</th>
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
              <td class="p-3 text-left ltr-nums text-red-600 whitespace-nowrap">
                {{ n(r.variance_rial) > 0 ? '+' : '' }}{{ money(n(r.variance_rial), false) }}
              </td>
              <td class="p-3 text-xs" :class="r.note ? 'text-slate-600' : 'text-amber-600'">
                {{ r.note || (r.kind === 'unbudgeted' ? 'خارج از بودجه' : 'علت ثبت نشده') }}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
