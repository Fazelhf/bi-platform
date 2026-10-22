<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { productionInputApi, type ProdInput } from "@/api/productionInput";
import { num } from "@/utils/format";
import { submitHint, submittedMessage } from "@/utils/approval";
import { selectIfZero } from "@/utils/inputs";
import MoneyInput from "@/components/MoneyInput.vue";
import ExportActions from "@/components/ExportActions.vue";

type Shift = "day" | "night";
type Row = Record<string, any>;

const periods = ref<{ id: number; label: string }[]>([]);
/** The month picked, and within it the week or day تولید records at. */
const selectedMonth = ref<number | null>(null);
const units = ref<{ id: number; label: string }[]>([]);
const grain = ref<"month" | "week" | "day">("month");
const selectedPeriod = ref<number | null>(null);
const data = ref<ProdInput | null>(null);
const loading = ref(true);
const saving = ref("");

/**
 * Only the cutting lines (and the print machine's shift count) are recorded
 * per shift; costs, print area and roll counts belong to the whole period.
 * So the shift switch lives on section 1 alone, not on the page.
 */
const view = ref<Shift | "compare">("day");

const SHIFT_FA: Record<Shift, string> = { day: "شیفت روز", night: "شیفت شب" };

// Column groups of the cutting sheet. `sub` labels sit under the group.
const ACTUAL_COLS = [
  { key: "actual_journal", label: "ژورنال" },
  { key: "actual_pos", label: "پوز" },
  { key: "actual_receipt", label: "رسید" },
];
const QUALITY_COLS = [
  { key: "waste_pct", label: "ضایعات ٪" },
  { key: "repair_count", label: "تعمیری" },
];
const DOWNTIME_COLS = [
  { key: "downtime_breakdown_shifts", label: "خرابی" },
  { key: "downtime_sizechange_shifts", label: "تغییر سایز" },
  { key: "downtime_nowork_shifts", label: "ظرفیت خالی" },
];

/** Costs kept off this form — entered elsewhere (finance), by stable code. */
const HIDDEN_COSTS = new Set(["cost-rent", "cost-production", "cost-salary"]);
const visibleCosts = computed(() =>
  (data.value?.costs ?? []).filter((c) => !HIDDEN_COSTS.has(c.category_code ?? "")),
);

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    data.value = await productionInputApi.get(selectedPeriod.value);
  } finally {
    loading.value = false;
  }
}

function rowsOf(shift: Shift): Row[] {
  return (shift === "night" ? data.value?.cutting_night : data.value?.cutting_day) ?? [];
}
const n = (v: unknown) => Number(v) || 0;
const actualOf = (r: Row) => ACTUAL_COLS.reduce((s, c) => s + n(r[c.key]), 0);
const sum = (rows: Row[], key: string) => rows.reduce((s, r) => s + n(r[key]), 0);

function totalsOf(shift: Shift) {
  const rows = rowsOf(shift);
  const out: Record<string, number> = { actual: rows.reduce((s, r) => s + actualOf(r), 0) };
  for (const k of ["active_shifts", "output_units", ...ACTUAL_COLS.map((c) => c.key),
    ...DOWNTIME_COLS.map((c) => c.key)]) out[k] = sum(rows, k);
  out.downtime = DOWNTIME_COLS.reduce((s, c) => s + out[c.key], 0);
  return out;
}
const totals = computed(() => ({ day: totalsOf("day"), night: totalsOf("night") }));

const currentRows = computed(() => (view.value === "compare" ? [] : rowsOf(view.value)));
const currentTotals = computed(() => totals.value[view.value === "night" ? "night" : "day"]);

const comparisonRows = computed(() => {
  const nights = rowsOf("night");
  return rowsOf("day").map((d) => {
    const nr = nights.find((r) => r.machine === d.machine) ?? {};
    const downtime = (r: Row) => DOWNTIME_COLS.reduce((s, c) => s + n(r[c.key]), 0);
    return {
      machine: d.machine,
      name: d.machine_name,
      index: [n(d.output_units), n(nr.output_units)],
      actual: [actualOf(d), actualOf(nr)],
      downtime: [downtime(d), downtime(nr)],
    };
  });
});

const COLOR_FA: Record<number, string> = { 1: "تک‌رنگ", 2: "دو‌رنگ", 3: "سه‌رنگ", 4: "چهار‌رنگ" };

// Live helpers so managers see totals while they type.
const totalCost = computed(() => visibleCosts.value.reduce((s, c) => s + n(c.amount_rial), 0));
const printTotal = computed(() =>
  (data.value?.print_colors ?? []).reduce((s, c) => s + n(c.area_sqm), 0),
);
const revenueTotal = computed(() =>
  (data.value?.rolls ?? []).reduce((s, r) => s + n(r.quantity) * n(r.piece_rate_rial), 0),
);

async function save(submit: boolean) {
  const d = data.value!;
  saving.value = submit ? "در حال ارسال…" : "در حال ذخیره…";
  try {
    await productionInputApi.save({
      period: selectedPeriod.value,
      submit,
      total_headcount: d.benchmark.total_headcount,
      cutting_day: d.cutting_day ?? [],
      cutting_night: d.cutting_night ?? [],
      print_day: d.print_day ?? null,
      print_night: d.print_night ?? null,
      print_colors: d.print_colors,
      costs: d.costs,
      rolls: d.rolls,
    });
    saving.value = submit ? `${submittedMessage()} ✓` : "ذخیره شد ✓";
    if (submit) await load();
  } catch (e: any) {
    saving.value = "خطا: " + (e?.response?.status === 403 ? "دسترسی ندارید" : "ذخیره نشد");
  }
}

/**
 * The periods تولید records at inside the chosen month — the month itself,
 * its weeks, or its days, as the CEO set it for this section.
 */
async function loadUnits() {
  if (!selectedMonth.value) return;
  const progress = await salesApi.monthProgress(selectedMonth.value, { department: "production" });
  grain.value = (progress.grain ?? "month") as typeof grain.value;
  if (grain.value === "month") {
    units.value = [{ id: selectedMonth.value, label: progress.period.label }];
  } else if (grain.value === "week") {
    units.value = progress.weeks.map((w) => ({ id: w.id, label: w.label }));
  } else {
    units.value = progress.weeks.flatMap((w) =>
      (w.day_periods ?? []).map((d) => ({ id: d.id, label: d.label })),
    );
  }
  // Open on the first week/day of the month.
  selectedPeriod.value = units.value[0]?.id ?? null;
}

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedMonth.value = periods.value[0]?.id ?? null;
  await loadUnits();
  await load();
});
watch(selectedMonth, loadUnits);
watch(selectedPeriod, load);

const INPUT =
  "w-full bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition";
const FIELD =
  "w-40 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none transition";
</script>

<template>
  <div class="space-y-4 pb-8">
    <!-- Header -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">ورود اطلاعات تولید</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          خطوط برش را برای شیفت روز و شب جداگانه پر کنید؛ شاخص‌ها پس از تأیید مدیر تولید محاسبه می‌شوند.
        </p>
      </div>
      <div class="flex items-center gap-3 flex-wrap">
        <span class="text-sm" :class="saving.startsWith('خطا') ? 'text-red-500' : 'text-accent-600'">{{ saving }}</span>
        <ExportActions :excel="false" />
        <select v-model.number="selectedMonth" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <select
          v-if="grain !== 'month'"
          v-model.number="selectedPeriod"
          class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm"
          :title="grain === 'week' ? 'تولید هفتگی ثبت می‌شود' : 'تولید روزانه ثبت می‌شود'"
        >
          <option v-for="u in units" :key="u.id" :value="u.id">{{ u.label }}</option>
        </select>
      </div>
    </div>

    <div v-if="loading || !data" class="text-slate-400">در حال بارگذاری…</div>

    <template v-else>
      <!-- Table 1: cutting lines, per shift. The night shift wears the app's
           own dark theme: `.dark` on this section alone flips every colour
           token inside it, so it follows the skin instead of fixed hexes. -->
      <section
        class="bg-surface text-ink rounded-card shadow-soft p-5 transition-colors duration-300"
        :class="{ dark: view === 'night' }"
      >
        <div class="flex items-center justify-between flex-wrap gap-3 mb-4">
          <div class="flex items-center gap-2">
            <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۱</span>
            <h3 class="font-bold text-ink">خطوط برش</h3>
            <span
              v-if="view !== 'compare'"
              class="text-xs font-medium rounded-full px-2.5 py-0.5"
              :class="view === 'night' ? 'bg-indigo-500/20 text-indigo-300' : 'bg-amber-500/10 text-amber-600'"
            >{{ SHIFT_FA[view] }}</span>
          </div>

          <!-- Shift switch: each tab carries its shift's actual total, so a
               shift left empty is visible before switching to it. -->
          <div class="flex items-center gap-1 p-1 rounded-xl bg-slate-100" role="tablist">
            <button
              v-for="s in (['day', 'night'] as Shift[])"
              :key="s"
              type="button"
              role="tab"
              :aria-selected="view === s"
              class="px-3 py-1.5 rounded-lg text-sm transition flex items-center gap-2"
              :class="view === s ? 'bg-surface text-ink shadow-soft font-semibold' : 'text-slate-500 hover:text-ink'"
              @click="view = s"
            >
              <span class="w-2 h-2 rounded-full" :class="s === 'night' ? 'bg-indigo-500' : 'bg-amber-500'"></span>
              {{ SHIFT_FA[s] }}
              <span class="text-xs text-slate-400 ltr-nums">{{ num(totals[s].actual) }}</span>
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="view === 'compare'"
              class="px-3 py-1.5 rounded-lg text-sm transition"
              :class="view === 'compare' ? 'bg-surface text-ink shadow-soft font-semibold' : 'text-slate-500 hover:text-ink'"
              @click="view = 'compare'"
            >
              مقایسه روز و شب
            </button>
          </div>
        </div>

        <!-- Entry sheet for one shift -->
        <div v-if="view !== 'compare'" class="overflow-x-auto">
          <table v-entry-table class="w-full text-sm min-w-[900px]">
            <thead>
              <tr class="text-xs text-slate-400">
                <th></th>
                <th></th>
                <th></th>
                <th :colspan="ACTUAL_COLS.length + 1" class="font-semibold text-accent-600 pt-1 pb-1.5 border-b-2 border-accent-500/40 bg-accent-50/60 rounded-t-lg">
                  تولید واقعی
                </th>
                <th :colspan="QUALITY_COLS.length" class="font-semibold pt-1 pb-1.5 border-b-2 border-slate-200">کیفیت</th>
                <th :colspan="DOWNTIME_COLS.length" class="font-semibold pt-1 pb-1.5 border-b-2 border-slate-200">خواب (شیفت)</th>
              </tr>
              <tr class="text-slate-400 border-b border-slate-100 text-xs">
                <th class="text-right font-medium py-2 pr-2">خط تولید</th>
                <th class="font-medium py-2 px-1.5 text-center">شیفت فعال</th>
                <th class="font-medium py-2 px-1.5 text-center border-l border-slate-100">تولید (شاخص)</th>
                <th v-for="c in ACTUAL_COLS" :key="c.key" class="font-medium py-2 px-1.5 text-center bg-accent-50/60">
                  <span class="sr-only">تولید واقعی — </span>{{ c.label }}
                </th>
                <th class="font-medium py-2 px-1.5 text-center bg-accent-50/60 border-l border-slate-100">
                  <span class="sr-only">تولید واقعی — </span>جمع
                </th>
                <th v-for="c in QUALITY_COLS" :key="c.key" class="font-medium py-2 px-1.5 text-center">{{ c.label }}</th>
                <th v-for="(c, i) in DOWNTIME_COLS" :key="c.key" class="font-medium py-2 px-1.5 text-center" :class="i === 0 ? 'border-r border-slate-100' : ''">
                  <span class="sr-only">خواب — </span>{{ c.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in currentRows" :key="m.machine" class="border-b border-slate-50">
                <td class="py-2 pr-2 font-medium whitespace-nowrap">{{ m.machine_name }}</td>
                <td class="py-1.5 px-1">
                  <input v-model="m.active_shifts" type="number" step="any" :class="INPUT" @focus="selectIfZero" />
                </td>
                <td class="py-1.5 px-1 border-l border-slate-100">
                  <input v-model="m.output_units" type="number" step="any" :class="[INPUT, 'font-semibold']" @focus="selectIfZero" />
                </td>
                <td v-for="c in ACTUAL_COLS" :key="c.key" class="py-1.5 px-1 bg-accent-50/40">
                  <input v-model="m[c.key]" type="number" step="any" :class="INPUT" @focus="selectIfZero" />
                </td>
                <td class="sum-cell py-1.5 px-2 text-center font-bold text-ink ltr-nums bg-accent-50/40 border-l border-slate-100">
                  {{ num(actualOf(m)) }}
                </td>
                <td v-for="c in QUALITY_COLS" :key="c.key" class="py-1.5 px-1">
                  <input v-model="m[c.key]" type="number" step="any" :class="INPUT" @focus="selectIfZero" />
                </td>
                <td v-for="(c, i) in DOWNTIME_COLS" :key="c.key" class="py-1.5 px-1" :class="i === 0 ? 'border-r border-slate-100' : ''">
                  <input v-model="m[c.key]" type="number" step="any" :class="INPUT" @focus="selectIfZero" />
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="text-xs font-semibold text-slate-500">
                <td class="py-2.5 pr-2 whitespace-nowrap">جمع {{ SHIFT_FA[view] }}</td>
                <td class="py-2.5 text-center ltr-nums">{{ num(currentTotals.active_shifts) }}</td>
                <td class="py-2.5 text-center ltr-nums text-ink">{{ num(currentTotals.output_units) }}</td>
                <td v-for="c in ACTUAL_COLS" :key="c.key" class="py-2.5 text-center ltr-nums">{{ num(currentTotals[c.key]) }}</td>
                <td class="py-2.5 text-center ltr-nums text-accent-600 font-bold">{{ num(currentTotals.actual) }}</td>
                <td v-for="c in QUALITY_COLS" :key="c.key" class="py-2.5 text-center text-slate-300">—</td>
                <td v-for="c in DOWNTIME_COLS" :key="c.key" class="py-2.5 text-center ltr-nums">{{ num(currentTotals[c.key]) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <!-- Day vs night, read-only -->
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm min-w-[720px]">
            <thead>
              <tr class="text-xs text-slate-400">
                <th></th>
                <th colspan="3" class="font-semibold pt-1 pb-1.5 border-b-2 border-slate-200">تولید (شاخص)</th>
                <th colspan="3" class="font-semibold text-accent-600 pt-1 pb-1.5 border-b-2 border-accent-500/40 bg-accent-50/60">تولید واقعی</th>
                <th colspan="2" class="font-semibold pt-1 pb-1.5 border-b-2 border-slate-200">خواب (شیفت)</th>
              </tr>
              <tr class="text-slate-400 border-b border-slate-100 text-xs">
                <th class="text-right font-medium py-2 pr-2">خط تولید</th>
                <template v-for="g in ['index', 'actual']" :key="g">
                  <th class="font-medium py-2 px-2 text-center" :class="g === 'actual' ? 'bg-accent-50/60' : ''">روز</th>
                  <th class="font-medium py-2 px-2 text-center" :class="g === 'actual' ? 'bg-accent-50/60' : ''">شب</th>
                  <th class="font-medium py-2 px-2 text-center border-l border-slate-100" :class="g === 'actual' ? 'bg-accent-50/60' : ''">جمع</th>
                </template>
                <th class="font-medium py-2 px-2 text-center">روز</th>
                <th class="font-medium py-2 px-2 text-center">شب</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in comparisonRows" :key="r.machine" class="border-b border-slate-50">
                <td class="py-2.5 pr-2 font-medium text-ink whitespace-nowrap">{{ r.name }}</td>
                <template v-for="g in (['index', 'actual'] as const)" :key="g">
                  <td class="py-2 px-2 text-center ltr-nums text-slate-600" :class="g === 'actual' ? 'bg-accent-50/40' : ''">{{ num(r[g][0]) }}</td>
                  <td class="py-2 px-2 text-center ltr-nums text-slate-600" :class="g === 'actual' ? 'bg-accent-50/40' : ''">{{ num(r[g][1]) }}</td>
                  <td class="py-2 px-2 text-center ltr-nums font-bold text-ink border-l border-slate-100" :class="g === 'actual' ? 'bg-accent-50/40' : ''">{{ num(r[g][0] + r[g][1]) }}</td>
                </template>
                <td class="py-2 px-2 text-center ltr-nums text-slate-600">{{ num(r.downtime[0]) }}</td>
                <td class="py-2 px-2 text-center ltr-nums text-slate-600">{{ num(r.downtime[1]) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="text-xs font-semibold text-slate-600">
                <td class="py-3 pr-2">جمع کارخانه</td>
                <td class="py-3 text-center ltr-nums">{{ num(totals.day.output_units) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(totals.night.output_units) }}</td>
                <td class="py-3 text-center ltr-nums font-bold text-ink border-l border-slate-100">{{ num(totals.day.output_units + totals.night.output_units) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(totals.day.actual) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(totals.night.actual) }}</td>
                <td class="py-3 text-center ltr-nums font-bold text-accent-600 border-l border-slate-100">{{ num(totals.day.actual + totals.night.actual) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(totals.day.downtime) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(totals.night.downtime) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <!-- Table 2: resources & costs (whole period) -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center gap-2 mb-4">
          <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۲</span>
          <h3 class="font-bold text-ink">منابع و هزینه‌ها</h3>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
          <label class="flex items-center justify-between gap-3">
            <span class="text-sm text-slate-600">تعداد کل نیروی انسانی (نفرروز)</span>
            <input v-model.number="data.benchmark.total_headcount" type="number" :class="FIELD" @focus="selectIfZero" />
          </label>
          <template v-for="c in visibleCosts" :key="c.category">
            <label class="flex items-center justify-between gap-3">
              <span class="text-sm text-slate-600">{{ c.category_name }}</span>
              <MoneyInput v-model="c.amount_rial" :class="FIELD" />
            </label>
            <!-- «سایر» says what it was for -->
            <label v-if="c.category_code === 'cost-other'" class="flex items-center justify-between gap-3">
              <span class="text-sm text-slate-600">شرح هزینه‌ی سایر</span>
              <input
                v-model="c.description"
                type="text"
                placeholder="مثلاً خرید قطعه، خدمات بیرونی…"
                class="flex-1 max-w-xs bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-3 py-1.5 text-sm outline-none transition"
              />
            </label>
          </template>
        </div>
        <div class="mt-4 pt-3 border-t border-slate-100 flex justify-between text-sm">
          <span class="text-slate-500">جمع کل هزینه</span>
          <span class="font-bold text-ink ltr-nums">{{ num(totalCost) }} ریال</span>
        </div>
      </section>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Table 3: print by colour -->
        <section class="bg-surface rounded-card shadow-soft p-5">
          <div class="flex items-center gap-2 mb-4">
            <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۳</span>
            <h3 class="font-bold text-ink">چاپ (متراژ به تفکیک رنگ)</h3>
          </div>
          <div class="space-y-2">
            <label v-for="c in data.print_colors" :key="c.color_count" class="flex items-center justify-between gap-3">
              <span class="text-sm text-slate-600">{{ COLOR_FA[c.color_count] }} (متر مربع)</span>
              <input v-model="c.area_sqm" type="number" step="any" :class="FIELD" @focus="selectIfZero" />
            </label>
          </div>
          <div class="mt-3 pt-3 border-t border-slate-100 flex justify-between text-sm">
            <span class="text-slate-500">مجموع متراژ چاپ</span>
            <span class="font-bold text-ink ltr-nums">{{ num(printTotal) }} م²</span>
          </div>
          <!-- The print machine's shifts, day and night side by side -->
          <div v-if="data.print_day || data.print_night" class="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between gap-3">
            <span class="text-sm text-slate-600">شیفت فعال دستگاه چاپ</span>
            <div class="flex items-center gap-2">
              <label v-if="data.print_day" class="flex items-center gap-1.5 text-xs text-slate-500">
                <span class="w-2 h-2 rounded-full bg-amber-500"></span>روز
                <input v-model="data.print_day.active_shifts" type="number" step="any"
                  class="w-16 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums text-sm outline-none transition"
                  @focus="selectIfZero" />
              </label>
              <label v-if="data.print_night" class="flex items-center gap-1.5 text-xs text-slate-500">
                <span class="w-2 h-2 rounded-full bg-indigo-500"></span>شب
                <input v-model="data.print_night.active_shifts" type="number" step="any"
                  class="w-16 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-center ltr-nums text-sm outline-none transition"
                  @focus="selectIfZero" />
              </label>
            </div>
          </div>
        </section>

        <!-- Table 4: roll counts -->
        <section class="bg-surface rounded-card shadow-soft p-5">
          <div class="flex items-center gap-2 mb-4">
            <span class="w-7 h-7 rounded-lg bg-panel text-white text-xs flex items-center justify-center font-bold">۴</span>
            <h3 class="font-bold text-ink">تعداد رول‌ها</h3>
          </div>
          <div class="space-y-2">
            <label v-for="r in data.rolls" :key="r.product" class="flex items-center justify-between gap-3">
              <span class="text-sm text-slate-600">
                {{ r.product_name }}
                <span class="text-xs text-slate-400 ltr-nums">(اجرت {{ num(r.piece_rate_rial) }})</span>
              </span>
              <input v-model="r.quantity" type="number" step="any" :class="[FIELD, 'w-32']" @focus="selectIfZero" />
            </label>
          </div>
          <div class="mt-3 pt-3 border-t border-slate-100 flex justify-between text-sm">
            <span class="text-slate-500">درآمد اجرت (برآورد)</span>
            <span class="font-bold text-accent-600 ltr-nums">{{ num(revenueTotal) }} ریال</span>
          </div>
        </section>
      </div>

      <!-- Sticky action bar -->
      <div class="sticky bottom-4 z-30 bg-panel text-white rounded-card shadow-pop p-3 flex items-center justify-between">
        <span class="hidden sm:inline text-sm px-2 text-white/80">{{ submitHint() }}</span>
        <div class="flex gap-2">
          <button class="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-sm" @click="save(false)">ذخیره پیش‌نویس</button>
          <button class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium" @click="save(true)">
            ذخیره و ارسال برای تایید
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
