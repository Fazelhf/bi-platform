<script setup lang="ts">
/**
 * انحراف بودجه — what was expected beside what happened, down the tree.
 *
 * Monthly, like the rest of the budget: the month's plan against everything
 * recorded for that month.
 *
 * Colour comes from the server's verdict, never from the sign: spending more
 * than planned is bad, collecting more is good.
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  apiError,
  budgetApi,
  type Direction,
  type VarianceCell,
  type VarianceReport,
  type VarianceRow,
} from "@/api/budget";
import { useBudgetContext } from "@/composables/useBudgetContext";
import { loadMoneySettings, useMoney } from "@/composables/useMoney";
import { prompt, toast } from "@/composables/useUi";
import { useAuthStore } from "@/stores/auth";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import BulletBars from "@/components/charts/BulletBars.vue";

const { budgets, budgetId, periodId, months, linkQuery, init } = useBudgetContext();
const { money, unitLabel } = useMoney();
const auth = useAuthStore();

const canWriteNotes = computed(() => auth.department === "finance" || !!auth.me?.is_superuser);

const report = ref<VarianceReport | null>(null);
const loading = ref(true);
const error = ref("");

const dir = ref<"all" | Direction>("all");
const onlyMaterial = ref(false);
const showBaseline = ref(false);
const collapsed = reactive(new Set<string>());

const FA = new Intl.NumberFormat("fa-IR");
const n = (v: string | number | null | undefined) => Number(v ?? 0);

// ---- load -------------------------------------------------------------

async function load() {
  const target = periodId.value;
  if (!budgetId.value || !target) {
    report.value = null;
    loading.value = false;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    report.value = await budgetApi.variance(budgetId.value, target);
  } catch (e: any) {
    report.value = null;
    error.value = e?.response?.status === 403
      ? "بخش مالی برای شما قابل مشاهده نیست."
      : apiError(e, "گزارش انحراف ساخته نشد.");
  } finally {
    loading.value = false;
  }
}

watch([budgetId, periodId], load);

onMounted(async () => {
  try {
    await loadMoneySettings();
    await init();
    await load();
  } catch (e) {
    error.value = apiError(e, "بارگذاری ناموفق بود.");
    loading.value = false;
  }
});

// ---- rows -------------------------------------------------------------

/** Every non-category row beneath a category, until the tree steps back out. */
function descendants(rows: VarianceRow[], index: number): VarianceRow[] {
  const head = rows[index];
  const out: VarianceRow[] = [];
  for (let i = index + 1; i < rows.length && rows[i].depth > head.depth; i++) {
    if (rows[i].kind !== "category") out.push(rows[i]);
  }
  return out;
}

const visibleRows = computed(() => {
  const all = (report.value?.rows ?? []).filter((r) => dir.value === "all" || r.direction === dir.value);

  // «فقط مهم» keeps a category only when something beneath it is material,
  // so a filtered grid still shows where each surviving line sits.
  const filtered = onlyMaterial.value
    ? all.filter((r, i) =>
        r.kind === "category" ? descendants(all, i).some((d) => d.is_material) : r.is_material,
      )
    : all;

  const out: VarianceRow[] = [];
  let hideBelow: number | null = null;
  for (const row of filtered) {
    if (hideBelow !== null && row.depth > hideBelow) continue;
    hideBelow = null;
    out.push(row);
    if (row.kind === "category" && collapsed.has(row.code)) hideBelow = row.depth;
  }
  return out;
});

const leafRows = computed(() => (report.value?.rows ?? []).filter((r) => r.kind !== "category"));
const materialCount = computed(() => leafRows.value.filter((r) => r.is_material).length);
/** Material, unfavourable, unexplained — the list for the monthly meeting. */
const unexplained = computed(
  () => leafRows.value.filter((r) => r.is_material && r.verdict === "bad" && r.kind === "line" && !r.note).length,
);

function toggle(row: VarianceRow) {
  if (collapsed.has(row.code)) collapsed.delete(row.code);
  else collapsed.add(row.code);
}
function collapseAll(on: boolean) {
  collapsed.clear();
  if (on) for (const r of report.value?.rows ?? []) if (r.kind === "category") collapsed.add(r.code);
}

// ---- formatting --------------------------------------------------------

const verdictText: Record<string, string> = {
  good: "text-green-600",
  bad: "text-red-600",
  "on-track": "text-slate-400",
};
const verdictLabel: Record<string, string> = {
  good: "مطلوب",
  bad: "نامطلوب",
  "on-track": "طبق برنامه",
};
const verdictChip: Record<string, string> = {
  good: "bg-green-50 text-green-700",
  bad: "bg-red-50 text-red-600",
  "on-track": "bg-slate-100 text-slate-500",
};

function signed(v: string | number) {
  const x = n(v);
  return `${x > 0 ? "+" : ""}${money(x, false)}`;
}
function pct(p: number | null) {
  if (p === null || p === undefined) return "—";
  const r = Math.round(p * 10) / 10;
  return `${r > 0 ? "+" : ""}${FA.format(r)}٪`;
}
/** Share of plan used — the little bar under «واقعی». Capped so 400% still fits. */
function usage(cell: VarianceCell) {
  const b = n(cell.budget_rial);
  if (!b) return null;
  return Math.min(n(cell.actual_rial) / b, 1.5) / 1.5;
}

// ---- notes ------------------------------------------------------------

async function editNote(row: VarianceRow) {
  const r = report.value;
  if (!r || !row.line_id || !r.budget_period_id) return;
  const answer = await prompt({
    title: `علت انحراف — ${row.label}`,
    message: `بودجه ${money(n(row.budget_rial))}، واقعی ${money(n(row.actual_rial))}. چرا؟`,
    placeholder: "مثلاً: خرید پیش از افزایش قیمت جمبو جلو افتاد",
    value: row.note,
  });
  if (answer === null) return;
  try {
    await budgetApi.saveNote(r.budget_period_id, row.line_id, answer);
    row.note = answer;
    toast.success("علت انحراف ثبت شد.");
  } catch (e) {
    toast.error(apiError(e, "ثبت نشد."));
  }
}

/** Top-level groups, plan against actual — the tree's first level, drawn. */
function groupsOf(side: Direction) {
  return (report.value?.rows ?? [])
    .filter((r) => r.depth === 0 && r.direction === side && (n(r.budget_rial) || n(r.actual_rial)))
    .map((r) => ({ label: r.label, budget: n(r.budget_rial), actual: n(r.actual_rial), verdict: r.verdict }));
}
const inGroups = computed(() => groupsOf("in"));
const outGroups = computed(() => groupsOf("out"));

const totalCards = computed(() => {
  const t = report.value?.totals;
  if (!t) return [];
  return [
    { key: "in", title: "ورودی", cell: t.in },
    { key: "out", title: "خروجی", cell: t.out },
    { key: "net", title: "خالص", cell: t.net },
  ];
});
</script>

<template>
  <div class="space-y-4">
    <!-- Header -->
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-bold text-ink">انحراف بودجه</h1>
        <p class="text-xs text-slate-400 mt-0.5">
          مورد انتظار در برابر واقعی · همه ارقام به <span class="font-medium">{{ unitLabel }}</span>
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
          :to="{ name: 'finance-budget', query: linkQuery }"
          class="px-3 py-1.5 text-sm rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200"
        >داشبورد</router-link>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>

    <section v-else-if="!loading && !budgets.length" class="bg-surface rounded-card shadow-soft p-10 text-center">
      <p class="font-semibold text-ink">هنوز بودجه‌ای تعریف نشده</p>
      <router-link :to="{ name: 'finance-budget-plan' }" class="inline-block mt-3 text-sm text-brand-700">رفتن به تعریف بودجه ←</router-link>
    </section>

    <DashboardSkeleton v-else-if="loading && !report" />

    <template v-else-if="report">
      <!-- Nothing recorded yet: the plan is being compared against zero. -->
      <div v-if="!report.has_actuals" class="rounded-card p-3 text-sm bg-sky-50 text-sky-800 leading-6">
        <span class="font-semibold">برای {{ report.period.label }} هنوز هیچ رقم واقعی ثبت نشده است.</span>
        ستون «واقعی» صفر است، پس انحراف‌های زیر یعنی «هنوز ثبت نشده»، نه کسری یا صرفه‌جویی.
      </div>

      <div
        v-if="report.status !== 'approved'"
        class="rounded-card p-3 text-sm bg-slate-100 text-slate-600"
      >
        بودجهٔ {{ report.month.label }} هنوز تصویب نشده — مقایسه با ارقام پیش‌نویس است.
      </div>

      <!-- Totals -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div v-for="c in totalCards" :key="c.key" class="bg-surface rounded-card shadow-soft p-4">
          <div class="flex items-center justify-between">
            <p class="text-xs font-semibold text-ink">{{ c.title }}</p>
            <span class="px-1.5 py-0.5 rounded-md text-[10px]" :class="verdictChip[c.cell.verdict]">{{ verdictLabel[c.cell.verdict] }}</span>
          </div>
          <div class="grid grid-cols-2 gap-2 mt-3 text-xs">
            <div>
              <p class="text-slate-400">مورد انتظار</p>
              <p class="font-semibold text-slate-600 ltr-nums mt-0.5">{{ money(n(c.cell.budget_rial), false) }}</p>
            </div>
            <div>
              <p class="text-slate-400">واقعی</p>
              <p class="font-semibold text-ink ltr-nums mt-0.5">{{ money(n(c.cell.actual_rial), false) }}</p>
            </div>
          </div>
          <p class="text-lg font-bold ltr-nums mt-2" :class="verdictText[c.cell.verdict]">
            {{ signed(c.cell.variance_rial) }}
            <span class="text-xs font-medium">{{ pct(c.cell.variance_pct) }}</span>
          </p>
        </div>
      </div>

      <div v-if="inGroups.length || outGroups.length" class="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <BulletBars v-if="outGroups.length" title="خروجی به تفکیک گروه" :items="outGroups" />
        <BulletBars v-if="inGroups.length" title="ورودی به تفکیک گروه" :items="inGroups" />
      </div>

      <!-- Filters -->
      <section class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center justify-between gap-3">
        <div class="flex flex-wrap items-center gap-2">
          <div class="flex bg-slate-100 rounded-xl p-0.5">
            <button
              v-for="d in ([['all', 'همه'], ['in', 'ورودی'], ['out', 'خروجی']] as const)"
              :key="d[0]"
              class="px-3 py-1 text-xs rounded-lg transition"
              :class="dir === d[0] ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-500'"
              @click="dir = d[0]"
            >{{ d[1] }}</button>
          </div>
          <label class="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
            <input v-model="onlyMaterial" type="checkbox" class="rounded" /> فقط انحراف‌های مهم
          </label>
          <label class="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
            <input v-model="showBaseline" type="checkbox" class="rounded" /> ستون مصوب
          </label>
          <button class="text-xs text-slate-500 hover:text-ink" @click="collapseAll(true)">بستن همه</button>
          <button class="text-xs text-slate-500 hover:text-ink" @click="collapseAll(false)">باز کردن همه</button>
        </div>
        <div class="flex flex-wrap items-center gap-2 text-[11px]">
          <span class="px-2 py-1 rounded-lg bg-slate-100 text-slate-600">
            مهم: {{ FA.format(materialCount) }}
          </span>
          <span v-if="unexplained" class="px-2 py-1 rounded-lg bg-amber-50 text-amber-700">
            نامطلوبِ بدون علت: {{ FA.format(unexplained) }}
          </span>
          <span v-if="report.unbudgeted_count" class="px-2 py-1 rounded-lg bg-red-50 text-red-600">
            خارج از بودجه: {{ FA.format(report.unbudgeted_count) }}
          </span>
          <span class="text-slate-400">
            آستانه: {{ FA.format(n(report.thresholds.pct)) }}٪
            <template v-if="n(report.thresholds.rial)"> و {{ money(n(report.thresholds.rial)) }}</template>
          </span>
        </div>
      </section>

      <!-- Tree grid -->
      <section class="bg-surface rounded-card shadow-soft">
        <p v-if="!visibleRows.length" class="text-sm text-slate-400 text-center py-10">
          {{ onlyMaterial ? 'انحراف مهمی در این دوره نیست.' : 'در این دوره نه بودجه‌ای ثبت شده نه حرکتی.' }}
        </p>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead>
              <tr class="text-[11px] text-slate-500 border-b border-slate-100">
                <th class="text-right font-medium p-3 min-w-[16rem]">سرفصل</th>
                <th class="text-left font-medium p-3">مورد انتظار</th>
                <th v-if="showBaseline" class="text-left font-medium p-3">مصوب</th>
                <th class="text-left font-medium p-3 min-w-[8rem]">واقعی</th>
                <th class="text-left font-medium p-3">انحراف</th>
                <th class="text-left font-medium p-3">٪</th>
                <th class="text-right font-medium p-3 min-w-[12rem]">وضعیت / علت</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visibleRows"
                :key="`${row.kind}-${row.code}-${row.line_id ?? ''}-${row.direction}`"
                class="border-b border-slate-50"
                :class="row.kind === 'category' ? (row.depth === 0 ? 'bg-slate-50/80 font-semibold' : 'bg-slate-50/30 font-medium') : 'hover:bg-slate-50/50'"
              >
                <td class="p-2" :style="{ paddingInlineStart: `${row.depth * 18 + 10}px` }">
                  <div class="flex items-center gap-1.5">
                    <button
                      v-if="row.kind === 'category'"
                      class="w-4 h-4 text-[10px] text-slate-400 hover:text-ink transition-transform"
                      :class="collapsed.has(row.code) ? '' : '-rotate-90'"
                      @click="toggle(row)"
                    >◀</button>
                    <span v-else class="w-4"></span>
                    <span
                      :class="row.kind === 'unbudgeted' ? 'text-amber-700 italic' : 'text-ink'"
                    >{{ row.label }}</span>
                    <span v-if="row.is_material && row.kind !== 'category'" class="w-1.5 h-1.5 rounded-full bg-current" :class="verdictText[row.verdict]" title="انحراف مهم"></span>
                  </div>
                </td>
                <td class="p-2 text-left ltr-nums text-slate-600 whitespace-nowrap">{{ money(n(row.budget_rial), false) }}</td>
                <td v-if="showBaseline" class="p-2 text-left ltr-nums text-slate-400 whitespace-nowrap">
                  {{ row.baseline_rial === null ? '—' : money(n(row.baseline_rial), false) }}
                </td>
                <td class="p-2 text-left whitespace-nowrap">
                  <p class="ltr-nums text-ink">{{ money(n(row.actual_rial), false) }}</p>
                  <div v-if="usage(row) !== null" class="h-1 bg-slate-100 rounded-full mt-1 overflow-hidden relative">
                    <!-- the 100% mark sits at two-thirds, since the bar is capped at 150% -->
                    <span class="absolute inset-y-0 w-px bg-slate-400" style="left: 66.6%"></span>
                    <span
                      class="block h-full rounded-full"
                      :class="row.verdict === 'bad' ? 'bg-red-400' : row.verdict === 'good' ? 'bg-green-500' : 'bg-slate-400'"
                      :style="{ width: `${(usage(row) ?? 0) * 100}%` }"
                    ></span>
                  </div>
                </td>
                <td class="p-2 text-left ltr-nums whitespace-nowrap" :class="verdictText[row.verdict]">{{ signed(row.variance_rial) }}</td>
                <td class="p-2 text-left ltr-nums whitespace-nowrap text-xs" :class="verdictText[row.verdict]">{{ pct(row.variance_pct) }}</td>
                <td class="p-2">
                  <div class="flex items-center gap-2">
                    <span v-if="row.kind !== 'category'" class="px-1.5 py-0.5 rounded-md text-[10px] shrink-0" :class="verdictChip[row.verdict]">
                      {{ row.kind === 'unbudgeted' ? 'بدون بودجه' : verdictLabel[row.verdict] }}
                    </span>
                    <template v-if="row.kind === 'line'">
                      <button
                        v-if="row.note"
                        class="text-xs text-slate-600 truncate max-w-[14rem] text-right hover:text-ink"
                        :title="row.note"
                        :disabled="!canWriteNotes"
                        @click="editNote(row)"
                      >{{ row.note }}</button>
                      <button
                        v-else-if="row.is_material && row.verdict === 'bad' && canWriteNotes"
                        class="text-[11px] px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 hover:bg-amber-100"
                        @click="editNote(row)"
                      >+ ثبت علت</button>
                      <button
                        v-else-if="canWriteNotes"
                        class="text-[11px] text-slate-300 hover:text-slate-500"
                        @click="editNote(row)"
                      >یادداشت</button>
                    </template>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
