<script setup lang="ts">
/**
 * مدیریت بودجه — rename, move its span, switch it off, empty it, delete it,
 * or take it out as the Excel sheet it was planned in.
 *
 * Everything destructive says what it will take with it — counted on the
 * server — before it asks, and nothing here touches the cash ledger or the
 * categories a budget created: those may already be in use elsewhere.
 */
import { computed, reactive, ref, watch } from "vue";
import { apiError, budgetApi, type Budget, type BudgetStats, type ClearWhat } from "@/api/budget";
import { confirm, prompt, toast } from "@/composables/useUi";

const props = defineProps<{
  budget: Budget;
  monthPeriods: { id: number; label: string; jalali_year: number }[];
}>();
const emit = defineEmits<{ changed: [selectId?: number | null] }>();

const FA = new Intl.NumberFormat("fa-IR");
const open = ref(false);
const stats = ref<BudgetStats | null>(null);
const busy = ref(false);
const edit = reactive({ title: "", start: 0, end: 0, is_active: true });

function reset() {
  edit.title = props.budget.title;
  edit.start = props.budget.start_period;
  edit.end = props.budget.end_period;
  edit.is_active = props.budget.is_active;
}
watch(() => props.budget, reset, { immediate: true });

async function loadStats() {
  try {
    stats.value = await budgetApi.stats(props.budget.id);
  } catch {
    stats.value = null;
  }
}
watch(open, (v) => v && loadStats());
watch(() => props.budget.id, () => open.value && loadStats());

const index = (id: number) => props.monthPeriods.findIndex((p) => p.id === id);
const shrinks = computed(() =>
  index(edit.start) > index(props.budget.start_period) || index(edit.end) < index(props.budget.end_period),
);
const dirty = computed(() =>
  edit.title.trim() !== props.budget.title || edit.start !== props.budget.start_period
  || edit.end !== props.budget.end_period || edit.is_active !== props.budget.is_active,
);

async function save() {
  if (!edit.title.trim()) return toast.error("عنوان خالی است.");
  if (index(edit.start) > index(edit.end)) return toast.error("ماه پایان پیش از ماه شروع است.");
  if (shrinks.value) {
    const ok = await confirm({
      title: "کوتاه کردن بازهٔ بودجه",
      message: "ماه‌هایی که از بازه بیرون می‌افتند با همهٔ ارقامشان (بودجه، پیش‌بینی فروش و واقعی) حذف می‌شوند.",
      danger: true,
    });
    if (!ok) return;
  }
  busy.value = true;
  try {
    const start = props.monthPeriods.find((p) => p.id === edit.start);
    await budgetApi.update(props.budget.id, {
      title: edit.title.trim(),
      start_period: edit.start,
      end_period: edit.end,
      jalali_year: start?.jalali_year ?? props.budget.jalali_year,
      is_active: edit.is_active,
    });
    toast.success("بودجه به‌روز شد.");
    emit("changed", props.budget.id);
    loadStats();
  } catch (e) {
    toast.error(apiError(e, "ذخیره نشد."));
  } finally {
    busy.value = false;
  }
}

const clearOptions: { what: ClearWhat; label: string; count: (s: BudgetStats) => number; note: string }[] = [
  { what: "plan", label: "ارقام بودجه", count: (s) => s.amounts, note: "سرفصل‌ها می‌مانند؛ تصویب ماه‌ها برداشته می‌شود" },
  { what: "sales", label: "پیش‌بینی فروش", count: (s) => s.forecasts, note: "فروش واقعی بخش فروش دست نمی‌خورد" },
  { what: "actuals", label: "ارقام واقعیِ واردشده", count: (s) => s.actuals, note: "سرفصل‌ها دوباره رقم دفتر نقدینگی را نشان می‌دهند" },
  { what: "lines", label: "سرفصل‌ها و همهٔ ارقامشان", count: (s) => s.lines, note: "بودجه خالی می‌ماند؛ دسته‌های نقدینگی حذف نمی‌شوند" },
];

async function clear(opt: (typeof clearOptions)[number]) {
  const ok = await confirm({
    title: `پاک کردن ${opt.label}`,
    message: `${stats.value ? `${FA.format(opt.count(stats.value))} مورد از «${props.budget.title}» پاک می‌شود. ` : ""}${opt.note}. این کار برگشت ندارد.`,
    danger: true,
  });
  if (!ok) return;
  busy.value = true;
  try {
    await budgetApi.clear(props.budget.id, opt.what);
    toast.success(`${opt.label} پاک شد.`);
    emit("changed", props.budget.id);
    loadStats();
  } catch (e) {
    toast.error(apiError(e, "پاک نشد."));
  } finally {
    busy.value = false;
  }
}

async function remove() {
  const s = stats.value;
  const typed = await prompt({
    title: "حذف کامل بودجه",
    message:
      `«${props.budget.title}» با ${s ? `${FA.format(s.lines)} سرفصل، ${FA.format(s.amounts)} رقم بودجه، ` +
      `${FA.format(s.forecasts)} پیش‌بینی فروش و ${FA.format(s.actuals)} رقم واقعی` : "همهٔ ارقامش"} حذف می‌شود و برنمی‌گردد. ` +
      "برای تأیید، عنوان بودجه را بنویسید.",
    placeholder: props.budget.title,
  });
  if (typed === null) return;
  if (typed.trim() !== props.budget.title.trim()) return toast.error("عنوان وارد شده با عنوان بودجه یکی نیست.");
  busy.value = true;
  try {
    await budgetApi.remove(props.budget.id);
    toast.success("بودجه حذف شد.");
    open.value = false;
    emit("changed", null);
  } catch (e) {
    toast.error(apiError(e, "حذف نشد."));
  } finally {
    busy.value = false;
  }
}

async function exportExcel() {
  try {
    const blob = await budgetApi.exportExcel(props.budget.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${props.budget.title}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast.error(apiError(e, "خروجی ساخته نشد."));
  }
}
</script>

<template>
  <section class="bg-surface rounded-card shadow-soft">
    <button
      class="w-full flex items-center justify-between gap-3 p-4 text-right"
      :aria-expanded="open"
      @click="open = !open"
    >
      <div>
        <h2 class="text-sm font-semibold text-ink">مدیریت بودجه</h2>
        <p class="text-[11px] text-slate-400 mt-0.5">ویرایش عنوان و بازه، خروجی اکسل، پاک کردن ارقام یا حذف کامل</p>
      </div>
      <span class="text-slate-400 text-sm">{{ open ? '▴' : '▾' }}</span>
    </button>

    <div v-if="open" class="border-t border-slate-100 p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
      <!-- Edit -->
      <div class="lg:col-span-2 space-y-3">
        <div class="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <label class="block sm:col-span-2">
            <span class="text-[11px] text-slate-400">عنوان</span>
            <input v-model="edit.title" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-[11px] text-slate-400">از ماه</span>
            <select v-model.number="edit.start" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
              <option v-for="p in monthPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-[11px] text-slate-400">تا ماه</span>
            <select v-model.number="edit.end" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-1.5 text-sm bg-surface">
              <option v-for="p in monthPeriods" :key="p.id" :value="p.id">{{ p.label }}</option>
            </select>
          </label>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <label class="flex items-center gap-2 text-sm text-slate-600">
            <input v-model="edit.is_active" type="checkbox" /> فعال (در فهرست‌ها و داشبورد پیش‌فرض)
          </label>
          <span v-if="shrinks" class="text-[11px] text-red-600">ماه‌های بیرون‌افتاده با ارقامشان حذف می‌شوند</span>
          <div class="flex gap-2 ms-auto">
            <button v-if="dirty" class="px-3 py-1.5 text-sm rounded-xl bg-slate-100 text-slate-600" @click="reset">انصراف</button>
            <button
              class="px-4 py-1.5 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40"
              :disabled="!dirty || busy" @click="save"
            >ذخیرهٔ تغییرات</button>
          </div>
        </div>
        <div v-if="stats" class="flex flex-wrap gap-2 text-[11px]">
          <span class="px-2 py-1 rounded-lg bg-slate-100 text-slate-600">{{ FA.format(stats.months) }} ماه · {{ FA.format(stats.approved) }} مصوب</span>
          <span class="px-2 py-1 rounded-lg bg-slate-100 text-slate-600">{{ FA.format(stats.lines) }} سرفصل</span>
          <span class="px-2 py-1 rounded-lg bg-slate-100 text-slate-600">{{ FA.format(stats.amounts) }} رقم بودجه</span>
          <span class="px-2 py-1 rounded-lg bg-sky-50 text-sky-700">{{ FA.format(stats.forecasts) }} پیش‌بینی فروش</span>
          <span class="px-2 py-1 rounded-lg bg-emerald-50 text-emerald-700">{{ FA.format(stats.actuals) }} رقم واقعیِ واردشده</span>
        </div>
        <button class="px-3 py-1.5 text-sm rounded-xl bg-emerald-50 text-emerald-700 hover:bg-emerald-100" @click="exportExcel">
          ⬇ خروجی اکسل (همان قالب ورود — ستون‌های بودجه و واقعی)
        </button>
      </div>

      <!-- Danger zone -->
      <div class="rounded-xl border border-red-100 p-3 space-y-2">
        <p class="text-xs font-semibold text-red-700">پاک‌سازی</p>
        <button
          v-for="o in clearOptions" :key="o.what"
          class="w-full flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg text-sm bg-red-50/60 text-red-700 hover:bg-red-100 disabled:opacity-40"
          :disabled="busy || (stats ? !o.count(stats) : false)"
          @click="clear(o)"
        >
          <span>پاک کردن {{ o.label }}</span>
          <span v-if="stats" class="text-[11px] ltr-nums">{{ FA.format(o.count(stats)) }}</span>
        </button>
        <button
          class="w-full px-3 py-1.5 rounded-lg text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-40"
          :disabled="busy" @click="remove"
        >حذف کامل این بودجه</button>
      </div>
    </div>
  </section>
</template>
