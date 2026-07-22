<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { rial } from "@/utils/format";

// سود و زیان — درآمد vs هزینه as horizontal bars on one axis.
const props = defineProps<{ revenue: number; cost: number }>();

const el = ref<HTMLElement | null>(null);
const option = computed<EChartsOption>(() => ({
  grid: { top: 30, right: 20, bottom: 20, left: 70 },
  tooltip: { trigger: "axis", valueFormatter: (v) => rial(Number(v)) },
  legend: { top: 0, textStyle: { fontSize: 11 } },
  xAxis: { type: "value", axisLabel: { formatter: (v: number) => rial(v), fontSize: 9 } },
  yAxis: { type: "category", data: [""], axisLabel: { show: false } },
  series: [
    { name: "درآمد", type: "bar", data: [props.revenue],
      itemStyle: { color: "#34d399", borderRadius: 4 }, barWidth: 22 },
    { name: "هزینه", type: "bar", data: [props.cost],
      itemStyle: { color: "#f472b6", borderRadius: 4 }, barWidth: 22 },
  ],
}));
useChart(el, option);
</script>

<template>
  <div class="bg-white rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">سود و زیان (درآمد در برابر هزینه)</h3>
    <div ref="el" style="height: 160px"></div>
  </div>
</template>
