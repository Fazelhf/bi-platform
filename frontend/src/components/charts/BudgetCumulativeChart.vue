<script setup lang="ts">
/**
 * مانده تجمعی — how much cash the plan expected the company to be sitting on,
 * beside how much it actually is.
 *
 * A month's surplus says which way cash moved, not where it stands; this is
 * where it stands.
 * The actual line stops at the last month with any recorded movement — a flat
 * line running into months that have not happened yet would read as «on
 * plan», which is the opposite of what it means.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, COLORS, TOOLTIP, compact, mutedColor } from "./theme";

const props = withDefaults(defineProps<{
  title: string;
  labels: string[];
  budget: number[];
  actual: (number | null)[];
  height?: number;
}>(), { height: 280 });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  return {
    grid: { top: 36, right: 16, bottom: 40, left: 56 },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      valueFormatter: (v) => (v === null || v === undefined ? "—" : compact(Number(v))),
    },
    legend: {
      top: 0,
      itemWidth: 14,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: mutedColor() },
    },
    xAxis: { ...AXIS.category, data: props.labels, boundaryGap: false },
    yAxis: {
      ...AXIS.value,
      axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
    },
    series: [
      {
        name: "بودجه",
        type: "line",
        data: props.budget,
        symbol: "circle",
        symbolSize: 6,
        lineStyle: { type: "dashed", width: 2, color: COLORS.ideal },
        itemStyle: { color: COLORS.ideal },
      },
      {
        name: "واقعی",
        type: "line",
        data: props.actual,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { width: 3, color: COLORS.actual },
        itemStyle: { color: COLORS.actual },
        areaStyle: { color: COLORS.actual, opacity: 0.08 },
      },
    ],
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <div ref="el" :style="{ height: height + 'px' }"></div>
  </div>
</template>
