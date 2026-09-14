<script setup lang="ts">
/**
 * بزرگ‌ترین انحراف‌ها — the lines to look at first, largest on top.
 *
 * Plotted by effect on cash rather than by raw variance, so every bar on the
 * left side cost the company money and every bar on the right saved it,
 * whichever direction the line itself flows.
 */
import { computed, ref } from "vue";
import type { EChartsOption } from "echarts";
import { useChart } from "@/composables/useChart";
import { useUiStore } from "@/stores/ui";
import { AXIS, COLORS, TOOLTIP, compact } from "./theme";
import type { Verdict } from "@/api/budget";

const props = withDefaults(defineProps<{
  title: string;
  items: { label: string; effect: number; verdict: Verdict }[];
  limit?: number;
  height?: number;
}>(), { limit: 10, height: 320 });

const ui = useUiStore();
const el = ref<HTMLElement | null>(null);

const top = computed(() =>
  [...props.items]
    .sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect))
    .slice(0, props.limit)
    .reverse(), // ECharts draws the first category at the bottom
);

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  const short = (s: string) => (s.length > 22 ? `${s.slice(0, 21)}…` : s);
  return {
    grid: { top: 10, right: 20, bottom: 24, left: 10, containLabel: true },
    tooltip: {
      ...TOOLTIP,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: any) => {
        const item = top.value[params?.[0]?.dataIndex ?? 0];
        if (!item) return "";
        const sign = item.effect > 0 ? "+" : "";
        const word = item.verdict === "good" ? "به نفع نقدینگی" : "به ضرر نقدینگی";
        return `${item.label}<br/>${sign}${compact(item.effect)} — ${word}`;
      },
    },
    xAxis: {
      ...AXIS.value,
      axisLabel: { ...AXIS.value.axisLabel, formatter: (v: number) => compact(v) },
    },
    yAxis: {
      ...AXIS.category,
      data: top.value.map((i) => short(i.label)),
      axisLabel: { ...AXIS.category.axisLabel, fontSize: 11 },
    },
    series: [{
      type: "bar",
      barMaxWidth: 18,
      data: top.value.map((i) => ({
        value: i.effect,
        itemStyle: {
          color: i.verdict === "good" ? COLORS.target : COLORS.rose,
          borderRadius: 4,
        },
      })),
    }],
  };
});

useChart(el, option);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4">
    <h3 class="text-sm font-semibold text-ink mb-1 text-center">{{ title }}</h3>
    <p v-if="!items.length" class="text-xs text-slate-400 text-center py-10">انحرافی ثبت نشده است.</p>
    <div v-show="items.length" ref="el" :style="{ height: height + 'px' }"></div>
  </div>
</template>
