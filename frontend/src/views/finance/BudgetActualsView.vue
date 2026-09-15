<script setup lang="ts">
/**
 * ورود ارقام واقعی بودجه — the finance team's weekly sheet.
 *
 * The CEO defines the budget; this is where finance reports what actually
 * happened against every سرفصل of it. Figures go in one week at a time, like
 * sales entry: the week's plan is the month's pro-rated by day count, and
 * «کل ماه» shows the month as the read-only sum of its weeks.
 *
 * Enter moves down the column, so a week of figures can be keyed without the
 * mouse; nothing is saved until «ذخیره».
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import {
  apiError,
  budgetApi,
  type ActualEntryLine,
  type ActualEntrySheet,
  type Direction,
  type Verdict,
} from "@/api/budget";
import { useBudgetContext } from "@/composables/useBudgetContext";
import { loadMoneySettings, useMoney } from "@/composables/useMoney";
import { confirm, toast } from "@/composables/useUi";
import MoneyInput from "@/components/MoneyInput.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";

const { budgets, budgetId, periodId, months, linkQuery, init } = useBudgetContext();
const { money, unitLabel } = useMoney();

const sheet = ref<ActualEntrySheet | null>(null);
const loading = ref(true);
const saving = ref(false);
const error = ref("");

/** The week being keyed; null when the month itself is the entry period. */
const weekId = ref<number | null>(null);
/** «کل ماه» — the month read as the sum of its weeks. */
const monthView = ref(false);

const FA = new Intl.NumberFormat("fa-IR");
const n = (v: string | number | null | undefined) => Number(v ?? 0);

// ---- edits ------------------------------------------------------------------

/** Unsaved edits by line id. Anything here differs from what is stored. */
const draft = reactive<Record<number, { amount: string; note: string }>>({});
const dirtyCount = computed(() => Object.keys(draft).length);

function clearDraft() {
  for (const k of Object.keys(draft)) delete draft[Number(k)];
}

const amountOf = (line: ActualEntryLine) => draft[line.line_id]?.amount ?? line.actual_rial;
const noteOf = (line: ActualEntryLine) => draft[line.line_id]?.note ?? line.note;

function setCell(line: ActualEntryLine, amount: string, note: string) {
  // Typing a figure back to what is stored is not an edit.
  if (n(amount) === n(line.actual_rial) && note === line.note) delete draft[line.line_id];
  else draft[line.line_id] = { amount, note };
}
function setAmount(line: ActualEntryLine, raw: string) {
  setCell(line, raw === "" || raw === "-" ? "0" : raw, noteOf(line));
}
function setNote(line: ActualEntryLine, note: string) {
  setCell(line, amountOf(line), note);
}
const isDirty = (line: ActualEntryLine) => line.line_id in draft;

// ---- figures as typed --------------------------------------------------------------

/** Over plan is bad for money going out and good for money coming in. */
function verdictOf(direction: Direction, variance: number): Verdict {
  if (variance === 0) return "on-track";
  return (direction === "in" ? variance > 0 : variance < 0) ? "good" : "bad";
}
const varianceOf = (line: ActualEntryLine) => n(amountOf(line)) - n(line.budget_rial);

const verdictText: Record<Verdict, string> = {
  good: "text-green-600",
  bad: "text-red-600",
  "on-track": "text-slate-400",
};

function signed(v: number) {
  return `${v > 0 ? "+" : ""}${money(v, false)}`;
}

const sections = computed(() =>
  (["in", "out"] as Direction[]).map((dir) => {
    const lines = (sheet.value?.lines ?? []).filter((l) => l.direction === dir);
    // One group per parent category, in the order each first appears. Lines
    // come back ordered by the plan, not by parent, so grouping only while
    // consecutive printed «فروش» and «سایر» as headers more than once.
    const byTitle = new Map<string, ActualEntryLine[]>();
    for (const line of lines) {
      const title = line.parent_name || "سایر";
      byTitle.set(title, [...(byTitle.get(title) ?? []), line]);
    }
    const groups = [...byTitle.entries()].map(([title, grouped]) => ({ title, lines: grouped }));
    const budget = lines.reduce((s, l) => s + n(l.budget_rial), 0);
    const actual = lines.reduce((s, l) => s + n(amountOf(l)), 0);
    return {
      dir,
      title: dir === "in" ? "ورودی" : "خروجی",
      groups,
      budget,
      actual,
      verdict: verdictOf(dir, actual - budget),
    };
  }),
);

/** Row position across both sections, for Enter-moves-down. */
const rowIndex = computed(() => {
  const map = new Map<number, number>();
  let i = 0;
  for (const s of sections.value) for (const g of s.groups) for (const l of g.lines) map.set(l.line_id, i++);
  return map;
});

function moveDown(row: number, e: KeyboardEvent) {
  const next = e.shiftKey ? row - 1 : row + 1;
  const input = document.querySelector<HTMLInputElement>(`td[data-row="${next}"] input`);
  if (input) {
    input.focus();
    input.select();
  }
}

// ---- weeks --------------------------------------------------------------------------

/** Whether the month is cut into weeks (otherwise the month is the entry period). */
const isWeekly = computed(() => {
  const s = sheet.value;
  return !!s && !(s.weeks.length === 1 && s.weeks[0].period_id === s.month.id);
});

const readonly = computed(() => !sheet.value?.can_edit);

// ---- load / save ---------------------------------------------------------------------

async function fetchSheet(targetId: number) {
  if (!budgetId.value) return;
  loading.value = true;
  error.value = "";
  try {
    sheet.value = await budgetApi.actuals(budgetId.value, targetId);
  } catch (e: any) {
    sheet.value = null;
    error.value = e?.response?.status === 403
      ? "بخش مالی برای شما قابل مشاهده نیست."
      : apiError(e, "برگهٔ ارقام واقعی بارگذاری نشد.");
  } finally {
    loading.value = false;
  }
}

/**
 * Open a month: read it once to learn its weeks, then land on the first week
 * nobody has keyed yet — or the last one, when every week has figures.
 */
async function openMonth() {
  clearDraft();
  monthView.value = false;
  weekId.value = null;
  if (!budgetId.value || !periodId.value) {
    sheet.value = null;
    loading.value = false;
    return;
  }
  await fetchSheet(periodId.value);
  const s = sheet.value;
  if (!s || !s.is_rollup) return;
  const next = s.weeks.find((w) => w.entered === 0) ?? s.weeks[s.weeks.length - 1];
  weekId.value = next.period_id;
  await fetchSheet(next.period_id);
}

async function leaveDraft(): Promise<boolean> {
  if (!dirtyCount.value) return true;
  const ok = await confirm({
    title: "تغییرات ذخیره نشده",
    message: "ارقامی که وارد کرده‌اید هنوز ذخیره نشده‌اند. بدون ذخیره ادامه می‌دهید؟",
    danger: true,
  });
  if (ok) clearDraft();
  return ok;
}

async function pickWeek(id: number) {
  if (!monthView.value && weekId.value === id) return;
  if (!(await leaveDraft())) return;
  monthView.value = false;
  weekId.value = id;
  await fetchSheet(id);
}

async function openMonthView() {
  if (monthView.value || !periodId.value) return;
  if (!(await leaveDraft())) return;
  monthView.value = true;
  await fetchSheet(periodId.value);
}

async function save() {
  const s = sheet.value;
  if (!s || !budgetId.value || !dirtyCount.value) return;
  saving.value = true;
  try {
    const cells = Object.entries(draft).map(([id, d]) => ({
      line_id: Number(id),
      amount_rial: d.amount,
      note: d.note,
    }));
    const res = await budgetApi.saveActuals(budgetId.value, s.period.id, cells);
    clearDraft();
    await fetchSheet(s.period.id);
    toast.success(`${FA.format(res.written)} سرفصل ذخیره شد.`);
  } catch (e) {
    toast.error(apiError(e, "ذخیره نشد."));
  } finally {
    saving.value = false;
  }
}

// ---- lifecycle ---------------------------------------------------------------------------

watch([budgetId, periodId], async ([b, p], [ob, op]) => {
  if (b === ob && p === op) return;
  await openMonth();
});

onMounted(async () => {
  try {
    await loadMoneySettings();
    await init();
    await openMonth();
  } catch (e) {
    error.value = apiError(e, "بارگذاری ناموفق بود.");
    loading.value = false;
  }
});

onBeforeRouteLeave(async () => leaveDraft());
const beforeUnload = (e: BeforeUnloadEvent) => {
  if (dirtyCount.value) e.preventDefault();
};
window.addEventListener("beforeunload", beforeUnload);
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));

const enteredCount = computed(() => (sheet.value?.lines ?? []).filter((l) => l.entered).length);
</script>

<template>
  <div class="space-y-4 pb-8">
    <!-- Header -->
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-bold text-ink">ورود ارقام واقعی بودجه</h1>
        <p class="text-xs text-slate-400 mt-0.5">
          برای هر سرفصل، رقم واقعی همان هفته را وارد کنید · مبالغ به ریال · نمایش به
          <span class="font-medium">{{ unitLabel }}</span>
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
        >انحراف بودجه</router-link>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>

    <section v-else-if="!loading && !budgets.length" class="bg-surface rounded-card shadow-soft p-10 text-center">
      <p class="font-semibold text-ink">هنوز بودجه‌ای تعریف نشده</p>
      <p class="text-sm text-slate-400 mt-1">تعریف بودجه با مدیرعامل است؛ پس از تعریف، سرفصل‌ها اینجا ظاهر می‌شوند.</p>
    </section>

    <DashboardSkeleton v-else-if="loading && !sheet" />

    <template v-else-if="sheet">
      <!-- Week strip: only when the month is cut into weeks -->
      <section v-if="isWeekly" class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
        <span class="text-xs text-slate-500 px-1">هفته:</span>
        <button
          class="px-3 py-1.5 rounded-xl text-sm transition-colors border"
          :class="monthView
            ? 'bg-panel text-white border-panel'
            : 'bg-surface hover:bg-slate-50 text-brand-700 border-brand-500/40'"
          title="جمع همهٔ هفته‌های این ماه — فقط برای دیدن"
          @click="openMonthView"
        >کل ماه</button>
        <button
          v-for="w in sheet.weeks"
          :key="w.period_id"
          class="px-3 py-1.5 rounded-xl text-sm transition-colors flex items-center gap-1.5"
          :class="!monthView && weekId === w.period_id
            ? 'bg-panel text-white'
            : 'bg-slate-50 hover:bg-slate-100 text-slate-600'"
          :title="`${w.days} روز · ${FA.format(w.entered)} سرفصل ثبت شده`"
          @click="pickWeek(w.period_id)"
        >
          <span class="w-2 h-2 rounded-full" :class="w.entered ? 'bg-accent-500' : 'bg-slate-300'"></span>
          {{ w.label }}
        </button>
        <span class="text-xs text-slate-400 mr-auto">
          {{ FA.format(sheet.weeks.filter((w) => w.entered).length) }} از {{ FA.format(sheet.weeks.length) }} هفته شروع شده
        </span>
      </section>

      <div v-if="sheet.is_rollup" class="rounded-card p-3 text-sm bg-slate-100 text-slate-600 leading-6">
        <span class="font-semibold">کل {{ sheet.month.label }}</span> — جمع همهٔ هفته‌ها، فقط خواندنی.
        برای وارد کردن رقم، یک هفته را انتخاب کنید.
      </div>
      <div v-else-if="readonly" class="rounded-card p-3 text-sm bg-slate-100 text-slate-600">
        ثبت ارقام واقعی با واحد مالی است؛ این برگه برای شما فقط خواندنی است.
      </div>
      <div v-else-if="isWeekly" class="rounded-card p-3 text-xs bg-sky-50 text-sky-800 leading-6">
        در حال ثبت <span class="font-semibold">{{ sheet.period.label }}</span>.
        «بودجهٔ این هفته» همان بودجهٔ ماه است به نسبت روزهای هفته؛ ستون «جمع ماه تاکنون» جمع همهٔ هفته‌های ثبت‌شده است.
      </div>

      <p v-if="!sheet.line_count" class="bg-surface rounded-card shadow-soft p-10 text-center text-sm text-slate-400">
        این بودجه هنوز سرفصلی ندارد — سرفصل‌ها را مدیرعامل در «تعریف بودجه» اضافه می‌کند.
      </p>

      <template v-else>
        <!-- Totals, live as figures are typed -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div v-for="s in sections" :key="s.dir" class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs font-semibold" :class="s.dir === 'in' ? 'text-green-700' : 'text-red-600'">{{ s.title }}</p>
            <div class="grid grid-cols-2 gap-2 mt-2 text-xs">
              <div>
                <p class="text-slate-400">بودجهٔ این دوره</p>
                <p class="font-semibold text-slate-600 ltr-nums mt-0.5">{{ money(s.budget, false) }}</p>
              </div>
              <div>
                <p class="text-slate-400">واقعی</p>
                <p class="font-semibold text-ink ltr-nums mt-0.5">{{ money(s.actual, false) }}</p>
              </div>
            </div>
            <p class="text-base font-bold ltr-nums mt-2" :class="verdictText[s.verdict]">{{ signed(s.actual - s.budget) }}</p>
          </div>
          <div class="bg-surface rounded-card shadow-soft p-4">
            <p class="text-xs font-semibold text-ink">پیشرفت ثبت</p>
            <p class="text-2xl font-bold text-ink mt-2">
              {{ FA.format(enteredCount) }}
              <span class="text-sm font-normal text-slate-400">از {{ FA.format(sheet.line_count) }} سرفصل</span>
            </p>
            <p v-if="dirtyCount" class="text-xs text-amber-600 mt-1">{{ FA.format(dirtyCount) }} تغییر ذخیره‌نشده</p>
          </div>
        </div>

        <!-- The sheet -->
        <section class="bg-surface rounded-card shadow-soft">
          <div class="overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="text-[11px] text-slate-500 border-b border-slate-100">
                  <th class="text-right font-medium p-3 min-w-[15rem]">سرفصل</th>
                  <th class="text-left font-medium p-3">{{ sheet.is_rollup || !isWeekly ? "بودجهٔ ماه" : "بودجهٔ این هفته" }}</th>
                  <th class="text-left font-medium p-3 min-w-[11rem]">رقم واقعی</th>
                  <th class="text-left font-medium p-3">انحراف</th>
                  <th v-if="isWeekly && !sheet.is_rollup" class="text-left font-medium p-3">جمع ماه تاکنون</th>
                  <th class="text-right font-medium p-3 min-w-[12rem]">توضیح</th>
                </tr>
              </thead>

              <tbody v-for="s in sections" :key="s.dir">
                <tr v-if="s.groups.length">
                  <td colspan="6" class="px-3 pt-4 pb-1 text-xs font-bold" :class="s.dir === 'in' ? 'text-green-700' : 'text-red-600'">
                    {{ s.title }}
                  </td>
                </tr>
                <template v-for="g in s.groups" :key="`${s.dir}-${g.title}`">
                  <tr>
                    <td colspan="6" class="px-3 pt-2 pb-1 text-[11px] text-slate-400">{{ g.title }}</td>
                  </tr>
                  <tr v-for="line in g.lines" :key="line.line_id" class="border-b border-slate-50 hover:bg-slate-50/50">
                    <td class="p-2 ps-5">
                      <p class="text-ink">{{ line.category_name }}</p>
                      <p v-if="line.counterparty" class="text-[11px] text-slate-500">{{ line.counterparty }}</p>
                    </td>
                    <td class="p-2 text-left ltr-nums text-slate-600 whitespace-nowrap">{{ money(n(line.budget_rial), false) }}</td>
                    <td
                      class="p-1.5"
                      :data-row="rowIndex.get(line.line_id)"
                      @keydown.enter.prevent="moveDown(rowIndex.get(line.line_id) ?? 0, $event)"
                    >
                      <MoneyInput
                        v-if="!readonly"
                        :model-value="amountOf(line)"
                        class="w-full border rounded-lg px-2 py-1 text-sm text-left ltr-nums bg-surface focus:outline-none focus:ring-2 focus:ring-brand-500/30"
                        :class="isDirty(line) ? 'border-amber-300 bg-amber-50/60' : line.entered ? 'border-slate-200' : 'border-slate-200 bg-slate-50/60'"
                        @update:model-value="(v: string) => setAmount(line, v)"
                      />
                      <p v-else class="text-left ltr-nums px-2 py-1 text-ink">{{ money(n(line.actual_rial), false) }}</p>
                    </td>
                    <td class="p-2 text-left ltr-nums whitespace-nowrap" :class="verdictText[verdictOf(line.direction, varianceOf(line))]">
                      {{ signed(varianceOf(line)) }}
                    </td>
                    <td v-if="isWeekly && !sheet.is_rollup" class="p-2 text-left ltr-nums text-slate-500 whitespace-nowrap">
                      {{ money(n(line.month_actual_rial), false) }}
                      <span class="text-[10px] text-slate-400">از {{ money(n(line.month_budget_rial), false) }}</span>
                    </td>
                    <td class="p-1.5">
                      <input
                        v-if="!readonly"
                        :value="noteOf(line)"
                        placeholder="اختیاری"
                        maxlength="250"
                        class="w-full border border-slate-200 rounded-lg px-2 py-1 text-xs bg-surface focus:outline-none focus:ring-2 focus:ring-brand-500/30"
                        @input="(e) => setNote(line, (e.target as HTMLInputElement).value)"
                      />
                      <p v-else class="text-xs text-slate-500 truncate max-w-[16rem]" :title="line.note">{{ line.note || "—" }}</p>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Save bar -->
        <div
          v-if="!readonly"
          class="sticky bottom-4 z-30 bg-panel text-white rounded-card shadow-pop p-3 flex flex-wrap items-center justify-between gap-2"
        >
          <span class="text-sm px-2 text-white/70">
            {{ dirtyCount ? `${FA.format(dirtyCount)} تغییر ذخیره‌نشده` : "Enter خانهٔ پایین · Shift+Enter خانهٔ بالا" }}
          </span>
          <button
            class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium transition disabled:opacity-40"
            :disabled="!dirtyCount || saving"
            @click="save"
          >{{ saving ? "در حال ذخیره…" : "ذخیره" }}</button>
        </div>
      </template>
    </template>
  </div>
</template>
