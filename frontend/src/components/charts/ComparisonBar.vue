<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";

// واقعی / مطلوب / ایده‌آل — colours mirror the source workbook (blue/green/pink).
const props = defineProps<{
  title: string;
  actual: number | null;
  target: number | null;
  ideal: number | null;
  unit?: string;
}>();

const el = ref<HTMLElement | null>(null);

const option = computed<EChartsOption>(() => ({
  grid: { top: 24, right: 12, bottom: 28, left: 48 },
  tooltip: { trigger: "axis" },
  xAxis: {
    type: "category",
    data: ["واقعی", "مطلوب", "ایده‌آل"],
    axisLabel: { fontSize: 12 },
  },
  yAxis: { type: "value", axisLabel: { fontSize: 10 } },
  series: [
    {
      type: "bar",
      barWidth: "45%",
      data: [
        { value: props.actual ?? 0, itemStyle: { color: "#4f7cf6" } },
        { value: props.target ?? 0, itemStyle: { color: "#34d399" } },
        { value: props.ideal ?? 0, itemStyle: { color: "#f472b6" } },
      ],
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: "top", fontSize: 10 },
    },
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
