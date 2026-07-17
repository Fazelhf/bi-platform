<script setup lang="ts">
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { rial } from "@/utils/format";

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
  const cat = { type: "category" as const, data: props.categories, axisLabel: { fontSize: 11 } };
  const val = {
    type: "value" as const,
    axisLabel: { formatter: (v: number) => rial(v) },
  };
  const series: EChartsOption["series"] = [
    {
      name: props.title,
      type: "bar",
      data: props.values,
      itemStyle: { color: props.color ?? "#3b6fed", borderRadius: 4 },
    },
  ];
  if (props.second) {
    series.push({
      name: props.second.name,
      type: "bar",
      data: props.second.values,
      itemStyle: { color: "#cbd5e1", borderRadius: 4 },
    });
  }
  return {
    grid: { left: props.horizontal ? 90 : 50, right: 20, top: 30, bottom: props.horizontal ? 20 : 60 },
    tooltip: { trigger: "axis", valueFormatter: (v) => rial(Number(v)) },
    legend: props.second ? { top: 0, textStyle: { fontSize: 11 } } : undefined,
    xAxis: props.horizontal ? val : { ...cat, axisLabel: { ...cat.axisLabel, rotate: 45 } },
    yAxis: props.horizontal ? cat : val,
    series,
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
    <h3 class="text-sm font-semibold text-slate-700 mb-2">{{ title }}</h3>
    <div ref="el" class="w-full" style="height: 300px"></div>
  </div>
</template>
