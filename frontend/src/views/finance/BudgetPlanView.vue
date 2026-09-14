<script setup lang="ts">
/**
 * تعریف بودجه — the planning grid.
 *
 * Budgets are defined here, by hand: one row per line, one column per month,
 * ورودی above خروجی, a net row at the bottom. Enter moves down a column, so
 * seven months of figures can be keyed without reaching for the mouse.
 *
 * Around the figures: approval per month, a mark on any figure that has
 * drifted from what was approved, and a reason asked for when an approved
 * figure is changed.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import {
  apiError,
  budgetApi,
  type BudgetGrid,
  type Direction,
  type GridLine,
  type GridMonth,
  type SalesForecastRow,
  type TreeCategory,
} from "@/api/budget";
import { financeApi, type CreditLine } from "@/api/finance";
import { useBudgetContext } from "@/composables/useBudgetContext";
import { faYear, loadMoneySettings, useMoney } from "@/composables/useMoney";
import { confirm, prompt, toast } from "@/composables/useUi";
import MoneyInput from "@/components/MoneyInput.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";

const {
  budgets, monthPeriods, budgetId, budget, linkQuery, init, refreshBudgets,
} = useBudgetContext();
const { money } = useMoney();

const grid = ref<BudgetGrid | null>(null);
const loading = ref(true);
const saving = ref(false);
const error = ref("");

const FA = new Intl.NumberFormat("fa-IR");
const n = (v: string | number | null | undefined) => Number(v ?? 0);

// ---- edits --------------------------------------------------------------

/** Edited values keyed `${budgetPeriodId}:${lineId}`. Anything here is unsaved. */
const draft = reactive<Record<string, string>>({});
const dirtyCount = computed(() => Object.keys(draft).length);
const key = (bpId: number, lineId: number) => `${bpId}:${lineId}`;

function stored(line: GridLine, bpId: number): string {
  return line.cells[String(bpId)]?.amount_rial ?? "0";
}
function value(line: GridLine, bpId: number): string {
  const k = key(bpId, line.id);
  return k in draft ? draft[k] : stored(line, bpId);
}
function setValue(line: GridLine, bpId: number, raw: string) {
  const k = key(bpId, line.id);
  const clean = raw === "" || raw === "-" ? "0" : raw;
  // Typing a figure back to what is saved is not an edit.
  if (n(clean) === n(stored(line, bpId))) delete draft[k];
  else draft[k] = clean;
}
const isDirty = (line: GridLine, bpId: number) => key(bpId, line.id) in draft;

// ---- sales forecast ---------------------------------------------------------
// Same draft, a different key shape (`bp:s:channel`), so one save and one
// «unsaved changes» count cover both.

const sKey = (bpId: number, channel: string) => `${bpId}:s:${channel}`;
function sStored(row: SalesForecastRow, bpId: number): string {
  return row.cells[String(bpId)]?.amount_rial ?? "0";
}
function sValue(row: SalesForecastRow, bpId: number): string {
  const k = sKey(bpId, row.channel);
  return k in draft ? draft[k] : sStored(row, bpId);
}
function setSValue(row: SalesForecastRow, bpId: number, raw: string) {
  const k = sKey(bpId, row.channel);
  const clean = raw === "" || raw === "-" ? "0" : raw;
  if (n(clean) === n(sStored(row, bpId))) delete draft[k];
  else draft[k] = clean;
}
const sDirty = (row: SalesForecastRow, bpId: number) => sKey(bpId, row.channel) in draft;
function sDrift(row: SalesForecastRow, m: GridMonth): string | null {
  const baseline = row.cells[String(m.budget_period_id)]?.baseline_rial;
  if (baseline === null || baseline === undefined) return null;
  return n(sValue(row, m.budget_period_id)) !== n(baseline) ? baseline : null;
}
const sRowTotal = (row: SalesForecastRow) =>
  (grid.value?.months ?? []).reduce((s, m) => s + n(sValue(row, m.budget_period_id)), 0);
const salesMonthTotal = (bpId: number) =>
  (grid.value?.sales ?? []).reduce((s, r) => s + n(sValue(r, bpId)), 0);
const salesTotal = computed(() =>
  (grid.value?.months ?? []).reduce((s, m) => s + salesMonthTotal(m.budget_period_id), 0),
);

/** The live figure has moved away from the approved one. */
function drift(line: GridLine, m: GridMonth): string | null {
  const baseline = line.cells[String(m.budget_period_id)]?.baseline_rial;
  if (baseline === null || baseline === undefined) return null;
  return n(value(line, m.budget_period_id)) !== n(baseline) ? baseline : null;
}

// ---- shape --------------------------------------------------------------

const sections = computed(() =>
  (["in", "out"] as Direction[]).map((dir) => ({
    dir,
    title: dir === "in" ? "ورودی" : "خروجی",
    lines: (grid.value?.lines ?? []).filter((l) => l.direction === dir),
  })),
);

/** Row position across both sections, for Enter-moves-down. */
const rowIndex = computed(() => {
  const map = new Map<number, number>();
  // The sales rows sit above the cash lines and take the first indices.
  let i = grid.value?.sales?.length ?? 0;
  for (const s of sections.value) for (const l of s.lines) map.set(l.id, i++);
  return map;
});

const rowTotal = (line: GridLine) =>
  (grid.value?.months ?? []).reduce((s, m) => s + n(value(line, m.budget_period_id)), 0);

const colTotal = (dir: Direction, bpId: number) =>
  (grid.value?.lines ?? [])
    .filter((l) => l.direction === dir)
    .reduce((s, l) => s + n(value(l, bpId)), 0);

const sectionTotal = (dir: Direction) =>
  (grid.value?.months ?? []).reduce((s, m) => s + colTotal(dir, m.budget_period_id), 0);

const netFor = (bpId: number) => colTotal("in", bpId) - colTotal("out", bpId);
const netTotal = computed(() => sectionTotal("in") - sectionTotal("out"));

function moveDown(row: number, col: number, e: KeyboardEvent) {
  const next = e.shiftKey ? row - 1 : row + 1;
  const input = document.querySelector<HTMLInputElement>(
    `td[data-row="${next}"][data-col="${col}"] input`,
  );
  if (input) {
    input.focus();
    input.select();
  }
}

/** Copy the first filled month into the empty ones — seven identical rents. */
function fillRow(line: GridLine) {
  const months = grid.value?.months ?? [];
  const first = months.map((m) => value(line, m.budget_period_id)).find((v) => n(v) !== 0);
  if (!first) {
    toast.info("اول مبلغ یک ماه را وارد کنید.");
    return;
  }
  for (const m of months) {
    if (n(value(line, m.budget_period_id)) === 0) setValue(line, m.budget_period_id, first);
  }
}

// ---- load / save ----------------------------------------------------------

async function loadGrid() {
  if (!budgetId.value) {
    grid.value = null;
    loading.value = false;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    grid.value = await budgetApi.grid(budgetId.value);
  } catch (e: any) {
    grid.value = null;
    error.value = e?.response?.status === 403
      ? "بخش مالی برای شما قابل مشاهده نیست."
      : apiError(e, "جدول بودجه بارگذاری نشد.");
  } finally {
    loading.value = false;
  }
}

async function save() {
  const g = grid.value;
  if (!g || !dirtyCount.value) return;

  const approved = new Set(
    g.months.filter((m) => m.status === "approved").map((m) => m.budget_period_id),
  );
  const keys = Object.keys(draft);
  const touchesApproved = keys.some((k) => approved.has(Number(k.split(":")[0])));

  // Editable after approval was the requirement; silently editable was not.
  let reason = "";
  if (touchesApproved) {
    const answer = await prompt({
      title: "تغییر بودجهٔ مصوب",
      message: "برخی از این ارقام متعلق به ماه‌های مصوب‌اند. علت تغییر را بنویسید — در سابقهٔ تغییرات می‌ماند.",
      placeholder: "مثلاً: افزایش نرخ جمبو از مهر",
    });
    if (answer === null) return;
    reason = answer;
  }

  saving.value = true;
  try {
    const cells = keys.filter((k) => !k.includes(":s:")).map((k) => {
      const [bp, line] = k.split(":").map(Number);
      return {
        budget_period_id: bp,
        line_id: line,
        amount_rial: draft[k],
        ...(approved.has(bp) ? { reason } : {}),
      };
    });
    const salesCells = keys.filter((k) => k.includes(":s:")).map((k) => {
      const [bp, , channel] = k.split(":");
      return {
        budget_period_id: Number(bp),
        channel,
        amount_rial: draft[k],
        ...(approved.has(Number(bp)) ? { reason } : {}),
      };
    });
    const res = await budgetApi.saveGrid(cells, salesCells);
    for (const k of keys) delete draft[k];
    await loadGrid();
    toast.success(`${FA.format(res.written)} رقم ذخیره شد.`);
  } catch (e) {
    toast.error(apiError(e, "ذخیره نشد."));
  } finally {
    saving.value = false;
  }
}

async function approve(m: GridMonth) {
  if (dirtyCount.value) {
    toast.error("اول تغییرات ذخیره‌نشده را ذخیره کنید، بعد تصویب کنید.");
    return;
  }
  const ok = await confirm({
    title: `تصویب بودجهٔ ${m.label}`,
    message:
      "ارقام فعلی این ماه به‌عنوان «مصوب» ثبت می‌شوند. بعد از تصویب هم قابل ویرایش‌اند، " +
      "ولی عدد مصوب ثابت می‌ماند و هر تغییر با علتش در سابقه ثبت می‌شود.",
  });
  if (!ok || !grid.value) return;
  try {
    await budgetApi.approve(grid.value.budget.id, m.period_id);
    toast.success(`بودجهٔ ${m.label} تصویب شد.`);
    await Promise.all([loadGrid(), refreshBudgets()]);
  } catch (e) {
    toast.error(apiError(e, "تصویب انجام نشد."));
  }
}

// ---- new budget -----------------------------------------------------------

const showNew = ref(false);
const newBudget = reactive({ title: "", start: null as number | null, end: null as number | null });

async function createBudget() {
  const start = monthPeriods.value.find((p) => p.id === newBudget.start);
  if (!newBudget.title.trim() || !start || !newBudget.end) {
    toast.error("عنوان، ماه شروع و ماه پایان را کامل کنید.");
    return;
  }
  try {
    const created = await budgetApi.create({
      title: newBudget.title.trim(),
      jalali_year: start.jalali_year,
      start_period: newBudget.start!,
      end_period: newBudget.end,
    });
    showNew.value = false;
    newBudget.title = "";
    await refreshBudgets(created.id);
    toast.success("بودجه ساخته شد. حالا اقلامش را اضافه کنید.");
  } catch (e) {
    toast.error(apiError(e, "بودجه ساخته نشد."));
  }
}

// ---- lines ----------------------------------------------------------------

const categories = ref<TreeCategory[]>([]);
const creditLines = ref<CreditLine[]>([]);
const newLine = reactive({
  direction: "out" as Direction,
  category: null as number | null,
  credit_line: null as number | null,
});

/**
 * Leaves only, grouped under their parent. A parent is a roll-up — offering
 * it here is how figures would end up counted twice.
 */
const categoryGroups = computed(() => {
  const byId = new Map(categories.value.map((c) => [c.id, c]));
  const allowed = categories.value.filter(
    (c) =>
      c.is_leaf &&
      c.is_active &&
      c.code !== "unclassified" &&
      (c.direction === "both" || c.direction === newLine.direction),
  );
  const groups = new Map<string, TreeCategory[]>();
  for (const c of allowed) {
    const parent = c.parent ? byId.get(c.parent)?.name_fa ?? "" : "";
    const name = parent || "سایر دسته‌ها";
    groups.set(name, [...(groups.get(name) ?? []), c]);
  }
  return [...groups.entries()].map(([label, items]) => ({ label, items }));
});

const chosenCategory = computed(
  () => categories.value.find((c) => c.id === newLine.category) ?? null,
);

watch(() => newLine.direction, () => {
  newLine.category = null;
  newLine.credit_line = null;
});
watch(() => newLine.category, () => {
  if (!chosenCategory.value?.needs_credit_line) newLine.credit_line = null;
});

// ---- a line of one's own -------------------------------------------------

/**
 * Budgets are defined by hand here, and the category tree cannot anticipate
 * every line — «هزینهٔ تبلیغات», «تعمیرات ماشین‌آلات». So a new one is created
 * on the spot under the group it belongs to, and becomes a column in the cash
 * entry grid at the same moment, which is where its actuals will come from.
 */
const showNewCategory = ref(false);
const newCategory = reactive({ name: "", parent: null as number | null });

/** Groups only: a category that already holds figures cannot become one. */
const parentOptions = computed(() =>
  categories.value.filter(
    (c) =>
      !c.is_leaf &&
      c.is_active &&
      (c.direction === "both" || c.direction === newLine.direction),
  ),
);

async function createCategory() {
  const name = newCategory.name.trim();
  if (!name) {
    toast.error("نام قلم را بنویسید.");
    return;
  }
  try {
    const created = await budgetApi.createCategory({
      name_fa: name,
      parent: newCategory.parent,
      direction: newLine.direction,
    });
    categories.value = (await financeApi.categories()) as TreeCategory[];
    newLine.category = created.id;
    showNewCategory.value = false;
    newCategory.name = "";
    newCategory.parent = null;
    toast.success(`«${created.name_fa}» ساخته شد — حالا «افزودن» را بزنید.`);
  } catch (e) {
    toast.error(apiError(e, "قلم ساخته نشد."));
  }
}

async function addLine() {
  if (!grid.value || !newLine.category) {
    toast.error("دسته را انتخاب کنید.");
    return;
  }
  if (chosenCategory.value?.needs_credit_line && !newLine.credit_line) {
    toast.error("برای این دسته باید طرف‌حساب (تسهیلات / قرض) را هم انتخاب کنید.");
    return;
  }
  try {
    await budgetApi.addLine({
      budget: grid.value.budget.id,
      category: newLine.category,
      credit_line: newLine.credit_line,
      direction: newLine.direction,
    });
    newLine.category = null;
    newLine.credit_line = null;
    await loadGrid();
    toast.success("قلم اضافه شد.");
  } catch (e) {
    toast.error(apiError(e, "قلم اضافه نشد — شاید قبلاً در این بودجه هست."));
  }
}

async function removeLine(line: GridLine) {
  const ok = await confirm({
    title: "حذف قلم",
    message: `«${line.label}» و همهٔ ارقام بودجه‌ای‌اش از این بودجه حذف می‌شود. حرکت‌های نقدینگی ثبت‌شده دست نمی‌خورند.`,
    danger: true,
  });
  if (!ok) return;
  try {
    await budgetApi.removeLine(line.id);
    for (const k of Object.keys(draft)) if (k.endsWith(`:${line.id}`)) delete draft[k];
    await loadGrid();
  } catch (e) {
    toast.error(apiError(e, "قلم حذف نشد."));
  }
}

// ---- lifecycle ------------------------------------------------------------

watch(budgetId, (id, old) => {
  if (id === old) return;
  for (const k of Object.keys(draft)) delete draft[k];
  loadGrid();
});

onMounted(async () => {
  try {
    await loadMoneySettings();
    const [, cats, lines] = await Promise.all([
      init(),
      financeApi.categories(),
      financeApi.creditLines(),
    ]);
    categories.value = cats as TreeCategory[];
    creditLines.value = lines.filter((l) => l.status !== "cancelled");
    await loadGrid();
  } catch (e) {
    error.value = apiError(e, "بارگذاری ناموفق بود.");
    loading.value = false;
  }
});

// Seven months of typed figures should not vanish to a mis-click.
onBeforeRouteLeave(async () =>
  dirtyCount.value
    ? await confirm({
        title: "تغییرات ذخیره نشده",
        message: "ارقامی که وارد کرده‌اید هنوز ذخیره نشده‌اند. بدون ذخیره خارج می‌شوید؟",
        danger: true,
      })
    : true,
);
const beforeUnload = (e: BeforeUnloadEvent) => {
  if (dirtyCount.value) e.preventDefault();
};
window.addEventListener("beforeunload", beforeUnload);
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));

const statusChip = (s: string) =>
  s === "approved" ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-500";
</script>

<template>
  <div class="space-y-4">
    <!-- Header -->
    <section class="bg-surface rounded-card shadow-soft p-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-bold text-ink">تعریف بودجه</h1>
        <p class="text-xs text-slate-400 mt-0.5">
          ارقام مورد انتظار هر قلم در هر ماه · عملکرد واقعی از ورود نقدینگی خوانده می‌شود
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <label v-if="budgets.length" class="block">
          <span class="text-[11px] text-slate-400">بودجه</span>
          <select
            v-model.number="budgetId"
            class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
          >
            <option v-for="b in budgets" :key="b.id" :value="b.id">{{ b.title }}</option>
          </select>
        </label>
        <router-link
          v-if="budget"
          :to="{ name: 'finance-budget-variance', query: linkQuery }"
          class="px-3 py-1.5 text-sm rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200"
        >انحراف بودجه</router-link>
        <button
          v-if="grid?.can_edit !== false"
          class="px-3 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700"
          @click="showNew = !showNew"
        >+ بودجهٔ جدید</button>
      </div>
    </section>

    <!-- New budget -->
    <section v-if="showNew" class="bg-surface rounded-card shadow-soft p-4">
      <h2 class="text-sm font-semibold text-ink mb-3">بودجهٔ جدید</h2>
      <div class="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
        <label class="block sm:col-span-2">
          <span class="text-[11px] text-slate-400">عنوان</span>
          <input
            v-model="newBudget.title"
            placeholder="مثلاً: بودجهٔ نقدی نیمهٔ دوم ۱۴۰۴"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
          />
        </label>
        <label class="block">
          <span class="text-[11px] text-slate-400">از ماه</span>
          <select v-model.number="newBudget.start" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
            <option v-for="p in monthPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-[11px] text-slate-400">تا ماه</span>
          <select v-model.number="newBudget.end" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
            <option v-for="p in monthPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
      </div>
      <div class="flex gap-2 mt-3">
        <button class="px-4 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700" @click="createBudget">ساخت بودجه</button>
        <button class="px-4 py-1.5 text-sm rounded-xl bg-slate-100 text-slate-600" @click="showNew = false">انصراف</button>
      </div>
    </section>

    <p v-if="error" class="bg-red-50 text-red-600 rounded-card p-4 text-sm">{{ error }}</p>

    <DashboardSkeleton v-else-if="loading && !grid" />

    <section
      v-else-if="!budgets.length"
      class="bg-surface rounded-card shadow-soft p-10 text-center"
    >
      <p class="font-semibold text-ink">هنوز بودجه‌ای تعریف نشده</p>
      <p class="text-sm text-slate-400 mt-1">
        یک بودجه برای بازه‌ای از ماه‌ها بسازید، اقلامش را اضافه کنید و ارقام مورد انتظار را وارد کنید.
      </p>
      <button class="mt-4 px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700" @click="showNew = true">
        + ساخت اولین بودجه
      </button>
    </section>

    <template v-else-if="grid">
      <!-- Summary -->
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">پیش‌بینی فروش</p>
          <p class="text-lg font-bold text-brand-700 ltr-nums">{{ money(salesTotal) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">بازه</p>
          <p class="text-sm font-bold text-ink mt-1">{{ grid.budget.start_label }} تا {{ grid.budget.end_label }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">جمع ورودی مورد انتظار</p>
          <p class="text-lg font-bold text-green-600 ltr-nums">{{ money(sectionTotal('in')) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">جمع خروجی مورد انتظار</p>
          <p class="text-lg font-bold text-red-500 ltr-nums">{{ money(sectionTotal('out')) }}</p>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <p class="text-[11px] text-slate-400">ماه‌های مصوب</p>
          <p class="text-lg font-bold text-ink">
            {{ FA.format(grid.months.filter((m) => m.status === 'approved').length) }}
            <span class="text-sm text-slate-400 font-normal">از {{ FA.format(grid.months.length) }}</span>
          </p>
        </div>
      </div>

      <!-- Add line -->
      <section v-if="grid.can_edit" class="bg-surface rounded-card shadow-soft p-4">
        <h2 class="text-sm font-semibold text-ink mb-3">افزودن قلم</h2>
        <div class="flex flex-wrap items-end gap-3">
          <div>
            <span class="text-[11px] text-slate-400 block mb-1">جهت</span>
            <div class="flex bg-slate-100 rounded-xl p-0.5">
              <button
                v-for="d in ([['in', 'ورودی'], ['out', 'خروجی']] as const)"
                :key="d[0]"
                class="px-3 py-1 text-xs rounded-lg transition"
                :class="newLine.direction === d[0] ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-500'"
                @click="newLine.direction = d[0]"
              >{{ d[1] }}</button>
            </div>
          </div>
          <label class="block min-w-[14rem]">
            <span class="text-[11px] text-slate-400">دسته</span>
            <select v-model.number="newLine.category" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
              <option :value="null" disabled>انتخاب کنید…</option>
              <optgroup v-for="g in categoryGroups" :key="g.label" :label="g.label">
                <option v-for="c in g.items" :key="c.id" :value="c.id">{{ c.name_fa }}</option>
              </optgroup>
            </select>
          </label>
          <label v-if="chosenCategory?.needs_credit_line" class="block min-w-[14rem]">
            <span class="text-[11px] text-slate-400">طرف‌حساب</span>
            <select v-model.number="newLine.credit_line" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
              <option :value="null" disabled>انتخاب کنید…</option>
              <option v-for="c in creditLines" :key="c.id" :value="c.id">{{ c.counterparty }} — {{ c.title }}</option>
            </select>
          </label>
          <button class="px-4 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700" @click="addLine">افزودن</button>
          <button
            class="px-3 py-1.5 text-sm rounded-xl bg-slate-100 text-slate-600 hover:bg-slate-200"
            @click="showNewCategory = !showNewCategory"
          >+ قلم جدید</button>
        </div>
        <!-- A line not in the list yet -->
        <div v-if="showNewCategory" class="mt-3 p-3 rounded-xl bg-slate-50 flex flex-wrap items-end gap-3">
          <label class="block min-w-[14rem]">
            <span class="text-[11px] text-slate-400">نام قلم {{ newLine.direction === 'in' ? 'ورودی' : 'خروجی' }}</span>
            <input
              v-model="newCategory.name"
              placeholder="مثلاً: هزینهٔ تبلیغات"
              class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
              @keydown.enter.prevent="createCategory"
            />
          </label>
          <label class="block min-w-[12rem]">
            <span class="text-[11px] text-slate-400">زیر گروه</span>
            <select v-model.number="newCategory.parent" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
              <option :value="null">— گروه مستقل —</option>
              <option v-for="c in parentOptions" :key="c.id" :value="c.id">{{ c.name_fa }}</option>
            </select>
          </label>
          <button class="px-4 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700" @click="createCategory">ساخت قلم</button>
          <p class="basis-full text-[11px] text-slate-400">
            قلم تازه در صفحهٔ «ورود نقدینگی» هم ستون می‌شود تا عملکرد واقعی‌اش همان‌جا ثبت شود.
          </p>
        </div>

        <p v-if="chosenCategory?.needs_credit_line && !creditLines.length" class="text-xs text-amber-600 mt-2">
          هنوز هیچ تسهیلات یا قرضی تعریف نشده — اول از صفحهٔ نقدینگی طرف‌حساب را بسازید.
        </p>
      </section>

      <!-- Grid -->
      <section class="bg-surface rounded-card shadow-soft">
        <div class="flex flex-wrap items-center justify-between gap-2 p-4 border-b border-slate-100">
          <div>
            <h2 class="text-sm font-semibold text-ink">ارقام مورد انتظار</h2>
            <p class="text-[11px] text-slate-400 mt-0.5">
              مبالغ به ریال وارد می‌شوند · Enter خانهٔ پایین · Shift+Enter خانهٔ بالا
              <span class="inline-flex items-center gap-1 ms-2">
                <span class="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block"></span> با عدد مصوب فرق دارد
              </span>
            </p>
          </div>
          <div v-if="grid.can_edit" class="flex items-center gap-2">
            <span v-if="dirtyCount" class="text-xs text-amber-600">
              {{ FA.format(dirtyCount) }} تغییر ذخیره‌نشده
            </span>
            <button
              class="px-4 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40"
              :disabled="!dirtyCount || saving"
              @click="save"
            >{{ saving ? 'در حال ذخیره…' : 'ذخیره' }}</button>
          </div>
        </div>

        <p v-if="!grid.lines.length" class="text-sm text-slate-400 text-center py-10">
          این بودجه هنوز قلمی ندارد — از بخش «افزودن قلم» شروع کنید.
        </p>

        <div class="overflow-x-auto">
          <table class="min-w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr class="text-[11px] text-slate-500">
                <th class="sticky right-0 z-10 bg-surface text-right font-medium p-3 min-w-[15rem] border-b border-slate-100">قلم</th>
                <th
                  v-for="m in grid.months" :key="m.budget_period_id"
                  class="p-2 font-medium text-center border-b border-slate-100 min-w-[9.5rem]"
                >
                  <div class="text-ink">{{ m.label }}</div>
                  <div class="flex items-center justify-center gap-1 mt-1">
                    <span class="px-1.5 py-0.5 rounded-md text-[10px]" :class="statusChip(m.status)">{{ m.status_label }}</span>
                    <button
                      v-if="grid.can_edit && m.status === 'draft'"
                      class="px-1.5 py-0.5 rounded-md text-[10px] bg-brand-50 text-brand-700 hover:bg-brand-100"
                      @click="approve(m)"
                    >تصویب</button>
                  </div>
                </th>
                <th class="p-3 font-medium text-center border-b border-slate-100 min-w-[8rem]">جمع</th>
              </tr>
            </thead>

            <!-- Sales forecast: accrual, so it sits above the cash plan and
                 never enters the net row. -->
            <tbody v-if="grid.sales?.length">
              <tr>
                <td :colspan="grid.months.length + 2" class="sticky right-0 px-3 pt-4 pb-2 text-xs font-bold text-brand-700">
                  پیش‌بینی فروش
                  <span class="font-normal text-slate-400">— تعهدی؛ در خالص نقدی شمرده نمی‌شود</span>
                </td>
              </tr>
              <tr v-for="(row, si) in grid.sales" :key="row.channel" class="group hover:bg-slate-50/60">
                <td class="sticky right-0 z-10 bg-surface group-hover:bg-slate-50 p-2 pe-3 border-b border-slate-50">
                  <p class="text-ink">{{ row.label }}</p>
                </td>
                <td
                  v-for="(m, ci) in grid.months" :key="m.budget_period_id"
                  :data-row="si" :data-col="ci"
                  class="p-1.5 border-b border-slate-50"
                  @keydown.enter.prevent="moveDown(si, ci, $event)"
                >
                  <div class="relative">
                    <MoneyInput
                      v-if="grid.can_edit"
                      :model-value="sValue(row, m.budget_period_id)"
                      class="w-full border rounded-lg px-2 py-1 text-sm text-left ltr-nums bg-surface focus:outline-none focus:ring-2 focus:ring-brand-500/30"
                      :class="sDirty(row, m.budget_period_id) ? 'border-amber-300 bg-amber-50/60' : 'border-slate-200'"
                      @update:model-value="(v: string) => setSValue(row, m.budget_period_id, v)"
                    />
                    <p v-else class="text-left ltr-nums px-2 py-1">{{ FA.format(n(sValue(row, m.budget_period_id))) }}</p>
                    <span
                      v-if="sDrift(row, m)"
                      class="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-500"
                      :title="`عدد مصوب: ${FA.format(n(sDrift(row, m)))} ریال`"
                    ></span>
                  </div>
                </td>
                <td class="p-2 text-left ltr-nums text-slate-600 border-b border-slate-50 whitespace-nowrap">{{ money(sRowTotal(row), false) }}</td>
              </tr>
              <tr class="bg-slate-50/80 font-semibold">
                <td class="sticky right-0 z-10 bg-slate-50 p-2 pe-3 text-xs">جمع پیش‌بینی فروش</td>
                <td v-for="m in grid.months" :key="m.budget_period_id" class="p-2 text-left ltr-nums text-xs whitespace-nowrap">
                  {{ money(salesMonthTotal(m.budget_period_id), false) }}
                </td>
                <td class="p-2 text-left ltr-nums text-xs whitespace-nowrap">{{ money(salesTotal, false) }}</td>
              </tr>
            </tbody>

            <tbody v-for="section in sections" :key="section.dir">
              <tr>
                <td
                  :colspan="grid.months.length + 2"
                  class="sticky right-0 px-3 pt-4 pb-2 text-xs font-bold"
                  :class="section.dir === 'in' ? 'text-green-700' : 'text-red-600'"
                >{{ section.title }}</td>
              </tr>
              <tr v-if="!section.lines.length">
                <td :colspan="grid.months.length + 2" class="px-3 pb-3 text-xs text-slate-400">قلمی ندارد.</td>
              </tr>
              <tr v-for="line in section.lines" :key="line.id" class="group hover:bg-slate-50/60">
                <td class="sticky right-0 z-10 bg-surface group-hover:bg-slate-50 p-2 pe-3 border-b border-slate-50">
                  <div class="flex items-center justify-between gap-2">
                    <div class="min-w-0">
                      <p v-if="line.parent_name" class="text-[10px] text-slate-400 leading-none mb-0.5">{{ line.parent_name }}</p>
                      <p class="text-ink truncate">{{ line.category_name }}</p>
                      <p v-if="line.counterparty" class="text-[11px] text-slate-500 truncate">{{ line.counterparty }}</p>
                    </div>
                    <div v-if="grid.can_edit" class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <button class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 hover:text-ink" title="ماه‌های خالی را با مبلغ اولین ماه پر کن" @click="fillRow(line)">پرکردن</button>
                      <button class="text-[10px] px-1.5 py-0.5 rounded bg-red-50 text-red-500 hover:bg-red-100" @click="removeLine(line)">حذف</button>
                    </div>
                  </div>
                </td>
                <td
                  v-for="(m, ci) in grid.months" :key="m.budget_period_id"
                  :data-row="rowIndex.get(line.id)" :data-col="ci"
                  class="p-1.5 border-b border-slate-50"
                  @keydown.enter.prevent="moveDown(rowIndex.get(line.id) ?? 0, ci, $event)"
                >
                  <div class="relative">
                    <MoneyInput
                      v-if="grid.can_edit"
                      :model-value="value(line, m.budget_period_id)"
                      class="w-full border rounded-lg px-2 py-1 text-sm text-left ltr-nums bg-surface focus:outline-none focus:ring-2 focus:ring-brand-500/30"
                      :class="isDirty(line, m.budget_period_id) ? 'border-amber-300 bg-amber-50/60' : 'border-slate-200'"
                      @update:model-value="(v: string) => setValue(line, m.budget_period_id, v)"
                    />
                    <p v-else class="text-left ltr-nums px-2 py-1">{{ FA.format(n(value(line, m.budget_period_id))) }}</p>
                    <span
                      v-if="drift(line, m)"
                      class="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-500"
                      :title="`عدد مصوب: ${FA.format(n(drift(line, m)))} ریال`"
                    ></span>
                  </div>
                </td>
                <td class="p-2 text-left ltr-nums text-slate-600 border-b border-slate-50 whitespace-nowrap">{{ money(rowTotal(line), false) }}</td>
              </tr>
              <tr v-if="section.lines.length" class="bg-slate-50/80 font-semibold">
                <td class="sticky right-0 z-10 bg-slate-50 p-2 pe-3 text-xs">جمع {{ section.title }}</td>
                <td v-for="m in grid.months" :key="m.budget_period_id" class="p-2 text-left ltr-nums text-xs whitespace-nowrap">
                  {{ money(colTotal(section.dir, m.budget_period_id), false) }}
                </td>
                <td class="p-2 text-left ltr-nums text-xs whitespace-nowrap">{{ money(sectionTotal(section.dir), false) }}</td>
              </tr>
            </tbody>

            <tfoot>
              <tr class="font-bold">
                <td class="sticky right-0 z-10 bg-surface p-3 text-sm border-t-2 border-slate-200">خالص (ورودی − خروجی)</td>
                <td
                  v-for="m in grid.months" :key="m.budget_period_id"
                  class="p-2 text-left ltr-nums text-sm border-t-2 border-slate-200 whitespace-nowrap"
                  :class="netFor(m.budget_period_id) < 0 ? 'text-red-600' : 'text-green-600'"
                >{{ money(netFor(m.budget_period_id), false) }}</td>
                <td
                  class="p-2 text-left ltr-nums text-sm border-t-2 border-slate-200 whitespace-nowrap"
                  :class="netTotal < 0 ? 'text-red-600' : 'text-green-600'"
                >{{ money(netTotal, false) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <p class="text-[11px] text-slate-400 px-1">
        سال بودجه: {{ faYear(grid.budget.jalali_year) }} ·
        پیش‌بینی فروش تعهدی است و با فروش ثبت‌شدهٔ هر کانال مقایسه می‌شود؛ پولِ آن در «وصول نقدی» و «وصول مطالبات» بودجه‌بندی می‌شود.
      </p>
    </template>
  </div>
</template>
