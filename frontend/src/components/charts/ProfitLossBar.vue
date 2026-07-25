<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { AXIS, COLORS, TOOLTIP, barGradient, compact } from "./theme";
import { rial } from "@/utils/format";

// سود و زیان — درآمد (green) vs هزینه (rose) as horizontal bars.
const props = defineProps<{ revenue: number; cost: number }>();

const el = ref<HTMLElement | null>(null);
const option = computed<EChartsOption>(() => ({
  grid: { top: 28, right: 24, bottom: 16, left: 66 },
  tooltip: { ...TOOLTIP, trigger: "axis", valueFormatter: (v) => rial(Number(v)) },
  legend: { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#64748b" } },
  xAxis: { ...AXIS.value, axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) } },
  yAxis: { ...AXIS.category, data: [""], axisLabel: { show: false } },
  series: [
    { name: "درآمد", type: "bar", data: [props.revenue], barWidth: 20,
      itemStyle: { color: barGradient(COLORS.target), borderRadius: [0, 6, 6, 0] } },
    { name: "هزینه", type: "bar", data: [props.cost], barWidth: 20,
      itemStyle: { color: barGradient(COLORS.rose), borderRadius: [0, 6, 6, 0] } },
  ],
}));
useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">سود و زیان (درآمد در برابر هزینه)</h3>
    <div ref="el" style="height: 150px"></div>
  </div>
</template>
