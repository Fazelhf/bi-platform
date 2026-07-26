<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import {
  AXIS, TOOLTIP, barGradient, barRadius, compact, labelColor, mutedColor,
  seriesColor, surfaceColor,
} from "./theme";

/**
 * One chart for the workbook's chart sheets: 1..n series over shared
 * categories, as bars or a pie. Styling follows the CEO's chosen theme.
 */
const props = withDefaults(defineProps<{
  title: string;
  categories: string[];
  series: { name: string; values: (number | null)[] }[];
  kind?: "bar" | "pie";
  height?: number;
  percent?: boolean;
}>(), { kind: "bar", height: 240, percent: false });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

const option = computed<EChartsOption>(() => {
  // Re-read the theme so switching it re-renders every chart.
  void ui.chartTheme;
  const fmt = (v: number) => (props.percent ? `${Math.round(v * 10) / 10}٪` : compact(v));

  if (props.kind === "pie") {
    // Slices worth nothing still drew a label ("پارسا مروتی ۰٪") that collided
    // with its neighbours, and the names were already in the legend below —
    // so the labels now carry only the value and the legend names them.
    const slices = props.categories
      .map((name, i) => ({ name, value: Number(props.series[0]?.values[i] ?? 0), i }))
      .filter((s) => s.value > 0);

    return {
      tooltip: { ...TOOLTIP, trigger: "item", formatter: (p: any) => `${p.name}: ${fmt(p.value)}` },
      legend: {
        type: "scroll",
        bottom: 0,
        itemWidth: 9,
        itemHeight: 9,
        textStyle: { fontSize: 10, color: mutedColor() },
        pageTextStyle: { color: mutedColor() },
      },
      series: [{
        type: "pie",
        radius: ["45%", "68%"],
        center: ["50%", "42%"],
        minAngle: 4,             // a 1% slice stays clickable
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          // Match the card, not white — otherwise dark mode gets bright seams.
          borderColor: surfaceColor(),
          borderWidth: 2,
        },
        label: { fontSize: 10, color: labelColor(), formatter: (p: any) => fmt(p.value) },
        labelLine: { length: 6, length2: 6, lineStyle: { color: mutedColor() } },
        data: slices.map((s) => ({
          name: s.name, value: s.value,
          itemStyle: { color: seriesColor(s.i) },
        })),
      }],
    };
  }

  const multi = props.series.length > 1;
  return {
    grid: { top: multi ? 34 : 26, right: 14, bottom: 46, left: 46 },
    tooltip: { ...TOOLTIP, trigger: "axis",
      valueFormatter: (v) => fmt(Number(v)) },
    legend: multi
      ? { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: mutedColor() } }
      : undefined,
    xAxis: { ...AXIS.category, data: props.categories,
      axisLabel: { ...AXIS.category.axisLabel, rotate: 38, fontSize: 10 } },
    yAxis: { ...AXIS.value, axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => fmt(v) } },
    series: props.series.map((s, i) => ({
      name: s.name,
      type: "bar" as const,
      data: s.values,
      barMaxWidth: 30,
      itemStyle: {
        color: barGradient(seriesColor(i)),
        borderRadius: [barRadius(), barRadius(), 0, 0],
      },
    })),
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
