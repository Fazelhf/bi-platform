<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { productionInputApi, type ProdInput } from "@/api/productionInput";
import { num } from "@/utils/format";
import { submitHint, submittedMessage } from "@/utils/approval";
import { selectIfZero } from "@/utils/inputs";
import MoneyInput from "@/components/MoneyInput.vue";
import ExportActions from "@/components/ExportActions.vue";

const periods = ref<{ id: number; label: string }[]>([]);
/** The month picked, and within it the week or day تولید records at. */
const selectedMonth = ref<number | null>(null);
const units = ref<{ id: number; label: string }[]>([]);
const grain = ref<"month" | "week" | "day">("month");
const selectedPeriod = ref<number | null>(null);
const data = ref<ProdInput | null>(null);
const loading = ref(true);
const saving = ref("");

// Two-shift support: 'day' | 'night' | 'compare'
const activeShift = ref<"day" | "night" | "compare">("day");

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    const res = await productionInputApi.get(selectedPeriod.value);
    if (!res.cutting_day || res.cutting_day.length === 0) {
      res.cutting_day = JSON.parse(JSON.stringify(res.cutting || []));
    }
    if (!res.cutting_night || res.cutting_night.length === 0) {
      res.cutting_night = (res.cutting_day || []).map((m: any) => ({
        machine: m.machine,
        machine_name: m.machine_name,
        kind: m.kind,
        shift: "night",
        active_shifts: "0",
        output_units: "0",
        actual_journal: "0",
        actual_pos: "0",
        actual_receipt: "0",
        waste_pct: "0",
        repair_count: "0",
        downtime_breakdown_shifts: "0",
        downtime_sizechange_shifts: "0",
        downtime_nowork_shifts: "0",
        status: "draft",
      }));
    }
    if (!res.print_day && res.print) {
      res.print_day = JSON.parse(JSON.stringify(res.print));
    }
    if (!res.print_night && res.print_day) {
      res.print_night = {
        ...JSON.parse(JSON.stringify(res.print_day)),
        shift: "night",
        active_shifts: "0",
      };
    }
    data.value = res;
  } finally {
    loading.value = false;
  }
}

const currentPrint = computed(() => {
  if (!data.value) return null;
  if (activeShift.value === "night") {
    return data.value.print_night ?? data.value.print;
  }
  return data.value.print_day ?? data.value.print;
});

// Section 5: Exclude specific costs from Section 2 UI
const EXCLUDED_COST_NAMES = ["هزینه اجاره", "هزینه تولید", "هزینه حقوق"];
const visibleCosts = computed(() =>
  (data.value?.costs ?? []).filter(
    (c) => !EXCLUDED_COST_NAMES.some((ex) => c.category_name?.trim() === ex || c.category_name?.includes(ex)),
  ),
);

function isOtherCost(c: { category_code?: string; category_name?: string }): boolean {
  return c.category_code === "cost-other" || c.category_name?.trim() === "سایر";
}

// Live helpers so managers see totals while they type.
const totalCost = computed(() =>
  visibleCosts.value.reduce((s, c) => s + Number(c.amount_rial || 0), 0),
);
const printTotal = computed(() =>
  (data.value?.print_colors ?? []).reduce((s, c) => s + Number(c.area_sqm || 0), 0),
);
const revenueTotal = computed(() =>
  (data.value?.rolls ?? []).reduce(
    (s, r) => s + Number(r.quantity || 0) * Number(r.piece_rate_rial || 0), 0,
  ),
);

// Aggregations per shift
function sumField(list: Record<string, any>[] | undefined, field: string): number {
  return (list ?? []).reduce((s, r) => s + (Number(r[field]) || 0), 0);
}

const dayTotals = computed(() => {
  const list = data.value?.cutting_day ?? [];
  const indexOutput = sumField(list, "output_units");
  const journal = sumField(list, "actual_journal");
  const pos = sumField(list, "actual_pos");
  const receipt = sumField(list, "actual_receipt");
  const actualTotal = journal + pos + receipt;
  const activeShifts = sumField(list, "active_shifts");
  const downtime = sumField(list, "downtime_breakdown_shifts") + sumField(list, "downtime_sizechange_shifts") + sumField(list, "downtime_nowork_shifts");
  return { indexOutput, journal, pos, receipt, actualTotal, activeShifts, downtime };
});

const nightTotals = computed(() => {
  const list = data.value?.cutting_night ?? [];
  const indexOutput = sumField(list, "output_units");
  const journal = sumField(list, "actual_journal");
  const pos = sumField(list, "actual_pos");
  const receipt = sumField(list, "actual_receipt");
  const actualTotal = journal + pos + receipt;
  const activeShifts = sumField(list, "active_shifts");
  const downtime = sumField(list, "downtime_breakdown_shifts") + sumField(list, "downtime_sizechange_shifts") + sumField(list, "downtime_nowork_shifts");
  return { indexOutput, journal, pos, receipt, actualTotal, activeShifts, downtime };
});

const combinedTotals = computed(() => ({
  indexOutput: dayTotals.value.indexOutput + nightTotals.value.indexOutput,
  journal: dayTotals.value.journal + nightTotals.value.journal,
  pos: dayTotals.value.pos + nightTotals.value.pos,
  receipt: dayTotals.value.receipt + nightTotals.value.receipt,
  actualTotal: dayTotals.value.actualTotal + nightTotals.value.actualTotal,
  activeShifts: dayTotals.value.activeShifts + nightTotals.value.activeShifts,
  downtime: dayTotals.value.downtime + nightTotals.value.downtime,
}));

// Current cutting list to show in single-shift edit mode
const currentCuttingRows = computed(() => {
  if (!data.value) return [];
  return activeShift.value === "night" ? data.value.cutting_night ?? [] : data.value.cutting_day ?? [];
});

// Comparison rows for both shifts side-by-side
const comparisonRows = computed(() => {
  if (!data.value) return [];
  const days = data.value.cutting_day ?? [];
  const nights = data.value.cutting_night ?? [];
  return days.map((dayRow, i) => {
    const nightRow = nights[i] || {};
    const dayActual = (Number(dayRow.actual_journal) || 0) + (Number(dayRow.actual_pos) || 0) + (Number(dayRow.actual_receipt) || 0);
    const nightActual = (Number(nightRow.actual_journal) || 0) + (Number(nightRow.actual_pos) || 0) + (Number(nightRow.actual_receipt) || 0);
    return {
      machine_name: dayRow.machine_name,
      day_index: Number(dayRow.output_units) || 0,
      night_index: Number(nightRow.output_units) || 0,
      total_index: (Number(dayRow.output_units) || 0) + (Number(nightRow.output_units) || 0),
      day_actual: dayActual,
      night_actual: nightActual,
      total_actual: dayActual + nightActual,
      day_journal: Number(dayRow.actual_journal) || 0,
      night_journal: Number(nightRow.actual_journal) || 0,
      day_pos: Number(dayRow.actual_pos) || 0,
      night_pos: Number(nightRow.actual_pos) || 0,
      day_receipt: Number(dayRow.actual_receipt) || 0,
      night_receipt: Number(nightRow.actual_receipt) || 0,
      day_shifts: Number(dayRow.active_shifts) || 0,
      night_shifts: Number(nightRow.active_shifts) || 0,
    };
  });
});

const COLOR_FA: Record<number, string> = { 1: "تک‌رنگ", 2: "دو‌رنگ", 3: "سه‌رنگ", 4: "چهار‌رنگ" };

function buildPayload(submit: boolean) {
  const d = data.value!;
  const cuttingDay = d.cutting_day ?? [];
  const cuttingNight = d.cutting_night ?? [];
  const printDay = d.print_day ?? d.print;
  const printNight = d.print_night;
  return {
    period: selectedPeriod.value,
    submit,
    total_headcount: d.benchmark.total_headcount,
    cutting: [...cuttingDay, ...cuttingNight],
    cutting_day: cuttingDay,
    cutting_night: cuttingNight,
    print: currentPrint.value ?? d.print,
    print_day: printDay,
    print_night: printNight,
    print_colors: d.print_colors,
    costs: d.costs,
    rolls: d.rolls,
  };
}

async function save(submit: boolean) {
  saving.value = submit ? "در حال ارسال…" : "در حال ذخیره…";
  try {
    await productionInputApi.save(buildPayload(submit));
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
</script>

<template>
  <div class="space-y-4 pb-8">
    <!-- Header -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">ورود اطلاعات تولید</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          اطلاعات شیفت روز و شیفت شب را جداگانه ثبت کنید؛ شاخص‌ها پس از تأیید مدیر محاسبه می‌شوند.
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-sm font-medium" :class="saving.startsWith('خطا') ? 'text-red-500' : 'text-accent-600'">{{ saving }}</span>
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

    <div v-if="loading || !data" class="text-slate-400 py-12 text-center">در حال بارگذاری…</div>

    <template v-else>
      <!-- Global Shift Control Bar (Applies to all entered data) -->
      <div
        class="rounded-card p-4 transition-all duration-300 border shadow-soft flex items-center justify-between flex-wrap gap-4"
        :class="activeShift === 'night'
          ? 'bg-slate-900 text-slate-100 border-slate-800 shadow-pop'
          : 'bg-surface text-ink border-slate-200'"
      >
        <div class="flex items-center gap-3">
          <div
            class="w-10 h-10 rounded-xl flex items-center justify-center font-bold text-sm transition-colors"
            :class="activeShift === 'night' ? 'bg-indigo-600/30 text-indigo-400 border border-indigo-500/30' : 'bg-slate-100 text-slate-700 border border-slate-200'"
          >
            <svg v-if="activeShift === 'day'" class="w-5 h-5 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
            </svg>
            <svg v-else-if="activeShift === 'night'" class="w-5 h-5 text-indigo-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
            <svg v-else class="w-5 h-5 text-slate-600 dark:text-slate-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5" />
            </svg>
          </div>
          <div>
            <div class="text-xs text-slate-400">شیفت کاری فعال فرم ورود اطلاعات</div>
            <div class="text-sm font-bold" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">
              {{ activeShift === 'day' ? 'شیفت روز (Day Shift)' : activeShift === 'night' ? 'شیفت شب (Night Shift)' : 'مقایسه جامع دو شیفت کاری' }}
            </div>
          </div>
        </div>

        <!-- Shift Selector Buttons -->
        <div
          class="flex items-center gap-1.5 p-1 rounded-xl transition-colors"
          :class="activeShift === 'night' ? 'bg-slate-800 border border-slate-700' : 'bg-slate-100 border border-slate-200'"
        >
          <button
            type="button"
            class="px-4 py-2 rounded-lg text-sm transition-all font-semibold flex items-center gap-2"
            :class="activeShift === 'day'
              ? 'bg-white text-ink shadow-sm'
              : (activeShift === 'night' ? 'text-slate-400 hover:text-white' : 'text-slate-600 hover:text-ink')"
            @click="activeShift = 'day'"
          >
            <span class="w-2 h-2 rounded-full" :class="activeShift === 'day' ? 'bg-amber-500' : 'bg-transparent'"></span>
            شیفت روز
          </button>
          <button
            type="button"
            class="px-4 py-2 rounded-lg text-sm transition-all font-semibold flex items-center gap-2"
            :class="activeShift === 'night'
              ? 'bg-indigo-600 text-white shadow-sm'
              : 'text-slate-600 hover:text-ink'"
            @click="activeShift = 'night'"
          >
            <span class="w-2 h-2 rounded-full" :class="activeShift === 'night' ? 'bg-white' : 'bg-transparent'"></span>
            شیفت شب
          </button>
          <button
            type="button"
            class="px-4 py-2 rounded-lg text-sm transition-all font-semibold flex items-center gap-2"
            :class="activeShift === 'compare'
              ? 'bg-panel text-white shadow-sm'
              : (activeShift === 'night' ? 'text-slate-400 hover:text-white' : 'text-slate-600 hover:text-ink')"
            @click="activeShift = 'compare'"
          >
            مقایسه دو شیفت
          </button>
        </div>
      </div>

      <!-- Formal Live Summary Strip -->
      <div
        class="flex items-center justify-between flex-wrap gap-3 py-2.5 px-4 rounded-xl text-xs border transition-colors duration-300"
        :class="activeShift === 'night'
          ? 'bg-slate-900 border-slate-800 text-slate-300'
          : 'bg-surface border-slate-200 text-slate-600 shadow-soft'"
      >
        <div class="flex items-center gap-2">
          <span class="text-slate-400">وضعیت شیفت جاری:</span>
          <span class="font-bold" :class="activeShift === 'night' ? 'text-indigo-400' : 'text-ink'">
            {{ activeShift === 'day' ? 'شیفت روز' : activeShift === 'night' ? 'شیفت شب' : 'مجموع روز + شب' }}
          </span>
        </div>
        <div class="flex items-center gap-6 flex-wrap text-xs">
          <div>
            <span class="ml-1 text-slate-400">تولید (شاخص):</span>
            <strong class="font-bold ltr-nums" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">
              {{ num(activeShift === 'day' ? dayTotals.indexOutput : activeShift === 'night' ? nightTotals.indexOutput : combinedTotals.indexOutput) }}
            </strong>
          </div>
          <div>
            <span class="ml-1 text-slate-400">تولید واقعی:</span>
            <strong class="font-bold ltr-nums" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">
              {{ num(activeShift === 'day' ? dayTotals.actualTotal : activeShift === 'night' ? nightTotals.actualTotal : combinedTotals.actualTotal) }}
            </strong>
          </div>
          <div>
            <span class="ml-1 text-slate-400">شیفت فعال:</span>
            <strong class="font-bold ltr-nums" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">
              {{ num(activeShift === 'day' ? dayTotals.activeShifts : activeShift === 'night' ? nightTotals.activeShifts : combinedTotals.activeShifts) }}
            </strong>
          </div>
          <div>
            <span class="ml-1 text-slate-400">مجموع توقفات:</span>
            <strong class="font-bold ltr-nums" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">
              {{ num(activeShift === 'day' ? dayTotals.downtime : activeShift === 'night' ? nightTotals.downtime : combinedTotals.downtime) }}
            </strong>
          </div>
        </div>
      </div>

      <!-- Section 1: Cutting lines -->
      <section
        class="rounded-card shadow-soft p-5 transition-all duration-300"
        :class="activeShift === 'night'
          ? 'bg-slate-900 text-slate-100 border border-slate-800 shadow-pop'
          : 'bg-surface text-ink border border-slate-100 dark:border-slate-800'"
      >
        <!-- Section Header -->
        <div class="flex items-center gap-2 mb-4">
          <span
            class="w-7 h-7 rounded-lg text-xs flex items-center justify-center font-bold transition-colors"
            :class="activeShift === 'night' ? 'bg-indigo-600 text-white' : 'bg-panel text-white'"
          >۱</span>
          <div>
            <h3 class="font-bold transition-colors" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">خطوط برش</h3>
            <p class="text-xs transition-colors" :class="activeShift === 'night' ? 'text-slate-400' : 'text-slate-400'">
              {{ activeShift === 'compare' ? 'مقایسه عملکرد شیفت روز و شب خطوط برش' : `ورود داده‌های خطوط برش (${activeShift === 'night' ? 'شیفت شب' : 'شیفت روز'})` }}
            </p>
          </div>
        </div>

        <!-- Table View: Day or Night Shift (Editing Mode) -->
        <div v-if="activeShift !== 'compare'" class="overflow-x-auto">
          <table v-entry-table class="w-full text-sm min-w-[950px]">
            <thead>
              <tr
                class="border-b text-xs font-medium"
                :class="activeShift === 'night' ? 'text-slate-400 border-slate-800' : 'text-slate-400 border-slate-100'"
              >
                <th
                  class="text-right font-medium py-2.5 pr-2 whitespace-nowrap"
                  :style="activeShift === 'night' ? { backgroundColor: '#0f172a' } : {}"
                >خط تولید</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">شیفت فعال</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">تولید (شاخص)</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">واقعی: ژورنال</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">واقعی: پوز</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">واقعی: رسید</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">جمع تولید واقعی</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">ضایعات ٪</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">تعمیری</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">خواب (خرابی)</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">خواب (تغییر سایز)</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">خواب (ظرفیت خالی)</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="m in currentCuttingRows"
                :key="m.machine"
                class="border-b transition-colors"
                :class="activeShift === 'night'
                  ? 'border-slate-800/80 hover:bg-slate-800/50'
                  : 'border-slate-50 hover:bg-slate-50/50'"
              >
                <!-- Machine name -->
                <td
                  class="py-2 pr-2 font-medium whitespace-nowrap transition-colors"
                  :class="activeShift === 'night' ? 'text-slate-200' : 'text-ink'"
                  :style="activeShift === 'night' ? { backgroundColor: '#0f172a' } : {}"
                >
                  {{ m.machine_name }}
                </td>

                <!-- Active shifts -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.active_shifts"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Index Output (تولید شاخص) -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.output_units"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums font-semibold outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Actual Production: Journal -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.actual_journal"
                    type="number" step="any"
                    placeholder="۰"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Actual Production: POS -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.actual_pos"
                    type="number" step="any"
                    placeholder="۰"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Actual Production: Receipt -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.actual_receipt"
                    type="number" step="any"
                    placeholder="۰"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Calculated Total Actual -->
                <td
                  class="py-1.5 px-2 text-center font-bold ltr-nums whitespace-nowrap rounded-lg"
                  :class="activeShift === 'night'
                    ? 'bg-slate-800/70 text-emerald-400'
                    : 'bg-slate-50/60 text-ink'"
                >
                  {{ num((Number(m.actual_journal) || 0) + (Number(m.actual_pos) || 0) + (Number(m.actual_receipt) || 0)) }}
                </td>

                <!-- Quality: Waste % -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.waste_pct"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Quality: Repairs -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.repair_count"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Downtime: Breakdown -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.downtime_breakdown_shifts"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Downtime: Size change -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.downtime_sizechange_shifts"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>

                <!-- Downtime: Capacity (formerly no-order) -->
                <td class="py-1.5 px-1">
                  <input
                    v-model="m.downtime_nowork_shifts"
                    type="number" step="any"
                    class="w-full rounded-lg px-2 py-1.5 text-center ltr-nums outline-none transition"
                    :class="activeShift === 'night'
                      ? 'bg-slate-800/90 text-white border border-slate-700/70 focus:bg-slate-800 focus:border-indigo-500'
                      : 'bg-slate-50 text-ink focus:bg-surface border border-transparent focus:border-accent-500'"
                    @focus="selectIfZero"
                  />
                </td>
              </tr>
            </tbody>
            <!-- Footer Totals -->
            <tfoot>
              <tr
                class="border-t text-xs font-semibold"
                :class="activeShift === 'night'
                  ? 'border-slate-800 text-slate-300'
                  : 'border-slate-200 text-slate-600'"
              >
                <td
                  class="py-2.5 pr-2"
                  :style="activeShift === 'night' ? { backgroundColor: '#0f172a' } : {}"
                >جمع کل</td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? dayTotals.activeShifts : nightTotals.activeShifts) }}
                </td>
                <td class="py-2.5 text-center ltr-nums font-bold" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">
                  {{ num(activeShift === 'day' ? dayTotals.indexOutput : nightTotals.indexOutput) }}
                </td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? dayTotals.journal : nightTotals.journal) }}
                </td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? dayTotals.pos : nightTotals.pos) }}
                </td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? dayTotals.receipt : nightTotals.receipt) }}
                </td>
                <td class="py-2.5 text-center ltr-nums font-bold" :class="activeShift === 'night' ? 'text-emerald-400' : 'text-ink'">
                  {{ num(activeShift === 'day' ? dayTotals.actualTotal : nightTotals.actualTotal) }}
                </td>
                <td class="py-2.5 text-center text-slate-400">—</td>
                <td class="py-2.5 text-center text-slate-400">—</td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? sumField(data?.cutting_day, 'downtime_breakdown_shifts') : sumField(data?.cutting_night, 'downtime_breakdown_shifts')) }}
                </td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? sumField(data?.cutting_day, 'downtime_sizechange_shifts') : sumField(data?.cutting_night, 'downtime_sizechange_shifts')) }}
                </td>
                <td class="py-2.5 text-center ltr-nums" :class="activeShift === 'night' ? 'text-white' : ''">
                  {{ num(activeShift === 'day' ? sumField(data?.cutting_day, 'downtime_nowork_shifts') : sumField(data?.cutting_night, 'downtime_nowork_shifts')) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        <!-- Comparison Table: Day vs Night Shift -->
        <div v-else class="overflow-x-auto">
          <table v-entry-table class="w-full text-sm min-w-[1000px]">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100 dark:border-slate-800 text-xs">
                <th class="text-right font-medium py-2.5 pr-2 whitespace-nowrap">خط تولید</th>
                <th class="text-center font-medium py-2.5 px-2 whitespace-nowrap">شاخص: روز</th>
                <th class="text-center font-medium py-2.5 px-2 whitespace-nowrap bg-slate-100/60 dark:bg-slate-800/40">شاخص: شب</th>
                <th class="text-center font-medium py-2.5 px-2 whitespace-nowrap">مجموع شاخص</th>
                <th class="text-center font-medium py-2.5 px-2 whitespace-nowrap">واقعی: روز</th>
                <th class="text-center font-medium py-2.5 px-2 whitespace-nowrap bg-slate-100/60 dark:bg-slate-800/40">واقعی: شب</th>
                <th class="text-center font-medium py-2.5 px-2 whitespace-nowrap">مجموع واقعی</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">روز: ژورنال</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">روز: پوز</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap">روز: رسید</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap bg-slate-100/60 dark:bg-slate-800/40">شب: ژورنال</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap bg-slate-100/60 dark:bg-slate-800/40">شب: پوز</th>
                <th class="text-center font-medium py-2.5 px-1.5 whitespace-nowrap bg-slate-100/60 dark:bg-slate-800/40">شب: رسید</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in comparisonRows"
                :key="row.machine_name"
                class="border-b border-slate-50 dark:border-slate-800/50 hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors"
              >
                <td class="py-2.5 pr-2 font-medium text-ink whitespace-nowrap">{{ row.machine_name }}</td>
                <!-- Index Output -->
                <td class="py-2 px-2 text-center ltr-nums text-slate-600 dark:text-slate-400">{{ num(row.day_index) }}</td>
                <td class="py-2 px-2 text-center ltr-nums text-slate-600 dark:text-slate-300 bg-slate-100/40 dark:bg-slate-800/30">{{ num(row.night_index) }}</td>
                <td class="py-2 px-2 text-center ltr-nums font-bold text-ink bg-slate-50/40 dark:bg-slate-800/50 rounded">{{ num(row.total_index) }}</td>
                <!-- Actual Output -->
                <td class="py-2 px-2 text-center ltr-nums text-slate-600 dark:text-slate-400">{{ num(row.day_actual) }}</td>
                <td class="py-2 px-2 text-center ltr-nums text-slate-600 dark:text-slate-300 bg-slate-100/40 dark:bg-slate-800/30">{{ num(row.night_actual) }}</td>
                <td class="py-2 px-2 text-center ltr-nums font-bold text-ink bg-slate-50/40 dark:bg-slate-800/50 rounded">{{ num(row.total_actual) }}</td>
                <!-- Day Breakdown -->
                <td class="py-2 px-1.5 text-center ltr-nums text-slate-500 dark:text-slate-400">{{ num(row.day_journal) }}</td>
                <td class="py-2 px-1.5 text-center ltr-nums text-slate-500 dark:text-slate-400">{{ num(row.day_pos) }}</td>
                <td class="py-2 px-1.5 text-center ltr-nums text-slate-500 dark:text-slate-400">{{ num(row.day_receipt) }}</td>
                <!-- Night Breakdown -->
                <td class="py-2 px-1.5 text-center ltr-nums text-slate-500 dark:text-slate-300 bg-slate-100/40 dark:bg-slate-800/30">{{ num(row.night_journal) }}</td>
                <td class="py-2 px-1.5 text-center ltr-nums text-slate-500 dark:text-slate-300 bg-slate-100/40 dark:bg-slate-800/30">{{ num(row.night_pos) }}</td>
                <td class="py-2 px-1.5 text-center ltr-nums text-slate-500 dark:text-slate-300 bg-slate-100/40 dark:bg-slate-800/30">{{ num(row.night_receipt) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <td class="py-3 pr-2">مجموع کارخانه</td>
                <td class="py-3 text-center ltr-nums">{{ num(dayTotals.indexOutput) }}</td>
                <td class="py-3 text-center ltr-nums bg-slate-100/40 dark:bg-slate-800/30">{{ num(nightTotals.indexOutput) }}</td>
                <td class="py-3 text-center ltr-nums font-bold text-ink bg-slate-50/60 dark:bg-slate-800/60">{{ num(combinedTotals.indexOutput) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(dayTotals.actualTotal) }}</td>
                <td class="py-3 text-center ltr-nums bg-slate-100/40 dark:bg-slate-800/30">{{ num(nightTotals.actualTotal) }}</td>
                <td class="py-3 text-center ltr-nums font-bold text-ink bg-slate-50/60 dark:bg-slate-800/60">{{ num(combinedTotals.actualTotal) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(dayTotals.journal) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(dayTotals.pos) }}</td>
                <td class="py-3 text-center ltr-nums">{{ num(dayTotals.receipt) }}</td>
                <td class="py-3 text-center ltr-nums bg-slate-100/40 dark:bg-slate-800/30">{{ num(nightTotals.journal) }}</td>
                <td class="py-3 text-center ltr-nums bg-slate-100/40 dark:bg-slate-800/30">{{ num(nightTotals.pos) }}</td>
                <td class="py-3 text-center ltr-nums bg-slate-100/40 dark:bg-slate-800/30">{{ num(nightTotals.receipt) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <!-- Section 2: Resources & Costs -->
      <section
        class="rounded-card p-5 transition-all duration-300 border shadow-soft"
        :class="activeShift === 'night'
          ? 'bg-slate-900 text-slate-100 border-slate-800 shadow-pop'
          : 'bg-surface text-ink border-slate-100'"
      >
        <div class="flex items-center gap-2 mb-4">
          <span
            class="w-7 h-7 rounded-lg text-xs flex items-center justify-center font-bold transition-colors"
            :class="activeShift === 'night' ? 'bg-indigo-600 text-white' : 'bg-panel text-white'"
          >۲</span>
          <div>
            <h3 class="font-bold transition-colors" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">منابع و هزینه‌ها</h3>
            <p class="text-xs transition-colors" :class="activeShift === 'night' ? 'text-slate-400' : 'text-slate-400'">
              ثبت هزینه‌های عملیاتی و تعداد نفرروز ({{ activeShift === 'night' ? 'شیفت شب' : 'شیفت روز' }})
            </p>
          </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
          <label class="flex items-center justify-between gap-3">
            <span class="text-sm transition-colors" :class="activeShift === 'night' ? 'text-slate-300' : 'text-slate-600'">تعداد کل نیروی انسانی (نفرروز)</span>
            <input
              v-model.number="data.benchmark.total_headcount"
              type="number"
              class="w-40 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none transition"
              :class="activeShift === 'night'
                ? 'bg-slate-800 text-white border border-slate-700 focus:border-indigo-500'
                : 'bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 text-ink'"
              @focus="selectIfZero"
            />
          </label>
          <!-- Display only visible costs (rent, production, salary excluded) -->
          <template v-for="c in visibleCosts" :key="c.category">
            <div class="space-y-1.5" :class="isOtherCost(c) ? 'md:col-span-2' : ''">
              <label class="flex items-center justify-between gap-3">
                <span class="text-sm transition-colors" :class="activeShift === 'night' ? 'text-slate-300' : 'text-slate-600'">{{ c.category_name }}</span>
                <MoneyInput
                  v-model="c.amount_rial"
                  class="w-40 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none transition"
                  :class="activeShift === 'night'
                    ? 'bg-slate-800 text-white border border-slate-700 focus:border-indigo-500'
                    : 'bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 text-ink'"
                />
              </label>
              <!-- Description input specifically for "سایر" -->
              <div
                v-if="isOtherCost(c)"
                class="flex items-center gap-2 pt-1 border-t transition-colors"
                :class="activeShift === 'night' ? 'border-slate-800' : 'border-slate-100'"
              >
                <span class="text-xs whitespace-nowrap transition-colors" :class="activeShift === 'night' ? 'text-slate-400' : 'text-slate-500'">توضیحات هزینه سایر:</span>
                <input
                  v-model="c.description"
                  type="text"
                  placeholder="علت یا شرح هزینه سایر را وارد کنید..."
                  class="flex-1 rounded-lg px-3 py-1.5 text-xs outline-none transition"
                  :class="activeShift === 'night'
                    ? 'bg-slate-800 text-white border border-slate-700 focus:border-indigo-500 placeholder-slate-500'
                    : 'bg-slate-50 focus:bg-surface border border-slate-200 focus:border-accent-500 text-ink'"
                />
              </div>
            </div>
          </template>
        </div>
        <div
          class="mt-4 pt-3 border-t flex justify-between text-sm transition-colors"
          :class="activeShift === 'night' ? 'border-slate-800 text-slate-400' : 'border-slate-100 text-slate-500'"
        >
          <span>جمع کل هزینه</span>
          <span class="font-bold ltr-nums transition-colors" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">{{ num(totalCost) }} ریال</span>
        </div>
      </section>

      <!-- Tables 3 & 4: Print by color & Roll Counts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Table 3: print by colour -->
        <section
          class="rounded-card p-5 transition-all duration-300 border shadow-soft"
          :class="activeShift === 'night'
            ? 'bg-slate-900 text-slate-100 border-slate-800 shadow-pop'
            : 'bg-surface text-ink border-slate-100'"
        >
          <div class="flex items-center gap-2 mb-4">
            <span
              class="w-7 h-7 rounded-lg text-xs flex items-center justify-center font-bold transition-colors"
              :class="activeShift === 'night' ? 'bg-indigo-600 text-white' : 'bg-panel text-white'"
            >۳</span>
            <div>
              <h3 class="font-bold transition-colors" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">چاپ (متراژ به تفکیک رنگ)</h3>
              <p class="text-xs transition-colors" :class="activeShift === 'night' ? 'text-slate-400' : 'text-slate-400'">
                ثبت متراژ چاپ و شیفت دستگاه چاپ ({{ activeShift === 'night' ? 'شیفت شب' : 'شیفت روز' }})
              </p>
            </div>
          </div>
          <div class="space-y-2">
            <label v-for="c in data.print_colors" :key="c.color_count" class="flex items-center justify-between gap-3">
              <span class="text-sm transition-colors" :class="activeShift === 'night' ? 'text-slate-300' : 'text-slate-600'">
                {{ COLOR_FA[c.color_count] }} (متر مربع)
              </span>
              <input
                v-model="c.area_sqm"
                type="number" step="any"
                class="w-40 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none transition"
                :class="activeShift === 'night'
                  ? 'bg-slate-800 text-white border border-slate-700 focus:border-indigo-500'
                  : 'bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 text-ink'"
                @focus="selectIfZero"
              />
            </label>
            <label v-if="currentPrint" class="flex items-center justify-between gap-3 pt-1">
              <span class="text-sm transition-colors" :class="activeShift === 'night' ? 'text-slate-300' : 'text-slate-600'">
                تعداد شیفت چاپ ({{ activeShift === 'night' ? 'شیفت شب' : 'شیفت روز' }})
              </span>
              <input
                v-model="currentPrint.active_shifts"
                type="number" step="any"
                class="w-40 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none transition"
                :class="activeShift === 'night'
                  ? 'bg-slate-800 text-white border border-slate-700 focus:border-indigo-500'
                  : 'bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 text-ink'"
                @focus="selectIfZero"
              />
            </label>
          </div>
          <div
            class="mt-3 pt-3 border-t flex justify-between text-sm transition-colors"
            :class="activeShift === 'night' ? 'border-slate-800 text-slate-400' : 'border-slate-100 text-slate-500'"
          >
            <span>مجموع متراژ چاپ</span>
            <span class="font-bold ltr-nums transition-colors" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">{{ num(printTotal) }} م²</span>
          </div>
        </section>

        <!-- Table 4: roll counts -->
        <section
          class="rounded-card p-5 transition-all duration-300 border shadow-soft"
          :class="activeShift === 'night'
            ? 'bg-slate-900 text-slate-100 border-slate-800 shadow-pop'
            : 'bg-surface text-ink border-slate-100'"
        >
          <div class="flex items-center gap-2 mb-4">
            <span
              class="w-7 h-7 rounded-lg text-xs flex items-center justify-center font-bold transition-colors"
              :class="activeShift === 'night' ? 'bg-indigo-600 text-white' : 'bg-panel text-white'"
            >۴</span>
            <div>
              <h3 class="font-bold transition-colors" :class="activeShift === 'night' ? 'text-white' : 'text-ink'">تعداد رول‌ها</h3>
              <p class="text-xs transition-colors" :class="activeShift === 'night' ? 'text-slate-400' : 'text-slate-400'">
                ثبت تعداد رول‌های تولیدی ({{ activeShift === 'night' ? 'شیفت شب' : 'شیفت روز' }})
              </p>
            </div>
          </div>
          <div class="space-y-2">
            <label v-for="r in data.rolls" :key="r.product" class="flex items-center justify-between gap-3">
              <span class="text-sm transition-colors" :class="activeShift === 'night' ? 'text-slate-300' : 'text-slate-600'">
                {{ r.product_name }}
                <span class="text-xs ltr-nums" :class="activeShift === 'night' ? 'text-slate-500' : 'text-slate-400'">(اجرت {{ num(r.piece_rate_rial) }})</span>
              </span>
              <input
                v-model="r.quantity"
                type="number" step="any"
                class="w-32 rounded-lg px-3 py-1.5 text-left ltr-nums outline-none transition"
                :class="activeShift === 'night'
                  ? 'bg-slate-800 text-white border border-slate-700 focus:border-indigo-500'
                  : 'bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 text-ink'"
                @focus="selectIfZero"
              />
            </label>
          </div>
          <div
            class="mt-3 pt-3 border-t flex justify-between text-sm transition-colors"
            :class="activeShift === 'night' ? 'border-slate-800 text-slate-400' : 'border-slate-100 text-slate-500'"
          >
            <span>درآمد اجرت (برآورد)</span>
            <span class="font-bold ltr-nums transition-colors" :class="activeShift === 'night' ? 'text-emerald-400' : 'text-accent-600'">{{ num(revenueTotal) }} ریال</span>
          </div>
        </section>
      </div>

      <!-- Sticky action bar -->
      <div
        class="sticky bottom-4 z-30 rounded-card shadow-pop p-3 flex items-center justify-between transition-colors border"
        :class="activeShift === 'night' ? 'bg-slate-900 border-slate-800 text-white' : 'bg-panel border-transparent text-white'"
      >
        <span class="text-sm px-2 text-white/80">{{ submitHint() }}</span>
        <div class="flex gap-2">
          <button class="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-sm transition" @click="save(false)">
            ذخیره پیش‌نویس
          </button>
          <button class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium transition" @click="save(true)">
            ذخیره و ارسال برای تایید
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
