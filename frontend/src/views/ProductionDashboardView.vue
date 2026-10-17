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
const machineOutput = computed(() => cutting.value.map((m) => m.output_units));
const machineAvg = computed(() =>
  cutting.value.map((m) => (m.active_shifts ? Math.round(m.output_units / m.active_shifts) : 0)),
);
const days = computed(() => data.value?.days_in_month ?? 30);
const activeShifts = computed(() => cutting.value.map((m) => m.active_shifts));
const inactiveShifts = computed(() => cutting.value.map((m) => Math.max(0, days.value - m.active_shifts)));

// Production Index vs Actual Totals
const totalIndexOutput = computed(() =>
  cutting.value.reduce((s, m) => s + (Number(m.output_units) || 0), 0),
);
const totalJournal = computed(() =>
  cutting.value.reduce((s, m) => s + (Number(m.actual_journal) || 0), 0),
);
const totalPos = computed(() =>
  cutting.value.reduce((s, m) => s + (Number(m.actual_pos) || 0), 0),
);
const totalReceipt = computed(() =>
  cutting.value.reduce((s, m) => s + (Number(m.actual_receipt) || 0), 0),
);
const totalActualOutput = computed(() =>
  totalJournal.value + totalPos.value + totalReceipt.value,
);

// Shifts breakdown
const dayShiftData = computed(() =>
  data.value?.shifts_data?.find((s) => s.shift === "day"),
);
const nightShiftData = computed(() =>
  data.value?.shifts_data?.find((s) => s.shift === "night"),
);

const dayOutput = computed(() => Number(dayShiftData.value?.output_units || 0));
const nightOutput = computed(() => Number(nightShiftData.value?.output_units || 0));

// Per-machine Day vs Night output
const machineDayOutput = computed(() => {
  const byMachine = data.value?.shifts_by_machine ?? [];
  return cutting.value.map((m) => {
    const found = byMachine.find(
      (b) => b.machine__name_fa === m.machine__name_fa && b.shift === "day",
    );
    return Number(found?.output_units || 0);
  });
});

const machineNightOutput = computed(() => {
  const byMachine = data.value?.shifts_by_machine ?? [];
  return cutting.value.map((m) => {
    const found = byMachine.find(
      (b) => b.machine__name_fa === m.machine__name_fa && b.shift === "night",
    );
    return Number(found?.output_units || 0);
  });
});

// Per-machine actual sub-branches
const machineJournal = computed(() => cutting.value.map((m) => Number(m.actual_journal || 0)));
const machinePos = computed(() => cutting.value.map((m) => Number(m.actual_pos || 0)));
const machineReceipt = computed(() => cutting.value.map((m) => Number(m.actual_receipt || 0)));

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
      <!-- Production & Shift Summary Cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="bg-surface rounded-card shadow-soft p-4 border border-slate-100">
          <div class="text-sm text-slate-500 mb-1">تولید (شاخص) کل</div>
          <div class="text-2xl font-bold ltr-nums text-ink">{{ num(totalIndexOutput) }}</div>
          <div class="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>شیفت روز: <strong class="text-ink font-semibold ltr-nums">{{ num(dayOutput) }}</strong></span>
            <span>شیفت شب: <strong class="text-ink font-semibold ltr-nums">{{ num(nightOutput) }}</strong></span>
          </div>
        </div>

        <div class="bg-surface rounded-card shadow-soft p-4 border border-slate-100">
          <div class="text-sm text-slate-500 mb-1">تولید واقعی کل</div>
          <div class="text-2xl font-bold ltr-nums text-ink">{{ num(totalActualOutput) }}</div>
          <div class="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>ژورنال: <strong class="text-ink font-semibold ltr-nums">{{ num(totalJournal) }}</strong></span>
            <span>پوز: <strong class="text-ink font-semibold ltr-nums">{{ num(totalPos) }}</strong></span>
            <span>رسید: <strong class="text-ink font-semibold ltr-nums">{{ num(totalReceipt) }}</strong></span>
          </div>
        </div>

        <div class="bg-surface rounded-card shadow-soft p-4 border border-slate-100">
          <div class="text-sm text-slate-500 mb-1">درآمد اجرت</div>
          <div class="text-2xl font-bold ltr-nums text-accent-600">{{ rial(data.financials.revenue) }}</div>
          <div class="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
            هزینه کل: <strong class="text-ink font-semibold ltr-nums">{{ rial(data.financials.cost) }}</strong>
          </div>
        </div>

        <div class="bg-surface rounded-card shadow-soft p-4 border border-slate-100">
          <div class="text-sm text-slate-500 mb-1">کارکرد خالص (سود تولید)</div>
          <div class="text-2xl font-bold ltr-nums" :class="data.financials.net >= 0 ? 'text-accent-600' : 'text-red-600'">
            {{ rial(data.financials.net) }}
          </div>
          <div class="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
            درصد بهره‌وری: <strong class="text-ink font-semibold ltr-nums">{{ Number(kpi('prod_productivity')?.efficiency_pct || 0).toFixed(1) }}٪</strong>
          </div>
        </div>
      </div>

      <!-- Note for "سایر" cost if filled -->
      <div
        v-if="data.other_cost_note?.description"
        class="bg-surface rounded-card shadow-soft p-4 border border-slate-100 flex items-start gap-3 transition-all"
      >
        <div class="w-8 h-8 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center shrink-0 mt-0.5">
          <svg class="w-4 h-4 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
            <h4 class="text-sm font-bold text-ink">توضیحات هزینه سایر</h4>
            <span v-if="data.other_cost_note.amount_rial" class="text-xs text-slate-500 font-medium">
              مبلغ: <strong class="text-ink ltr-nums">{{ rial(data.other_cost_note.amount_rial) }}</strong>
            </span>
          </div>
          <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
            {{ data.other_cost_note.description }}
          </p>
        </div>
      </div>

      <!-- Row 1: Shift Comparison & Actual Production Breakdown Charts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ShiftComparisonBar
          title="مقایسه تولید شیفت روز و شب (بر اساس خطوط برش)"
          :categories="machineNames"
          :dayValues="machineDayOutput"
          :nightValues="machineNightOutput"
        />
        <ActualProductionBar
          title="تفکیک تولید واقعی به زیرشاخه‌ها (ژورنال / پوز / رسید)"
          :categories="machineNames"
          :journal="machineJournal"
          :pos="machinePos"
          :receipt="machineReceipt"
        />
      </div>

      <!-- Row 2: productivity, labour, efficiency donut, production per machine -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <ComparisonBar title="بهره‌وری تولید"
          :actual="n(kpi('prod_productivity')?.actual)" :target="n(kpi('prod_productivity')?.target)" :ideal="n(kpi('prod_productivity')?.ideal)" />
        <ComparisonBar title="بهره‌وری نیروی انسانی"
          :actual="n(kpi('labor_productivity')?.actual)" :target="n(kpi('labor_productivity')?.target)" :ideal="n(kpi('labor_productivity')?.ideal)" />
        <DonutChart title="درصد بهره‌وری" :value="n(kpi('prod_productivity')?.efficiency_pct)" />
        <BarChart title="تولید (شاخص) بر اساس خط" :categories="machineNames" :values="machineOutput" color="#3b6fed" />
      </div>

      <!-- Row 3: avg per shift, waste, machine utilization, cost per roll -->
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <BarChart title="میانگین تولید در شیفت" :categories="machineNames" :values="machineAvg" color="#8b7cf6" />
        <ComparisonBar title="نرخ ضایعات"
          :actual="n(kpi('waste_rate')?.actual)" :target="n(kpi('waste_rate')?.target)" :ideal="n(kpi('waste_rate')?.ideal)" />
        <StackedMachineBar title="عملکرد دستگاه‌ها" :categories="machineNames" :active="activeShifts" :inactive="inactiveShifts" />
        <ComparisonBar title="هزینه تولید به ازای هر رول"
          :actual="n(kpi('cost_per_roll')?.actual)" :target="n(kpi('cost_per_roll')?.target)" :ideal="n(kpi('cost_per_roll')?.ideal)" />
      </div>

      <!-- Profit / loss -->
      <ProfitLossBar :revenue="data.financials.revenue" :cost="data.financials.cost" />

      <!-- The KPI comparison table -->
      <div class="bg-surface rounded-card shadow-soft p-5 overflow-x-auto border border-slate-100">
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
