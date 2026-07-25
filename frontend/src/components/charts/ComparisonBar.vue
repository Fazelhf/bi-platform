<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { AXIS, COLORS, TOOLTIP, barGradient, compact } from "./theme";

// واقعی / مطلوب / ایده‌آل — brand blue / green / soft violet.
const props = defineProps<{
  title: string;
  actual: number | null;
  target: number | null;
  ideal: number | null;
  unit?: string;
}>();

const el = ref<HTMLElement | null>(null);

const option = computed<EChartsOption>(() => ({
  grid: { top: 28, right: 14, bottom: 26, left: 42 },
  tooltip: { ...TOOLTIP, trigger: "axis",
    valueFormatter: (v) => compact(Number(v)) },
  xAxis: { ...AXIS.category, data: ["واقعی", "مطلوب", "ایده‌آل"] },
  yAxis: { ...AXIS.value, axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) } },
  series: [
    {
      type: "bar",
      barWidth: "46%",
      itemStyle: { borderRadius: [6, 6, 0, 0] },
      data: [
        { value: props.actual ?? 0, itemStyle: { color: barGradient(COLORS.actual) } },
        { value: props.target ?? 0, itemStyle: { color: barGradient(COLORS.target) } },
        { value: props.ideal ?? 0, itemStyle: { color: barGradient(COLORS.ideal) } },
      ],
      label: { show: true, position: "top", fontSize: 10, color: "#475569",
        formatter: (p: any) => compact(p.value) },
    },
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
