<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { rial } from "@/utils/format";
import { AXIS, COLORS, TOOLTIP, barGradient, compact } from "./charts/theme";

const props = defineProps<{
  title: string;
  categories: string[];
  values: number[];
  second?: { name: string; values: number[] };
  color?: string;
  horizontal?: boolean;
}>();

const el = ref<HTMLElement | null>(null);

const option = computed<EChartsOption>(() => {
  const cat = { ...AXIS.category, data: props.categories };
  const val = {
    ...AXIS.value,
    axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
  };
  const series: EChartsOption["series"] = [
    {
      name: props.title,
      type: "bar",
      data: props.values,
      barMaxWidth: 34,
      itemStyle: {
        color: barGradient(props.color ?? COLORS.actual),
        borderRadius: props.horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0],
      },
    },
  ];
  if (props.second) {
    series.push({
      name: props.second.name,
      type: "bar",
      data: props.second.values,
      barMaxWidth: 34,
      itemStyle: { color: COLORS.slate, borderRadius: props.horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0] },
    });
  }
  return {
    grid: { left: props.horizontal ? 90 : 46, right: 18, top: 28, bottom: props.horizontal ? 20 : 54 },
    tooltip: { ...TOOLTIP, trigger: "axis",
      valueFormatter: (v) => rial(Number(v)) },
    legend: props.second
      ? { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: "#64748b" } }
      : undefined,
    xAxis: props.horizontal ? val : { ...cat, axisLabel: { ...cat.axisLabel, rotate: 40 } },
    yAxis: props.horizontal ? cat : val,
    series,
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-2 text-center">{{ title }}</h3>
    <div ref="el" class="w-full" style="height: 280px"></div>
  </div>
</template>
