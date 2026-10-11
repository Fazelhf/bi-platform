<script setup lang="ts">
/**
 * بودجه از اکسل — the cash-flow workbook in, read first, written second.
 *
 * One file carries both halves of the budget: «بودجه <ماه>» columns are the
 * plan, «واقعی <ماه>» columns the actuals. The server reads the sheet and
 * writes nothing; this dialog shows the reading — which rows it will take,
 * which side of the ledger, which سرفصل each lands on — lets the user
 * correct any of it, and only then writes.
 *
 * Rows the sheet itself treats as subtotals, balances or memo lines arrive
 * unticked with the reason beside them; the four sales-channel rows go to
 * the sales forecast, whose actuals come from the sales section.
 */
import { computed, reactive, ref, watch } from "vue";
import {
  apiError,
  budgetApi,
  type Budget,
  type Direction,
  type ImportAnalysis,
  type ImportResult,
  type ImportRow,
  type TreeCategory,
} from "@/api/budget";
import { financeApi } from "@/api/finance";
import { useMoney } from "@/composables/useMoney";
import { confirm, toast } from "@/composables/useUi";

const props = withDefaults(defineProps<{
  budgets: Budget[];
  /** Preselects the target; null → a new budget. */
  budgetId: number | null;
  /** Which half the page is about — preselected, the other stays available. */
  focus?: "budget" | "actual";
  canPlan: boolean;
  canActual: boolean;
  label?: string;
}>(), { focus: "budget", label: "ورود از اکسل" });

const emit = defineEmits<{ done: [result: ImportResult] }>();
const { money } = useMoney();
const FA = new Intl.NumberFormat("fa-IR");
const n = (v: string | null | undefined) => Number(v ?? 0);

const open = ref(false);
const busy = ref(false);
const file = ref<File | null>(null);
const analysis = ref<ImportAnalysis | null>(null);
const result = ref<ImportResult | null>(null);
const categories = ref<TreeCategory[]>([]);
const showSkipped = ref(false);

const thisYear = (() => {
  const y = Number(new Intl.DateTimeFormat("en-u-ca-persian", { year: "numeric" }).format(new Date()).replace(/\D/g, ""));
  return y || 1405;
})();

const form = reactive({
  target: null as number | null, // null = new budget
  title: "",
  year: thisYear,
  sheet: "",
  unit: "rial" as "rial" | "toman",
  parts: { budget: false, actual: false },
  mode: "merge" as "merge" | "replace",
});

/** Per-row edits, keyed by the Excel row number. */
const edits = reactive<Record<number, { include?: boolean; direction?: Direction; category_id?: number | null }>>({});

function show() {
  open.value = true;
  result.value = null;
  analysis.value = null;
  file.value = null;
  form.target = props.budgetId;
  form.parts.budget = props.canPlan && props.focus === "budget";
  form.parts.actual = props.canActual;
  if (!form.parts.budget && !form.parts.actual) form.parts.budget = props.canPlan;
  const b = props.budgets.find((x) => x.id === props.budgetId);
  if (b) form.year = b.jalali_year;
  for (const k of Object.keys(edits)) delete edits[Number(k)];
  if (!categories.value.length) {
    financeApi.categories().then((c) => (categories.value = c as TreeCategory[])).catch(() => {});
  }
}
function close() {
  open.value = false;
}

function pick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0] ?? null;
  file.value = f;
  analysis.value = null;
  result.value = null;
  form.sheet = "";
  if (f) analyse();
}
function drop(e: DragEvent) {
  const f = e.dataTransfer?.files?.[0];
  if (f) {
    file.value = f;
    form.sheet = "";
    analyse();
  }
}

const formArgs = () => ({
  file: file.value!,
  year: form.year,
  budget: form.target,
  sheet: form.sheet || undefined,
  scale: form.unit === "toman" ? 10 : 1,
});

async function analyse() {
  if (!file.value) return;
  busy.value = true;
  try {
    analysis.value = await budgetApi.importExcel("analyse", formArgs());
    form.sheet = analysis.value.sheet;
    for (const k of Object.keys(edits)) delete edits[Number(k)];
    if (!analysis.value.months.some((m) => m.has_actual)) form.parts.actual = false;
  } catch (e) {
    analysis.value = null;
    toast.error(apiError(e, "فایل خوانده نشد."));
  } finally {
    busy.value = false;
  }
}

// Changing where it goes, the year or the unit changes the reading.
watch(() => [form.target, form.year, form.unit], () => {
  if (file.value && analysis.value) analyse();
});

// ---- the reading, with the user's edits on top ------------------------------

const rowOf = (r: ImportRow) => {
  const e = edits[r.row] ?? {};
  return {
    ...r,
    include: e.include ?? r.include,
    direction: e.direction ?? r.direction,
    category_id: "category_id" in e ? e.category_id ?? null : r.category_id,
  };
};
const rows = computed(() => (analysis.value?.rows ?? []).map(rowOf));
const taken = computed(() => rows.value.filter((r) => r.include && !r.is_total));
const skipped = computed(() => rows.value.filter((r) => !r.include || r.is_total));
/** The sheet's own totals, checked against the rows they are made of. */
const totalsChecked = computed(() => rows.value.filter((r) => r.is_total && r.check !== undefined && r.check !== null));
const totalsBroken = computed(() => totalsChecked.value.filter((r) => r.check === false));

function setEdit(r: ImportRow, patch: { include?: boolean; direction?: Direction; category_id?: number | null }) {
  edits[r.row] = { ...(edits[r.row] ?? {}), ...patch };
}

const sum = (fig: Record<string, string | null>) =>
  Object.values(fig).reduce((s, v) => s + n(v), 0);

const leaves = (dir: Direction) =>
  categories.value.filter((c) => c.is_leaf && c.is_active && c.code !== "unclassified"
    && (c.direction === "both" || c.direction === dir));
const parentName = (c: TreeCategory) =>
  categories.value.find((x) => x.id === c.parent)?.name_fa ?? "";

function destination(r: ReturnType<typeof rowOf>) {
  if (r.match === "sales") return { tone: "sky", text: `پیش‌بینی فروش · ${r.channel_label ?? r.channel}` };
  if (r.category_id) {
    const c = categories.value.find((x) => x.id === r.category_id);
    const name = c?.name_fa ?? r.category_name;
    const parent = c ? parentName(c) : r.category_parent;
    return { tone: r.match === "line" ? "slate" : "emerald", text: parent ? `${parent} › ${name}` : name };
  }
  return { tone: "amber", text: `سرفصل جدید${r.new_parent_name ? ` زیر «${r.new_parent_name}»` : ""}` };
}

const totals = computed(() => {
  const t = { inB: 0, outB: 0, inA: 0, outA: 0, sales: 0 };
  for (const r of taken.value) {
    if (r.match === "sales") {
      t.sales += sum(r.budget);
      continue;
    }
    if (r.direction === "in") {
      t.inB += sum(r.budget);
      t.inA += sum(r.actual);
    } else {
      t.outB += sum(r.budget);
      t.outA += sum(r.actual);
    }
  }
  return t;
});

const targetBudget = computed(() => props.budgets.find((b) => b.id === form.target) ?? null);
const canApply = computed(() =>
  !!analysis.value && !busy.value && (form.parts.budget || form.parts.actual) && taken.value.length > 0,
);

async function apply() {
  if (!analysis.value || !file.value) return;
  if (form.mode === "replace" && targetBudget.value) {
    const what = [form.parts.budget && "ارقام بودجه و پیش‌بینی فروش", form.parts.actual && "ارقام واقعی ثبت‌شده"]
      .filter(Boolean).join(" و ");
    const ok = await confirm({
      title: "جایگزینی کامل",
      message: `همهٔ ${what} «${targetBudget.value.title}» پاک و با فایل جایگزین می‌شود. ادامه می‌دهید؟`,
      danger: true,
    });
    if (!ok) return;
  }
  busy.value = true;
  try {
    const res = await budgetApi.importExcel("apply", formArgs(), {
      parts: [...(form.parts.budget ? ["budget" as const] : []), ...(form.parts.actual ? ["actual" as const] : [])],
      mode: form.mode,
      title: form.title,
      rows: Object.entries(edits).map(([row, e]) => ({ row: Number(row), ...e })),
    });
    result.value = res;
    emit("done", res);
    toast.success(res.created ? `بودجهٔ «${res.budget_title}» ساخته شد.` : "ورود از اکسل انجام شد.");
  } catch (e) {
    toast.error(apiError(e, "ورود انجام نشد."));
  } finally {
    busy.value = false;
  }
}

const tone: Record<string, string> = {
  sky: "bg-sky-50 text-sky-700",
  slate: "bg-slate-100 text-slate-600",
  emerald: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
};
const years = computed(() => [thisYear - 1, thisYear, thisYear + 1]);
const faYear = (y: number) => FA.format(y).replace(/٬/g, "");
</script>

<template>
  <button
    type="button"
    class="px-3 py-1.5 text-sm rounded-xl bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
    @click="show"
  >⬆ {{ label }}</button>

  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-3 sm:p-6 overflow-y-auto"
      dir="rtl"
      @click.self="close"
    >
      <div class="bg-surface rounded-card shadow-soft w-full max-w-6xl p-4 sm:p-5 space-y-4 mt-4">
        <div class="flex items-start gap-3">
          <div class="flex-1">
            <h2 class="text-base font-bold text-ink">ورود بودجه از اکسل</h2>
            <p class="text-xs text-slate-500 mt-1 leading-5">
              همان فایل جریان نقدی: ستون «بودجه &lt;ماه&gt;» برنامه است و «واقعی &lt;ماه&gt;» رقم واقعی.
              سطرهای جمع، مانده و سطرهای اطلاعاتی خودکار کنار گذاشته می‌شوند. تا «ثبت» را نزنید چیزی ذخیره نمی‌شود.
            </p>
          </div>
          <button class="text-slate-400 hover:text-ink text-xl leading-none" aria-label="بستن" @click="close">×</button>
        </div>

        <!-- Result -->
        <div v-if="result" class="rounded-xl bg-emerald-50 text-emerald-800 p-4 text-sm leading-7">
          <p class="font-semibold">{{ result.created ? 'بودجهٔ تازه ساخته شد' : 'بودجه به‌روز شد' }}: {{ result.budget_title }}</p>
          <p>
            {{ FA.format(result.lines) }} سرفصل ·
            {{ FA.format(result.written_budget) }} رقم بودجه ·
            {{ FA.format(result.written_forecasts) }} رقم پیش‌بینی فروش ·
            {{ FA.format(result.written_actual) }} رقم واقعی
            <template v-if="result.new_categories"> · {{ FA.format(result.new_categories) }} سرفصل تازه ساخته شد</template>
          </p>
          <p v-if="result.skipped_negative" class="text-amber-700">{{ FA.format(result.skipped_negative) }} رقم منفی وارد نشد.</p>
          <div class="flex gap-2 mt-3">
            <button class="px-4 py-1.5 rounded-xl bg-emerald-600 text-white text-sm" @click="close">بستن</button>
            <button class="px-4 py-1.5 rounded-xl bg-white text-emerald-700 text-sm" @click="show">فایل دیگر</button>
          </div>
        </div>

        <template v-else>
          <!-- Step 1: where and what -->
          <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
            <label class="block md:col-span-2">
              <span class="text-[11px] text-slate-400">مقصد</span>
              <select v-model="form.target" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
                <option v-if="canPlan" :value="null">+ بودجهٔ جدید از روی فایل</option>
                <option v-for="b in budgets" :key="b.id" :value="b.id">{{ b.title }} ({{ b.start_label }} تا {{ b.end_label }})</option>
              </select>
            </label>
            <label class="block">
              <span class="text-[11px] text-slate-400">سال ماه‌های فایل</span>
              <select v-model.number="form.year" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
                <option v-for="y in years" :key="y" :value="y">{{ faYear(y) }}</option>
              </select>
            </label>
            <label class="block">
              <span class="text-[11px] text-slate-400">واحد ارقام فایل</span>
              <select v-model="form.unit" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
                <option value="rial">ریال</option>
                <option value="toman">تومان (×۱۰ ذخیره می‌شود)</option>
              </select>
            </label>
            <label v-if="form.target === null" class="block md:col-span-2">
              <span class="text-[11px] text-slate-400">عنوان بودجهٔ جدید</span>
              <input
                v-model="form.title"
                placeholder="خالی بماند: «بودجهٔ نقدی <ماه اول> تا <ماه آخر>»"
                class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface"
              />
            </label>
          </div>

          <label
            class="block border-2 border-dashed border-slate-200 rounded-xl p-5 text-center cursor-pointer hover:border-brand-400 transition"
            @dragover.prevent
            @drop.prevent="drop"
          >
            <input type="file" accept=".xlsx" class="hidden" @change="pick" />
            <p class="text-sm text-ink">{{ file ? file.name : 'فایل اکسل را اینجا رها کنید یا کلیک کنید' }}</p>
            <p class="text-[11px] text-slate-400 mt-1">فقط ‎.xlsx‎ — برگهٔ کاری خودکار پیدا می‌شود</p>
          </label>

          <p v-if="busy && !analysis" class="text-sm text-slate-400 text-center">در حال خواندن فایل…</p>

          <!-- Step 2: the reading -->
          <template v-if="analysis">
            <div class="flex flex-wrap items-end gap-3">
              <label class="block">
                <span class="text-[11px] text-slate-400">برگه</span>
                <select v-model="form.sheet" class="mt-1 border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface" @change="analyse">
                  <option v-for="s in analysis.sheets" :key="s" :value="s">{{ s }}</option>
                </select>
              </label>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="m in analysis.months" :key="m.key"
                  class="px-2 py-1 rounded-lg text-[11px] bg-slate-100 text-slate-600"
                >
                  {{ m.label }}
                  <span v-if="m.has_budget" class="text-brand-700">· بودجه</span>
                  <span v-if="m.has_actual" class="text-emerald-700">· واقعی</span>
                </span>
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div class="rounded-xl bg-slate-50 p-3 space-y-2">
                <p class="text-xs font-semibold text-ink">چه چیزی وارد شود؟</p>
                <label class="flex items-center gap-2 text-sm" :class="!analysis.can_plan && 'opacity-50'">
                  <input v-model="form.parts.budget" type="checkbox" :disabled="!analysis.can_plan" />
                  ستون‌های «بودجه» (برنامه و پیش‌بینی فروش)
                  <span v-if="!analysis.can_plan" class="text-[11px] text-slate-400">— با مدیرعامل</span>
                </label>
                <label class="flex items-center gap-2 text-sm" :class="(!analysis.can_actual || !analysis.months.some((m) => m.has_actual)) && 'opacity-50'">
                  <input
                    v-model="form.parts.actual" type="checkbox"
                    :disabled="!analysis.can_actual || !analysis.months.some((m) => m.has_actual)"
                  />
                  ستون‌های «واقعی»
                  <span v-if="!analysis.can_actual" class="text-[11px] text-slate-400">— با واحد مالی</span>
                  <span v-else-if="!analysis.months.some((m) => m.has_actual)" class="text-[11px] text-slate-400">— در فایل نیست</span>
                </label>
              </div>
              <div v-if="form.target" class="rounded-xl bg-slate-50 p-3 space-y-2">
                <p class="text-xs font-semibold text-ink">با ارقام فعلی بودجه چه شود؟</p>
                <label class="flex items-start gap-2 text-sm">
                  <input v-model="form.mode" type="radio" value="merge" class="mt-1" />
                  <span>به‌روزرسانی — ارقام فایل جایگزین همان خانه‌ها، بقیه دست نمی‌خورد</span>
                </label>
                <label class="flex items-start gap-2 text-sm">
                  <input v-model="form.mode" type="radio" value="replace" class="mt-1" />
                  <span class="text-red-600">جایگزینی کامل — ارقام قبلی بخش‌های انتخاب‌شده پاک می‌شود</span>
                </label>
              </div>
            </div>

            <!-- What will go in -->
            <div class="grid grid-cols-2 md:grid-cols-5 gap-2 text-center">
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-[11px] text-slate-400">سطرهای واردشونده</p>
                <p class="font-bold text-ink">{{ FA.format(taken.length) }}</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-[11px] text-slate-400">بودجهٔ ورودی (جمع ماه‌ها)</p>
                <p class="font-bold text-ink text-sm">{{ money(totals.inB) }}</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-[11px] text-slate-400">بودجهٔ خروجی (جمع ماه‌ها)</p>
                <p class="font-bold text-ink text-sm">{{ money(totals.outB) }}</p>
              </div>
              <div class="rounded-xl bg-slate-50 p-2">
                <p class="text-[11px] text-slate-400">واقعی ورودی / خروجی</p>
                <p class="font-bold text-ink text-sm">{{ money(totals.inA, false) }} / {{ money(totals.outA, false) }}</p>
              </div>
              <div class="rounded-xl bg-sky-50 p-2">
                <p class="text-[11px] text-sky-700">پیش‌بینی فروش</p>
                <p class="font-bold text-sky-800 text-sm">{{ money(totals.sales) }}</p>
              </div>
            </div>

            <div class="overflow-x-auto border border-slate-100 rounded-xl">
              <table class="min-w-full text-sm">
                <thead class="bg-slate-50 text-[11px] text-slate-500">
                  <tr>
                    <th class="p-2 w-8"></th>
                    <th class="p-2 text-right font-medium">سطر اکسل</th>
                    <th class="p-2 text-right font-medium">جهت</th>
                    <th class="p-2 text-right font-medium">مقصد در بودجه</th>
                    <th class="p-2 text-left font-medium">جمع بودجه</th>
                    <th class="p-2 text-left font-medium">جمع واقعی</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in taken" :key="r.row" class="border-t border-slate-50 align-top">
                    <td class="p-2"><input type="checkbox" :checked="r.include" @change="setEdit(r, { include: false })" /></td>
                    <td class="p-2">
                      <p class="text-ink">{{ r.label }}</p>
                      <p class="text-[10px] text-slate-400">ردیف {{ FA.format(r.row) }}</p>
                      <p v-for="w in r.warnings" :key="w" class="text-[11px] text-amber-600">{{ w }}</p>
                    </td>
                    <td class="p-2">
                      <span v-if="r.match === 'sales'" class="text-[11px] text-slate-400">—</span>
                      <div v-else class="flex bg-slate-100 rounded-lg p-0.5 w-max">
                        <button
                          v-for="d in ([['in', 'ورودی'], ['out', 'خروجی']] as const)" :key="d[0]"
                          class="px-2 py-0.5 text-[11px] rounded-md"
                          :class="r.direction === d[0] ? 'bg-surface shadow-sm text-ink' : 'text-slate-500'"
                          @click="setEdit(r, { direction: d[0], category_id: null })"
                        >{{ d[1] }}</button>
                      </div>
                    </td>
                    <td class="p-2 min-w-[16rem]">
                      <span
                        v-if="r.match === 'sales'"
                        class="inline-block px-2 py-0.5 rounded-md text-[11px]" :class="tone.sky"
                      >{{ destination(r).text }}</span>
                      <div v-else class="space-y-1">
                        <span class="inline-block px-2 py-0.5 rounded-md text-[11px]" :class="tone[destination(r).tone]">{{ destination(r).text }}</span>
                        <select
                          class="block w-full border border-slate-200 rounded-lg px-2 py-1 text-xs bg-surface"
                          :value="r.category_id ?? ''"
                          @change="setEdit(r, { category_id: Number(($event.target as HTMLSelectElement).value) || null })"
                        >
                          <option value="">سرفصل جدید به نام همین سطر</option>
                          <option v-for="c in leaves(r.direction)" :key="c.id" :value="c.id">
                            {{ parentName(c) ? `${parentName(c)} › ` : '' }}{{ c.name_fa }}
                          </option>
                        </select>
                      </div>
                    </td>
                    <td class="p-2 text-left whitespace-nowrap" :class="form.parts.budget ? 'text-ink' : 'text-slate-300'">{{ money(sum(r.budget), false) }}</td>
                    <td class="p-2 text-left whitespace-nowrap" :class="form.parts.actual && r.match !== 'sales' ? 'text-ink' : 'text-slate-300'">
                      {{ r.match === 'sales' ? 'از بخش فروش' : money(sum(r.actual), false) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div>
              <button class="text-xs text-slate-500 hover:text-ink" @click="showSkipped = !showSkipped">
                {{ showSkipped ? '▾' : '▸' }} سطرهای کنار گذاشته ({{ FA.format(skipped.length) }})
              </button>
              <p v-if="totalsChecked.length" class="text-[11px] mt-1" :class="totalsBroken.length ? 'text-amber-600' : 'text-emerald-700'">
                <template v-if="!totalsBroken.length">
                  ✓ هر {{ FA.format(totalsChecked.length) }} سطر جمعِ اکسل با سطرهای خودش می‌خواند — پولشان در همان سطرها وارد می‌شود و خواندن دوباره‌شان یعنی دوبار شمردن.
                </template>
                <template v-else>⚠ {{ FA.format(totalsBroken.length) }} سطر جمع با سطرهای خودش نمی‌خواند — فایل را بررسی کنید.</template>
              </p>
              <table v-if="showSkipped" class="min-w-full text-sm mt-2">
                <tbody>
                  <tr v-for="r in skipped" :key="r.row" class="border-t border-slate-50 text-slate-500">
                    <td class="p-2 w-8">
                      <input v-if="!r.is_total" type="checkbox" :checked="false" @change="setEdit(r, { include: true })" />
                    </td>
                    <td class="p-2">{{ r.label || '(بدون شرح)' }} <span class="text-[10px]">· ردیف {{ FA.format(r.row) }}</span></td>
                    <td class="p-2 text-[11px]" :class="r.check === false ? 'text-amber-600' : r.check ? 'text-emerald-700' : ''">{{ r.reason || 'کنار گذاشته شد' }}</td>
                    <td class="p-2 text-left text-xs">{{ money(sum(r.budget), false) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="flex items-center justify-between gap-3 border-t border-slate-100 pt-3">
              <p class="text-[11px] text-slate-400 leading-5">
                پس از ورود هم همه‌چیز در صفحهٔ بودجه قابل ویرایش است. رقم واقعیِ واردشده جای رقم دفتر نقدینگی همان ماه را می‌گیرد.
              </p>
              <button
                class="px-5 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40 shrink-0"
                :disabled="!canApply"
                @click="apply"
              >{{ busy ? 'در حال ثبت…' : 'ثبت در بودجه' }}</button>
            </div>
          </template>
        </template>
      </div>
    </div>
  </Teleport>
</template>
