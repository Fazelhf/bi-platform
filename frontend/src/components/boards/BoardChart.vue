<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import {
  AXIS, TOOLTIP, barGradient, barRadius, compact, labelColor, mutedColor,
  seriesColor, surfaceColor,
} from "@/components/charts/theme";
import type { QueryResult, WidgetOptions } from "@/api/dashboards";
import { byUnit } from "./format";

/**
 * Every chart a built widget can be, from one query result.
 *
 * Deliberately one component rather than seven: the manager switches a card
 * from ستونی to خطی to دایره‌ای while building it, and each of those switches
 * would otherwise unmount and remount a chart — losing the animation and, more
 * importantly, flickering the preview they are trying to judge.
 */
const props = withDefaults(defineProps<{
  kind: string;
  result: QueryResult;
  options?: WidgetOptions;
}>(), { options: () => ({}) });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

const isPie = computed(() => props.kind === "pie" || props.kind === "donut");
const isHorizontal = computed(() => props.kind === "hbar");
const unit = computed(() => props.result.series[0]?.unit ?? "number");

function fmt(v: number): string {
  const u = unit.value;
  if (u === "percent") return `${Math.round(v * 10) / 10}٪`;
  return compact(v);
}

/** The tooltip is read, not glanced at — it gets the full formatting. */
function fmtFull(v: number): string {
  return byUnit(v, unit.value);
}

const option = computed<EChartsOption>(() => {
  void ui.chartTheme; // re-read so a theme switch redraws every card
  const { categories, series } = props.result;
  const showLegend = props.options.showLegend !== false && series.length > 1;

  if (isPie.value) {
    const slices = categories
      .map((name, i) => ({ name, value: Number(series[0]?.values[i] ?? 0), i }))
      .filter((s) => s.value > 0);
    return {
      tooltip: {
        ...TOOLTIP, trigger: "item",
        formatter: (p: any) => `${p.name}: ${fmtFull(p.value)} (${p.percent}٪)`,
      },
      legend: {
        type: "scroll", bottom: 0, itemWidth: 9, itemHeight: 9,
        textStyle: { fontSize: 10, color: mutedColor() },
        pageTextStyle: { color: mutedColor() },
      },
      series: [{
        type: "pie",
        radius: props.kind === "donut" ? ["46%", "70%"] : ["0%", "68%"],
        center: ["50%", "44%"],
        minAngle: 4,
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderColor: surfaceColor(), borderWidth: 2 },
        label: {
          fontSize: 10, color: labelColor(),
          show: props.options.showValues !== false,
          formatter: (p: any) => fmt(p.value),
        },
        labelLine: { length: 6, length2: 6, lineStyle: { color: mutedColor() } },
        data: slices.map((s) => ({
          name: s.name, value: s.value, itemStyle: { color: seriesColor(s.i) },
        })),
      }],
    };
  }

  const lineish = props.kind === "line" || props.kind === "area";
  const stacked = props.kind === "stacked";
  const catAxis = {
    ...AXIS.category,
    data: categories,
    axisLabel: {
      ...AXIS.category.axisLabel,
      fontSize: 10,
      rotate: isHorizontal.value || categories.length <= 6 ? 0 : 34,
      // A long employee name pushes the plot area to nothing; the tooltip
      // still carries the whole thing.
      formatter: (v: string) => (v.length > 16 ? `${v.slice(0, 15)}…` : v),
    },
  };
  const valAxis = {
    ...AXIS.value,
    axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => fmt(v) },
  };

  return {
    grid: {
      top: showLegend ? 32 : 14,
      right: 14,
      bottom: isHorizontal.value ? 14 : categories.length > 6 ? 62 : 30,
      left: isHorizontal.value ? 92 : 52,
    },
    tooltip: {
      ...TOOLTIP, trigger: "axis",
      valueFormatter: (v) => fmtFull(Number(v)),
    },
    legend: showLegend
      ? { top: 0, itemWidth: 10, itemHeight: 10,
          textStyle: { fontSize: 11, color: mutedColor() } }
      : undefined,
    xAxis: isHorizontal.value ? valAxis : catAxis,
    yAxis: isHorizontal.value ? { ...catAxis, inverse: true } : valAxis,
    series: series.map((s, i) => {
      const color = props.options.color && series.length === 1
        ? props.options.color
        : seriesColor(i);
      if (lineish) {
        return {
          name: s.name, type: "line" as const, data: s.values, smooth: true,
          symbolSize: 6, lineStyle: { width: 2.5, color },
          itemStyle: { color },
          areaStyle: props.kind === "area" ? { opacity: 0.16, color } : undefined,
        };
      }
      return {
        name: s.name,
        type: "bar" as const,
        data: s.values,
        stack: stacked ? "total" : undefined,
        barMaxWidth: 32,
        itemStyle: {
          color: barGradient(color),
          borderRadius: isHorizontal.value
            ? [0, barRadius(), barRadius(), 0]
            : [barRadius(), barRadius(), 0, 0],
        },
        label: props.options.showValues
          ? { show: true, position: isHorizontal.value ? "right" : "top",
              fontSize: 10, color: labelColor(),
              formatter: (p: any) => fmt(p.value) }
          : undefined,
      };
    }),
  };
});

useChart(el, option);
</script>

<template>
  <div ref="el" class="w-full h-full"></div>
</template>
