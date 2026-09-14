/**
 * Which budget and which month a budget page is looking at.
 *
 * The three budget pages — plan, variance, dashboard — are one workflow, and
 * jumping from «this line is 20% over» on the dashboard to the grid that
 * explains it must not land on a different month. So the choice lives in the
 * URL (`?budget=&period=`) rather than in each page: links carry it, reload
 * keeps it, and a shared link opens on the same figures.
 */
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { budgetApi, type Budget } from "@/api/budget";
import { salesApi } from "@/api/sales";
import type { Period } from "@/types";

const monthKey = (p: Pick<Period, "jalali_year" | "jalali_month">) =>
  p.jalali_year * 100 + p.jalali_month;

export function useBudgetContext() {
  const route = useRoute();
  const router = useRouter();

  const budgets = ref<Budget[]>([]);
  const periods = ref<Period[]>([]);
  const budgetId = ref<number | null>(null);
  const periodId = ref<number | null>(null);
  const ready = ref(false);

  const budget = computed(() => budgets.value.find((b) => b.id === budgetId.value) ?? null);

  /** Budgets are only ever set on months — weeks are chosen separately. */
  const monthPeriods = computed(() =>
    periods.value.filter((p) => !p.kind || p.kind === "month"),
  );

  /** The months inside the selected budget's span. */
  const months = computed<Period[]>(() => {
    const b = budget.value;
    if (!b) return [];
    const start = periods.value.find((p) => p.id === b.start_period);
    const end = periods.value.find((p) => p.id === b.end_period);
    if (!start || !end) return [];
    return monthPeriods.value.filter(
      (p) => monthKey(p) >= monthKey(start) && monthKey(p) <= monthKey(end),
    );
  });

  /**
   * The month to open on: the one in the URL if it belongs to this budget,
   * else the latest month that has started — a budget read in مهر is about
   * مهر, not about اسفند — else the first.
   */
  function defaultMonth(): number | null {
    const list = months.value;
    if (!list.length) return null;
    const asked = Number(route.query.period);
    if (list.some((p) => p.id === asked)) return asked;
    const today = new Date().toISOString().slice(0, 10);
    const started = list.filter((p) => p.start_date && p.start_date <= today);
    return (started.length ? started[started.length - 1] : list[0]).id;
  }

  async function init() {
    const [b, p] = await Promise.all([budgetApi.list(), salesApi.periods()]);
    budgets.value = b;
    periods.value = p;
    const asked = Number(route.query.budget);
    budgetId.value =
      b.find((x) => x.id === asked)?.id ??
      b.find((x) => x.is_active)?.id ??
      b[0]?.id ??
      null;
    periodId.value = defaultMonth();
    ready.value = true;
    syncQuery();
  }

  async function refreshBudgets(selectId?: number) {
    budgets.value = await budgetApi.list();
    if (selectId) budgetId.value = selectId;
  }

  function syncQuery() {
    const query = { ...route.query };
    if (budgetId.value) query.budget = String(budgetId.value);
    else delete query.budget;
    if (periodId.value) query.period = String(periodId.value);
    else delete query.period;
    router.replace({ query });
  }

  watch(budgetId, (id, old) => {
    if (!ready.value) return;
    if (id !== old) periodId.value = defaultMonth();
    syncQuery();
  });
  watch(periodId, () => {
    if (ready.value) syncQuery();
  });

  /** Query string for a link to a sibling budget page. */
  const linkQuery = computed(() => ({
    ...(budgetId.value ? { budget: String(budgetId.value) } : {}),
    ...(periodId.value ? { period: String(periodId.value) } : {}),
  }));

  return {
    budgets,
    periods,
    monthPeriods,
    budgetId,
    periodId,
    budget,
    months,
    ready,
    linkQuery,
    init,
    refreshBudgets,
  };
}
