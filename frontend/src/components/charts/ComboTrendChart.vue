<script setup lang="ts">
/**
 * Bars and lines on one time axis — flows as bars, the thing they add up to
 * (a balance, a plan, a net) as lines.
 *
 * Colours come from a `tone`, not a hex value, so every page draws money in
 * the same green and money out in the same red, whichever palette the CEO
 * picked. A line that lives on a very different scale (a balance beside daily
 * flows) can take the right-hand axis instead of flattening the bars.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, COLORS, TOOLTIP, barRadius, compact, mutedColor, seriesColor } from "./theme";

type Tone = "in" | "out" | "budget" | "actual" | "net";

interface BarSeries { name: string; values: (number | null)[]; tone?: Tone }
interface LineSeries extends BarSeries { dashed?: boolean; area?: boolean; secondAxis?: boolean }

const props = withDefaults(defineProps<{
  title: string;
  categories: string[];
  bars?: BarSeries[];
  lines?: LineSeries[];
  height?: number;
}>(), { bars: () => [], lines: () => [], height: 280 });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

function color(tone: Tone | undefined, index: number): string {
  switch (tone) {
    case "in": return COLORS.target;
    case "out": return COLORS.rose;
    case "budget": return COLORS.slate;
    case "actual": return COLORS.actual;
    case "net": return COLORS.ideal;
    default: return seriesColor(index);
  }
}

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const twoAxes = props.lines.some((l) => l.secondAxis);
  const valueAxis = (position: "left" | "right") => ({
    ...AXIS.value,
    position,
    axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
    ...(position === "right" ? { splitLine: { show: false } } : {}),
  });

  return {
    grid: { top: 40, right: twoAxes ? 56 : 16, bottom: 44, left: 56 },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      valueFormatter: (v) => (v === null || v === undefined ? "—" : compact(Number(v))),
    },
    legend: { top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11, color: mutedColor() } },
    xAxis: {
      ...AXIS.category,
      data: props.categories,
      axisLabel: { ...AXIS.category.axisLabel, fontSize: 10, rotate: props.categories.length > 8 ? 30 : 0 },
    },
    yAxis: twoAxes ? [valueAxis("left"), valueAxis("right")] : valueAxis("left"),
    series: [
      ...props.bars.map((b, i) => ({
        name: b.name,
        type: "bar" as const,
        data: b.values,
        barMaxWidth: 24,
        itemStyle: {
          color: color(b.tone, i),
          borderRadius: [barRadius(), barRadius(), 0, 0] as [number, number, number, number],
        },
      })),
      ...props.lines.map((l, i) => ({
        name: l.name,
        type: "line" as const,
        data: l.values,
        yAxisIndex: twoAxes && l.secondAxis ? 1 : 0,
        smooth: true,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 6,
        lineStyle: { width: 2.5, type: l.dashed ? ("dashed" as const) : ("solid" as const), color: color(l.tone, i + props.bars.length) },
        itemStyle: { color: color(l.tone, i + props.bars.length) },
        ...(l.area ? { areaStyle: { color: color(l.tone, i + props.bars.length), opacity: 0.08 } } : {}),
      })),
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
