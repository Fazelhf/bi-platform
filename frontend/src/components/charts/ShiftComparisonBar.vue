<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { num } from "@/utils/format";
import { AXIS, TOOLTIP, barGradient, barRadius, compact, mutedColor } from "./theme";

const DAY = "#f59e0b";
const NIGHT = "#6366f1";

const props = defineProps<{
  title: string;
  categories: string[];
  dayValues: number[];
  nightValues: number[];
}>();

const el = ref<HTMLElement | null>(null);

const option = computed<EChartsOption>(() => ({
  grid: { top: 36, right: 14, bottom: 26, left: 46 },
  tooltip: {
    ...TOOLTIP,
    trigger: "axis",
    valueFormatter: (v) => num(Number(v)),
  },
  legend: {
    top: 4,
    itemWidth: 10,
    itemHeight: 10,
    textStyle: { fontSize: 11, color: mutedColor() },
    data: ["شیفت روز", "شیفت شب"],
  },
  xAxis: { ...AXIS.category, data: props.categories },
  yAxis: {
    ...AXIS.value,
    axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
  },
  series: [
    {
      name: "شیفت روز",
      type: "bar",
      barMaxWidth: 24,
      data: props.dayValues,
      // The input form's shift colours: amber day, indigo night.
      itemStyle: { color: barGradient(DAY), borderRadius: [barRadius(), barRadius(), 0, 0] },
    },
    {
      name: "شیفت شب",
      type: "bar",
      barMaxWidth: 24,
      data: props.nightValues,
      itemStyle: { color: barGradient(NIGHT), borderRadius: [barRadius(), barRadius(), 0, 0] },
    },
  ],
}));

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <div ref="el" style="height: 220px"></div>
  </div>
</template>
