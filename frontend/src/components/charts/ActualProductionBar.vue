<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { num } from "@/utils/format";
import { AXIS, COLORS, TOOLTIP, compact, mutedColor } from "./theme";

const props = defineProps<{
  title: string;
  categories: string[];
  journal: number[];
  pos: number[];
  receipt: number[];
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
    data: ["ژورنال", "پوز", "رسید"],
  },
  xAxis: { ...AXIS.category, data: props.categories },
  yAxis: {
    ...AXIS.value,
    axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
  },
  series: [
    {
      name: "ژورنال",
      type: "bar",
      stack: "actual",
      barMaxWidth: 30,
      data: props.journal,
      itemStyle: {
        color: COLORS.actual,
        borderRadius: [0, 0, 0, 0],
      },
    },
    {
      name: "پوز",
      type: "bar",
      stack: "actual",
      barMaxWidth: 30,
      data: props.pos,
      itemStyle: {
        color: COLORS.target,
        borderRadius: [0, 0, 0, 0],
      },
    },
    {
      name: "رسید",
      type: "bar",
      stack: "actual",
      barMaxWidth: 30,
      data: props.receipt,
      itemStyle: {
        color: COLORS.slate,
        borderRadius: [4, 4, 0, 0],
      },
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
