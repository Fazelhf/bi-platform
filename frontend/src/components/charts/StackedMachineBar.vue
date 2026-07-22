<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";

// عملکرد دستگاه‌ها — active vs inactive shifts, stacked per line.
const props = defineProps<{
  title: string;
  categories: string[];
  active: number[];
  inactive: number[];
}>();

const el = ref<HTMLElement | null>(null);
const option = computed<EChartsOption>(() => ({
  grid: { top: 30, right: 12, bottom: 24, left: 32 },
  tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
  legend: { top: 0, textStyle: { fontSize: 11 } },
  xAxis: { type: "category", data: props.categories, axisLabel: { fontSize: 11 } },
  yAxis: { type: "value", axisLabel: { fontSize: 10 } },
  series: [
    { name: "شیفت فعال", type: "bar", stack: "s", data: props.active,
      itemStyle: { color: "#34d399" }, barWidth: "50%" },
    { name: "شیفت غیرفعال", type: "bar", stack: "s", data: props.inactive,
      itemStyle: { color: "#f472b6" } },
  ],
}));
useChart(el, option);
</script>

<template>
  <div class="bg-white rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <div ref="el" style="height: 220px"></div>
  </div>
</template>
