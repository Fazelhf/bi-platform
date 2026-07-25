<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { AXIS, COLORS, TOOLTIP, barGradient } from "./theme";

// عملکرد دستگاه‌ها — active (green) vs inactive (neutral) shifts, stacked.
const props = defineProps<{
  title: string;
  categories: string[];
  active: number[];
  inactive: number[];
}>();

const el = ref<HTMLElement | null>(null);
const option = computed<EChartsOption>(() => ({
  grid: { top: 34, right: 14, bottom: 24, left: 30 },
  tooltip: { ...TOOLTIP, trigger: "axis" },
  legend: { top: 2, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#64748b" } },
  xAxis: { ...AXIS.category, data: props.categories },
  yAxis: AXIS.value,
  series: [
    { name: "شیفت فعال", type: "bar", stack: "s", data: props.active, barWidth: "52%",
      itemStyle: { color: barGradient(COLORS.target), borderRadius: [0, 0, 4, 4] } },
    { name: "شیفت غیرفعال", type: "bar", stack: "s", data: props.inactive,
      itemStyle: { color: COLORS.slate, borderRadius: [4, 4, 0, 0] } },
  ],
}));
useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <div ref="el" style="height: 210px"></div>
  </div>
</template>
