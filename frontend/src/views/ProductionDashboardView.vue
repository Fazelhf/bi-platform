<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { salesApi } from "@/api/sales";
import { productionApi } from "@/api/production";
import { defaultPeriodId } from "@/types";
import type { KpiResult, Period, ProductionDashboard } from "@/types";
import ComparisonBar from "@/components/charts/ComparisonBar.vue";
import DonutChart from "@/components/charts/DonutChart.vue";
import StackedMachineBar from "@/components/charts/StackedMachineBar.vue";
import ShiftComparisonBar from "@/components/charts/ShiftComparisonBar.vue";
import ActualProductionBar from "@/components/charts/ActualProductionBar.vue";
import ProfitLossBar from "@/components/charts/ProfitLossBar.vue";
import BarChart from "@/components/BarChart.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import ExportActions from "@/components/ExportActions.vue";
import { kpiValue, num, rial } from "@/utils/format";
import SectionBoard from "@/components/boards/SectionBoard.vue";

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const data = ref<ProductionDashboard | null>(null);
const loading = ref(false);

function kpi(code: string): KpiResult | undefined {
  return data.value?.kpis.find((k) => k.kpi_code === code);
}
const n = (v: string | number | null | undefined) => (v == null ? null : Number(v));

// Per-machine (cutting lines only) for the machine charts.
const cutting = computed(() => (data.value?.machines ?? []).filter((m) => m.machine__kind === "cutting"));
const machineNames = computed(() => cutting.value.map((m) => m.machine__name_fa));
const machineAvg = computed(() =>
  cutting.value.map((m) => (m.active_shifts ? Math.round(m.output_units / m.active_shifts) : 0)),
);
const days = computed(() => data.value?.days_in_month ?? 30);

// Day and night, from the server's per-shift summary.
type ShiftKey = "index_output" | "journal" | "pos" | "receipt" | "actual_total" | "active_shifts"
  | "downtime" | "print_area" | "cost" | "revenue" | "headcount";
const EMPTY: Record<ShiftKey, number> = { index_output: 0, journal: 0, pos: 0, receipt: 0, actual_total: 0,
  active_shifts: 0, downtime: 0, print_area: 0, cost: 0, revenue: 0, headcount: 0 };
const shiftOf = (s: "day" | "night") =>
  computed<Record<ShiftKey, number>>(() => data.value?.shift_summary?.find((r) => r.shift === s) ?? EMPTY);
const day = shiftOf("day");
const night = shiftOf("night");
const total = (k: ShiftKey) => Number(day.value[k]) + Number(night.value[k]);

/** A line has as many shifts a month as there are shifts with figures in it. */
const shiftsRun = computed(() => (night.value.active_shifts > 0 ? 2 : 1));
const activeShifts = computed(() => cutting.value.map((m) => m.active_shifts));
const inactiveShifts = computed(() =>
  cutting.value.map((m) => Math.max(0, days.value * shiftsRun.value - m.active_shifts)),
);

// The comparison table: every section of the input form, day against night.
const SHIFT_ROWS: { key: ShiftKey; label: string; rial?: boolean }[] = [
  { key: "index_output", label: "تولید (شاخص)" },
  { key: "actual_total", label: "تولید واقعی" },
  { key: "active_shifts", label: "شیفت فعال خطوط برش" },
  { key: "downtime", label: "خواب خطوط (شیفت)" },
  { key: "print_area", label: "متراژ چاپ (م²)" },
  { key: "headcount", label: "نیروی انسانی (نفرروز)" },
  { key: "cost", label: "هزینه‌ها", rial: true },
  { key: "revenue", label: "درآمد اجرت", rial: true },
];
const nightShare = (k: ShiftKey) => {
  const t = total(k);
  return t ? (100 * Number(night.value[k])) / t : 0;
};
const fmt = (v: number, isRial?: boolean) => (isRial ? rial(v) : num(v));

// Per line: day vs night actual output, and its three branches.
const byMachine = computed(() => {
  const map = new Map<string, number>();
  for (const b of data.value?.shifts_by_machine ?? []) {
    map.set(`${b.machine__name_fa}|${b.shift}`,
      Number(b.actual_journal) + Number(b.actual_pos) + Number(b.actual_receipt));
  }
  return map;
});
const machineActual = (s: "day" | "night") =>
  computed(() => machineNames.value.map((name) => byMachine.value.get(`${name}|${s}`) ?? 0));
const machineDayActual = machineActual("day");
const machineNightActual = machineActual("night");
const machineJournal = computed(() => cutting.value.map((m) => Number(m.actual_journal || 0)));
const machinePos = computed(() => cutting.value.map((m) => Number(m.actual_pos || 0)));
const machineReceipt = computed(() => cutting.value.map((m) => Number(m.actual_receipt || 0)));
const efficiency = computed(() => {
  const v = kpi("prod_productivity")?.efficiency_pct;
  return v == null ? "—" : Number(v).toFixed(1) + "٪";
});

// The 7-row KPI comparison table
const KPI_ORDER = [
  "prod_productivity", "waste_rate", "line_stoppage_rate", "labor_productivity",
  "defect_free_rate", "cost_per_roll", "financial_return",
];
const kpiRows = computed(() =>
  KPI_ORDER.map((c) => kpi(c)).filter((k): k is KpiResult => !!k),
);

let latest = 0;

async function load() {
  if (!selectedPeriod.value) return;
  const mine = ++latest;
  loading.value = true;
  try {
    const result = await productionApi.dashboard(selectedPeriod.value);
    if (mine === latest) data.value = result;
  } finally {
    if (mine === latest) loading.value = false;
  }
}
onMounted(async () => {
  periods.value = await salesApi.periods();
  // Setting the period *is* the load: the watcher below fires on it.
  selectedPeriod.value = defaultPeriodId(periods.value);
});
watch(selectedPeriod, load);

function fmtCell(v: string | null, unit: string) {
  return v == null ? "—" : kpiValue(v, unit);
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold text-ink">داشبورد مدیریتی تولید</h2>
      <div class="flex items-center gap-2">
        <ExportActions section="production" :period="selectedPeriod" />
        <select v-model.number="selectedPeriod" class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition">
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <DashboardSkeleton v-if="loading || !data" :cards="3" :charts="4" />

    <template v-else>
      <!-- Headline figures -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400 mb-1">تولید (شاخص)</div>
          <div class="text-2xl font-bold ltr-nums text-ink">{{ num(total('index_output')) }}</div>
          <div class="mt-2 pt-2 border-t border-slate-100 flex justify-between gap-2 text-xs text-slate-500">
            <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span>روز <b class="text-ink ltr-nums">{{ num(day.index_output) }}</b></span>
            <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>شب <b class="text-ink ltr-nums">{{ num(night.index_output) }}</b></span>
          </div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400 mb-1">تولید واقعی</div>
          <div class="text-2xl font-bold ltr-nums text-ink">{{ num(total('actual_total')) }}</div>
          <div class="mt-2 pt-2 border-t border-slate-100 flex justify-between gap-2 text-xs text-slate-500">
            <span>ژورنال <b class="text-ink ltr-nums">{{ num(total('journal')) }}</b></span>
            <span>پوز <b class="text-ink ltr-nums">{{ num(total('pos')) }}</b></span>
            <span>رسید <b class="text-ink ltr-nums">{{ num(total('receipt')) }}</b></span>
          </div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400 mb-1">درآمد اجرت</div>
          <div class="text-2xl font-bold ltr-nums text-accent-600">{{ rial(data.financials.revenue) }}</div>
          <div class="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
            هزینه <b class="text-ink ltr-nums">{{ rial(data.financials.cost) }}</b>
          </div>
        </div>
        <div class="bg-surface rounded-card shadow-soft p-4">
          <div class="text-xs text-slate-400 mb-1">کارکرد خالص (سود تولید)</div>
          <div class="text-2xl font-bold ltr-nums" :class="data.financials.net >= 0 ? 'text-accent-600' : 'text-red-600'">
            {{ rial(data.financials.net) }}
          </div>
          <div class="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
            درصد بهره‌وری <b class="text-ink ltr-nums">{{ efficiency }}</b>
          </div>
        </div>
      </div>

      <!-- Day against night: every section of the input form, then line by line -->
      <div class="grid grid-cols-1 xl:grid-cols-5 gap-4">
        <div class="xl:col-span-3 bg-surface rounded-card shadow-soft p-5 overflow-x-auto">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-ink">شیفت روز در برابر شیفت شب</h3>
            <div class="flex items-center gap-3 text-xs text-slate-400">
              <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-500"></span>روز</span>
              <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-indigo-500"></span>شب</span>
            </div>
          </div>
          <table class="w-full text-sm min-w-[520px]">
            <thead>
              <tr class="text-slate-400 border-b border-slate-100 text-xs">
                <th class="text-right font-medium py-2"></th>
                <th class="font-medium py-2 px-2 text-center">روز</th>
                <th class="font-medium py-2 px-2 text-center">شب</th>
                <th class="font-medium py-2 px-2 text-center">جمع</th>
                <th class="font-medium py-2 px-2 text-right w-1/4">سهم شب</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in SHIFT_ROWS" :key="r.key" class="border-b border-slate-50">
                <td class="py-2 font-medium text-ink whitespace-nowrap">{{ r.label }}</td>
                <td class="py-2 px-2 text-center ltr-nums text-slate-600">{{ fmt(day[r.key], r.rial) }}</td>
                <td class="py-2 px-2 text-center ltr-nums text-slate-600">{{ fmt(night[r.key], r.rial) }}</td>
                <td class="py-2 px-2 text-center ltr-nums font-bold text-ink">{{ fmt(total(r.key), r.rial) }}</td>
                <td class="py-2 px-2">
                  <div class="flex items-center gap-2">
                    <div class="flex-1 h-1.5 rounded-full bg-amber-500/70 overflow-hidden">
                      <div class="h-full bg-indigo-500 rounded-full" :style="{ width: nightShare(r.key) + '%' }"></div>
                    </div>
                    <span class="text-[11px] text-slate-400 ltr-nums w-8 text-left">{{ total(r.key) ? Math.round(nightShare(r.key)) + '٪' : '—' }}</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="xl:col-span-2">
          <ShiftComparisonBar
            title="تولید واقعی هر خط — روز و شب"
            :categories="machineNames"
            :dayValues="machineDayActual"
            :nightValues="machineNightActual"
          />
        </div>
      </div>

      <!-- «سایر» costs, as each shift explained them -->
      <div v-if="data.other_cost_notes?.length" class="bg-surface rounded-card shadow-soft p-4">
        <h4 class="text-sm font-bold text-ink mb-2">شرح هزینه‌های سایر</h4>
        <ul class="space-y-1.5">
          <li v-for="(note, i) in data.other_cost_notes" :key="i" class="flex items-start justify-between gap-3 text-xs">
            <span class="text-slate-600 leading-relaxed">
              <span class="inline-flex items-center gap-1 ml-1.5 font-medium text-slate-500">
                <span class="w-1.5 h-1.5 rounded-full" :class="note.shift === 'night' ? 'bg-indigo-500' : 'bg-amber-500'"></span>{{ note.shift_label }}:
              </span>{{ note.description }}
            </span>
            <b class="text-ink ltr-nums whitespace-nowrap">{{ rial(note.amount_rial) }}</b>
          </li>
        </ul>
      </div>

      <!-- Actual output by line, and productivity -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div class="md:col-span-2">
          <ActualProductionBar
            title="تولید واقعی هر خط (ژورنال / پوز / رسید)"
            :categories="machineNames"
            :journal="machineJournal"
            :pos="machinePos"
            :receipt="machineReceipt"
          />
        </div>
        <ComparisonBar title="بهره‌وری تولید"
          :actual="n(kpi('prod_productivity')?.actual)" :target="n(kpi('prod_productivity')?.target)" :ideal="n(kpi('prod_productivity')?.ideal)" />
        <DonutChart title="درصد بهره‌وری" :value="n(kpi('prod_productivity')?.efficiency_pct)" />
      </div>

      <!-- Labour, average per shift, waste, machine utilisation -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <ComparisonBar title="بهره‌وری نیروی انسانی"
          :actual="n(kpi('labor_productivity')?.actual)" :target="n(kpi('labor_productivity')?.target)" :ideal="n(kpi('labor_productivity')?.ideal)" />
        <BarChart title="میانگین تولید هر شیفت" :categories="machineNames" :values="machineAvg" color="#8b7cf6" />
        <ComparisonBar title="نرخ ضایعات"
          :actual="n(kpi('waste_rate')?.actual)" :target="n(kpi('waste_rate')?.target)" :ideal="n(kpi('waste_rate')?.ideal)" />
        <StackedMachineBar title="عملکرد دستگاه‌ها (فعال / خواب)" :categories="machineNames" :active="activeShifts" :inactive="inactiveShifts" />
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ComparisonBar title="هزینه تولید به ازای هر رول"
          :actual="n(kpi('cost_per_roll')?.actual)" :target="n(kpi('cost_per_roll')?.target)" :ideal="n(kpi('cost_per_roll')?.ideal)" />
        <div class="lg:col-span-2">
          <ProfitLossBar :revenue="data.financials.revenue" :cost="data.financials.cost" />
        </div>
      </div>

      <!-- The KPI comparison table -->
      <div class="bg-surface rounded-card shadow-soft p-5 overflow-x-auto">
        <h3 class="font-bold text-ink mb-3">جدول شاخص‌های تولید</h3>
        <table class="w-full text-sm min-w-[640px]">
          <thead>
            <tr class="text-slate-400 border-b border-slate-100">
              <th class="text-right font-medium py-2">شاخص</th>
              <th class="text-center font-medium py-2">واقعی</th>
              <th class="text-center font-medium py-2">مطلوب</th>
              <th class="text-center font-medium py-2">ایده‌آل</th>
              <th class="text-center font-medium py-2">انحراف</th>
              <th class="text-center font-medium py-2">درصد بهره‌وری</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in kpiRows" :key="k.id" class="border-b border-slate-50 hover:bg-slate-50/60 transition-colors">
              <td class="py-2.5 font-medium">{{ k.kpi_name_fa }}</td>
              <td class="py-2.5 text-center ltr-nums bg-blue-50/50">{{ fmtCell(k.actual, k.unit) }}</td>
              <td class="py-2.5 text-center ltr-nums">{{ fmtCell(k.target, k.unit) }}</td>
              <td class="py-2.5 text-center ltr-nums">{{ fmtCell(k.ideal, k.unit) }}</td>
              <td class="py-2.5 text-center ltr-nums text-slate-500">{{ k.deviation == null ? "—" : num(k.deviation) }}</td>
              <td class="py-2.5 text-center ltr-nums font-semibold"
                :class="k.efficiency_pct == null ? 'text-slate-300' : (Number(k.efficiency_pct) >= 90 ? 'text-green-600' : Number(k.efficiency_pct) >= 60 ? 'text-amber-600' : 'text-red-600')">
                {{ k.efficiency_pct == null ? "—" : Number(k.efficiency_pct).toFixed(1) + "٪" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <!-- گزارش این بخش، روی همین صفحه -->
    <SectionBoard section="production" :period="selectedPeriod" />
  </div>
</template>
